from flask import Blueprint, Response, g, request, jsonify, stream_with_context, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import String, and_, cast, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import logging
import uuid
import os
import json
import tempfile
from flask import current_app
from werkzeug.utils import secure_filename

from models import (
    db, User, Job, Resume, Interview, Department, Position, Candidate, Offer,
    Employee, OnboardingTask, Probation, EmployeeChange, Resignation, Contract,
    AttendanceRecord, EmployeeRequest, ApprovalInstance, ApprovalRecord,
    AttendanceExternalPerson, AttendanceRawPunch,
    PerformanceCycle, PerformanceTemplate, PerformanceReview, SalaryProfile,
    PayrollRecord, TrainingCourse, TrainingPlan, TrainingRecord, Role,
    OperationLog, Notification, Feedback, AssistantAuditLog,
    CourseCategory, Course, CourseChapter, CourseHour, CourseAttachment,
    CourseAssignment, UserCourseProgress, UserHourProgress,
    ExamQuestion, ExamPaper, ExamTask, ExamAssignment, ExamAttempt,
    LearningPath, LearningPathAssignment, WrongQuestion, CourseReview,
    CompetencyModel, CompetencyAssessment,
    PKSeason, PointLog, Certificate,
    Reward, ExchangeRecord, TenantModule,
    AttendanceShift, AttendanceRuleSet, AttendanceGroup,
    AttendanceGroupMembership, AttendanceHoliday, AttendanceSchedule,
    AttendanceDailyResult,
)
from services.business_time import parse_business_datetime
from services.approval_workflow import (
    apply_employee_change, apply_salary_adjustment_to_profile,
    complete_approval, is_salary_related_change, salary_profile_for_employee,
)
from services.authz import (
    APPROVAL_ROLES,
    ORG_READ_ROLES,
    ORG_WRITE_ROLES,
    PAYROLL_READ_ROLES,
    PAYROLL_WRITE_ROLES,
    PRIVILEGED_ROLES,
    RECRUITMENT_ROLES,
    TRAINING_READ_ROLES,
    TRAINING_WRITE_ROLES,
    require_resource_access,
    require_roles,
)
from services.employee_portal_accounts import ensure_employee_portal_account
from services.tenant_account_password_reset import (
    TenantAccountNotFound,
    reset_management_password,
    reset_portal_password,
)
from services.tenant_user_creation import (
    TenantUserCreationError,
    create_management_account,
)
from services import storage
from services.tenancy import apply_tenant_scope, assign_tenant, current_tenant, current_tenant_id, enforce_create_limit, object_belongs_to_current_tenant, tenant_usage
from services.domain_workflows import WorkflowError, apply_workflow_transition, get_workflow_record, workflow_payload
from services.ai_resource_governance import (
    AIResourceDenied,
    assert_ai_resource_allowed,
    select_tenant_tier,
    tenant_entitlement_payload,
    tenant_usage_payload,
)
from services.tenant_storage_quota import (
    StorageQuotaExceeded,
    StorageUsageUnavailable,
    register_storage_quota_error_handler,
)

hrm_bp = Blueprint('hrm', __name__)
register_storage_quota_error_handler(hrm_bp)


def new_id():
    return str(uuid.uuid4())


def to_iso(value):
    return value.isoformat() if value else None


def _ai_error_response(exc: AIResourceDenied):
    payload, status = exc.to_response()
    return jsonify(payload), status


def _require_ai_resource(resource_domain: str, use_case: str):
    try:
        return assert_ai_resource_allowed(
            tenant_id=current_tenant_id(),
            user_id=get_jwt_identity(),
            resource_domain=resource_domain,
            use_case=use_case,
        )
    except AIResourceDenied as exc:
        return _ai_error_response(exc)


def parse_date(value):
    if value in (None, ''):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    value = str(value).replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return datetime.strptime(value[:10], '%Y-%m-%d').date()


def parse_datetime(value):
    try:
        return parse_business_datetime(value)
    except ValueError:
        value = str(value)
        return datetime.strptime(value[:19], '%Y-%m-%dT%H:%M:%S')


def parse_number(value):
    if value in (None, ''):
        return None
    return Decimal(str(value))


def parse_int(value):
    if value in (None, ''):
        return None
    return int(value)


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if value in (None, ''):
        return False
    return str(value).lower() in ('1', 'true', 'yes', 'y', '是', 'on')


def parse_jsonish(value):
    if value in (None, ''):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return [item.strip() for item in value.replace('，', ',').split(',') if item.strip()]
    return value


def normalize_payload(data):
    return data or {}


def add_months(base_date, months):
    if not base_date or not months:
        return None
    month = base_date.month - 1 + int(months)
    year = base_date.year + month // 12
    month = month % 12 + 1
    days = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(base_date.day, days[month - 1]))


def generate_employee_no():
    """生成员工工号（带重试，防并发竞态）。"""
    from sqlalchemy.exc import IntegrityError
    prefix = datetime.utcnow().strftime('E%Y%m')
    for _attempt in range(5):
        count = Employee.query.filter(Employee.employee_no.like(f'{prefix}%')).count() + 1
        candidate = f'{prefix}{count:04d}'
        # 检查是否已存在（防并发重复）
        if not Employee.query.filter_by(employee_no=candidate).first():
            return candidate
    # 极端并发场景：加随机后缀兜底
    import random
    return f'{prefix}{count:04d}{random.randint(10,99)}'


# Field mapping: input camelCase -> model snake_case + parser.
RESOURCE_CONFIG = {
    'departments': {
        'model': Department,
        'fields': {
            'name': ('name', str), 'code': ('code', str), 'parentId': ('parent_id', str),
            'managerId': ('manager_id', str), 'status': ('status', str), 'description': ('description', str),
        },
        'search': ['name', 'code'],
    },
    'positions': {
        'model': Position,
        'fields': {
            'title': ('title', str), 'category': ('category', str), 'departmentId': ('department_id', str),
            'level': ('level', str), 'responsibilities': ('responsibilities', str),
            'requirements': ('requirements', str), 'status': ('status', str),
        },
        'search': ['title', 'category', 'level'],
    },
    'candidates': {
        'model': Candidate,
        'fields': {
            'resumeId': ('resume_id', str), 'jobId': ('job_id', str), 'name': ('name', str),
            'email': ('email', str), 'phone': ('phone', str), 'status': ('status', str),
            'source': ('source', str), 'tags': ('tags', parse_jsonish), 'matchRecords': ('match_records', parse_jsonish),
            'aiSummary': ('ai_summary', str), 'aiRecommendation': ('ai_recommendation', str),
            'ownerId': ('owner_id', str), 'remark': ('remark', str),
        },
        'search': ['name', 'email', 'phone', 'source'],
        'before_list': 'sync_candidates',
        'eager': ['job', 'owner'],
    },
    'offers': {
        'model': Offer,
        'fields': {
            'candidateId': ('candidate_id', str), 'jobId': ('job_id', str), 'employeeId': ('employee_id', str),
            'title': ('title', str), 'salary': ('salary', parse_number), 'salaryStructure': ('salary_structure', parse_jsonish),
            'onboardingDate': ('onboarding_date', parse_date), 'workLocation': ('work_location', str),
            'status': ('status', str), 'approvalStatus': ('approval_status', str), 'remark': ('remark', str),
        },
        'search': ['title', 'work_location'],
        'eager': ['candidate', 'job'],
    },
    'employees': {
        'model': Employee,
        'fields': {
            'employeeNo': ('employee_no', str), 'name': ('name', str), 'email': ('email', str), 'phone': ('phone', str),
            'gender': ('gender', str), 'status': ('status', str), 'departmentId': ('department_id', str),
            'positionId': ('position_id', str), 'jobTitle': ('job_title', str), 'managerId': ('manager_id', str),
            'hireDate': ('hire_date', parse_date), 'probationMonths': ('probation_months', parse_int),
            'probationEndDate': ('probation_end_date', parse_date), 'attachments': ('attachments', parse_jsonish),
            'sourceOfferId': ('source_offer_id', str), 'candidateId': ('candidate_id', str), 'idNo': ('id_no', str),
            'address': ('address', str), 'emergencyContact': ('emergency_contact', str), 'remark': ('remark', str),
            'performanceParticipant': ('performance_participant', parse_bool),
        },
        'search': ['employee_no', 'name', 'email', 'phone', 'job_title'],
        'eager': ['department', 'position'],
    },
    'onboarding-tasks': {
        'model': OnboardingTask,
        'fields': {
            'employeeId': ('employee_id', str), 'name': ('name', str), 'taskType': ('task_type', str),
            'ownerId': ('owner_id', str), 'dueDate': ('due_date', parse_date), 'status': ('status', str),
            'materials': ('materials', parse_jsonish), 'remark': ('remark', str),
        },
        'search': ['name', 'task_type'],
        'eager': ['employee', 'owner'],
    },
    'probations': {
        'model': Probation,
        'fields': {
            'employeeId': ('employee_id', str), 'applyDate': ('apply_date', parse_date),
            'expectedRegularDate': ('expected_regular_date', parse_date), 'regularDate': ('regular_date', parse_date),
            'status': ('status', str), 'selfReview': ('self_review', str), 'managerReview': ('manager_review', str),
            'result': ('result', str), 'approvalId': ('approval_id', str), 'remark': ('remark', str),
        },
        'search': ['result'],
        'eager': ['employee'],
    },
    'employee-changes': {
        'model': EmployeeChange,
        'fields': {
            'employeeId': ('employee_id', str), 'changeType': ('change_type', str),
            'beforeDepartmentId': ('before_department_id', str), 'afterDepartmentId': ('after_department_id', str),
            'beforePositionId': ('before_position_id', str), 'afterPositionId': ('after_position_id', str),
            'beforeLevel': ('before_level', str), 'afterLevel': ('after_level', str),
            'salaryAdjustment': ('salary_adjustment', parse_number), 'effectiveDate': ('effective_date', parse_date),
            'reason': ('reason', str), 'status': ('status', str),
        },
        'search': ['change_type', 'reason'],
        'eager': ['employee', 'before_department', 'after_department', 'before_position', 'after_position'],
    },
    'resignations': {
        'model': Resignation,
        'fields': {
            'employeeId': ('employee_id', str), 'applyDate': ('apply_date', parse_date),
            'expectedLeaveDate': ('expected_leave_date', parse_date), 'actualLeaveDate': ('actual_leave_date', parse_date),
            'reason': ('reason', str), 'handoverItems': ('handover_items', parse_jsonish), 'status': ('status', str),
            'approvalId': ('approval_id', str), 'aiSummary': ('ai_summary', str),
        },
        'search': ['reason'],
        'eager': ['employee'],
    },
    'contracts': {
        'model': Contract,
        'fields': {
            'employeeId': ('employee_id', str), 'contractNo': ('contract_no', str), 'contractType': ('contract_type', str),
            'startDate': ('start_date', parse_date), 'endDate': ('end_date', parse_date), 'status': ('status', str),
            'reminderDate': ('reminder_date', parse_date), 'attachmentUrl': ('attachment_url', str), 'remark': ('remark', str),
        },
        'search': ['contract_no', 'contract_type'],
        'eager': ['employee'],
    },
    'attendance-records': {
        'model': AttendanceRecord,
        'fields': {
            'employeeId': ('employee_id', str), 'attendanceDate': ('attendance_date', parse_date),
            'checkInTime': ('check_in_time', parse_datetime), 'checkOutTime': ('check_out_time', parse_datetime),
            'workHours': ('work_hours', parse_number), 'status': ('status', str), 'source': ('source', str), 'remark': ('remark', str),
        },
        'search': ['status', 'source', 'remark'],
        'eager': ['employee'],
    },
    'employee-requests': {
        'model': EmployeeRequest,
        'fields': {
            'employeeId': ('employee_id', str), 'requestType': ('request_type', str), 'title': ('title', str),
            'startTime': ('start_time', parse_datetime), 'endTime': ('end_time', parse_datetime),
            'durationHours': ('duration_hours', parse_number), 'reason': ('reason', str), 'status': ('status', str),
            'approvalId': ('approval_id', str),
        },
        'search': ['title', 'request_type', 'reason'],
        'eager': ['employee'],
    },
    'performance-cycles': {
        'model': PerformanceCycle,
        'fields': {'name': ('name', str), 'cycleType': ('cycle_type', str), 'startDate': ('start_date', parse_date), 'endDate': ('end_date', parse_date), 'status': ('status', str), 'remark': ('remark', str)},
        'search': ['name', 'cycle_type'],
    },
    'performance-templates': {
        'model': PerformanceTemplate,
        'fields': {'name': ('name', str), 'templateType': ('template_type', str), 'indicators': ('indicators', parse_jsonish), 'status': ('status', str), 'remark': ('remark', str)},
        'search': ['name', 'template_type'],
    },
    'performance-reviews': {
        'model': PerformanceReview,
        'fields': {
            'employeeId': ('employee_id', str), 'cycleId': ('cycle_id', str), 'templateId': ('template_id', str),
            'selfReview': ('self_review', str), 'selfScore': ('self_score', parse_number),
            'managerScore': ('manager_score', parse_number), 'finalScore': ('final_score', parse_number),
            'grade': ('grade', str), 'result': ('result', str), 'remark': ('remark', str), 'status': ('status', str),
        },
        'search': ['grade', 'result', 'remark'],
        'eager': ['employee', 'cycle', 'template'],
    },
    'salary-profiles': {
        'model': SalaryProfile,
        'fields': {
            'employeeId': ('employee_id', str), 'baseSalary': ('base_salary', parse_number),
            'positionSalary': ('position_salary', parse_number), 'performanceSalary': ('performance_salary', parse_number),
            'allowance': ('allowance', parse_number), 'bonus': ('bonus', parse_number), 'deduction': ('deduction', parse_number),
            'currency': ('currency', str), 'status': ('status', str), 'remark': ('remark', str),
        },
        'search': ['currency', 'remark'],
        'eager': ['employee'],
    },
    'payroll-records': {
        'model': PayrollRecord,
        'fields': {
            'employeeId': ('employee_id', str), 'payrollMonth': ('payroll_month', str),
            'baseSalary': ('base_salary', parse_number), 'positionSalary': ('position_salary', parse_number),
            'performanceSalary': ('performance_salary', parse_number), 'bonus': ('bonus', parse_number),
            'allowance': ('allowance', parse_number), 'deduction': ('deduction', parse_number),
            'grossSalary': ('gross_salary', parse_number), 'netSalary': ('net_salary', parse_number),
            'status': ('status', str), 'employeeVisible': ('employee_visible', parse_bool), 'remark': ('remark', str),
        },
        'search': ['payroll_month', 'remark'],
        'eager': ['employee'],
    },
    'training-courses': {
        'model': TrainingCourse,
        'fields': {'name': ('name', str), 'category': ('category', str), 'lecturer': ('lecturer', str), 'durationHours': ('duration_hours', parse_number), 'description': ('description', str), 'status': ('status', str)},
        'search': ['name', 'category', 'lecturer'],
    },
    'training-plans': {
        'model': TrainingPlan,
        'fields': {'name': ('name', str), 'courseId': ('course_id', str), 'startTime': ('start_time', parse_datetime), 'endTime': ('end_time', parse_datetime), 'targetDepartments': ('target_departments', parse_jsonish), 'status': ('status', str), 'remark': ('remark', str)},
        'search': ['name', 'status'],
    },
    'training-records': {
        'model': TrainingRecord,
        'fields': {'planId': ('plan_id', str), 'courseId': ('course_id', str), 'employeeId': ('employee_id', str), 'status': ('status', str), 'result': ('result', str), 'score': ('score', parse_number), 'feedback': ('feedback', str)},
        'search': ['status', 'result', 'feedback'],
    },
    # ----- 培训体系（参照 PlayEdu 开源版）-----
    'course-categories': {
        'model': CourseCategory,
        'fields': {'name': ('name', str), 'parentId': ('parent_id', str), 'parentChain': ('parent_chain', str), 'sort': ('sort', parse_int)},
        'search': ['name'],
    },
    'courses': {
        'model': Course,
        'fields': {'title': ('title', str), 'categoryId': ('category_id', str), 'coverUrl': ('cover_url', str), 'isRequired': ('is_required', parse_bool), 'deadline': ('deadline', parse_datetime), 'shortDesc': ('short_desc', str), 'content': ('content', str), 'isShow': ('is_show', parse_bool), 'classHour': ('class_hour', parse_int), 'sort': ('sort', parse_int)},
        'search': ['title', 'short_desc'],
    },
    'course-chapters': {
        'model': CourseChapter,
        'fields': {'courseId': ('course_id', str), 'name': ('name', str), 'description': ('description', str), 'materials': ('materials', parse_jsonish), 'sort': ('sort', parse_int)},
        'search': ['name'],
    },
    'course-hours': {
        'model': CourseHour,
        'fields': {'courseId': ('course_id', str), 'chapterId': ('chapter_id', str), 'title': ('title', str), 'type': ('type', str), 'sort': ('sort', parse_int), 'videoKey': ('video_key', str), 'duration': ('duration', parse_int)},
        'search': ['title'],
    },
    'course-attachments': {
        'model': CourseAttachment,
        'fields': {'courseId': ('course_id', str), 'title': ('title', str), 'fileUrl': ('file_url', str), 'ext': ('ext', str), 'sort': ('sort', parse_int)},
        'search': ['title'],
    },
    'course-assignments': {
        'model': CourseAssignment,
        'fields': {'courseId': ('course_id', str), 'targetType': ('target_type', str), 'targetId': ('target_id', str)},
        'search': [],
    },
    'course-progress': {
        'model': UserCourseProgress,
        'fields': {'employeeId': ('employee_id', str), 'courseId': ('course_id', str), 'hourCount': ('hour_count', parse_int), 'finishedCount': ('finished_count', parse_int), 'progress': ('progress', parse_int), 'isFinished': ('is_finished', parse_bool)},
        'search': [],
        'read_only_create': True,  # 进度由门户上报，避免管理员误建
    },
    'hour-progress': {
        'model': UserHourProgress,
        'fields': {'employeeId': ('employee_id', str), 'courseId': ('course_id', str), 'hourId': ('hour_id', str), 'totalDuration': ('total_duration', parse_int), 'watchedDuration': ('watched_duration', parse_int), 'isFinished': ('is_finished', parse_bool)},
        'search': [],
        'read_only_create': True,
    },
    # ----- 考试体系（自研）-----
    'exam-questions': {
        'model': ExamQuestion,
        'fields': {'courseId': ('course_id', str), 'category': ('category', str), 'type': ('type', str), 'stem': ('stem', str), 'options': ('options', parse_jsonish), 'answer': ('answer', parse_jsonish), 'score': ('score', parse_number), 'explanation': ('explanation', str), 'difficulty': ('difficulty', parse_int), 'source': ('source', str), 'reviewStatus': ('review_status', str)},
        'search': ['stem', 'category'],
    },
    'exam-papers': {
        'model': ExamPaper,
        'fields': {'title': ('title', str), 'description': ('description', str), 'questionIds': ('question_ids', parse_jsonish), 'questionMode': ('question_mode', str), 'drawCount': ('draw_count', parse_int), 'totalScore': ('total_score', parse_number), 'passScore': ('pass_score', parse_number), 'durationMinutes': ('duration_minutes', parse_int), 'status': ('status', str), 'shuffle': ('shuffle', parse_bool)},
        'search': ['title'],
    },
    'exam-tasks': {
        'model': ExamTask,
        'fields': {'paperId': ('paper_id', str), 'title': ('title', str), 'description': ('description', str), 'startTime': ('start_time', parse_datetime), 'endTime': ('end_time', parse_datetime), 'maxAttempts': ('max_attempts', parse_int), 'targetType': ('target_type', str), 'targetIds': ('target_ids', parse_jsonish), 'status': ('status', str)},
        'search': ['title'],
    },
    'exam-assignments': {
        'model': ExamAssignment,
        'fields': {'taskId': ('task_id', str), 'employeeId': ('employee_id', str), 'attemptsUsed': ('attempts_used', parse_int), 'status': ('status', str)},
        'search': ['status'],
        'read_only_create': True,  # 由任务发布自动生成
    },
    'exam-attempts': {
        'model': ExamAttempt,
        'fields': {'assignmentId': ('assignment_id', str), 'employeeId': ('employee_id', str), 'taskId': ('task_id', str), 'paperId': ('paper_id', str), 'score': ('score', parse_number), 'passed': ('passed', parse_bool), 'status': ('status', str)},
        'search': ['status'],
        'read_only_create': True,  # 由门户 start/submit 管理
    },
    # ----- 学习地图 / 学习路径 -----
    'learning-paths': {
        'model': LearningPath,
        'fields': {'name': ('name', str), 'description': ('description', str), 'coverUrl': ('cover_url', str), 'targetPosition': ('target_position', str), 'targetDepartmentId': ('target_department_id', str), 'stages': ('stages', parse_jsonish), 'status': ('status', str)},
        'search': ['name', 'target_position'],
    },
    'learning-path-assignments': {
        'model': LearningPathAssignment,
        'fields': {'pathId': ('path_id', str), 'employeeId': ('employee_id', str), 'currentStage': ('current_stage', parse_int), 'progress': ('progress', parse_int), 'isCompleted': ('is_completed', parse_bool)},
        'search': [],
        'read_only_create': True,  # 由路径发布管理
    },
    # ----- 岗位胜任力测评 -----
    'competency-models': {
        'model': CompetencyModel,
        'fields': {'name': ('name', str), 'description': ('description', str), 'dimensions': ('dimensions', parse_jsonish), 'status': ('status', str)},
        'search': ['name'],
    },
    'competency-assessments': {
        'model': CompetencyAssessment,
        'fields': {'employeeId': ('employee_id', str), 'modelId': ('model_id', str), 'scores': ('scores', parse_jsonish), 'overallScore': ('overall_score', parse_int), 'assessor': ('assessor', str)},
        'search': [],
        'read_only_create': True,  # 由测评端点管理
    },
    'pk-seasons': {
        'model': PKSeason,
        'fields': {'name': ('name', str), 'description': ('description', str), 'startDate': ('start_date', parse_datetime), 'endDate': ('end_date', parse_datetime), 'metric': ('metric', str), 'participantDeptIds': ('participant_dept_ids', parse_jsonish), 'status': ('status', str)},
        'search': ['name'],
    },
    'rewards': {
        'model': Reward,
        'fields': {'name': ('name', str), 'description': ('description', str), 'icon': ('icon', str), 'rewardType': ('reward_type', str), 'pointsCost': ('points_cost', parse_int), 'stock': ('stock', parse_int), 'isActive': ('is_active', parse_bool)},
        'search': ['name'],
    },
    'exchange-records': {
        'model': ExchangeRecord,
        'fields': {'employeeId': ('employee_id', str), 'rewardId': ('reward_id', str), 'pointsCost': ('points_cost', parse_int), 'status': ('status', str), 'redeemCode': ('redeem_code', str)},
        'search': ['status'],
        'read_only_create': True,  # 由兑换端点管理
    },
    'roles': {
        'model': Role,
        'fields': {'code': ('code', str), 'name': ('name', str), 'description': ('description', str), 'permissions': ('permissions', parse_jsonish), 'status': ('status', str)},
        'search': ['code', 'name', 'description'],
    },
    'users': {
        'model': User,
        'fields': {'name': ('name', str), 'email': ('email', str), 'role': ('role', str), 'phone': ('phone', str), 'status': ('status', str), 'departmentId': ('department_id', str), 'employeeId': ('employee_id', str)},
        'search': ['name', 'email', 'role', 'phone'],
        'read_only_create': True,
    },
    'notifications': {
        'model': Notification,
        'fields': {'userId': ('user_id', str), 'title': ('title', str), 'content': ('content', str), 'noticeType': ('notice_type', str), 'status': ('status', str), 'linkUrl': ('link_url', str)},
        'search': ['title', 'content', 'notice_type'],
        'personal_scope': True,
    },
    'feedbacks': {
        'model': Feedback,
        'fields': {
            'userId': ('user_id', str),
            'feedbackType': ('feedback_type', str),
            'severity': ('severity', str),
            'title': ('title', str),
            'content': ('content', str),
            'pageUrl': ('page_url', str),
            'userAgent': ('user_agent', str),
            'attachments': ('attachments', parse_jsonish),
            'status': ('status', str),
            'handlerId': ('handler_id', str),
            'handlerReply': ('handler_reply', str),
            'handledAt': ('handled_at', parse_datetime),
            'reopenReason': ('reopen_reason', str),
            'reopenCurrentState': ('reopen_current_state', str),
        },
        'search': ['title', 'content', 'feedback_type', 'status'],
        'scope_to_user': True,  # 非管理员只看自己提交的
    },
    'operation-logs': {
        'model': OperationLog,
        'fields': {},
        'search': ['module', 'action', 'target_id'],
        'read_only': True,
    },
}


def get_config(resource):
    cfg = RESOURCE_CONFIG.get(resource)
    if not cfg:
        return None
    return cfg


def apply_fields(obj, data, fields):
    data = normalize_payload(data)
    for input_key, (attr, parser) in fields.items():
        if input_key in data:
            value = data.get(input_key)
            if parser is str:
                value = None if value in (None, '') else str(value)
                # 防超长文本导致 DB 500：字符串字段截断
                if value and len(value) > 5000:
                    value = value[:5000]
                # 对已知短字段进一步截断（防 MySQL VARCHAR 超限）
                if attr in ('title', 'name', 'category', 'lecturer', 'target_position', 'employee_name', 'course_title', 'reward_name') and value and len(value) > 195:
                    value = value[:195]
            else:
                value = parser(value)
            setattr(obj, attr, value)


def _validate_required(data, fields, model):
    """校验必填字段（name/title 等非空）。返回 (ok, error_msg)。"""
    # 根据 model 确定必填字段
    required_map = {
        'Course': ['title'],
        'CourseCategory': ['name'],
        'CourseChapter': ['name'],
        'CourseHour': ['title'],
        'ExamQuestion': ['stem'],
        'ExamPaper': ['title'],
        'ExamTask': ['title'],
        'LearningPath': ['name'],
        'CompetencyModel': ['name'],
        'PKSeason': ['name'],
        'Reward': ['name'],
    }
    model_name = model.__name__
    required_keys = required_map.get(model_name, [])
    for key in required_keys:
        val = data.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            return False, f'{key} 不能为空'
    return True, None


def _trim_text(value):
    if value is None:
        return ''
    return str(value).strip()


def _decimal_or_zero(value) -> Decimal:
    if value in (None, ''):
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalize_id_list(values):
    result = []
    seen = set()
    for value in (values or []):
        text = str(value or '').strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _camel_to_snake(value):
    result = []
    for char in str(value or ''):
        if char.isupper():
            result.append('_')
            result.append(char.lower())
        else:
            result.append(char)
    return ''.join(result).lstrip('_')


def _resource_filter_column(model, cfg, public_name):
    fields = cfg.get('fields') or {}
    if public_name in fields:
        attr_name = fields[public_name][0]
        if hasattr(model, attr_name):
            return getattr(model, attr_name)
    attr_name = _camel_to_snake(public_name)
    if hasattr(model, attr_name):
        return getattr(model, attr_name)
    return None


def _apply_resource_filters(query, model, cfg):
    department_ids = _normalize_id_list(str(request.args.get('departmentIds') or '').split(','))
    if department_ids:
        if hasattr(model, 'department_id'):
            query = query.filter(getattr(model, 'department_id').in_(department_ids))
        elif model is Department:
            query = query.filter(Department.id.in_(department_ids))
        elif hasattr(model, 'employee_id'):
            query = query.join(Employee, getattr(model, 'employee_id') == Employee.id).filter(Employee.department_id.in_(department_ids))

    ignored = {'page', 'size', 'keyword', 'departmentIds'}
    for key, value in request.args.items():
        if key in ignored or key.endswith('From') or key.endswith('To') or value in (None, ''):
            continue
        column = _resource_filter_column(model, cfg, key)
        if column is not None:
            query = query.filter(column == value)

    for key, value in request.args.items():
        if value in (None, ''):
            continue
        if key.endswith('From'):
            column = _resource_filter_column(model, cfg, key[:-4])
            if column is not None:
                query = query.filter(column >= value)
        elif key.endswith('To'):
            column = _resource_filter_column(model, cfg, key[:-2])
            if column is not None:
                query = query.filter(column <= value)
    return query


def _load_exam_paper_questions(question_ids):
    rows = ExamQuestion.query.filter(ExamQuestion.id.in_(question_ids)).all() if question_ids else []
    row_map = {row.id: row for row in rows}
    missing = [qid for qid in question_ids if qid not in row_map]
    ordered = [row_map[qid] for qid in question_ids if qid in row_map]
    return ordered, missing


def _infer_random_total_score(question_rows, draw_count):
    scores = {
        _decimal_or_zero(getattr(row, 'score', 0)).quantize(Decimal('0.01'))
        for row in (question_rows or [])
    }
    if len(scores) != 1:
        return None
    score = next(iter(scores))
    if score <= 0:
        return None
    return (score * Decimal(draw_count)).quantize(Decimal('0.01'))


def _validate_exam_paper(obj):
    obj.question_ids = _normalize_id_list(obj.question_ids)
    if not obj.question_ids:
        return '请至少选择一道题'

    question_mode = str(obj.question_mode or 'fixed').strip().lower() or 'fixed'
    if question_mode not in {'fixed', 'random'}:
        return 'questionMode 仅支持 fixed 或 random'
    obj.question_mode = question_mode

    question_rows, missing = _load_exam_paper_questions(obj.question_ids)
    if missing:
        return f'试卷中有 {len(missing)} 道题不存在或已删除'

    duration_minutes = int(obj.duration_minutes or 0)
    if duration_minutes <= 0:
        return '答题时长须大于 0'
    obj.duration_minutes = duration_minutes

    if question_mode == 'random':
        draw_count = int(obj.draw_count or 0)
        if draw_count <= 0:
            return '随机试卷请设置抽题数量'
        if draw_count > len(obj.question_ids):
            return '抽题数量不能超过题池数量'
        obj.draw_count = draw_count
        total_score = _decimal_or_zero(obj.total_score)
        if total_score <= 0:
            total_score = _infer_random_total_score(question_rows, draw_count)
            if total_score is None:
                return '随机试卷请填写总分'
        obj.total_score = total_score.quantize(Decimal('0.01'))
    else:
        obj.draw_count = None
        obj.total_score = sum(
            (_decimal_or_zero(getattr(row, 'score', 0)) for row in question_rows),
            Decimal('0'),
        ).quantize(Decimal('0.01'))

    pass_score = _decimal_or_zero(obj.pass_score)
    if pass_score <= 0:
        return '及格分须大于 0'
    if pass_score > _decimal_or_zero(obj.total_score):
        return '及格分不能超过总分'
    obj.pass_score = pass_score.quantize(Decimal('0.01'))
    return None


def _record_feedback_reopen(obj, old_status, data):
    reason = _trim_text(data.get('reopenReason'))
    current_state = _trim_text(data.get('reopenCurrentState'))
    if not reason or not current_state:
        return jsonify({'error': '重新打开原因和当前情况描述不能为空'}), 400

    history = list(obj.reopen_history or [])
    history.append({
        'fromStatus': old_status,
        'toStatus': 'pending',
        'reason': reason,
        'currentState': current_state,
        'reopenedBy': get_jwt_identity(),
        'reopenedAt': datetime.utcnow().isoformat(),
    })
    obj.reopen_reason = reason
    obj.reopen_current_state = current_state
    obj.reopen_history = history
    obj.handler_id = None
    obj.handled_at = None
    return None


def _notify_feedback_resolved(obj):
    if not obj.user_id:
        return
    link_url = f'/feedback?id={obj.id}'
    if obj.handled_at:
        existing = Notification.query.filter(
            Notification.user_id == obj.user_id,
            Notification.notice_type == 'feedback',
            Notification.link_url == link_url,
            Notification.created_at >= obj.handled_at,
        ).first()
        if existing:
            return
    elif Notification.query.filter_by(user_id=obj.user_id, notice_type='feedback', link_url=link_url).first():
        return
    db.session.add(Notification(
        id=new_id(),
        user_id=obj.user_id,
        title=f'问题反馈已修复：{obj.title}',
        content=obj.handler_reply or '你的反馈已处理完成，请查看详情。',
        notice_type='feedback',
        status='unread',
        link_url=link_url,
    ))


def log_operation(module, action, target_id=None, detail=None, *, strict=False):
    try:
        log = OperationLog(
            id=new_id(),
            user_id=get_jwt_identity(),
            module=module,
            action=action,
            target_id=target_id,
            detail=detail or {},
            ip=request.headers.get('X-Forwarded-For', request.remote_addr),
        )
        assign_tenant(log)
        db.session.add(log)
    except Exception:
        db.session.rollback()
        logging.getLogger('hengpintong.audit').warning(
            'audit_log_failed', extra={'module': module, 'action': action}
        )
        if strict:
            raise


def _reset_account_password(*, target_id, account_type, command, allowed_roles):
    denied = require_roles(allowed_roles, '无权限重置账号密码')
    if denied:
        return denied

    request_id = getattr(g, 'request_id', None)
    try:
        credential = command(
            tenant_id=current_tenant_id(),
            **target_id,
        )
        response_payload = {
            'account': credential.account.to_dict(),
            'initialPassword': credential.password,
            'requestId': request_id,
        }
        action = (
            'reset_management_password'
            if account_type == 'hrm'
            else 'reset_portal_password'
        )
        db.session.add(OperationLog(
            id=new_id(),
            tenant_id=current_tenant_id(),
            user_id=get_jwt_identity(),
            module='account_security',
            action=action,
            target_id=credential.account.id,
            detail={
                'credentialType': 'one_time',
                'accountType': account_type,
                'mustChangePassword': True,
            },
            ip=request.remote_addr,
        ))
        db.session.commit()
        response = jsonify(response_payload)
        response.headers['Cache-Control'] = 'no-store'
        return response
    except TenantAccountNotFound:
        db.session.rollback()
        return jsonify({
            'error': '账号不存在或不可用',
            'code': 'ACCOUNT_NOT_FOUND',
            'requestId': request_id,
        }), 404
    except Exception:
        db.session.rollback()
        logging.getLogger('hengpintong.account_security').error(
            'tenant_account_password_reset_failed',
            extra={'account_type': account_type},
        )
        return jsonify({
            'error': '密码重置失败，请稍后重试',
            'code': 'ACCOUNT_PASSWORD_RESET_FAILED',
            'requestId': request_id,
        }), 500


@hrm_bp.route('/users/<user_id>/reset-password', methods=['POST'])
@jwt_required()
def reset_user_password(user_id):
    return _reset_account_password(
        target_id={'user_id': user_id},
        account_type='hrm',
        command=reset_management_password,
        allowed_roles={'admin'},
    )


@hrm_bp.route('/users/create', methods=['POST'])
@jwt_required()
def create_user_account():
    denied = require_roles({'admin'}, '只有系统管理员可以创建用户')
    if denied:
        return denied

    request_id = getattr(g, 'request_id', None)
    try:
        limit_error = enforce_create_limit(User)
        if limit_error:
            return limit_error
        credential = create_management_account(
            tenant_id=current_tenant_id(),
            data=request.get_json() or {},
        )
        db.session.add(credential.account)
        db.session.flush()
        log_operation(
            'account_security',
            'create_management_account',
            credential.account.id,
            {
                'credentialType': 'one_time',
                'accountType': 'hrm',
                'mustChangePassword': True,
                'role': credential.account.role,
            },
            strict=True,
        )
        db.session.commit()
        response = jsonify({
            'account': credential.account.to_dict(),
            'initialPassword': credential.password,
            'requestId': request_id,
        })
        response.status_code = 201
        response.headers['Cache-Control'] = 'no-store'
        return response
    except TenantUserCreationError as exc:
        db.session.rollback()
        return jsonify({
            'error': exc.message,
            'code': exc.code,
            'requestId': request_id,
        }), exc.status_code
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': '该邮箱已存在',
            'code': 'USER_EMAIL_EXISTS',
            'requestId': request_id,
        }), 409
    except Exception:
        db.session.rollback()
        logging.getLogger('hengpintong.account_security').error(
            'tenant_management_account_creation_failed',
        )
        return jsonify({
            'error': '用户创建失败，请稍后重试',
            'code': 'USER_CREATE_FAILED',
            'requestId': request_id,
        }), 500


@hrm_bp.route('/employees/<employee_id>/reset-portal-password', methods=['POST'])
@jwt_required()
def reset_employee_portal_password(employee_id):
    return _reset_account_password(
        target_id={'employee_id': employee_id},
        account_type='employee_portal',
        command=reset_portal_password,
        allowed_roles=ORG_WRITE_ROLES,
    )


def _record_storage_references(obj, *, include_descendants=False):
    references = set()
    if isinstance(obj, Course):
        references.update(storage.storage_reference_keys(obj.cover_url))
        if include_descendants:
            for chapter in CourseChapter.query.filter_by(course_id=obj.id).all():
                references.update(storage.storage_reference_keys(chapter.materials))
            for hour in CourseHour.query.filter_by(course_id=obj.id).all():
                references.update(storage.storage_reference_keys(hour.video_key))
            for attachment in CourseAttachment.query.filter_by(course_id=obj.id).all():
                references.update(storage.storage_reference_keys(attachment.file_url))
    elif isinstance(obj, CourseChapter):
        references.update(storage.storage_reference_keys(obj.materials))
        if include_descendants:
            for hour in CourseHour.query.filter_by(chapter_id=obj.id).all():
                references.update(storage.storage_reference_keys(hour.video_key))
    elif isinstance(obj, CourseHour):
        references.update(storage.storage_reference_keys(obj.video_key))
    elif isinstance(obj, CourseAttachment):
        references.update(storage.storage_reference_keys(obj.file_url))
    elif isinstance(obj, Resume):
        references.update(storage.storage_reference_keys(obj.file_url))
    elif isinstance(obj, Interview):
        references.update(storage.storage_reference_keys(obj.feedback_file_url))
        references.update(storage.storage_reference_keys(obj.recording_url))
    elif isinstance(obj, Employee):
        references.update(storage.storage_reference_keys(obj.attachments))
        if include_descendants:
            for contract in Contract.query.filter_by(employee_id=obj.id).all():
                references.update(storage.storage_reference_keys(contract.attachment_url))
    elif isinstance(obj, Contract):
        references.update(storage.storage_reference_keys(obj.attachment_url))
    elif isinstance(obj, LearningPath):
        references.update(storage.storage_reference_keys(obj.cover_url))
    elif isinstance(obj, Certificate):
        references.update(storage.storage_reference_keys(obj.image_url))
    elif isinstance(obj, Feedback):
        references.update(storage.storage_reference_keys(obj.attachments))
    return references


def _release_unreferenced_storage(references, *, tenant_id):
    for reference in sorted(set(references or ())):
        storage.delete_object_if_unreferenced(reference, tenant_id=tenant_id)


def sync_candidates_from_resumes():
    existing = {row[0] for row in db.session.query(Candidate.resume_id).filter(Candidate.resume_id.isnot(None)).all()}
    new_count = 0
    for resume in Resume.query.order_by(Resume.created_at.desc()).all():
        if resume.id in existing:
            continue
        ai = resume.ai_analysis or {}
        match = {
            'jobId': resume.job_id,
            'score': ai.get('score'),
            'matchDegree': ai.get('matchDegree'),
            'createdAt': resume.created_at.isoformat() if resume.created_at else None,
        }
        candidate = Candidate(
            id=new_id(),
            resume_id=resume.id,
            job_id=resume.job_id,
            name=resume.candidate_name,
            email=resume.email,
            phone=resume.phone,
            status='screening',
            source='简历上传',
            tags=resume.tags or [],
            match_records=[match],
            ai_summary=ai.get('summary'),
            ai_recommendation=ai.get('recommendation'),
            owner_id=resume.created_by,
        )
        db.session.add(candidate)
        new_count += 1
    if new_count:
        db.session.commit()


def find_default_approver(current_user_id=None):
    preferred_roles = ['admin', 'hr_admin', 'manager']
    query = User.query.filter(User.status.in_(['active', None]) if hasattr(User, 'status') else True)
    for role in preferred_roles:
        approver = query.filter(User.role == role, User.id != current_user_id).first()
        if approver:
            return approver.id
    user = User.query.filter(User.id != current_user_id).first()
    return user.id if user else current_user_id


def create_approval(business_type, business_id, title, applicant_id=None, approver_id=None):
    existing = ApprovalInstance.query.filter_by(
        business_type=business_type,
        business_id=business_id,
        status='pending',
    ).first()
    if existing:
        return existing
    applicant_id = applicant_id or get_jwt_identity()
    approval = ApprovalInstance(
        id=new_id(),
        business_type=business_type,
        business_id=business_id,
        title=title,
        applicant_id=applicant_id,
        approver_id=approver_id or find_default_approver(applicant_id),
        status='pending',
        submitted_at=datetime.utcnow(),
    )
    db.session.add(approval)
    return approval


def update_business_by_approval(approval, approved, comment=''):
    status = 'approved' if approved else 'rejected'
    if approval.business_type == 'offer':
        obj = Offer.query.get(approval.business_id)
        if obj:
            obj.approval_status = status
            obj.status = 'sent' if approved else 'rejected'
    elif approval.business_type == 'employee_request':
        obj = EmployeeRequest.query.get(approval.business_id)
        if obj:
            obj.status = status
    elif approval.business_type == 'probation':
        obj = Probation.query.get(approval.business_id)
        if obj:
            obj.status = status
            if approved:
                obj.result = obj.result or '通过'
                obj.regular_date = obj.regular_date or date.today()
                employee = Employee.query.get(obj.employee_id)
                if employee:
                    employee.status = 'active'
    elif approval.business_type == 'resignation':
        obj = Resignation.query.get(approval.business_id)
        if obj:
            obj.status = status
            if approved:
                obj.actual_leave_date = obj.actual_leave_date or obj.expected_leave_date or date.today()
                employee = Employee.query.get(obj.employee_id)
                if employee:
                    employee.status = 'resigned'
    elif approval.business_type == 'employee_change':
        obj = EmployeeChange.query.get(approval.business_id)
        if obj:
            obj.status = status
            if approved:
                apply_employee_change(obj)
    elif approval.business_type == 'onboarding':
        obj = Employee.query.get(approval.business_id)
        if obj and approved:
            obj.status = 'probation'
    approval.remark = comment or approval.remark


def ensure_default_onboarding_tasks(employee_id, owner_id=None):
    employee = Employee.query.get(employee_id)
    if not employee:
        return []
    exists = OnboardingTask.query.filter_by(employee_id=employee_id).count()
    if exists:
        return OnboardingTask.query.filter_by(employee_id=employee_id).all()
    names = [
        ('资料收集', '收集身份证、银行卡、学历证明等入职材料'),
        ('合同签署', '准备并签署劳动合同/保密协议'),
        ('账号开通', '开通邮箱、系统账号、IM账号和权限'),
        ('设备发放', '准备电脑、工牌、办公用品'),
        ('入职培训', '安排公司制度、岗位职责与安全培训'),
        ('导师安排', '安排直属上级或带教导师'),
        ('社保公积金', '收集社保公积金信息并预留办理记录'),
    ]
    due = employee.hire_date or date.today()
    tasks = []
    for task_type, name in names:
        task = OnboardingTask(
            id=new_id(),
            employee_id=employee_id,
            name=name,
            task_type=task_type,
            owner_id=owner_id,
            due_date=due,
            status='pending',
            materials=[],
        )
        db.session.add(task)
        tasks.append(task)
    return tasks


def ensure_offer_salary_profile(employee, offer):
    if not employee or not offer or not offer.salary:
        return None
    profile = SalaryProfile.query.filter_by(employee_id=employee.id).first()
    if profile:
        return profile
    profile = SalaryProfile(
        id=new_id(),
        employee_id=employee.id,
        base_salary=offer.salary,
        status='active',
        remark='由Offer薪资自动生成，可后续拆分基本/岗位/绩效工资',
    )
    db.session.add(profile)
    return profile


def ensure_offer_contract(employee, offer, owner_id=None):
    if not employee:
        return None
    contract = Contract.query.filter_by(employee_id=employee.id).order_by(Contract.created_at.asc()).first()
    if contract:
        return contract
    start_date = employee.hire_date or (offer.onboarding_date if offer else None) or date.today()
    contract = Contract(
        id=new_id(),
        employee_id=employee.id,
        contract_no=f'HT-{employee.employee_no or employee.id[:8]}',
        contract_type='劳动合同',
        start_date=start_date,
        status='draft',
        reminder_date=start_date,
        created_by=owner_id,
        remark='由Offer转员工自动生成，待入职流程中完善合同期限与附件',
    )
    db.session.add(contract)
    return contract


def offer_onboarding_flow_payload(offer, employee, *, created):
    tasks = OnboardingTask.query.filter_by(employee_id=employee.id).order_by(OnboardingTask.created_at.asc()).all()
    contract = Contract.query.filter_by(employee_id=employee.id).order_by(Contract.created_at.asc()).first()
    salary_profile = SalaryProfile.query.filter_by(employee_id=employee.id).first()
    return {
        'employee': employee.to_dict(),
        'created': created,
        'onboardingTasks': [task.to_dict() for task in tasks],
        'contract': contract.to_dict() if contract else None,
        'salaryProfile': salary_profile.to_dict() if salary_profile else None,
        'flow': {
            'id': 'recruit_to_onboard',
            'name': '招聘到入职',
            'modules': ['offers', 'employees', 'onboarding-tasks', 'contracts', 'salary-profiles'],
            'offerId': offer.id if offer else None,
            'employeeId': employee.id,
        },
    }


def _rows_to_dict(rows):
    return [row.to_dict() for row in rows]


def _timeline_value(value):
    if not value:
        return None
    if isinstance(value, str):
        raw = value[:10]
        if len(raw) == 7:
            return f'{raw}-01'
        return raw
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _timeline_item(module, title, record_id, status=None, at=None, extra=None):
    return {
        'module': module,
        'title': title,
        'recordId': record_id,
        'status': status,
        'at': _timeline_value(at),
        'extra': extra or {},
    }


def employee_lifecycle_payload(employee):
    candidate_ids = {employee.candidate_id} if employee.candidate_id else set()
    offer_ids = set()

    candidates = []
    if employee.candidate_id:
        candidate = Candidate.query.get(employee.candidate_id)
        if candidate:
            candidates.append(candidate)
            candidate_ids.add(candidate.id)
    candidate_filters = []
    if candidate_ids:
        candidate_filters.append(Candidate.id.in_(candidate_ids))
    if employee.email:
        candidate_filters.append(Candidate.email == employee.email)
    if employee.name:
        candidate_filters.append(Candidate.name == employee.name)
    if candidate_filters:
        for candidate in Candidate.query.filter(or_(*candidate_filters)).all():
            if candidate.id not in candidate_ids:
                candidates.append(candidate)
                candidate_ids.add(candidate.id)

    resume_ids = {candidate.resume_id for candidate in candidates if candidate.resume_id}
    resumes = []
    resume_filters = []
    if resume_ids:
        resume_filters.append(Resume.id.in_(resume_ids))
    if employee.email:
        resume_filters.append(Resume.email == employee.email)
    if employee.name:
        resume_filters.append(Resume.candidate_name == employee.name)
    if resume_filters:
        seen = set()
        for resume in Resume.query.filter(or_(*resume_filters)).order_by(Resume.created_at.asc()).all():
            if resume.id not in seen:
                resumes.append(resume)
                seen.add(resume.id)
                resume_ids.add(resume.id)

    offers = []
    offer_filters = [Offer.employee_id == employee.id, Offer.employee_id == employee.employee_no]
    if employee.source_offer_id:
        offer_filters.append(Offer.id == employee.source_offer_id)
    if candidate_ids:
        offer_filters.append(Offer.candidate_id.in_(candidate_ids))
    for offer in Offer.query.filter(or_(*offer_filters)).order_by(Offer.created_at.asc()).all():
        if offer.id not in offer_ids:
            offers.append(offer)
        offer_ids.add(offer.id)

    interviews = []
    if resume_ids:
        # 预加载 resume 关系（消除时间线循环内 row.resume 懒加载）
        interviews = Interview.query.options(
            selectinload(Interview.resume)
        ).filter(Interview.resume_id.in_(resume_ids)).order_by(Interview.scheduled_at.asc()).all()

    onboarding_tasks = OnboardingTask.query.filter_by(employee_id=employee.id).order_by(OnboardingTask.due_date.asc()).all()
    contracts = Contract.query.filter_by(employee_id=employee.id).order_by(Contract.start_date.asc()).all()
    attendance_records = AttendanceRecord.query.filter_by(employee_id=employee.id).order_by(AttendanceRecord.attendance_date.asc()).all()
    employee_requests = EmployeeRequest.query.filter_by(employee_id=employee.id).order_by(EmployeeRequest.start_time.asc()).all()
    salary_profiles = SalaryProfile.query.filter_by(employee_id=employee.id).order_by(SalaryProfile.created_at.asc()).all()
    payroll_records = PayrollRecord.query.filter_by(employee_id=employee.id).order_by(PayrollRecord.payroll_month.asc()).all()
    performance_reviews = PerformanceReview.query.options(
        selectinload(PerformanceReview.cycle), selectinload(PerformanceReview.template)
    ).filter_by(employee_id=employee.id).order_by(PerformanceReview.created_at.asc()).all()
    training_records = TrainingRecord.query.options(
        selectinload(TrainingRecord.course)
    ).filter_by(employee_id=employee.id).order_by(TrainingRecord.created_at.asc()).all()
    probations = Probation.query.filter_by(employee_id=employee.id).order_by(Probation.apply_date.asc()).all()
    employee_changes = EmployeeChange.query.filter_by(employee_id=employee.id).order_by(EmployeeChange.effective_date.asc()).all()
    resignations = Resignation.query.filter_by(employee_id=employee.id).order_by(Resignation.apply_date.asc()).all()

    approval_business = [('onboarding', employee.id)]
    approval_business.extend(('offer', row.id) for row in offers)
    approval_business.extend(('employee_request', row.id) for row in employee_requests)
    approval_business.extend(('probation', row.id) for row in probations)
    approval_business.extend(('employee_change', row.id) for row in employee_changes)
    approval_business.extend(('resignation', row.id) for row in resignations)
    approvals = []
    if approval_business:
        approval_filters = [
            (ApprovalInstance.business_type == business_type) & (ApprovalInstance.business_id == business_id)
            for business_type, business_id in approval_business
        ]
        approvals = ApprovalInstance.query.filter(or_(*approval_filters)).order_by(ApprovalInstance.created_at.asc()).all()

    related_ids = {
        employee.id,
        employee.employee_no,
        employee.source_offer_id,
        employee.candidate_id,
        *[row.id for row in resumes],
        *[row.id for row in candidates],
        *[row.id for row in interviews],
        *[row.id for row in offers],
        *[row.id for row in onboarding_tasks],
        *[row.id for row in contracts],
        *[row.id for row in employee_requests],
        *[row.id for row in salary_profiles],
        *[row.id for row in payroll_records],
        *[row.id for row in performance_reviews],
        *[row.id for row in training_records],
        *[row.id for row in probations],
        *[row.id for row in employee_changes],
        *[row.id for row in resignations],
        *[row.id for row in approvals],
    }
    related_ids = {item for item in related_ids if item}
    operation_logs = []
    if related_ids:
        operation_logs = OperationLog.query.filter(or_(
            OperationLog.target_id.in_(related_ids),
            cast(OperationLog.detail, String).like(f'%{employee.id}%'),
        )).order_by(OperationLog.created_at.desc()).limit(30).all()

    timeline = []
    for row in resumes:
        timeline.append(_timeline_item('resumes', f'简历录入：{row.candidate_name}', row.id, None, row.created_at))
    for row in candidates:
        timeline.append(_timeline_item('candidates', f'候选人：{row.name}', row.id, row.status, row.created_at))
    for row in interviews:
        timeline.append(_timeline_item('interviews', f'面试：{row.resume.candidate_name if row.resume else row.id}', row.id, row.status, row.scheduled_at))
    for row in offers:
        timeline.append(_timeline_item('offers', row.title, row.id, row.status, row.created_at))
    timeline.append(_timeline_item('employees', f'员工档案：{employee.name}', employee.id, employee.status, employee.hire_date))
    for row in onboarding_tasks:
        timeline.append(_timeline_item('onboarding-tasks', row.name, row.id, row.status, row.due_date))
    for row in contracts:
        timeline.append(_timeline_item('contracts', row.contract_no or '劳动合同', row.id, row.status, row.start_date))
    for row in probations:
        timeline.append(_timeline_item('probations', f'转正：{employee.name}', row.id, row.status, row.apply_date))
    for row in employee_changes:
        timeline.append(_timeline_item('employee-changes', f'人事异动：{row.change_type}', row.id, row.status, row.effective_date))
    for row in performance_reviews:
        timeline.append(_timeline_item('performance-reviews', f'绩效评估：{row.cycle.name if row.cycle else row.id}', row.id, row.status, row.created_at))
    for row in training_records:
        timeline.append(_timeline_item('training-records', f'培训：{row.course.name if row.course else row.id}', row.id, row.status, row.created_at))
    for row in employee_requests:
        timeline.append(_timeline_item('employee-requests', row.title or row.request_type, row.id, row.status, row.start_time))
    for row in payroll_records:
        timeline.append(_timeline_item('payroll-records', f'工资条：{row.payroll_month}', row.id, row.status, row.payroll_month))
    for row in resignations:
        timeline.append(_timeline_item('resignations', f'离职：{employee.name}', row.id, row.status, row.actual_leave_date or row.expected_leave_date or row.apply_date))
    timeline = sorted(timeline, key=lambda item: item.get('at') or '')

    records = {
        'resumes': _rows_to_dict(resumes),
        'candidates': _rows_to_dict(candidates),
        'interviews': _rows_to_dict(interviews),
        'offers': _rows_to_dict(offers),
        'onboardingTasks': _rows_to_dict(onboarding_tasks),
        'contracts': _rows_to_dict(contracts),
        'attendanceRecords': _rows_to_dict(attendance_records),
        'employeeRequests': _rows_to_dict(employee_requests),
        'salaryProfiles': _rows_to_dict(salary_profiles),
        'payrollRecords': _rows_to_dict(payroll_records),
        'performanceReviews': _rows_to_dict(performance_reviews),
        'trainingRecords': _rows_to_dict(training_records),
        'probations': _rows_to_dict(probations),
        'employeeChanges': _rows_to_dict(employee_changes),
        'resignations': _rows_to_dict(resignations),
        'approvals': _rows_to_dict(approvals),
        'operationLogs': _rows_to_dict(operation_logs),
    }
    module_counts = {key: len(value) for key, value in records.items()}

    checks = [
        {
            'id': 'recruitment_source',
            'label': '招聘来源',
            'ok': bool(resumes and candidates and offers),
            'modules': ['resumes', 'candidates', 'interviews', 'offers'],
        },
        {
            'id': 'onboarding_foundation',
            'label': '入职基础',
            'ok': bool(onboarding_tasks and contracts and salary_profiles),
            'modules': ['onboarding-tasks', 'contracts', 'salary-profiles'],
        },
        {
            'id': 'attendance_to_payroll',
            'label': '考勤薪酬',
            'ok': bool(attendance_records and payroll_records),
            'modules': ['attendance-records', 'employee-requests', 'payroll-records'],
        },
        {
            'id': 'growth_compensation',
            'label': '成长薪酬',
            'ok': bool(performance_reviews and training_records),
            'modules': ['performance-reviews', 'training-records', 'employee-changes'],
        },
        {
            'id': 'approval_trace',
            'label': '审批追踪',
            'ok': bool(approvals),
            'modules': ['approvals', 'operation-logs'],
        },
    ]
    if employee.status == 'resigned':
        checks.append({
            'id': 'separation',
            'label': '离职闭环',
            'ok': bool(resignations and any(row.status == 'approved' for row in approvals)),
            'modules': ['resignations', 'approvals'],
        })

    return {
        'employee': employee.to_dict(),
        'moduleCounts': module_counts,
        'connectivity': checks,
        'timeline': timeline,
        'records': records,
        'flow': {
            'id': 'employee_lifecycle',
            'name': '员工全生命周期',
            'modules': [
                'resumes', 'candidates', 'interviews', 'offers', 'employees', 'onboarding-tasks',
                'contracts', 'attendance-records', 'employee-requests', 'salary-profiles',
                'payroll-records', 'performance-reviews', 'training-records', 'probations',
                'employee-changes', 'resignations', 'approvals', 'operation-logs',
            ],
        },
    }


def calculate_payroll(obj):
    gross = sum([
        obj.base_salary or Decimal('0'), obj.position_salary or Decimal('0'), obj.performance_salary or Decimal('0'),
        obj.bonus or Decimal('0'), obj.allowance or Decimal('0'),
    ])
    obj.gross_salary = obj.gross_salary or gross
    obj.net_salary = obj.net_salary or (gross - (obj.deduction or Decimal('0')))


PAYROLL_ACTIVE_EMPLOYEE_STATUSES = ('active', 'probation')
PAYROLL_STATUS_ORDER = ('normal', 'late', 'early_leave', 'missing_card', 'leave', 'overtime')
PAYROLL_APPROVED_STATUSES = ('approved',)
PAYROLL_WORKDAYS_PER_MONTH = Decimal('21.75')
PAYROLL_WORK_HOURS_PER_DAY = Decimal('8')
PAYROLL_OVERTIME_RATE = Decimal('1.5')
PAYROLL_LATE_DEDUCTION = Decimal('20')
PAYROLL_EARLY_LEAVE_DEDUCTION = Decimal('20')
PAYROLL_MISSING_CARD_DEDUCTION = Decimal('50')
PAYROLL_MONEY = Decimal('0.01')


def payroll_money(value):
    return (value or Decimal('0')).quantize(PAYROLL_MONEY, rounding=ROUND_HALF_UP)


def parse_payroll_month(value):
    raw = str(value or '').strip()
    if not raw:
        return date.today().strftime('%Y-%m')
    try:
        return datetime.strptime(raw[:7], '%Y-%m').strftime('%Y-%m')
    except ValueError:
        return None


def payroll_month_bounds(month_key):
    start = datetime.strptime(month_key, '%Y-%m').date()
    return start, add_months(start, 1)


def request_type_matches(value, aliases):
    raw = str(value or '').strip().lower()
    return raw in aliases


def payroll_attendance_status_counts(employee_id, start, end):
    rows = AttendanceRecord.query.filter(
        AttendanceRecord.employee_id == employee_id,
        AttendanceRecord.attendance_date >= start,
        AttendanceRecord.attendance_date < end,
    ).all()
    counts = {}
    for row in rows:
        status = row.status or 'unknown'
        counts[status] = counts.get(status, 0) + 1
    return rows, counts


def payroll_approved_request_hours(employee_id, start, end):
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.min.time())
    rows = EmployeeRequest.query.filter(
        EmployeeRequest.employee_id == employee_id,
        EmployeeRequest.status.in_(PAYROLL_APPROVED_STATUSES),
        EmployeeRequest.start_time >= start_dt,
        EmployeeRequest.start_time < end_dt,
    ).all()
    leave_hours = Decimal('0')
    overtime_hours = Decimal('0')
    for row in rows:
        hours = row.duration_hours or Decimal('0')
        if request_type_matches(row.request_type, {'leave', '请假'}):
            leave_hours += hours
        elif request_type_matches(row.request_type, {'overtime', '加班'}):
            overtime_hours += hours
    return rows, leave_hours, overtime_hours


def payroll_status_summary(status_counts):
    parts = []
    seen = set()
    for status in PAYROLL_STATUS_ORDER:
        if status_counts.get(status):
            parts.append(f'{status}={status_counts[status]}')
            seen.add(status)
    for status in sorted(set(status_counts) - seen):
        parts.append(f'{status}={status_counts[status]}')
    return ', '.join(parts) if parts else 'none'


def build_monthly_payroll_record(profile, employee, month_key, attendance_rows=None,
                                  status_counts=None, request_rows=None,
                                  leave_hours=None, overtime_hours=None, existing_record=None):
    """构建/更新单条月度工资记录。

    支持两种调用方式：
    - 单条调用（默认）：内部自行查 attendance/request/existing record（向后兼容）
    - 批量调用：调用方预取 attendance_rows/status_counts/request_rows/leave_hours/
      overtime_hours/existing_record 传入，避免逐员工查库的 N+1。
    """
    start, end = payroll_month_bounds(month_key)
    if attendance_rows is None or status_counts is None:
        attendance_rows, status_counts = payroll_attendance_status_counts(employee.id, start, end)
    if request_rows is None or leave_hours is None or overtime_hours is None:
        request_rows, leave_hours, overtime_hours = payroll_approved_request_hours(employee.id, start, end)

    base_salary = payroll_money(profile.base_salary)
    position_salary = payroll_money(profile.position_salary)
    performance_salary = payroll_money(profile.performance_salary)
    allowance = payroll_money(profile.allowance)
    profile_bonus = payroll_money(profile.bonus)
    profile_deduction = payroll_money(profile.deduction)

    hourly_rate = Decimal('0')
    if PAYROLL_WORKDAYS_PER_MONTH and PAYROLL_WORK_HOURS_PER_DAY:
        hourly_rate = base_salary / PAYROLL_WORKDAYS_PER_MONTH / PAYROLL_WORK_HOURS_PER_DAY
    leave_deduction = payroll_money(leave_hours * hourly_rate)
    overtime_bonus = payroll_money(overtime_hours * hourly_rate * PAYROLL_OVERTIME_RATE)
    late_deduction = PAYROLL_LATE_DEDUCTION * Decimal(status_counts.get('late', 0))
    early_leave_deduction = PAYROLL_EARLY_LEAVE_DEDUCTION * Decimal(status_counts.get('early_leave', 0))
    missing_card_deduction = PAYROLL_MISSING_CARD_DEDUCTION * Decimal(status_counts.get('missing_card', 0))

    bonus = payroll_money(profile_bonus + overtime_bonus)
    deduction = payroll_money(
        profile_deduction + leave_deduction + late_deduction + early_leave_deduction + missing_card_deduction
    )
    gross = payroll_money(base_salary + position_salary + performance_salary + allowance + bonus)
    net = payroll_money(gross - deduction)

    # 优先使用调用方预取的 existing_record，否则回退到单条查询（向后兼容）
    if existing_record is not None:
        record = existing_record
        created = False
    else:
        record = PayrollRecord.query.filter_by(employee_id=employee.id, payroll_month=month_key).first()
        created = record is None
        if created:
            record = PayrollRecord(id=new_id(), employee_id=employee.id, payroll_month=month_key)
            db.session.add(record)

    record.base_salary = base_salary
    record.position_salary = position_salary
    record.performance_salary = performance_salary
    record.allowance = allowance
    record.bonus = bonus
    record.deduction = deduction
    record.gross_salary = gross
    record.net_salary = net
    record.status = 'calculated'
    record.employee_visible = False
    record.remark = (
        f'Generated from salary profile and monthly attendance. '
        f'attendance: {payroll_status_summary(status_counts)}. '
        f'requests: leave_hours={payroll_money(leave_hours):.2f}, overtime_hours={payroll_money(overtime_hours):.2f}. '
        f'adjustments: overtime_bonus={overtime_bonus:.2f}, leave_deduction={leave_deduction:.2f}, '
        f'late_deduction={late_deduction:.2f}, early_leave_deduction={early_leave_deduction:.2f}, '
        f'missing_card_deduction={missing_card_deduction:.2f}.'
    )
    record.updated_at = datetime.utcnow()

    metrics = {
        'attendanceRecords': len(attendance_rows),
        'attendanceExceptions': sum(count for status, count in status_counts.items() if status != 'normal'),
        'approvedRequests': len(request_rows),
        'approvedLeaveHours': payroll_money(leave_hours),
        'approvedOvertimeHours': payroll_money(overtime_hours),
        'overtimeBonus': overtime_bonus,
        'attendanceDeduction': payroll_money(leave_deduction + late_deduction + early_leave_deduction + missing_card_deduction),
    }
    return record, created, metrics


def decimal_metric(value):
    return float(payroll_money(value))


def monthly_payroll_flow_payload(month_key, records, created_count, updated_count, skipped_profiles, metrics):
    return {
        'month': month_key,
        'createdCount': created_count,
        'updatedCount': updated_count,
        'skippedCount': len(skipped_profiles),
        'skippedProfiles': skipped_profiles,
        'records': [record.to_dict() for record in records],
        'metrics': {
            'employees': len(records),
            'attendanceRecords': metrics['attendanceRecords'],
            'attendanceExceptions': metrics['attendanceExceptions'],
            'approvedRequests': metrics['approvedRequests'],
            'approvedLeaveHours': decimal_metric(metrics['approvedLeaveHours']),
            'approvedOvertimeHours': decimal_metric(metrics['approvedOvertimeHours']),
            'overtimeBonus': decimal_metric(metrics['overtimeBonus']),
            'attendanceDeduction': decimal_metric(metrics['attendanceDeduction']),
            'grossTotal': decimal_metric(metrics['grossTotal']),
            'netTotal': decimal_metric(metrics['netTotal']),
        },
        'flow': {
            'id': 'attendance_to_payroll',
            'name': 'Attendance to payroll',
            'modules': ['attendance-records', 'employee-requests', 'salary-profiles', 'payroll-records'],
        },
    }


def performance_salary_change_payload(review, change, created):
    profile = SalaryProfile.query.filter_by(employee_id=review.employee_id).first()
    return {
        'created': created,
        'performanceReview': review.to_dict(),
        'salaryChange': change.to_dict(),
        'salaryProfile': profile.to_dict() if profile else None,
        'flow': {
            'id': 'performance_to_compensation',
            'name': 'Performance to compensation',
            'modules': ['performance-reviews', 'employee-changes', 'salary-profiles', 'payroll-records'],
        },
    }


def performance_training_flow_payload(review, course, plan, record, created):
    return {
        'created': created,
        'performanceReview': review.to_dict(),
        'trainingCourse': course.to_dict(),
        'trainingPlan': plan.to_dict(),
        'trainingRecord': record.to_dict(),
        'flow': {
            'id': 'performance_to_growth',
            'name': 'Performance to growth',
            'modules': ['performance-reviews', 'training-courses', 'training-plans', 'training-records'],
        },
    }


def build_ai_result(scene, payload):
    record = payload.get('record') or {}
    module = payload.get('module') or scene
    name = record.get('name') or record.get('candidateName') or record.get('employeeName') or record.get('title') or '该对象'
    if scene in ('candidate-summary', 'candidate'):
        text = f'{name}当前处于{record.get("status", "候选人")}阶段，建议结合简历AI评分、面试表现和岗位匹配度判断推进优先级。'
    elif scene in ('hiring-advice', 'offer'):
        text = f'{name}的录用决策建议：确认薪资预算、岗位HC和面试结论后再发起Offer审批；如候选人匹配度高，可优先推进。'
    elif scene in ('employee-summary', 'employee'):
        text = f'{name}员工档案摘要：请重点关注所属部门、岗位、入职日期、合同状态、考勤异常和绩效记录，作为人事动作依据。'
    elif scene in ('probation-draft', 'probation'):
        text = f'{name}转正评价草稿：试用期表现总体可从目标达成、岗位胜任、协作沟通、学习成长四方面评价，并给出是否转正建议。'
    elif scene in ('resignation-summary', 'resignation'):
        text = f'{name}离职原因总结：建议从薪酬福利、管理关系、职业发展、工作强度和个人原因维度归类，沉淀组织改进建议。'
    elif scene in ('dashboard-advice', 'dashboard'):
        text = 'HR数据分析建议：关注招聘转化率、待入职积压、考勤异常、试用期转正和离职原因；建议设置月度人力例会跟踪趋势。'
    else:
        text = f'{module} AI建议：当前为基础版规则生成，已预留后续接入大模型接口的位置，可结合业务上下文生成更完整内容。'
    return {
        'scene': scene,
        'summary': text,
        'suggestions': [
            '补齐关键字段，保证数据可追踪',
            '对待审批事项设置责任人和截止时间',
            '将AI结论作为辅助建议，不替代HR最终判断',
        ],
        'generatedAt': datetime.utcnow().isoformat(),
    }


@hrm_bp.route('/meta', methods=['GET'])
@jwt_required()
def get_meta():
    from services.hrm_module_catalog import module_catalog_payload

    return jsonify({
        'resources': sorted(RESOURCE_CONFIG.keys()),
        'moduleCatalog': module_catalog_payload(),
        'roles': [role.to_dict() for role in Role.query.order_by(Role.code.asc()).all()],
        'statusOptions': {
            'employee': ['pending_onboard', 'probation', 'active', 'inactive', 'resigned'],
            'approval': ['draft', 'pending', 'approved', 'rejected', 'cancelled'],
            'offer': ['draft', 'pending', 'sent', 'accepted', 'rejected', 'converted'],
            'attendance': ['normal', 'late', 'early_leave', 'missing_card', 'leave', 'overtime'],
            'requestType': ['leave', 'overtime', 'travel', '补卡'],
        },
    })


@hrm_bp.route('/tenant/modules', methods=['GET'])
@jwt_required()
def current_tenant_modules():
    tenant_id = current_tenant_id()
    if not tenant_id:
        return jsonify({'error': '缺少企业租户上下文', 'code': 'TENANT_REQUIRED'}), 403
    modules = TenantModule.query.filter_by(tenant_id=tenant_id).order_by(TenantModule.module_key.asc()).all()
    return jsonify([module.to_dict() for module in modules])


@hrm_bp.route('/dashboard', methods=['GET'])
@jwt_required()
def dashboard():
    denied = require_roles(ORG_READ_ROLES | PAYROLL_READ_ROLES, '无权限查看 HR 仪表盘')
    if denied:
        return denied
    today = date.today()
    month_start = today.replace(day=1)
    month_key = today.strftime('%Y-%m')
    active_statuses = ['probation', 'active']

    department_distribution = []
    # 单次 GROUP BY 查询替代 N+1 循环
    dept_counts = (
        db.session.query(Department.name, func.count(Employee.id))
        .outerjoin(Employee, (Employee.department_id == Department.id) & Employee.status.in_(active_statuses))
        .group_by(Department.id, Department.name)
        .order_by(Department.name.asc())
        .all()
    )
    for dept_name, count in dept_counts:
        department_distribution.append({'name': dept_name, 'value': count})

    employee_status_distribution = [
        {'name': status or 'unknown', 'value': count}
        for status, count in db.session.query(Employee.status, func.count(Employee.id)).group_by(Employee.status).all()
    ]

    performance_distribution = [
        {'name': grade or '未评级', 'value': count}
        for grade, count in db.session.query(PerformanceReview.grade, func.count(PerformanceReview.id)).group_by(PerformanceReview.grade).all()
    ]

    request_distribution = [
        {'name': req_type or 'unknown', 'value': count}
        for req_type, count in db.session.query(EmployeeRequest.request_type, func.count(EmployeeRequest.id)).group_by(EmployeeRequest.request_type).all()
    ]

    payroll_total = db.session.query(func.coalesce(func.sum(PayrollRecord.net_salary), 0)).filter(PayrollRecord.payroll_month == month_key).scalar()

    data = {
        'cards': {
            'activeEmployees': Employee.query.filter(Employee.status.in_(active_statuses)).count(),
            'pendingOnboard': Employee.query.filter(Employee.status == 'pending_onboard').count(),
            'monthOnboard': Employee.query.filter(Employee.hire_date >= month_start).count(),
            'monthResigned': Resignation.query.filter(Resignation.actual_leave_date >= month_start).count(),
            'openJobs': Job.query.filter(Job.status == 'open').count(),
            'resumes': Resume.query.count(),
            'interviews': Interview.query.count(),
            'offers': Offer.query.count(),
            'attendanceExceptions': AttendanceRecord.query.filter(AttendanceRecord.status != 'normal').count(),
            'requests': EmployeeRequest.query.count(),
            'payrollTotal': float(payroll_total or 0),
        },
        'departmentDistribution': department_distribution,
        'employeeStatusDistribution': employee_status_distribution,
        'requestDistribution': request_distribution,
        'performanceDistribution': performance_distribution,
        'aiAdvice': build_ai_result('dashboard-advice', {}).get('summary'),
    }
    return jsonify(data)


@hrm_bp.route('/attendance/monthly', methods=['GET'])
@jwt_required()
def attendance_monthly():
    denied = require_roles(ORG_READ_ROLES | PAYROLL_READ_ROLES, '无权限查看月度考勤')
    if denied:
        return denied
    month = request.args.get('month') or date.today().strftime('%Y-%m')
    start = datetime.strptime(month + '-01', '%Y-%m-%d').date()
    end = add_months(start, 1)
    record_query = AttendanceRecord.query.join(Employee, AttendanceRecord.employee_id == Employee.id).filter(
        AttendanceRecord.attendance_date >= start,
        AttendanceRecord.attendance_date < end,
    )
    tenant_id = current_tenant_id()
    if tenant_id:
        record_query = record_query.filter(Employee.tenant_id == tenant_id)
    records = record_query.all()
    by_employee = {}

    def employee_item(employee_id, employee=None):
        item = by_employee.setdefault(employee_id, {
            'employeeId': employee_id,
            'employeeName': employee.name if employee else None,
            'normal': 0, 'late': 0, 'earlyLeave': 0, 'missingCard': 0, 'leave': 0, 'overtime': 0,
            'travel': 0, 'makeupCard': 0, 'approvedRequests': 0, 'exceptions': 0,
        })
        if employee and not item.get('employeeName'):
            item['employeeName'] = employee.name
        return item

    for record in records:
        item = employee_item(record.employee_id, record.employee)
        status = record.status
        if status == 'normal':
            item['normal'] += 1
        elif status == 'late':
            item['late'] += 1; item['exceptions'] += 1
        elif status == 'early_leave':
            item['earlyLeave'] += 1; item['exceptions'] += 1
        elif status == 'missing_card':
            item['missingCard'] += 1; item['exceptions'] += 1
        elif status == 'leave':
            item['leave'] += 1
        elif status == 'overtime':
            item['overtime'] += 1
        elif status == 'travel':
            item['travel'] += 1
        elif status == 'makeup_card':
            item['makeupCard'] += 1

    approved_requests = EmployeeRequest.query.filter(
        EmployeeRequest.status == 'approved',
        EmployeeRequest.start_time >= datetime.combine(start, datetime.min.time()),
        EmployeeRequest.start_time < datetime.combine(end, datetime.min.time()),
    ).all()
    request_status_map = {
        'leave': 'leave',
        '请假': 'leave',
        'overtime': 'overtime',
        '加班': 'overtime',
        'travel': 'travel',
        '出差': 'travel',
        'makeup_card': 'makeupCard',
        '补卡': 'makeupCard',
    }
    request_sources = []
    for req in approved_requests:
        item = employee_item(req.employee_id, req.employee)
        key = request_status_map.get(str(req.request_type or '').strip())
        if not key:
            continue
        item[key] += 1
        item['approvedRequests'] += 1
        request_sources.append(req.to_dict())

    rows = list(by_employee.values())
    return jsonify({
        'month': month,
        'records': rows,
        'sourceCounts': {
            'attendanceRecords': AttendanceRecord.query.count(),
            'attendanceRecordsInMonth': len(records),
            'approvedRequests': len(approved_requests),
        },
        'requestSources': request_sources,
        'flow': {
            'id': 'attendance_to_payroll',
            'modules': ['attendance-records', 'employee-requests', 'attendance-stats', 'payroll-records'],
        },
    })


@hrm_bp.route('/approvals/my-applications', methods=['GET'])
@jwt_required()
def my_applications():
    user_id = get_jwt_identity()
    data = ApprovalInstance.query.options(
        selectinload(ApprovalInstance.applicant), selectinload(ApprovalInstance.approver)
    ).filter_by(applicant_id=user_id).order_by(ApprovalInstance.created_at.desc()).all()
    return jsonify([item.to_dict() for item in data])


@hrm_bp.route('/approvals/pending', methods=['GET'])
@jwt_required()
def pending_approvals():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    query = ApprovalInstance.query.options(
        selectinload(ApprovalInstance.applicant), selectinload(ApprovalInstance.approver)
    ).filter_by(status='pending')
    if not user or user.role not in ('admin', 'hr_admin', 'manager', 'executive'):
        query = query.filter(ApprovalInstance.approver_id == user_id)
    data = query.order_by(ApprovalInstance.created_at.desc()).all()
    return jsonify([item.to_dict() for item in data])


@hrm_bp.route('/approvals/records', methods=['GET'])
@jwt_required()
def approval_records():
    denied = require_roles(APPROVAL_ROLES, '无权限查看审批记录')
    if denied:
        return denied
    # selectinload 消除 to_dict 内 approval/approver 懒加载的 N+1（上限 300 行）
    data = ApprovalRecord.query.options(
        selectinload(ApprovalRecord.approval), selectinload(ApprovalRecord.approver)
    ).order_by(ApprovalRecord.created_at.desc()).limit(300).all()
    return jsonify([item.to_dict() for item in data])


@hrm_bp.route('/approvals/<approval_id>/<action>', methods=['POST'])
@jwt_required()
def handle_approval(approval_id, action):
    denied = require_roles(APPROVAL_ROLES, '无权限处理审批')
    if denied:
        return denied
    if action not in ('approve', 'reject'):
        return jsonify({'error': 'Unsupported action'}), 400
    data = request.get_json() or {}
    try:
        completed = complete_approval(
            approval_id,
            action,
            approver_id=get_jwt_identity(),
            comment=data.get('comment'),
            operation_source='approval_center',
            ip=request.headers.get('X-Forwarded-For', request.remote_addr),
        )
    except LookupError:
        return jsonify({'error': 'Approval not found'}), 404
    except RuntimeError:
        return jsonify({'error': 'Approval already completed'}), 400
    except ValueError:
        return jsonify({'error': 'Unsupported action'}), 400
    db.session.commit()
    return jsonify({'approval': completed['approval'].to_dict(), 'record': completed['record'].to_dict()})


@hrm_bp.route('/ai/<scene>', methods=['POST'])
@jwt_required()
def ai_scene(scene):
    result = build_ai_result(scene, request.get_json() or {})
    return jsonify(result)


@hrm_bp.route('/assistant/skills', methods=['GET'])
@jwt_required()
def assistant_list_skills():
    """返回当前用户角色可用的技能卡片列表（含表单字段定义）。"""
    from models import User
    user = User.query.get(get_jwt_identity())
    role = (user.role if user else 'viewer') or 'viewer'
    from services.assistant_core.skill_cards import get_cards_for_role
    cards = get_cards_for_role(role)
    return jsonify(cards)


@hrm_bp.route('/ai/entitlements', methods=['GET'])
@jwt_required()
def tenant_ai_entitlements():
    tenant_id = current_tenant_id()
    if not tenant_id:
        return jsonify({'error': '缺少企业租户上下文', 'code': 'TENANT_REQUIRED'}), 403
    return jsonify(tenant_entitlement_payload(tenant_id))


@hrm_bp.route('/ai/usage', methods=['GET'])
@jwt_required()
def tenant_ai_usage():
    tenant_id = current_tenant_id()
    if not tenant_id:
        return jsonify({'error': '缺少企业租户上下文', 'code': 'TENANT_REQUIRED'}), 403
    return jsonify(tenant_usage_payload(tenant_id, tenant_safe=True))


@hrm_bp.route('/ai/entitlements/<resource_domain>/select-tier', methods=['POST'])
@jwt_required()
def tenant_ai_select_tier(resource_domain):
    tenant_id = current_tenant_id()
    if not tenant_id:
        return jsonify({'error': '缺少企业租户上下文', 'code': 'TENANT_REQUIRED'}), 403
    data = request.get_json() or {}
    try:
        row = select_tenant_tier(tenant_id, resource_domain, str(data.get('tier') or '').strip())
    except AIResourceDenied as exc:
        return _ai_error_response(exc)
    return jsonify({'entitlement': row.to_dict(tenant_safe=True)})


@hrm_bp.route('/assistant/optimize-prompt', methods=['POST'])
@jwt_required()
def assistant_optimize_prompt():
    """Turn a rough request into an executable, evidence-grounded assistant prompt."""
    allowed = _require_ai_resource('assistant', 'prompt_optimization')
    if not hasattr(allowed, 'resource_domain'):
        return allowed
    from services.assistant_core.memory import build_context
    from services.assistant_core.prompt_optimizer import optimize_prompt

    data = request.get_json() or {}
    text = str(data.get('prompt') or '')[:800]
    session_id = str(data.get('sessionId') or '').strip() or None
    ctx = build_context(get_jwt_identity(), session_id)
    return jsonify(optimize_prompt(text, ctx))


@hrm_bp.route('/assistant/model-call-test', methods=['POST'])
@jwt_required()
def assistant_model_call_test():
    """Run a real LLM connectivity test and write the normal audit log."""
    return jsonify({'error': 'AI 诊断已迁移至平台后台', 'code': 'PLATFORM_AI_DIAGNOSTICS_ONLY'}), 403


@hrm_bp.route('/assistant/model-stream-test', methods=['POST'])
@jwt_required()
def assistant_model_stream_test():
    """Run a real streaming LLM connectivity test and audit the provider call."""
    return jsonify({'error': 'AI 诊断已迁移至平台后台', 'code': 'PLATFORM_AI_DIAGNOSTICS_ONLY'}), 403


@hrm_bp.route('/assistant/evaluation-cases', methods=['GET'])
@jwt_required()
def assistant_evaluation_cases():
    """Return systematic Copilot evaluation cases and root-cause taxonomy."""
    return jsonify({'error': 'AI 评估已迁移至平台后台', 'code': 'PLATFORM_AI_DIAGNOSTICS_ONLY'}), 403


@hrm_bp.route('/assistant/evaluation-runs', methods=['GET'])
@jwt_required()
def assistant_evaluation_runs():
    """List recent Copilot evaluation records."""
    return jsonify({'error': 'AI 评估已迁移至平台后台', 'code': 'PLATFORM_AI_DIAGNOSTICS_ONLY'}), 403


@hrm_bp.route('/assistant/evaluation-runs/<run_id>', methods=['GET'])
@jwt_required()
def assistant_evaluation_run_detail(run_id):
    """Return one evaluation record with captured response payload."""
    return jsonify({'error': 'AI 评估已迁移至平台后台', 'code': 'PLATFORM_AI_DIAGNOSTICS_ONLY'}), 403


@hrm_bp.route('/assistant/evaluation-runs', methods=['POST'])
@jwt_required()
def assistant_evaluation_run_create():
    """Run one or more Copilot evaluation cases and persist results."""
    return jsonify({'error': 'AI 评估已迁移至平台后台', 'code': 'PLATFORM_AI_DIAGNOSTICS_ONLY'}), 403


@hrm_bp.route('/assistant/transcribe', methods=['POST'])
@jwt_required()
def assistant_transcribe_audio():
    """Transcribe short assistant voice input snippets into editable prompt text."""
    allowed = _require_ai_resource('assistant', 'assistant_voice_transcription')
    if not hasattr(allowed, 'resource_domain'):
        return allowed
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'error': '请上传语音文件'}), 400

    raw_name = secure_filename(file.filename) or 'assistant-voice.webm'
    ext = raw_name.rsplit('.', 1)[1].lower() if '.' in raw_name else 'webm'
    if ext not in {'webm', 'wav', 'mp3', 'm4a', 'ogg', 'mpeg', 'mp4'}:
        return jsonify({'error': '暂不支持该音频格式'}), 400

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp:
            temp_path = tmp.name
            file.save(tmp)
        if os.path.getsize(temp_path) > 10 * 1024 * 1024:
            return jsonify({'error': '语音片段过长，请控制在 10MB 以内'}), 400

        from services.speech_to_text import format_transcript, transcribe_audio

        result = transcribe_audio(
            temp_path,
            language='zh',
            tenant_id=current_tenant_id(),
            user_id=get_jwt_identity(),
            resource_domain='assistant',
            use_case='assistant_voice_transcription',
            request_id=getattr(g, 'request_id', None) or request.headers.get('X-Request-ID'),
        )
        if not result.get('success'):
            return jsonify({'error': result.get('error') or '语音识别失败'}), 502
        text = format_transcript(result.get('text') or '')
        return jsonify({'text': text, 'provider': 'server_asr'})
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


@hrm_bp.route('/assistant/model-settings', methods=['GET'])
@jwt_required()
def assistant_model_settings_get():
    """Return effective model routing configuration for the agent console."""
    from services.assistant_core.model_settings import public_settings

    return jsonify(public_settings())


@hrm_bp.route('/assistant/model-settings', methods=['POST'])
@jwt_required()
def assistant_model_settings_update():
    """Persist model profiles and agent reasoning feature switches."""
    from services.assistant_core.model_settings import public_settings, save_settings

    user = User.query.get(get_jwt_identity())
    if not user or user.role not in ('admin', 'hr_admin'):
        return jsonify({'error': '仅管理员可修改 AI 模型配置'}), 403
    save_settings(request.get_json() or {})
    return jsonify(public_settings())


def _current_user_can_manage_assistant():
    user = User.query.get(get_jwt_identity())
    return bool(user and user.role in ('admin', 'hr_admin'))


def _assistant_audit_query_from_request():
    query = AssistantAuditLog.query
    days = request.args.get('days', type=int)
    if days:
        days = min(max(days, 1), 365)
        query = query.filter(AssistantAuditLog.created_at >= datetime.utcnow() - timedelta(days=days))

    filters = {
        'userId': ('user_id', request.args.get('userId')),
        'sessionId': ('session_id', request.args.get('sessionId')),
        'useCase': ('use_case', request.args.get('useCase')),
        'modelProfile': ('model_profile', request.args.get('modelProfile')),
        'status': ('status', request.args.get('status')),
        'model': ('model', request.args.get('model')),
    }
    for _, (attr, value) in filters.items():
        if value:
            query = query.filter(getattr(AssistantAuditLog, attr) == value)

    keyword = (request.args.get('keyword') or '').strip()
    if keyword:
        like = f'%{keyword}%'
        query = query.outerjoin(User, AssistantAuditLog.user_id == User.id).filter(or_(
            AssistantAuditLog.request_id.like(like),
            AssistantAuditLog.model.like(like),
            AssistantAuditLog.use_case.like(like),
            AssistantAuditLog.response_content.like(like),
            AssistantAuditLog.error_message.like(like),
            cast(AssistantAuditLog.prompt_messages, String).like(like),
            cast(AssistantAuditLog.response_meta, String).like(like),
            User.name.like(like),
            User.email.like(like),
        ))
    return query


def _assistant_stream_skips_provider(result):
    if not isinstance(result, dict):
        return False
    meta = result.get('meta') if isinstance(result.get('meta'), dict) else {}
    route_decision = meta.get('routeDecision') if isinstance(meta.get('routeDecision'), dict) else {}
    copilot = result.get('copilot') if isinstance(result.get('copilot'), dict) else {}
    safety_flags = route_decision.get('safetyFlags') if isinstance(route_decision.get('safetyFlags'), list) else []
    return (
        str(meta.get('routeTrack') or route_decision.get('routeTrack') or copilot.get('routeTrack') or '') == 'CONFIRMED_ACTION'
        or str(route_decision.get('intent') or meta.get('taskTemplateId') or copilot.get('intent') or '') == 'execute_pending_action'
        or str(meta.get('taskType') or route_decision.get('taskType') or copilot.get('taskType') or '') == 'forbidden'
        or str(meta.get('errorCode') or copilot.get('errorCode') or '') == 'permission_denied'
        or 'permission_denied' in safety_flags
    )


@hrm_bp.route('/assistant/audit-logs', methods=['GET'])
@jwt_required()
def assistant_audit_logs_list():
    """List model-call audit records for AI governance."""
    if not _current_user_can_manage_assistant():
        return jsonify({'error': '仅管理员可查看 AI 调用审计'}), 403

    limit = min(max(request.args.get('limit', default=50, type=int) or 50, 1), 200)
    query = _assistant_audit_query_from_request()
    rows = query.order_by(AssistantAuditLog.created_at.desc()).limit(limit).all()
    return jsonify([row.to_dict() for row in rows])


@hrm_bp.route('/assistant/audit-summary', methods=['GET'])
@jwt_required()
def assistant_audit_summary():
    """Aggregate model-call audit records for monitoring and optimization."""
    if not _current_user_can_manage_assistant():
        return jsonify({'error': '仅管理员可查看 AI 调用审计'}), 403

    rows = _assistant_audit_query_from_request().order_by(AssistantAuditLog.created_at.desc()).limit(1000).all()
    latencies = [row.latency_ms for row in rows if row.latency_ms is not None]

    def breakdown(getter, limit=8):
        counts = {}
        for row in rows:
            key = getter(row) or 'unknown'
            counts[key] = counts.get(key, 0) + 1
        return [
            {'name': key, 'count': count}
            for key, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
        ]

    by_status = breakdown(lambda row: row.status)
    status_counts = {item['name']: item['count'] for item in by_status}
    recent_errors = [
        row.to_dict()
        for row in rows
        if row.status != 'success' or row.error_message
    ][:5]

    return jsonify({
        'generatedAt': datetime.utcnow().isoformat(),
        'totalCalls': len(rows),
        'successCount': status_counts.get('success', 0),
        'errorCount': sum(
            count for status, count in status_counts.items()
            if status not in ('success', 'timeout')
        ),
        'timeoutCount': status_counts.get('timeout', 0),
        'avgLatencyMs': round(sum(latencies) / len(latencies), 1) if latencies else None,
        'maxLatencyMs': max(latencies) if latencies else None,
        'promptChars': sum(row.prompt_chars or 0 for row in rows),
        'responseChars': sum(row.response_chars or 0 for row in rows),
        'byStatus': by_status,
        'byProfile': breakdown(lambda row: row.model_profile),
        'byUseCase': breakdown(lambda row: row.use_case),
        'byModel': breakdown(lambda row: row.model),
        'recentErrors': recent_errors,
    })


@hrm_bp.route('/assistant/audit-logs/<log_id>', methods=['GET'])
@jwt_required()
def assistant_audit_log_detail(log_id):
    """Return a single audit record including prompt and response payload."""
    if not _current_user_can_manage_assistant():
        return jsonify({'error': '仅管理员可查看 AI 调用审计'}), 403
    row = AssistantAuditLog.query.get(log_id)
    if not row:
        return jsonify({'error': '审计记录不存在'}), 404
    return jsonify(row.to_dict(include_payload=True))


@hrm_bp.route('/assistant/skill-first/route-traces', methods=['GET'])
@jwt_required()
def assistant_skill_first_route_traces():
    """List Skill-first route traces for route debugging and replay."""
    if not _current_user_can_manage_assistant():
        return jsonify({'error': '仅管理员可查看 Skill-first 路由轨迹'}), 403
    from services.assistant_core.skill_first.observability import query_route_traces

    rows = query_route_traces(
        limit=request.args.get('limit', default=50, type=int),
        request_id=(request.args.get('requestId') or '').strip() or None,
        selected_skill=(request.args.get('selectedSkill') or '').strip() or None,
        fallback_reason=(request.args.get('fallbackReason') or '').strip() or None,
        permission_result=(request.args.get('permissionResult') or '').strip() or None,
        keyword=(request.args.get('keyword') or '').strip() or None,
    )
    return jsonify({
        'items': rows,
        'total': len(rows),
        'source': 'artifacts/assistant-routing/skill-first-routes.jsonl',
    })


@hrm_bp.route('/assistant/skill-first/failure-samples', methods=['GET'])
@jwt_required()
def assistant_skill_first_failure_samples():
    """List captured Skill-first failure samples for the learning loop."""
    if not _current_user_can_manage_assistant():
        return jsonify({'error': '仅管理员可查看 Skill-first 失败样本'}), 403
    from services.assistant_core.skill_first.failure_samples import query_failure_samples

    rows = query_failure_samples(
        limit=request.args.get('limit', default=50, type=int),
        kind=(request.args.get('kind') or '').strip() or None,
        request_id=(request.args.get('requestId') or '').strip() or None,
        selected_skill=(request.args.get('selectedSkill') or '').strip() or None,
        keyword=(request.args.get('keyword') or '').strip() or None,
    )
    return jsonify({
        'items': rows,
        'total': len(rows),
        'source': 'artifacts/assistant-routing/skill-first-failure-samples.jsonl',
        'evalPatchCommand': 'node scripts/generate-skill-card-eval-patch.mjs',
    })


@hrm_bp.route('/assistant/skill-first/llm-health', methods=['GET', 'POST'])
@jwt_required()
def assistant_skill_first_llm_health():
    """Inspect or reset per-node Skill-first LLM health state."""
    if not _current_user_can_manage_assistant():
        return jsonify({'error': '仅管理员可管理 Skill-first LLM 健康状态'}), 403
    from services.assistant_core.skill_first import llm_health

    if request.method == 'POST':
        llm_health.reset()
        return jsonify({'ok': True, 'reset': True, 'health': llm_health.snapshot()})
    return jsonify({'ok': True, 'health': llm_health.snapshot()})


@hrm_bp.route('/assistant/skill-first/route-traces/<request_id>/replay', methods=['GET'])
@jwt_required()
def assistant_skill_first_route_trace_replay(request_id):
    """Replay Skill-first recall/planning for a captured trace without executing tools."""
    if not _current_user_can_manage_assistant():
        return jsonify({'error': '仅管理员可重放 Skill-first 路由'}), 403
    from services.assistant_core.memory import build_context
    from services.assistant_core.skill_first.cards import get_card
    from services.assistant_core.skill_first.observability import get_route_trace
    from services.assistant_core.skill_first.planner import plan_skill
    from services.assistant_core.skill_first.semantic_index import recall_skills

    trace = get_route_trace(request_id)
    if not trace:
        return jsonify({'error': 'Skill-first 路由轨迹不存在'}), 404
    user_text = str(trace.get('user_text') or '').strip()
    if not user_text:
        return jsonify({'error': '路由轨迹缺少 user_text，无法重放'}), 400

    ctx = build_context(
        get_jwt_identity(),
        str(request.args.get('sessionId') or '').strip() or None,
        request_id=f'replay-{request_id}',
        client_context={'mode': 'skill_first_route_replay', 'sourceRequestId': request_id},
    )
    candidates = recall_skills(user_text, top_k=request.args.get('topK', default=8, type=int) or 8)
    plan = plan_skill(user_text, ctx, candidates)
    card = get_card(plan.selected_skill or '')
    original_skill = trace.get('selected_skill')
    return jsonify({
        'sourceRequestId': request_id,
        'mode': 'plan_only_no_tool_execution',
        'userText': user_text,
        'original': {
            'selectedSkill': original_skill,
            'confidence': trace.get('confidence'),
            'routeReason': trace.get('route_reason'),
            'fallbackReason': trace.get('fallback_reason'),
        },
        'replay': {
            'normalizedQuery': plan.normalized_query,
            'selectedSkill': plan.selected_skill,
            'confidence': plan.confidence,
            'slotValues': plan.slot_values,
            'missingSlots': plan.missing_slots,
            'routeReason': plan.route_reason,
            'fallbackReason': plan.fallback_reason,
            'plannerSource': plan.planner_source,
            'executor': card.executor if card else None,
            'sideEffect': card.side_effect if card else None,
            'confirmationPolicy': card.confirmation_policy if card else None,
        },
        'topKSkills': [item.to_dict() for item in candidates],
        'changed': original_skill != plan.selected_skill,
    })


@hrm_bp.route('/assistant/query', methods=['POST'])
@jwt_required()
def assistant_query_endpoint():
    """智能助手主入口：根据用户问题做跨模块检索 + AI 总结。

    支持两种调用模式：
    1. 自然语言：{ question, sessionId }
    2. 技能直调：{ skillId, params, sessionId }  —— 跳过路由，直接执行
    """
    from services.assistant import (
        assistant_apply_streamed_answer,
        assistant_query,
        assistant_skill_invoke,
        assistant_stream_grounded_response,
    )
    allowed = _require_ai_resource('assistant', 'dialogue')
    if not hasattr(allowed, 'resource_domain'):
        return allowed
    data = request.get_json() or {}
    session_id = (data.get('sessionId') or '').strip() or None
    client_context = data.get('clientContext') if isinstance(data.get('clientContext'), dict) else {}
    user_id = get_jwt_identity()
    wants_stream = bool(data.get('stream'))
    request_id = getattr(g, 'request_id', None) or request.headers.get('X-Request-ID') or uuid.uuid4().hex
    tenant = current_tenant()
    if tenant and tenant.ai_monthly_quota:
        usage = tenant_usage(tenant.id)
        if usage['aiCallsThisMonth'] >= tenant.ai_monthly_quota:
            return jsonify({
                'error': 'AI 月额度已用完',
                'code': 'AI_QUOTA_EXCEEDED',
                'limit': tenant.ai_monthly_quota,
                'current': usage['aiCallsThisMonth'],
            }), 403

    # 模式 2：技能直调
    skill_id = (data.get('skillId') or '').strip()
    question = (data.get('question') or '').strip()

    if wants_stream:
        def sse(event: str, payload: dict) -> str:
            return f'event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n'

        @stream_with_context
        def generate():
            yield sse('status', {'message': '已收到请求，正在连接聘小犀...'})
            try:
                if skill_id:
                    params = data.get('params') or {}
                    yield sse('status', {'message': '正在执行技能并整理结果...'})
                    result = assistant_skill_invoke(
                        skill_id=skill_id,
                        params=params,
                        user_id=user_id,
                        session_id=session_id,
                        request_id=request_id,
                        client_context=client_context,
                    )
                    stream_prompt = f'[技能调用] {skill_id}'
                else:
                    if not question:
                        yield sse('error', {'error': '请输入问题'})
                        return
                    if len(question) > 800:
                        yield sse('error', {'error': '问题过长，请精简到 800 字以内'})
                        return
                    yield sse('status', {'message': '正在理解意图、读取上下文并生成回答...'})
                    result = assistant_query(
                        question,
                        user_id=user_id,
                        session_id=session_id,
                        request_id=request_id,
                        client_context=client_context,
                    )
                    stream_prompt = question
                streamed = []
                if _assistant_stream_skips_provider(result):
                    yield sse('status', {'message': '正在返回系统校验结果...'})
                else:
                    yield sse('status', {'message': '正在调用硅基流动生成流式回复...'})
                for chunk in assistant_stream_grounded_response(
                    stream_prompt,
                    result,
                    user_id=user_id,
                    session_id=result.get('sessionId') or session_id,
                    request_id=request_id,
                    client_context=client_context,
                ):
                    if not chunk:
                        continue
                    streamed.append(str(chunk))
                    yield sse('delta', {'content': str(chunk)})
                if streamed:
                    result = assistant_apply_streamed_answer(
                        result,
                        ''.join(streamed),
                        user_id=user_id,
                    )
                yield sse('final', result)
            except Exception as exc:
                from logging import getLogger
                getLogger('hengpintong.assistant').exception('assistant_stream_failed')
                yield sse('error', {'error': str(exc) or '助手请求失败'})

        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
            },
        )

    if skill_id:
        params = data.get('params') or {}
        try:
            result = assistant_skill_invoke(
                skill_id=skill_id,
                params=params,
                user_id=user_id,
                session_id=session_id,
                request_id=request_id,
                client_context=client_context,
            )
            return jsonify(result)
        except Exception:
            from logging import getLogger
            getLogger('hengpintong.assistant').exception('assistant_skill_invoke_failed')
            raise

    # 模式 1：自然语言
    if not question:
        return jsonify({'error': '请输入问题'}), 400
    if len(question) > 800:
        return jsonify({'error': '问题过长，请精简到 800 字以内'}), 400
    try:
        result = assistant_query(
            question,
            user_id=user_id,
            session_id=session_id,
            request_id=request_id,
            client_context=client_context,
        )
        return jsonify(result)
    except Exception:
        from logging import getLogger
        getLogger('hengpintong.assistant').exception('assistant_query_failed')
        raise


@hrm_bp.route('/assistant/sessions', methods=['GET'])
@jwt_required()
def assistant_list_sessions():
    """列出当前用户的对话会话（按更新时间倒序）。"""
    from models import AssistantSession
    user_id = get_jwt_identity()
    rows = (AssistantSession.query
            .filter(AssistantSession.user_id == user_id, AssistantSession.message_count > 0)
            .with_entities(
                AssistantSession.id,
                AssistantSession.user_id,
                AssistantSession.title,
                AssistantSession.is_active,
                AssistantSession.message_count,
                AssistantSession.created_at,
                AssistantSession.updated_at,
            )
            .order_by(AssistantSession.updated_at.desc())
            .limit(20)
            .all())
    return jsonify([{
        'id': row.id,
        'userId': row.user_id,
        'title': row.title,
        'isActive': row.is_active,
        'messageCount': row.message_count,
        'createdAt': to_iso(row.created_at),
        'updatedAt': to_iso(row.updated_at),
    } for row in rows])


@hrm_bp.route('/assistant/sessions/<session_id>', methods=['GET'])
@jwt_required()
def assistant_get_session(session_id):
    """获取指定会话详情（含消息）。严格校验所有权。"""
    from models import AssistantSession
    user_id = get_jwt_identity()
    sess = AssistantSession.query.filter_by(id=session_id, user_id=user_id).first()
    if not sess:
        return jsonify({'error': '会话不存在'}), 404
    return jsonify(sess.to_dict(include_messages=True))


@hrm_bp.route('/assistant/sessions/<session_id>', methods=['DELETE'])
@jwt_required()
def assistant_delete_session(session_id):
    """删除会话。严格校验所有权。"""
    from models import AssistantSession
    user_id = get_jwt_identity()
    sess = AssistantSession.query.filter_by(id=session_id, user_id=user_id).first()
    if not sess:
        return jsonify({'error': '会话不存在'}), 404
    db.session.delete(sess)
    db.session.commit()
    return jsonify({'removed': True})


@hrm_bp.route('/assistant/sessions/new', methods=['POST'])
@jwt_required()
def assistant_new_session():
    """归档当前活跃会话，创建一个新会话。"""
    from models import AssistantSession
    user_id = get_jwt_identity()
    current = AssistantSession.query.filter_by(user_id=user_id, is_active=True).order_by(
        AssistantSession.updated_at.desc()
    ).first()
    if current and (current.message_count or 0) == 0:
        return jsonify(current.to_dict()), 200
    AssistantSession.query.filter_by(user_id=user_id, is_active=True).update({'is_active': False})
    sess = AssistantSession(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=None,
        messages=[],
        is_active=True,
        message_count=0,
    )
    assign_tenant(sess)
    db.session.add(sess)
    db.session.commit()
    return jsonify(sess.to_dict()), 201


@hrm_bp.route('/offers/<offer_id>/submit-approval', methods=['POST'])
@jwt_required()
def submit_offer_approval(offer_id):
    denied = require_roles(RECRUITMENT_ROLES, '无权限提交 Offer 审批')
    if denied:
        return denied
    offer = Offer.query.get(offer_id)
    if not offer:
        return jsonify({'error': 'Offer not found'}), 404
    approval = create_approval('offer', offer.id, f'Offer审批：{offer.title}')
    offer.approval_status = 'pending'
    offer.status = 'pending'
    db.session.flush()
    log_operation('offers', 'submit_approval', offer.id)
    db.session.commit()
    return jsonify({'offer': offer.to_dict(), 'approval': approval.to_dict()})


@hrm_bp.route('/offers/<offer_id>/accept', methods=['POST'])
@jwt_required()
def accept_offer(offer_id):
    denied = require_roles(RECRUITMENT_ROLES, '无权限更新 Offer')
    if denied:
        return denied
    offer = Offer.query.get(offer_id)
    if not offer:
        return jsonify({'error': 'Offer not found'}), 404
    offer.status = 'accepted'
    offer.accepted_at = datetime.utcnow()
    if offer.candidate:
        offer.candidate.status = 'offer_accepted'
    log_operation('offers', 'accept', offer.id)
    db.session.commit()
    return jsonify(offer.to_dict())


@hrm_bp.route('/offers/<offer_id>/reject', methods=['POST'])
@jwt_required()
def reject_offer(offer_id):
    denied = require_roles(RECRUITMENT_ROLES, '无权限更新 Offer')
    if denied:
        return denied
    offer = Offer.query.get(offer_id)
    if not offer:
        return jsonify({'error': 'Offer not found'}), 404
    offer.status = 'rejected'
    offer.rejected_at = datetime.utcnow()
    if offer.candidate:
        offer.candidate.status = 'offer_rejected'
    log_operation('offers', 'reject', offer.id)
    db.session.commit()
    return jsonify(offer.to_dict())


@hrm_bp.route('/payroll-records/generate-month', methods=['POST'])
@jwt_required()
def generate_monthly_payroll_records():
    denied = require_roles(PAYROLL_WRITE_ROLES, '无权限生成工资单')
    if denied:
        return denied
    data = request.get_json() or {}
    month_key = parse_payroll_month(data.get('month') or data.get('payrollMonth'))
    if not month_key:
        return jsonify({'error': 'Invalid payroll month, expected YYYY-MM'}), 400

    profiles = SalaryProfile.query.options(
        selectinload(SalaryProfile.employee)
    ).filter(
        or_(SalaryProfile.status.is_(None), SalaryProfile.status == 'active')
    ).order_by(SalaryProfile.created_at.asc()).all()
    created_count = 0
    updated_count = 0
    records = []
    skipped_profiles = []

    # === 批量预加载：消除循环内逐员工 attendance/request/existing-record 的 3-4N 查询 ===
    active_profiles = []
    for profile in profiles:
        employee = profile.employee
        if not employee or employee.status not in PAYROLL_ACTIVE_EMPLOYEE_STATUSES:
            skipped_profiles.append({
                'profileId': profile.id,
                'employeeId': profile.employee_id,
                'reason': 'employee_not_active',
            })
        else:
            active_profiles.append(profile)

    metrics = {
        'attendanceRecords': 0,
        'attendanceExceptions': 0,
        'approvedRequests': 0,
        'approvedLeaveHours': Decimal('0'),
        'approvedOvertimeHours': Decimal('0'),
        'overtimeBonus': Decimal('0'),
        'attendanceDeduction': Decimal('0'),
        'grossTotal': Decimal('0'),
        'netTotal': Decimal('0'),
    }

    if active_profiles:
        start, end = payroll_month_bounds(month_key)
        start_dt = datetime.combine(start, datetime.min.time())
        end_dt = datetime.combine(end, datetime.min.time())
        active_emp_ids = [p.employee_id for p in active_profiles]

        # 一次查询：本月所有相关考勤记录，按员工分组
        all_attendance = AttendanceRecord.query.filter(
            AttendanceRecord.employee_id.in_(active_emp_ids),
            AttendanceRecord.attendance_date >= start,
            AttendanceRecord.attendance_date < end,
        ).all()
        attendance_by_emp = {}
        for row in all_attendance:
            attendance_by_emp.setdefault(row.employee_id, []).append(row)

        # 一次查询：本月所有已批准请求，按员工分组
        all_requests = EmployeeRequest.query.filter(
            EmployeeRequest.employee_id.in_(active_emp_ids),
            EmployeeRequest.status.in_(PAYROLL_APPROVED_STATUSES),
            EmployeeRequest.start_time >= start_dt,
            EmployeeRequest.start_time < end_dt,
        ).all()
        requests_by_emp = {}
        for row in all_requests:
            requests_by_emp.setdefault(row.employee_id, []).append(row)

        # 一次查询：本月已有工资记录，按员工索引（用于幂等更新）
        existing_records = PayrollRecord.query.filter(
            PayrollRecord.employee_id.in_(active_emp_ids),
            PayrollRecord.payroll_month == month_key,
        ).all()
        existing_by_emp = {r.employee_id: r for r in existing_records}

    for profile in active_profiles:
        employee = profile.employee
        emp_id = employee.id
        # 从预加载的分组数据构造该员工的子集（避免逐员工查库）
        att_rows = attendance_by_emp.get(emp_id, [])
        att_counts = {}
        for row in att_rows:
            status = row.status or 'unknown'
            att_counts[status] = att_counts.get(status, 0) + 1

        req_rows = requests_by_emp.get(emp_id, [])
        leave_hours = Decimal('0')
        overtime_hours = Decimal('0')
        for row in req_rows:
            hours = row.duration_hours or Decimal('0')
            if request_type_matches(row.request_type, {'leave', '请假'}):
                leave_hours += hours
            elif request_type_matches(row.request_type, {'overtime', '加班'}):
                overtime_hours += hours

        record, created, record_metrics = build_monthly_payroll_record(
            profile, employee, month_key,
            attendance_rows=att_rows, status_counts=att_counts,
            request_rows=req_rows, leave_hours=leave_hours, overtime_hours=overtime_hours,
            existing_record=existing_by_emp.get(emp_id),
        )
        created_count += 1 if created else 0
        updated_count += 0 if created else 1
        records.append(record)
        for key in ('attendanceRecords', 'attendanceExceptions', 'approvedRequests'):
            metrics[key] += record_metrics[key]
        for key in ('approvedLeaveHours', 'approvedOvertimeHours', 'overtimeBonus', 'attendanceDeduction'):
            metrics[key] += record_metrics[key]
        metrics['grossTotal'] += record.gross_salary or Decimal('0')
        metrics['netTotal'] += record.net_salary or Decimal('0')

    log_operation('payroll-records', 'generate_month', None, {
        'month': month_key,
        'createdCount': created_count,
        'updatedCount': updated_count,
        'skippedCount': len(skipped_profiles),
    })
    db.session.commit()
    return jsonify(monthly_payroll_flow_payload(
        month_key,
        records,
        created_count,
        updated_count,
        skipped_profiles,
        metrics,
    ))


@hrm_bp.route('/performance-reviews/<review_id>/generate-salary-change', methods=['POST'])
@jwt_required()
def generate_performance_salary_change(review_id):
    denied = require_roles(ORG_WRITE_ROLES | PAYROLL_WRITE_ROLES, '无权限生成薪资异动')
    if denied:
        return denied
    review = PerformanceReview.query.get(review_id)
    if not review:
        return jsonify({'error': 'Performance review not found'}), 404
    if review.status not in ('completed', 'finalized', 'closed'):
        return jsonify({'error': 'Performance review must be completed before compensation linkage'}), 400

    data = request.get_json() or {}
    salary_adjustment = parse_number(data.get('salaryAdjustment'))
    if salary_adjustment is None:
        salary_adjustment = Decimal('0')
    effective_date = parse_date(data.get('effectiveDate')) or date.today()

    existing = EmployeeChange.query.filter(
        EmployeeChange.employee_id == review.employee_id,
        EmployeeChange.change_type == 'performance_salary_adjustment',
        EmployeeChange.reason.like(f'%performance review {review.id}%'),
    ).order_by(EmployeeChange.created_at.asc()).first()
    if existing:
        return jsonify(performance_salary_change_payload(review, existing, created=False))

    cycle_name = review.cycle.name if review.cycle else 'performance cycle'
    change = EmployeeChange(
        id=new_id(),
        employee_id=review.employee_id,
        change_type='performance_salary_adjustment',
        salary_adjustment=salary_adjustment,
        effective_date=effective_date,
        reason=(
            f'Generated from performance review {review.id}; cycle={cycle_name}; '
            f'grade={review.grade or "-"}; final_score={review.final_score or "-"}'
        ),
        status='draft',
        created_by=get_jwt_identity(),
    )
    db.session.add(change)
    log_operation('performance-reviews', 'generate_salary_change', review.id, {
        'employeeId': review.employee_id,
        'changeId': change.id,
        'salaryAdjustment': str(salary_adjustment),
    })
    db.session.commit()
    return jsonify(performance_salary_change_payload(review, change, created=True))


# ---------------------------------------------------------------------------
# User ↔ Employee 绑定（员工门户前置：账号要能认出员工档案）
# ---------------------------------------------------------------------------

@hrm_bp.route('/users/bind-employees', methods=['POST'])
@jwt_required()
def bind_users_to_employees():
    """按 email 批量绑定 User.employee_id。仅 admin/hr_admin。"""
    user_id = get_jwt_identity()
    actor = User.query.get(user_id)
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403

    from services.user_employee_binding import bind_users_by_email
    stats = bind_users_by_email(dry_run=False)
    log_operation('users', 'bind_employees', None, stats)
    return jsonify(stats)


# ---------------------------------------------------------------------------
# 培训体系：课程指派 + 视频上传（管理侧 bespoke 端点）
# ---------------------------------------------------------------------------

@hrm_bp.route('/courses/<course_id>/assign', methods=['POST'])
@jwt_required()
def assign_course(course_id):
    """指派课程到部门/员工。body: {deptIds: [], userIds: []}（任一可空）。

    全量覆盖：先删旧指派，再写新的。
    """
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    course = Course.query.get(course_id)
    if not course:
        return jsonify({'error': '课程不存在'}), 404

    data = request.get_json() or {}
    dept_ids = [d for d in (data.get('deptIds') or []) if d]
    user_ids = [u for u in (data.get('userIds') or []) if u]

    CourseAssignment.query.filter_by(course_id=course_id).delete()
    new_rows = []
    for did in dept_ids:
        new_rows.append(CourseAssignment(id=new_id(), course_id=course_id,
                                          target_type='dept', target_id=str(did)))
    for uid in user_ids:
        new_rows.append(CourseAssignment(id=new_id(), course_id=course_id,
                                          target_type='user', target_id=str(uid)))
    for r in new_rows:
        db.session.add(r)
    log_operation('courses', 'assign', course_id, {
        'deptIds': dept_ids, 'userIds': user_ids,
    })
    # 通知被指派的员工（展开部门→员工）
    from services.course_access import course_assigned_employee_ids
    from services.training_notify import notify_many
    target_emps = course_assigned_employee_ids(course_id)
    notify_many(list(target_emps), f'新课程：{course.title}',
                f'您有新课程「{course.title}」可以学习了。',
                notice_type='course', link_url='/portal/my-courses')
    db.session.commit()

    rows = CourseAssignment.query.filter_by(course_id=course_id).all()
    # 批量预查 dept/employee 名称（消除 N+1）
    dept_ids = [r.target_id for r in rows if r.target_type == 'dept']
    user_ids = [r.target_id for r in rows if r.target_type == 'user']
    name_map = {}
    if dept_ids:
        for d in Department.query.filter(Department.id.in_(dept_ids)).all():
            name_map[('dept', d.id)] = d.name
    if user_ids:
        for e in Employee.query.filter(Employee.id.in_(user_ids)).all():
            name_map[('user', e.id)] = e.name
    return jsonify({
        'courseId': course_id,
        'assignments': [a.to_dict(name_map) for a in rows],
        'deptCount': len(dept_ids),
        'userCount': len(user_ids),
    })


@hrm_bp.route('/course-hours/<hour_id>/upload-video', methods=['POST'])
@jwt_required()
def upload_course_video(hour_id):
    """上传课时视频到对象存储。multipart/form-data: file=..."""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    hour = CourseHour.query.get(hour_id)
    if not hour:
        return jsonify({'error': '课时不存在'}), 404

    if 'file' not in request.files:
        return jsonify({'error': '未提供文件'}), 400
    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'error': '空文件'}), 400

    # 扩展名白名单（视频）
    ext = (file.filename.rsplit('.', 1)[-1].lower()
           if '.' in file.filename else 'mp4')
    if ext not in {'mp4', 'webm', 'mov', 'm4v', 'avi'}:
        return jsonify({'error': f'不支持的视频格式: {ext}'}), 400

    old_references = _record_storage_references(hour)
    object_key = f'courses/{hour.course_id}/{hour_id}_{new_id()}.{ext}'
    staged_object_key = None
    try:
        object_key = storage.upload_video(
            file.stream,
            object_key,
            content_type=f'video/{ext}',
            replacing_object_key=hour.video_key,
        )
        staged_object_key = object_key
    except (StorageQuotaExceeded, StorageUsageUnavailable):
        raise
    except Exception as exc:
        return jsonify({'error': f'上传失败: {exc}'}), 500

    try:
        hour.video_key = object_key
        log_operation('course-hours', 'upload_video', hour_id, {'key': object_key}, strict=True)
        db.session.commit()
    except Exception:
        db.session.rollback()
        if staged_object_key and staged_object_key not in old_references:
            storage.delete_object(staged_object_key)
        raise
    _release_unreferenced_storage(
        old_references - storage.storage_reference_keys(object_key),
        tenant_id=hour.tenant_id,
    )

    return jsonify({
        'hourId': hour_id,
        'videoKey': object_key,
        'videoUrl': storage.presigned_url(object_key),
    })


@hrm_bp.route('/courses/<course_id>/upload-cover', methods=['POST'])
@jwt_required()
def upload_course_cover(course_id):
    """上传课程封面图到 /uploads。multipart: file=..."""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    course = Course.query.get(course_id)
    if not course:
        return jsonify({'error': '课程不存在'}), 404
    if 'file' not in request.files:
        return jsonify({'error': '未提供文件'}), 400
    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'error': '空文件'}), 400
    ext = (file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg')
    if ext not in {'jpg', 'jpeg', 'png', 'webp', 'gif'}:
        return jsonify({'error': f'封面仅支持图片: {ext}'}), 400
    old_references = _record_storage_references(course)
    file_id = new_id()
    filename = f'courses/{course_id}/cover_{file_id}.{ext}'
    filename = storage.save_local_upload(file, filename)
    course.cover_url = f'/uploads/{filename}'
    try:
        log_operation('courses', 'upload_cover', course_id, {'url': course.cover_url}, strict=True)
        db.session.commit()
    except Exception:
        db.session.rollback()
        storage.delete_object_if_unreferenced(filename, tenant_id=course.tenant_id)
        raise
    _release_unreferenced_storage(
        old_references - storage.storage_reference_keys(course.cover_url),
        tenant_id=course.tenant_id,
    )
    return jsonify({'courseId': course_id, 'coverUrl': course.cover_url})


# ---------------------------------------------------------------------------
# 考试：AI 出题 + 题目审核（管理侧 bespoke 端点）
# ---------------------------------------------------------------------------

@hrm_bp.route('/exam-questions/generate', methods=['POST'])
@jwt_required()
def generate_exam_questions():
    """AI 出题。body: {courseId?, sourceText?, count, types?}.

    - 若给 courseId 且无 sourceText：自动从课程章节标题/附件文本拼资料。
    - 生成的题以 review_status='pending' 写入题库，返回供管理员审核。
    """
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    allowed = _require_ai_resource('exam_ai', 'exam_generation')
    if not hasattr(allowed, 'resource_domain'):
        return allowed

    data = request.get_json() or {}
    course_id = data.get('courseId')
    source_text = (data.get('sourceText') or '').strip()
    count = int(data.get('count') or 5)
    types = data.get('types') or ['single', 'multiple', 'judge']

    # 若无 source_text 但有 courseId：从课程内容拼资料
    if not source_text and course_id:
        source_text = _gather_course_source_text(course_id)
    if not source_text:
        return jsonify({'error': '请提供培训资料文本或指定课程'}), 400

    from services.exam_generation import generate_questions
    questions = generate_questions(source_text, count=count, types=types)
    if not questions:
        return jsonify({'error': 'AI 未能生成有效题目，请重试或更换资料', 'questions': []}), 200

    # 写入题库（pending 审核状态）
    created = []
    for q in questions:
        eq = ExamQuestion(
            id=new_id(),
            course_id=course_id,
            type=q['type'],
            stem=q['stem'],
            options=q['options'],
            answer=q['answer'],
            explanation=q.get('explanation'),
            difficulty=q.get('difficulty', 3),
            score=Decimal('5'),
            source='ai',
            review_status='pending',
        )
        db.session.add(eq)
        created.append(eq)
    log_operation('exam-questions', 'ai_generate', None, {
        'courseId': course_id, 'count': len(created), 'types': types,
    })
    db.session.commit()
    return jsonify({'questions': [q.to_dict() for q in created], 'count': len(created)})


@hrm_bp.route('/exam-questions/<question_id>/approve', methods=['POST'])
@jwt_required()
def approve_exam_question(question_id):
    """审核通过题目。"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    q = ExamQuestion.query.get(question_id)
    if not q:
        return jsonify({'error': '题目不存在'}), 404
    q.review_status = 'approved'
    q.reviewed_by = actor.id
    q.reviewed_at = datetime.utcnow()
    log_operation('exam-questions', 'approve', question_id)
    db.session.commit()
    return jsonify(q.to_dict())


@hrm_bp.route('/exam-questions/<question_id>/reject', methods=['POST'])
@jwt_required()
def reject_exam_question(question_id):
    """驳回题目。"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    q = ExamQuestion.query.get(question_id)
    if not q:
        return jsonify({'error': '题目不存在'}), 404
    q.review_status = 'rejected'
    q.reviewed_by = actor.id
    q.reviewed_at = datetime.utcnow()
    log_operation('exam-questions', 'reject', question_id)
    db.session.commit()
    return jsonify(q.to_dict())


@hrm_bp.route('/exam-questions/batch-approve', methods=['POST'])
@jwt_required()
def batch_approve_exam_questions():
    """批量审核通过。body: {ids: [...]}。"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    data = request.get_json() or {}
    ids = [i for i in (data.get('ids') or []) if i]
    if not ids:
        return jsonify({'error': 'ids 为空'}), 400
    rows = ExamQuestion.query.filter(ExamQuestion.id.in_(ids)).all()
    now = datetime.utcnow()
    for q in rows:
        q.review_status = 'approved'
        q.reviewed_by = actor.id
        q.reviewed_at = now
    log_operation('exam-questions', 'batch_approve', None, {'ids': ids, 'count': len(rows)})
    db.session.commit()
    return jsonify({'approved': len(rows), 'ids': [q.id for q in rows]})


# ---------------------------------------------------------------------------
# 考试：任务发布 + 进度统计（管理侧）
# ---------------------------------------------------------------------------

@hrm_bp.route('/exam-tasks/<task_id>/publish', methods=['POST'])
@jwt_required()
def publish_exam_task(task_id):
    """发布考试任务：把 target（部门/员工）展开为 per-员工 ExamAssignment。"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    task = ExamTask.query.get(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404
    if task.status not in ('draft', 'published'):
        return jsonify({'error': f"任务状态 {task.status} 不可发布"}), 400
    paper = ExamPaper.query.get(task.paper_id) if task.paper_id else None
    if not paper:
        return jsonify({'error': '试卷不存在'}), 400
    paper_error = _validate_exam_paper(paper)
    if paper_error:
        db.session.rollback()
        return jsonify({'error': paper_error}), 400
    # 校验试卷题目都已审核通过
    qids = paper.question_ids or []
    if not qids:
        return jsonify({'error': '试卷未配置题目'}), 400
    pending = ExamQuestion.query.filter(
        ExamQuestion.id.in_(qids), ExamQuestion.review_status != 'approved'
    ).count()
    if pending:
        return jsonify({'error': f'试卷中有 {pending} 道题未通过审核'}), 400

    # 展开 target 为员工 id 集合
    target_ids = task.target_ids or []
    employee_ids = set()
    if task.target_type == 'user':
        employee_ids = {str(i) for i in target_ids if i}
    else:  # dept
        from services.course_access import _department_descendant_ids
        dept_ids = set()
        for did in target_ids:
            if did:
                dept_ids |= _department_descendant_ids(str(did))
        if dept_ids:
            rows = Employee.query.filter(
                Employee.department_id.in_(dept_ids),
                Employee.status.in_(['active', 'pending_onboard', 'probation']),
            ).with_entities(Employee.id).all()
            employee_ids = {r[0] for r in rows}

    # upsert assignments（已存在的更新，新的插入）
    existing = {a.employee_id: a for a in ExamAssignment.query.filter_by(task_id=task_id).all()}
    new_count = 0
    for emp_id in employee_ids:
        if emp_id not in existing:
            db.session.add(ExamAssignment(
                id=new_id(), task_id=task_id, employee_id=emp_id,
                attempts_used=0, status='assigned',
            ))
            new_count += 1
    task.status = 'published'
    log_operation('exam-tasks', 'publish', task_id, {
        'assignedTotal': len(employee_ids), 'newlyAssigned': new_count,
    })
    # 通知被指派员工
    from services.training_notify import notify_many
    notify_many(list(employee_ids), f'新考试：{task.title}',
                f'您被指派参加考试「{task.title}」，请在规定时间内完成。' +
                (f'截止时间：{task.end_time.strftime("%Y-%m-%d")}' if task.end_time else ''),
                notice_type='exam', link_url='/portal/my-exams')
    db.session.commit()
    return jsonify({
        'taskId': task_id,
        'status': 'published',
        'assignedTotal': len(employee_ids),
        'newlyAssigned': new_count,
    })


@hrm_bp.route('/courses/<course_id>/progress', methods=['GET'])
@jwt_required()
def course_progress_overview(course_id):
    """查看单个课程的员工学习进度。"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    course = Course.query.get(course_id)
    if not course:
        return jsonify({'error': '课程不存在'}), 404
    from services.course_access import course_assigned_employee_ids
    assigned = course_assigned_employee_ids(course_id)
    progress_map = {
        p.employee_id: p for p in UserCourseProgress.query.filter_by(course_id=course_id).all()
    }
    # 每员工累计观看时长 + 最后观看时间
    from sqlalchemy import func
    duration_rows = db.session.query(
        UserHourProgress.employee_id,
        func.coalesce(func.sum(UserHourProgress.watched_duration), 0).label('total_sec'),
        func.max(UserHourProgress.updated_at).label('last_at'),
    ).filter_by(course_id=course_id).group_by(UserHourProgress.employee_id).all()
    duration_map = {r[0]: {'sec': int(r[1]), 'lastAt': r[2]} for r in duration_rows}
    total_hours = CourseHour.query.filter_by(course_id=course_id).count()
    # 批量预加载员工 + 部门（消除循环内逐条 query.get 的 N+1）
    emp_map = {e.id: e for e in Employee.query.filter(Employee.id.in_(assigned)).all()} if assigned else {}
    dept_ids = {e.department_id for e in emp_map.values() if e.department_id}
    dept_map = {d.id: d.name for d in Department.query.filter(Department.id.in_(dept_ids)).all()} if dept_ids else {}
    roster = []
    finished = 0
    for emp_id in assigned:
        emp = emp_map.get(emp_id)
        p = progress_map.get(emp_id)
        is_fin = bool(p and p.is_finished)
        if is_fin:
            finished += 1
        dept_name = dept_map.get(emp.department_id) if (emp and emp.department_id) else None
        dur = duration_map.get(emp_id, {})
        total_sec = dur.get('sec', 0)
        roster.append({
            'employeeId': emp_id,
            'employeeName': emp.name if emp else None,
            'department': dept_name,
            'progress': p.progress if p else 0,
            'finishedCount': p.finished_count if p else 0,
            'totalHours': total_hours,
            'isFinished': is_fin,
            'finishedAt': p.finished_at.isoformat() if (p and p.finished_at) else None,
            'watchedSeconds': total_sec,
            'watchedMinutes': round(total_sec / 60),
            'lastWatchedAt': dur.get('lastAt').isoformat() if dur.get('lastAt') else None,
        })
    return jsonify({
        'courseId': course_id,
        'title': course.title,
        'totalHours': total_hours,
        'assigned': len(assigned),
        'finished': finished,
        'completionRate': round(finished / len(assigned), 4) if assigned else 0,
        'roster': roster,
    })


@hrm_bp.route('/exam-tasks/<task_id>/progress', methods=['GET'])
@jwt_required()
def exam_task_progress(task_id):
    """查看考试任务进度：完成率/通过率/成绩单。"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    task = ExamTask.query.get(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404

    assignments = ExamAssignment.query.filter_by(task_id=task_id).all()
    # 每个员工取最高分 attempt
    score_rows = db.session.query(
        ExamAttempt.employee_id,
        func.max(ExamAttempt.score).label('best_score'),
    ).filter_by(task_id=task_id, status='submitted').group_by(
        ExamAttempt.employee_id
    ).all()
    best_scores = {r[0]: float(r[1]) if r[1] is not None else None for r in score_rows}
    attempted_ids = {r[0] for r in score_rows}

    paper = ExamPaper.query.get(task.paper_id) if task.paper_id else None
    pass_score = float(paper.pass_score) if paper else 0

    total = len(assignments)
    attempted = len(attempted_ids & {a.employee_id for a in assignments})
    passed = sum(1 for s in best_scores.values() if s is not None and s >= pass_score)

    # 批量预加载员工 + 部门（消除循环内逐条 query.get 的 N+1，原代码部门还被查两次）
    assign_emp_ids = {a.employee_id for a in assignments}
    emp_map = {e.id: e for e in Employee.query.filter(Employee.id.in_(assign_emp_ids)).all()} if assign_emp_ids else {}
    dept_ids = {e.department_id for e in emp_map.values() if e.department_id}
    dept_map = {d.id: d.name for d in Department.query.filter(Department.id.in_(dept_ids)).all()} if dept_ids else {}

    roster = []
    for a in assignments:
        emp = emp_map.get(a.employee_id)
        roster.append({
            'employeeId': a.employee_id,
            'employeeName': emp.name if emp else None,
            'department': dept_map.get(emp.department_id) if (emp and emp.department_id) else None,
            'attemptsUsed': a.attempts_used,
            'status': a.status,
            'bestScore': best_scores.get(a.employee_id),
            'passed': (best_scores.get(a.employee_id) or 0) >= pass_score if a.employee_id in best_scores else None,
        })

    return jsonify({
        'taskId': task_id,
        'title': task.title,
        'total': total,
        'attempted': attempted,
        'passed': passed,
        'completionRate': round(attempted / total, 4) if total else 0,
        'passRate': round(passed / total, 4) if total else 0,
        'passScore': pass_score,
        'roster': roster,
    })


# ---------------------------------------------------------------------------
# 学习路径：发布 + 进度统计
# ---------------------------------------------------------------------------

@hrm_bp.route('/learning-paths/<path_id>/publish', methods=['POST'])
@jwt_required()
def publish_learning_path(path_id):
    """发布学习路径：展开目标员工授权。"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    path = LearningPath.query.get(path_id)
    if not path:
        return jsonify({'error': '路径不存在'}), 404
    if not path.stages:
        return jsonify({'error': '路径无阶段配置'}), 400

    # 按目标部门展开员工（无部门则全员）
    from services.course_access import course_assigned_employee_ids, _department_descendant_ids
    if path.target_department_id:
        dept_ids = _department_descendant_ids(path.target_department_id)
        rows = Employee.query.filter(
            Employee.department_id.in_(dept_ids),
            Employee.status.in_(['active', 'pending_onboard', 'probation']),
        ).with_entities(Employee.id).all()
        employee_ids = {r[0] for r in rows}
    else:
        # 无部门限定 → 全员
        rows = Employee.query.filter(
            Employee.status.in_(['active', 'pending_onboard', 'probation'])
        ).with_entities(Employee.id).all()
        employee_ids = {r[0] for r in rows}

    existing = {a.employee_id for a in LearningPathAssignment.query.filter_by(path_id=path_id).all()}
    new_count = 0
    for emp_id in employee_ids:
        if emp_id not in existing:
            db.session.add(LearningPathAssignment(
                id=new_id(), path_id=path_id, employee_id=emp_id,
                current_stage=0, progress=0, is_completed=False,
            ))
            new_count += 1
    path.status = 'published'
    log_operation('learning-paths', 'publish', path_id, {
        'assignedTotal': len(employee_ids), 'newlyAssigned': new_count,
    })
    # 通知被指派员工
    from services.training_notify import notify_many
    notify_many(list(employee_ids), f'新学习路径：{path.name}',
                f'您被分配了学习路径「{path.name}」，按阶段闯关学习吧！',
                notice_type='learning_path', link_url='/portal/learning-paths')
    db.session.commit()
    return jsonify({
        'pathId': path_id, 'status': 'published',
        'assignedTotal': len(employee_ids), 'newlyAssigned': new_count,
    })


@hrm_bp.route('/learning-paths/<path_id>/progress', methods=['GET'])
@jwt_required()
def learning_path_progress(path_id):
    """查看学习路径的整体进度（管理员）。"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    path = LearningPath.query.get(path_id)
    if not path:
        return jsonify({'error': '路径不存在'}), 404
    from services.learning_path_progress import compute_assignment_progress
    assignments = LearningPathAssignment.query.filter_by(path_id=path_id).all()
    # 批量预加载员工 + 部门（消除循环内逐条 query.get 的 N+1）
    a_emp_ids = {a.employee_id for a in assignments}
    a_emp_map = {e.id: e for e in Employee.query.filter(Employee.id.in_(a_emp_ids)).all()} if a_emp_ids else {}
    a_dept_ids = {e.department_id for e in a_emp_map.values() if e.department_id}
    a_dept_map = {d.id: d.name for d in Department.query.filter(Department.id.in_(a_dept_ids)).all()} if a_dept_ids else {}
    roster = []
    completed = 0
    for a in assignments:
        compute_assignment_progress(a)  # 实时重算
        if a.is_completed:
            completed += 1
        emp = a_emp_map.get(a.employee_id)
        dept_name = a_dept_map.get(emp.department_id) if (emp and emp.department_id) else None
        roster.append({
            'employeeId': a.employee_id,
            'employeeName': emp.name if emp else None,
            'department': dept_name,
            'currentStage': a.current_stage,
            'progress': a.progress,
            'isCompleted': a.is_completed,
            'completedAt': a.completed_at.isoformat() if a.completed_at else None,
        })
    db.session.commit()
    return jsonify({
        'pathId': path_id,
        'name': path.name,
        'assigned': len(assignments),
        'completed': completed,
        'completionRate': round(completed / len(assignments), 4) if assignments else 0,
        'roster': roster,
    })


# ---------------------------------------------------------------------------
# 课程评价汇总（管理员）
# ---------------------------------------------------------------------------

@hrm_bp.route('/courses/learning-stats', methods=['GET'])
@jwt_required()
def courses_learning_stats():
    """所有课程的学习统计（管理员）：每门课的学习人数、完成人数、平均进度。

    用于课程目录页展示“谁在学、学到哪”。数据基于 UserCourseProgress。
    返回 [{courseId, learnerCount, finishedCount, avgProgress}]
    """
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    from services.course_access import course_assigned_employee_ids

    courses = Course.query.all()
    if not courses:
        return jsonify([])
    course_ids = [c.id for c in courses]
    # 一次性查所有课程进度（学习人数/完成/进度）
    rows = db.session.query(
        UserCourseProgress.course_id,
        func.count(func.distinct(UserCourseProgress.employee_id)),
        func.coalesce(func.sum(db.case((UserCourseProgress.is_finished == True, 1), else_=0)), 0),
        func.coalesce(func.avg(UserCourseProgress.progress), 0),
    ).filter(UserCourseProgress.course_id.in_(course_ids)).group_by(UserCourseProgress.course_id).all()
    stats_map = {r[0]: {'learner': r[1], 'finished': r[2], 'avgProgress': round(float(r[3]))} for r in rows}
    result = []
    for c in courses:
        s = stats_map.get(c.id, {'learner': 0, 'finished': 0, 'avgProgress': 0})
        # 分配总人数（指派展开；无指派=全员可见，取在职人数）
        try:
            assigned = len(course_assigned_employee_ids(c.id))
        except Exception:
            assigned = 0
        result.append({
            'courseId': c.id,
            'learnerCount': s['learner'],
            'finishedCount': s['finished'],
            'avgProgress': s['avgProgress'],
            'assignedCount': assigned,
        })
    return jsonify(result)


@hrm_bp.route('/courses/reviews-summary', methods=['GET'])
@jwt_required()
def courses_reviews_summary():
    """所有课程的评分汇总排行（管理员）。"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    from sqlalchemy import func
    rows = db.session.query(
        CourseReview.course_id,
        func.count(CourseReview.id).label('cnt'),
        func.avg(CourseReview.rating).label('avg'),
    ).group_by(CourseReview.course_id).all()
    # 批量预加载课程标题（消除循环内逐条 Course.query.get 的 N+1）
    course_ids = [r[0] for r in rows]
    title_map = {}
    if course_ids:
        for c in Course.query.filter(Course.id.in_(course_ids)).with_entities(Course.id, Course.title).all():
            title_map[c[0]] = c[1]
    result = []
    for course_id, cnt, avg in rows:
        result.append({
            'courseId': course_id,
            'courseTitle': title_map.get(course_id),
            'reviewCount': cnt,
            'avgRating': round(float(avg), 1) if avg else 0,
        })
    result.sort(key=lambda x: x['avgRating'], reverse=True)
    return jsonify(result)


@hrm_bp.route('/courses/<course_id>/reviews', methods=['GET'])
@jwt_required()
def admin_course_reviews(course_id):
    """查看某课程所有评价详情（管理员）。"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    reviews = CourseReview.query.filter_by(course_id=course_id).order_by(
        CourseReview.updated_at.desc()
    ).all()
    from sqlalchemy import func as F
    summary_rows = db.session.query(
        F.count(CourseReview.id),
        F.avg(CourseReview.rating),
        F.avg(CourseReview.content_quality),
        F.avg(CourseReview.clarity),
        F.avg(CourseReview.practicality),
    ).filter_by(course_id=course_id).first()
    summary = {
        'count': summary_rows[0] or 0,
        'avgRating': round(float(summary_rows[1]), 1) if summary_rows[1] else 0,
        'avgContent': round(float(summary_rows[2]), 1) if summary_rows[2] else 0,
        'avgClarity': round(float(summary_rows[3]), 1) if summary_rows[3] else 0,
        'avgPracticality': round(float(summary_rows[4]), 1) if summary_rows[4] else 0,
    }
    return jsonify({
        'summary': summary,
        'reviews': [r.to_dict() for r in reviews],
    })


# ---------------------------------------------------------------------------
# 岗位胜任力测评：提交测评 + 短板课程推荐
# ---------------------------------------------------------------------------

@hrm_bp.route('/competency-assessments/submit', methods=['POST'])
@jwt_required()
def submit_competency_assessment():
    """提交胜任力测评。自动计算 gap、短板维度、综合达标率。

    body: {modelId, employeeId, scores: {dimKey: level(1-5)}, assessor?}
    """
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    data = request.get_json() or {}
    model_id = data.get('modelId')
    employee_id = data.get('employeeId')
    scores = data.get('scores') or {}
    if not model_id or not employee_id or not scores:
        return jsonify({'error': '缺少 modelId/employeeId/scores'}), 400

    model = CompetencyModel.query.get(model_id)
    if not model:
        return jsonify({'error': '胜任力模型不存在'}), 404

    # 计算 gap（要求 - 实际，负数归零）+ 短板（gap 最大的维度）
    dims = model.dimensions or []
    gaps = {}
    for dim in dims:
        key = dim.get('key')
        required = int(dim.get('requiredLevel') or 0)
        actual = int(scores.get(key, 0) or 0)
        gaps[key] = max(0, required - actual)

    # 综合达标率：实际总分 / 要求总分 * 100
    total_required = sum(int(d.get('requiredLevel') or 0) for d in dims)
    total_actual = sum(min(int(scores.get(d.get('key'), 0) or 0), int(d.get('requiredLevel') or 0)) for d in dims)
    overall = int(total_actual / total_required * 100) if total_required else 0

    # 短板：gap > 0 的维度，按 gap 降序取前 3
    weak = sorted(
        [(d.get('key'), gaps[d.get('key')]) for d in dims if gaps.get(d.get('key'), 0) > 0],
        key=lambda x: -x[1]
    )[:3]
    weakest = [k for k, _ in weak]

    # 覆盖式：同一员工+同一模型只保留最新一条
    existing = CompetencyAssessment.query.filter_by(
        employee_id=employee_id, model_id=model_id
    ).first()
    if existing:
        a = existing
    else:
        a = CompetencyAssessment(id=new_id(), employee_id=employee_id, model_id=model_id)
        db.session.add(a)
    a.scores = scores
    a.gaps = gaps
    a.overall_score = overall
    a.weakest_dims = weakest
    a.assessor = data.get('assessor') or actor.id
    log_operation('competency-assessments', 'submit', a.id, {
        'employeeId': employee_id, 'modelId': model_id, 'overall': overall, 'weakest': weakest,
    })
    db.session.commit()
    return jsonify(a.to_dict(include_model=True))


@hrm_bp.route('/competency-assessments/<assessment_id>/recommendations', methods=['GET'])
@jwt_required()
def competency_course_recommendations(assessment_id):
    """根据测评短板推荐补短板课程。

    逻辑：短板维度的 name 匹配课程的 category 或 short_desc，推荐相关课程。
    """
    actor = User.query.get(get_jwt_identity())
    if not actor:
        return jsonify({'error': '无权限'}), 403
    a = CompetencyAssessment.query.get(assessment_id)
    if not a:
        return jsonify({'error': '测评记录不存在'}), 404
    model = a.model
    dims = model.dimensions or []
    weak_names = [d.get('name', '') for d in dims if d.get('key') in (a.weakest_dims or [])]

    # 按短板关键词匹配课程（category 或 short_desc 包含）
    recommended = []
    if weak_names:
        courses = Course.query.filter_by(is_show=True).all()
        # 批量预加载分类名（消除循环内逐条 CourseCategory.query.get 的 N+1）
        cat_ids = {c.category_id for c in courses if c.category_id}
        cat_name_map = {}
        if cat_ids:
            for cat in CourseCategory.query.filter(CourseCategory.id.in_(cat_ids)).with_entities(CourseCategory.id, CourseCategory.name).all():
                cat_name_map[cat[0]] = cat[1]
        for c in courses:
            text = f"{c.short_desc or ''} {c.category_id or ''}"
            if c.category_id and cat_name_map.get(c.category_id):
                text += f" {cat_name_map[c.category_id]}"
            for wn in weak_names:
                if wn and wn in text:
                    recommended.append(c.to_dict())
                    break
    return jsonify({
        'assessmentId': assessment_id,
        'weakDimensions': weak_names,
        'recommendedCourses': recommended[:6],
    })


# ---------------------------------------------------------------------------
# 学习数据看板（管理员全局视图）
# ---------------------------------------------------------------------------

@hrm_bp.route('/analytics/dashboard', methods=['GET'])
@jwt_required()
def training_analytics_dashboard():
    """培训+考试全局数据看板：核心指标 + 图表数据。"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    from sqlalchemy import func

    # --- 核心指标 ---
    course_total = Course.query.filter_by(is_show=True).count()
    # 有培训授权的员工数（被指派过课程或考试）
    assigned_emp_ids = set()
    for a in CourseAssignment.query.with_entities(CourseAssignment.target_id).filter_by(target_type='user'):
        assigned_emp_ids.add(a[0])
    for cp in UserCourseProgress.query.with_entities(UserCourseProgress.employee_id).distinct():
        assigned_emp_ids.add(cp[0])
    learner_count = len(assigned_emp_ids) or Employee.query.filter(Employee.status.in_(['active', 'probation'])).count()

    # 考试通过率
    attempts = ExamAttempt.query.filter_by(status='submitted').all()
    exam_pass_rate = round(sum(1 for a in attempts if a.passed) / len(attempts) * 100, 1) if attempts else 0

    # 人均学习时长（分钟）
    total_sec = db.session.query(func.coalesce(func.sum(UserHourProgress.watched_duration), 0)).scalar() or 0
    avg_minutes = round(total_sec / 60 / learner_count) if learner_count else 0

    # --- 图表1: 课程完成率分布（批量查询消除 N+1） ---
    course_completion = []
    top_courses = Course.query.filter_by(is_show=True).limit(10).all()
    if top_courses:
        top_course_ids = [c.id for c in top_courses]
        # 批量查完成数
        finish_rows = db.session.query(
            UserCourseProgress.course_id, func.count(UserCourseProgress.id)
        ).filter(
            UserCourseProgress.course_id.in_(top_course_ids),
            UserCourseProgress.is_finished == True
        ).group_by(UserCourseProgress.course_id).all()
        finish_map = {r[0]: r[1] for r in finish_rows}
        # 批量查指派数（从 CourseAssignment 展开太重，用 UserCourseProgress 的 enrolled 近似）
        enrolled_rows = db.session.query(
            UserCourseProgress.course_id, func.count(func.distinct(UserCourseProgress.employee_id))
        ).filter(UserCourseProgress.course_id.in_(top_course_ids)).group_by(UserCourseProgress.course_id).all()
        enrolled_map = {r[0]: r[1] for r in enrolled_rows}
        for c in top_courses:
            finished = finish_map.get(c.id, 0)
            assigned = enrolled_map.get(c.id, 0)
            rate = round(finished / assigned * 100) if assigned else 0
            course_completion.append({'title': c.title, 'assigned': assigned, 'finished': finished, 'rate': rate})

    # --- 图表2: 部门学习活跃度（批量预查消除 N+1） ---
    dept_activity = []
    depts = Department.query.all()
    # 一次性查所有有学习记录的员工+部门
    all_progress = db.session.query(
        UserCourseProgress.employee_id
    ).distinct().all()
    learning_emp_ids = {r[0] for r in all_progress}
    # 员工→部门映射
    emp_dept_map = {}
    if learning_emp_ids:
        for e in Employee.query.filter(Employee.id.in_(list(learning_emp_ids))).all():
            emp_dept_map[e.id] = e.department_id
    # 按部门聚合
    from collections import defaultdict
    dept_learn_count = defaultdict(int)
    for eid in learning_emp_ids:
        did = emp_dept_map.get(eid)
        if did:
            dept_learn_count[did] += 1
    # 批量查观看时长
    duration_rows = db.session.query(
        Employee.department_id, func.coalesce(func.sum(UserHourProgress.watched_duration), 0)
    ).join(UserHourProgress, UserHourProgress.employee_id == Employee.id
    ).group_by(Employee.department_id).all()
    dept_minutes = {r[0]: int(r[1] // 60) for r in duration_rows}
    for d in depts:
        learn_count = dept_learn_count.get(d.id, 0)
        minutes = dept_minutes.get(d.id, 0)
        if learn_count or minutes:
            dept_activity.append({'name': d.name, 'learnCount': learn_count, 'minutes': minutes})
    dept_activity.sort(key=lambda x: -x['minutes'])

    # --- 图表3: 热门课程 Top5（SQL 聚合消除 N+1） ---
    popular_rows = db.session.query(
        UserCourseProgress.course_id, func.count(func.distinct(UserCourseProgress.employee_id))
    ).group_by(UserCourseProgress.course_id).order_by(
        func.count(func.distinct(UserCourseProgress.employee_id)).desc()
    ).limit(5).all()
    popular_course_ids = [r[0] for r in popular_rows]
    popular_course_map = {c.id: c.title for c in Course.query.filter(Course.id.in_(popular_course_ids)).all()} if popular_course_ids else {}
    popular = [{'title': popular_course_map.get(r[0], '?'), 'learnerCount': r[1]} for r in popular_rows]

    # --- 图表4: 考试统计（按任务，SQL GROUP BY 消除 Python 循环 O(tasks×attempts)） ---
    from sqlalchemy import case
    published_tasks = ExamTask.query.filter_by(status='published').all()
    published_task_ids = [t.id for t in published_tasks]
    published_task_titles = {t.id: t.title for t in published_tasks}
    exam_stats = []
    if published_task_ids:
        # 一次 GROUP BY 拿到每场考试的提交数、通过数、平均分
        passed_expr = func.sum(case((ExamAttempt.passed == True, 1), else_=0))
        stat_rows = db.session.query(
            ExamAttempt.task_id,
            func.count(ExamAttempt.id).label('submissions'),
            passed_expr.label('passed_cnt'),
            func.avg(ExamAttempt.score).label('avg_score'),
        ).filter(
            ExamAttempt.task_id.in_(published_task_ids),
            ExamAttempt.status == 'submitted',
        ).group_by(ExamAttempt.task_id).all()
        seen_task_ids = set()
        for tid, submissions, passed_cnt, avg_score in stat_rows:
            seen_task_ids.add(tid)
            submissions = int(submissions or 0)
            passed_cnt = int(passed_cnt or 0)
            avg = round(float(avg_score), 1) if avg_score is not None else 0
            exam_stats.append({
                'title': published_task_titles.get(tid, '?'),
                'submissions': submissions,
                'passed': passed_cnt,
                'avgScore': avg,
                'passRate': round(passed_cnt / submissions * 100) if submissions else 0,
            })
    # 补上无提交的已发布考试（显示 0）
    for tid, title in published_task_titles.items():
        if tid not in seen_task_ids:
            exam_stats.append({'title': title, 'submissions': 0, 'passed': 0, 'avgScore': 0, 'passRate': 0})

    return jsonify({
        'metrics': {
            'courseTotal': course_total,
            'learnerCount': learner_count,
            'examPassRate': exam_pass_rate,
            'avgLearningMinutes': avg_minutes,
            'attemptCount': len(attempts),
            'questionCount': ExamQuestion.query.filter_by(review_status='approved').count(),
        },
        'courseCompletion': course_completion,
        'deptActivity': dept_activity[:8],
        'popularCourses': popular,
        'examStats': exam_stats,
    })


# ---------------------------------------------------------------------------
# 学习数据导出（Excel：成绩单/学习进度/积分排行）
# ---------------------------------------------------------------------------

@hrm_bp.route('/export/exam-results/<task_id>', methods=['GET'])
@jwt_required()
def export_exam_results(task_id):
    """导出考试成绩单 Excel。"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    from services.data_export import export_exam_results as do_export
    buf = do_export(task_id)
    task = ExamTask.query.get(task_id)
    filename = f'成绩单_{task.title if task else task_id}_{datetime.utcnow().strftime("%Y%m%d")}.xlsx'
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@hrm_bp.route('/export/course-progress/<course_id>', methods=['GET'])
@jwt_required()
def export_course_progress(course_id):
    """导出课程学习进度 Excel。"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    from services.data_export import export_course_progress as do_export
    buf = do_export(course_id)
    course = Course.query.get(course_id)
    filename = f'学习进度_{course.title if course else course_id}_{datetime.utcnow().strftime("%Y%m%d")}.xlsx'
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@hrm_bp.route('/export/points-leaderboard', methods=['GET'])
@jwt_required()
def export_points():
    """导出积分排行榜 Excel。"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    from services.data_export import export_points_leaderboard
    buf = export_points_leaderboard()
    filename = f'积分排行榜_{datetime.utcnow().strftime("%Y%m%d")}.xlsx'
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ---------------------------------------------------------------------------
# 团队 PK 竞赛：赛季排行榜聚合
# ---------------------------------------------------------------------------

@hrm_bp.route('/pk-seasons/<season_id>/leaderboard', methods=['GET'])
@jwt_required()
def pk_season_leaderboard(season_id):
    """赛季排行榜：按部门聚合积分 + 个人贡献榜。"""
    actor = User.query.get(get_jwt_identity())
    if not actor:
        return jsonify({'error': '无权限'}), 403
    season = PKSeason.query.get(season_id)
    if not season:
        return jsonify({'error': '赛季不存在'}), 404

    from sqlalchemy import func
    start, end = season.start_date, season.end_date
    dept_ids = season.participant_dept_ids or []
    metric = season.metric or 'total_points'

    # 赛季内积分日志
    q = db.session.query(
        PointLog.employee_id,
        func.sum(PointLog.points).label('pts'),
    ).filter(
        PointLog.created_at >= start, PointLog.created_at <= end,
        PointLog.action != 'wrong_question_mastered',
    ).group_by(PointLog.employee_id)

    emp_points = {r[0]: int(r[1]) for r in q.all()}

    # 按部门聚合
    depts = Department.query.all() if not dept_ids else Department.query.filter(Department.id.in_(dept_ids)).all()
    team_board = []
    individual_board = []
    for d in depts:
        emps = Employee.query.filter_by(department_id=d.id).all()
        emp_ids = [e.id for e in emps]
        dept_pts = sum(emp_points.get(eid, 0) for eid in emp_ids)
        avg_pts = round(dept_pts / len(emp_ids), 1) if emp_ids else 0
        score = dept_pts if metric == 'total_points' else avg_pts
        team_board.append({
            'deptId': d.id, 'deptName': d.name,
            'memberCount': len(emp_ids),
            'totalPoints': dept_pts, 'avgPoints': avg_pts, 'score': score,
        })
        # 个人贡献
        for eid in emp_ids:
            if emp_points.get(eid, 0) > 0:
                individual_board.append({
                    'employeeId': eid, 'employeeName': next((e.name for e in emps if e.id == eid), None),
                    'deptName': d.name, 'points': emp_points[eid],
                })

    team_board.sort(key=lambda x: -x['score'])
    individual_board.sort(key=lambda x: -x['points'])

    # 加排名
    for i, t in enumerate(team_board):
        t['rank'] = i + 1
    for i, p in enumerate(individual_board):
        p['rank'] = i + 1

    return jsonify({
        'season': season.to_dict(),
        'teamBoard': team_board,
        'individualBoard': individual_board[:20],
    })


# ---------------------------------------------------------------------------
# 学习提醒：手动触发催学检查
# ---------------------------------------------------------------------------

@hrm_bp.route('/study-reminder/run-check', methods=['POST'])
@jwt_required()
def run_study_reminder_check():
    """手动触发催学检查（管理员）。"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    from services.study_reminder import run_daily_check
    sent = run_daily_check()
    log_operation('study-reminder', 'manual_check', None, {'sent': sent})
    return jsonify({'sent': sent, 'message': f'已发送 {sent} 条催学通知'})


@hrm_bp.route('/export/learning-report/<employee_id>', methods=['GET'])
@jwt_required()
def export_learning_report(employee_id):
    """导出员工个人学习总结 PDF 报告。"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    from services.pdf_report import generate_learning_report
    try:
        buf = generate_learning_report(employee_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    emp = Employee.query.get(employee_id)
    filename = f'学习总结_{emp.name if emp else employee_id}_{datetime.utcnow().strftime("%Y%m%d")}.pdf'
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype='application/pdf')


def _gather_course_source_text(course_id: str) -> str:
    """从课程内容拼接出题源文本：章节/课时标题 + 附件文本。"""
    parts = []
    course = Course.query.get(course_id)
    if not course:
        return ''
    if course.short_desc:
        parts.append(course.short_desc)
    if course.content:
        parts.append(course.content)
    # 课时标题
    hours = CourseHour.query.filter_by(course_id=course_id).all()
    for h in hours:
        parts.append(f'【{h.title}】')
    # 附件文本（尝试提取 PDF/Word/TXT）
    attachments = CourseAttachment.query.filter_by(course_id=course_id).all()
    for att in attachments:
        if not att.file_url:
            continue
        try:
            # file_url 形如 /uploads/xxx 或绝对路径
            path = att.file_url
            if path.startswith('/uploads/'):
                path = os.path.join(current_app.config['UPLOAD_FOLDER'],
                                    path[len('/uploads/'):])
            if os.path.isfile(path):
                from services.pdf_parser import extract_text_from_file
                text = extract_text_from_file(path)
                if text:
                    parts.append(text[:2000])
        except Exception:
            continue
    return '\n'.join(p for p in parts if p).strip()


# ---------------------------------------------------------------------------
# 章节文档资料（管理员上传/管理章节的学习材料）
# ---------------------------------------------------------------------------

@hrm_bp.route('/course-chapters/<chapter_id>/upload-material', methods=['POST'])
@jwt_required()
def upload_chapter_material(chapter_id):
    """上传章节文档资料到 /uploads。multipart: file=..., title?(form)"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    chapter = CourseChapter.query.get(chapter_id)
    if not chapter:
        return jsonify({'error': '章节不存在'}), 404
    if 'file' not in request.files:
        return jsonify({'error': '未提供文件'}), 400
    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'error': '空文件'}), 400
    ext = (file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else '')
    allowed = {'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'txt', 'md', 'png', 'jpg', 'jpeg'}
    if ext not in allowed:
        return jsonify({'error': f'不支持的格式: {ext}'}), 400

    file_id = new_id()
    filename = f'chapters/{chapter_id}/{file_id}.{ext}'
    from services.storage import save_local_upload
    filename = save_local_upload(file, filename)
    url = f'/uploads/{filename}'
    title = request.form.get('title') or os.path.splitext(secure_filename(file.filename))[0]
    materials = list(chapter.materials or [])
    materials.append({'title': title, 'url': url, 'ext': ext})
    chapter.materials = materials
    try:
        log_operation('course-chapters', 'upload_material', chapter_id, {'url': url}, strict=True)
        db.session.commit()
    except Exception:
        db.session.rollback()
        storage.delete_object_if_unreferenced(filename, tenant_id=chapter.tenant_id)
        raise
    return jsonify({'chapterId': chapter_id, 'material': materials[-1], 'materials': materials})


@hrm_bp.route('/course-chapters/<chapter_id>/materials', methods=['PUT'])
@jwt_required()
def update_chapter_materials(chapter_id):
    """设置章节资料列表（前端管理增删后整体回写）。body: {materials: [{title,url,ext}]}"""
    actor = User.query.get(get_jwt_identity())
    if not actor or actor.role not in PRIVILEGED_ROLES:
        return jsonify({'error': '无权限'}), 403
    chapter = CourseChapter.query.get(chapter_id)
    if not chapter:
        return jsonify({'error': '章节不存在'}), 404
    old_references = _record_storage_references(chapter)
    data = request.get_json() or {}
    new_materials = data.get('materials') or []
    new_references = storage.storage_reference_keys(new_materials)
    try:
        storage.assert_storage_references_belong_to_tenant(
            new_references - old_references,
            tenant_id=chapter.tenant_id,
        )
    except storage.StorageTenantBindingError as exc:
        db.session.rollback()
        return jsonify(exc.to_payload()), 400
    chapter.materials = new_materials
    db.session.commit()
    _release_unreferenced_storage(
        old_references - new_references,
        tenant_id=chapter.tenant_id,
    )
    return jsonify({'chapterId': chapter_id, 'materials': chapter.materials or []})


@hrm_bp.route('/performance-reviews/<review_id>/generate-training-plan', methods=['POST'])
@jwt_required()
def generate_performance_training_plan(review_id):
    denied = require_roles(ORG_WRITE_ROLES | TRAINING_WRITE_ROLES, '无权限生成培训计划')
    if denied:
        return denied
    review = PerformanceReview.query.get(review_id)
    if not review:
        return jsonify({'error': 'Performance review not found'}), 404
    if review.status not in ('completed', 'finalized', 'closed'):
        return jsonify({'error': 'Performance review must be completed before growth linkage'}), 400

    existing_record = TrainingRecord.query.filter(
        TrainingRecord.employee_id == review.employee_id,
        TrainingRecord.feedback.like(f'%performance review {review.id}%'),
    ).order_by(TrainingRecord.created_at.asc()).first()
    if existing_record:
        existing_plan = TrainingPlan.query.get(existing_record.plan_id) if existing_record.plan_id else None
        existing_course = TrainingCourse.query.get(existing_record.course_id) if existing_record.course_id else None
        if existing_plan and existing_course:
            return jsonify(performance_training_flow_payload(
                review,
                existing_course,
                existing_plan,
                existing_record,
                created=False,
            ))

    data = request.get_json() or {}
    employee_name = review.employee.name if review.employee else 'Employee'
    course_name = _trim_text(data.get('courseName')) or f'Performance Growth Coaching - {employee_name}'
    plan_name = _trim_text(data.get('planName')) or f'{employee_name} growth plan from performance review {review.id}'
    start_time = parse_datetime(data.get('startTime')) if data.get('startTime') else datetime.utcnow()
    end_time = parse_datetime(data.get('endTime')) if data.get('endTime') else start_time + timedelta(days=30)
    marker = f'performance review {review.id}'

    course = TrainingCourse.query.filter_by(name=course_name).first()
    course_created = False
    if not course:
        course = TrainingCourse(
            id=new_id(),
            name=course_name,
            category='Performance growth',
            description=(
                f'Generated from {marker}; grade={review.grade or "-"}; '
                f'final_score={review.final_score or "-"}; result={review.result or "-"}'
            ),
            status='active',
        )
        db.session.add(course)
        db.session.flush()
        course_created = True

    plan = TrainingPlan(
        id=new_id(),
        name=plan_name,
        course_id=course.id,
        start_time=start_time,
        end_time=end_time,
        status='planned',
        remark=(
            f'Generated from {marker}; employee={employee_name}; '
            f'grade={review.grade or "-"}; final score {review.final_score or "-"}'
        ),
    )
    db.session.add(plan)
    db.session.flush()

    record = TrainingRecord(
        id=new_id(),
        plan_id=plan.id,
        course_id=course.id,
        employee_id=review.employee_id,
        status='registered',
        feedback=(
            f'Generated from {marker}; final score {review.final_score or "-"}; '
            f'grade={review.grade or "-"}; result={review.result or "-"}'
        ),
    )
    db.session.add(record)
    log_operation('performance-reviews', 'generate_training_plan', review.id, {
        'employeeId': review.employee_id,
        'courseId': course.id,
        'planId': plan.id,
        'recordId': record.id,
        'courseCreated': course_created,
    })
    db.session.commit()
    return jsonify(performance_training_flow_payload(review, course, plan, record, created=True))


@hrm_bp.route('/offers/<offer_id>/convert-to-employee', methods=['POST'])
@jwt_required()
def convert_offer_to_employee(offer_id):
    denied = require_roles(ORG_WRITE_ROLES | RECRUITMENT_ROLES, '无权限将 Offer 转为员工')
    if denied:
        return denied
    current_user_id = get_jwt_identity()
    offer = Offer.query.get(offer_id)
    if not offer:
        return jsonify({'error': 'Offer not found'}), 404
    if offer.employee_id:
        employee = Employee.query.get(offer.employee_id)
        if employee:
            ensure_default_onboarding_tasks(employee.id, current_user_id)
            ensure_offer_salary_profile(employee, offer)
            ensure_offer_contract(employee, offer, current_user_id)
            db.session.commit()
            return jsonify(offer_onboarding_flow_payload(offer, employee, created=False))
    employee = Employee.query.filter_by(source_offer_id=offer.id).first()
    if employee:
        offer.employee_id = employee.id
        ensure_default_onboarding_tasks(employee.id, current_user_id)
        ensure_offer_salary_profile(employee, offer)
        ensure_offer_contract(employee, offer, current_user_id)
        db.session.commit()
        return jsonify(offer_onboarding_flow_payload(offer, employee, created=False))
    candidate = offer.candidate
    if not candidate:
        return jsonify({'error': 'Offer has no candidate'}), 400
    job = offer.job or Job.query.get(candidate.job_id)
    hire_date = offer.onboarding_date or date.today()
    employee = Employee(
        id=new_id(),
        employee_no=generate_employee_no(),
        name=candidate.name,
        email=candidate.email,
        phone=candidate.phone,
        status='pending_onboard',
        department_id=job.department_id if job else None,
        job_title=job.title if job else offer.title,
        hire_date=hire_date,
        probation_months=3,
        probation_end_date=add_months(hire_date, 3),
        source_offer_id=offer.id,
        candidate_id=candidate.id,
        created_by=current_user_id,
        updated_by=current_user_id,
        remark='由Offer一键转员工自动生成',
    )
    db.session.add(employee)
    db.session.flush()
    ensure_employee_portal_account(employee)
    offer.employee_id = employee.id
    offer.status = 'converted'
    candidate.status = 'converted'
    ensure_default_onboarding_tasks(employee.id, current_user_id)
    ensure_offer_salary_profile(employee, offer)
    ensure_offer_contract(employee, offer, current_user_id)
    db.session.add(Notification(
        id=new_id(),
        user_id=current_user_id,
        title='候选人已转员工',
        content=f'{employee.name} 已生成员工档案，状态为待入职',
        notice_type='employee',
        status='unread',
        link_url=f'/hrm/employees?id={employee.id}',
    ))
    log_operation('offers', 'convert_to_employee', offer.id, {'employeeId': employee.id})
    db.session.commit()
    return jsonify(offer_onboarding_flow_payload(offer, employee, created=True))


@hrm_bp.route('/employees/<employee_id>/generate-onboarding', methods=['POST'])
@jwt_required()
def generate_onboarding(employee_id):
    denied = require_roles(ORG_WRITE_ROLES, '无权限生成入职任务')
    if denied:
        return denied
    employee = Employee.query.get(employee_id)
    if not employee:
        return jsonify({'error': 'Employee not found'}), 404
    tasks = ensure_default_onboarding_tasks(employee_id, get_jwt_identity())
    log_operation('employees', 'generate_onboarding', employee_id)
    db.session.commit()
    return jsonify({'employee': employee.to_dict(), 'tasks': [task.to_dict() for task in tasks]})


@hrm_bp.route('/employees/<employee_id>/submit-onboarding', methods=['POST'])
@jwt_required()
def submit_onboarding_approval(employee_id):
    denied = require_roles(ORG_WRITE_ROLES, '无权限提交入职审批')
    if denied:
        return denied
    employee = Employee.query.get(employee_id)
    if not employee:
        return jsonify({'error': 'Employee not found'}), 404
    approval = create_approval('onboarding', employee.id, f'入职审批：{employee.name}')
    log_operation('employees', 'submit_onboarding', employee_id)
    db.session.commit()
    return jsonify({'employee': employee.to_dict(), 'approval': approval.to_dict()})


@hrm_bp.route('/employees/<employee_id>/lifecycle', methods=['GET'])
@jwt_required()
def employee_lifecycle(employee_id):
    denied = require_roles(ORG_READ_ROLES, '无权限查看员工生命周期')
    if denied:
        return denied
    employee = Employee.query.get(employee_id)
    if not employee:
        return jsonify({'error': 'Employee not found'}), 404
    return jsonify(employee_lifecycle_payload(employee))


@hrm_bp.route('/<resource>/<item_id>/submit', methods=['POST'])
@jwt_required()
def submit_business(resource, item_id):
    rbac_err = _check_resource_rbac(resource, write=True)
    if rbac_err:
        return rbac_err
    model_map = {
        'employee-changes': (EmployeeChange, 'employee_change', lambda obj: f'Employee change approval: {obj.employee.name if obj.employee else "Employee"}'),
        'employee-requests': (EmployeeRequest, 'employee_request', lambda obj: f'{obj.employee.name if obj.employee else "员工"}{obj.request_type}申请'),
        'probations': (Probation, 'probation', lambda obj: f'转正审批：{obj.employee.name if obj.employee else "员工"}'),
        'resignations': (Resignation, 'resignation', lambda obj: f'离职审批：{obj.employee.name if obj.employee else "员工"}'),
    }
    item = model_map.get(resource)
    if not item:
        return jsonify({'error': 'Unsupported submit resource'}), 400
    model, business_type, title_builder = item
    obj = model.query.get(item_id)
    if not obj:
        return jsonify({'error': 'Not found'}), 404
    approval = create_approval(business_type, obj.id, title_builder(obj))
    obj.status = 'pending'
    if hasattr(obj, 'approval_id'):
        obj.approval_id = approval.id
    log_operation(resource, 'submit', item_id)
    db.session.commit()
    return jsonify({'record': obj.to_dict(), 'approval': approval.to_dict()})


@hrm_bp.route('/<resource>/<item_id>/cancel', methods=['POST'])
@jwt_required()
def cancel_business(resource, item_id):
    rbac_err = _check_resource_rbac(resource, write=True)
    if rbac_err:
        return rbac_err
    cfg = get_config(resource)
    if not cfg:
        return jsonify({'error': 'Unknown resource'}), 404
    obj = cfg['model'].query.get(item_id)
    if not obj or not hasattr(obj, 'status'):
        return jsonify({'error': 'Not found'}), 404
    obj.status = 'cancelled'
    log_operation(resource, 'cancel', item_id)
    db.session.commit()
    return jsonify(obj.to_dict())


def _check_resource_rbac(resource, write=False):
    """统一资源级角色检查。返回 None=通过，否则返回错误响应。"""
    return require_resource_access(resource, write=write)


@hrm_bp.route('/<resource>/<item_id>/workflow', methods=['GET'])
@jwt_required()
def get_resource_workflow(resource, item_id):
    rbac_err = _check_resource_rbac(resource)
    if rbac_err:
        return rbac_err
    try:
        record = get_workflow_record(resource, item_id)
        return jsonify(workflow_payload(resource, record))
    except WorkflowError as exc:
        return jsonify({'error': str(exc)}), exc.status_code


@hrm_bp.route('/<resource>/<item_id>/workflow/<transition>', methods=['POST'])
@jwt_required()
def run_resource_workflow(resource, item_id, transition):
    rbac_err = _check_resource_rbac(resource, write=True)
    if rbac_err:
        return rbac_err
    try:
        result = apply_workflow_transition(resource, item_id, transition, request.get_json() or {})
        return jsonify(result)
    except WorkflowError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), exc.status_code


@hrm_bp.route('/<resource>', methods=['GET'])
@jwt_required()
def list_resource(resource):
    cfg = get_config(resource)
    if not cfg:
        return jsonify({'error': '未知资源类型'}), 404
    rbac_err = _check_resource_rbac(resource)
    if rbac_err:
        return rbac_err
    if cfg.get('before_list') == 'sync_candidates':
        sync_candidates_from_resumes()
    model = cfg['model']
    query = apply_tenant_scope(model.query, model)
    tenant = current_tenant()
    if (
        resource == 'employees'
        and tenant
        and tenant.slug == 'HPT-00000001'
        and not request.args.get('status')
        and request.args.get('includeInactive', '').lower() not in {'1', 'true', 'yes'}
    ):
        query = query.filter(Employee.status.in_(('active', 'probation')))
    # 批量预加载关系（消除 to_dict 内懒加载 N+1）；selectinload 每关系一次 IN 查询，避免笛卡尔积
    eager_rels = cfg.get('eager') or []
    if eager_rels:
        opts = []
        for rel_name in eager_rels:
            rel = getattr(model, rel_name, None)
            if rel is not None:
                opts.append(selectinload(rel))
        if opts:
            query = query.options(*opts)
    # scope_to_user：非管理员只能看到自己提交的记录
    if cfg.get('scope_to_user'):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        admin_roles = {'admin', 'hr_admin'}
        if current_user and current_user.role not in admin_roles and hasattr(model, 'user_id'):
            query = query.filter(model.user_id == current_user_id)
    if cfg.get('personal_scope') and hasattr(model, 'user_id'):
        current_user_id = get_jwt_identity()
        if model is Notification:
            query = query.filter(or_(
                model.user_id == current_user_id,
                and_(model.user_id.is_(None), model.employee_id.is_(None)),
            ))
        else:
            query = query.filter(or_(model.user_id == current_user_id, model.user_id.is_(None)))
    keyword = request.args.get('keyword')
    if keyword and cfg.get('search'):
        like = f'%{keyword}%'
        query = query.filter(or_(*[getattr(model, field).like(like) for field in cfg['search'] if hasattr(model, field)]))
    query = _apply_resource_filters(query, model, cfg)
    if resource == 'attendance-records':
        tenant_id = current_tenant_id()
        if tenant_id:
            query = query.filter(
                AttendanceRecord.employee_id.in_(
                    db.session.query(Employee.id).filter(Employee.tenant_id == tenant_id)
                )
            )
        query = query.order_by(AttendanceRecord.attendance_date.desc(), AttendanceRecord.check_in_time.desc())
    elif hasattr(model, 'created_at'):
        query = query.order_by(model.created_at.desc())

    # 分页支持：page + size 参数（向后兼容：不传则返回全部，最多 1000）
    page = request.args.get('page', type=int)
    size = request.args.get('size', type=int, default=50)
    if page and page > 0:
        size = max(1, min(size, 200))  # 单页上限 200，避免 0/负数导致除零或绕过分页
        total = query.count()
        data = query.offset((page - 1) * size).limit(size).all()
        return jsonify({
            'items': [item.to_dict() for item in data],
            'total': total,
            'page': page,
            'size': size,
            'pages': (total + size - 1) // size,
        })
    else:
        # 兼容旧前端：不传 page 时返回数组（最多 1000）
        data = query.limit(1000).all()
    return jsonify([item.to_dict() for item in data])


@hrm_bp.route('/oa-employee-sync/status', methods=['GET'])
@jwt_required()
def oa_employee_sync_status():
    denied = require_roles({'admin', 'hr_admin'}, '无权限查看 OA 人员同步状态')
    if denied:
        return denied
    tenant = current_tenant()
    if not tenant or tenant.slug != 'HPT-00000001':
        return jsonify({'error': 'Not found'}), 404
    from services.oa_employee_sync import latest_sync_run

    latest = latest_sync_run(tenant.slug)
    return jsonify({
        'enabled': os.getenv('OA_EMPLOYEE_SYNC_ENABLED', '0') == '1',
        'tenantSlug': tenant.slug,
        'latestRun': latest.to_dict() if latest else None,
    })


@hrm_bp.route('/oa-employee-sync/run', methods=['POST'])
@jwt_required()
def run_oa_employee_sync():
    denied = require_roles({'admin', 'hr_admin'}, '无权限执行 OA 人员同步')
    if denied:
        return denied
    tenant = current_tenant()
    if not tenant or tenant.slug != 'HPT-00000001':
        return jsonify({'error': 'Not found'}), 404
    from services.oa_employee_sync import OaSyncBusy, OaSyncDisabled, sync_oa_employees

    try:
        result = sync_oa_employees(tenant_slug=tenant.slug, trigger='manual')
    except OaSyncBusy:
        return jsonify({'error': 'OA 人员同步正在执行', 'code': 'OA_SYNC_BUSY'}), 409
    except OaSyncDisabled as exc:
        return jsonify({'error': str(exc), 'code': 'OA_SYNC_DISABLED'}), 503
    return jsonify({
        'runId': result.run_id,
        'sourceCount': result.source_count,
        'createdCount': result.created_count,
        'updatedCount': result.updated_count,
        'archivedCount': result.archived_count,
        'unchangedCount': result.unchanged_count,
    })


@hrm_bp.route('/oa-employee-sync/preview', methods=['POST'])
@jwt_required()
def preview_oa_employee_sync_route():
    denied = require_roles({'admin', 'hr_admin'}, '无权限预检 OA 人员同步')
    if denied:
        return denied
    tenant = current_tenant()
    if not tenant or tenant.slug != 'HPT-00000001':
        return jsonify({'error': 'Not found'}), 404
    from services.oa_employee_sync import OaSyncDisabled, preview_oa_employee_sync

    try:
        preview = preview_oa_employee_sync(tenant_slug=tenant.slug)
    except OaSyncDisabled as exc:
        return jsonify({'error': str(exc), 'code': 'OA_SYNC_DISABLED'}), 503
    return jsonify({
        'readOnly': True,
        'sourceCount': preview.source_count,
        'createCount': preview.create_count,
        'updateCount': preview.update_count,
        'archiveCount': preview.archive_count,
        'createNames': list(preview.create_names),
        'archiveNames': list(preview.archive_names),
    })


def _attendance_sync_guard(message: str):
    denied = require_roles({'admin', 'hr_admin'}, message)
    if denied:
        return denied
    tenant = current_tenant()
    if not tenant or tenant.slug != 'HPT-00000001':
        return jsonify({'error': 'Not found'}), 404
    return None


@hrm_bp.route('/attendance-sync/status', methods=['GET'])
@jwt_required()
def attendance_sync_status():
    denied = _attendance_sync_guard('无权限查看考勤机同步状态')
    if denied:
        return denied
    from services.attendance_punch_sync import (
        credentials_configured,
        latest_sync_run,
        mapping_summary,
    )

    latest = latest_sync_run()
    summary = mapping_summary()
    return jsonify({
        'enabled': os.getenv('ATTENDANCE_SYNC_ENABLED', '0') == '1',
        'configured': credentials_configured(),
        'tenantSlug': current_tenant().slug,
        'latestRun': latest.to_dict() if latest else None,
        'people': {
            'unmatched': summary['unmatched'],
            'suggested': summary['suggested'],
            'confirmed': summary['confirmed'],
            'ignored': summary['ignored'],
        },
        'punchCount': summary['punches'],
        'dailyRecordCount': summary['daily_records'],
    })


@hrm_bp.route('/attendance-sync/run', methods=['POST'])
@jwt_required()
def run_attendance_sync():
    denied = _attendance_sync_guard('无权限执行考勤机同步')
    if denied:
        return denied
    from services.attendance_punch_sync import (
        AttendanceSyncBusy,
        AttendanceSyncDisabled,
        sync_attendance_punches,
    )

    try:
        payload = request.get_json(silent=True) or {}
        since = None
        since_value = str(payload.get('since') or '').strip()
        if since_value:
            try:
                since = datetime.strptime(since_value[:10], '%Y-%m-%d')
            except ValueError:
                return jsonify({'error': 'since 格式应为 YYYY-MM-DD', 'code': 'ATTENDANCE_SYNC_INVALID'}), 400
        result = sync_attendance_punches(trigger='manual', since=since)
    except AttendanceSyncBusy:
        return jsonify({'error': '考勤机同步正在执行', 'code': 'ATTENDANCE_SYNC_BUSY'}), 409
    except AttendanceSyncDisabled as exc:
        return jsonify({'error': str(exc), 'code': 'ATTENDANCE_SYNC_DISABLED'}), 503
    return jsonify({
        'runId': result.run_id,
        'peopleRead': result.people_read,
        'peopleUpserted': result.people_upserted,
        'punchesRead': result.punches_read,
        'punchesInserted': result.punches_inserted,
        'punchesDuplicate': result.punches_duplicate,
        'unmatchedCount': result.unmatched_count,
        'suggestedCount': result.suggested_count,
        'confirmedCount': result.confirmed_count,
        'dailyRecordsUpserted': result.daily_records_upserted,
    })


@hrm_bp.route('/attendance-sync/people', methods=['GET'])
@jwt_required()
def attendance_sync_people():
    denied = _attendance_sync_guard('无权限查看考勤机人员映射')
    if denied:
        return denied
    from services.attendance_punch_sync import list_external_people

    status = (request.args.get('status') or '').strip() or None
    people = list_external_people(status=status)
    return jsonify([person.to_dict() for person in people])


@hrm_bp.route('/attendance-sync/people/<person_id>/confirm', methods=['POST'])
@jwt_required()
def attendance_sync_confirm_person(person_id: str):
    denied = _attendance_sync_guard('无权限确认考勤机人员映射')
    if denied:
        return denied
    from services.attendance_punch_sync import confirm_external_person

    payload = request.get_json(silent=True) or {}
    employee_id = str(payload.get('employeeId') or '').strip()
    if not employee_id:
        return jsonify({'error': '请选择员工', 'code': 'EMPLOYEE_REQUIRED'}), 400
    try:
        person = confirm_external_person(
            person_id,
            employee_id=employee_id,
            actor_user_id=get_jwt_identity(),
        )
    except LookupError:
        return jsonify({'error': 'Not found'}), 404
    except ValueError as exc:
        return jsonify({'error': str(exc), 'code': 'EMPLOYEE_ALREADY_MAPPED'}), 409
    return jsonify(person.to_dict())


@hrm_bp.route('/attendance-sync/people/<person_id>/ignore', methods=['POST'])
@jwt_required()
def attendance_sync_ignore_person(person_id: str):
    denied = _attendance_sync_guard('无权限忽略考勤机人员')
    if denied:
        return denied
    from services.attendance_punch_sync import ignore_external_person

    try:
        person = ignore_external_person(person_id, actor_user_id=get_jwt_identity())
    except LookupError:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(person.to_dict())


def _attendance_policy_guard(message: str):
    denied = require_roles({'admin', 'hr_admin'}, message)
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    return None


def _attendance_policy_error(exc):
    db.session.rollback()
    return jsonify({'error': str(exc), 'code': getattr(exc, 'code', 'ATTENDANCE_POLICY_INVALID')}), 400


def _attendance_policy_model(kind: str):
    return {
        'shifts': AttendanceShift,
        'rule-sets': AttendanceRuleSet,
        'groups': AttendanceGroup,
        'memberships': AttendanceGroupMembership,
        'holidays': AttendanceHoliday,
        'schedules': AttendanceSchedule,
    }.get(kind)


@hrm_bp.route('/attendance-policy/snapshot', methods=['GET'])
@jwt_required()
def attendance_policy_snapshot_route():
    denied = _attendance_policy_guard('无权限查看考勤制度')
    if denied:
        return denied
    from services.attendance_policy import policy_snapshot

    return jsonify({
        **policy_snapshot(current_tenant_id()),
        'generatedAt': datetime.utcnow().isoformat() + 'Z',
    })


@hrm_bp.route('/attendance-policy/daily-results', methods=['GET'])
@jwt_required()
def attendance_policy_daily_results_route():
    denied = _attendance_policy_guard('无权限查看考勤日报')
    if denied:
        return denied
    from services.attendance_policy import AttendancePolicyError, list_daily_results

    try:
        limit = int(request.args.get('limit', '500'))
        rows = list_daily_results(
            current_tenant_id(),
            start_value=request.args.get('startDate'),
            end_value=request.args.get('endDate'),
            employee_id=(request.args.get('employeeId') or '').strip() or None,
            status=(request.args.get('status') or '').strip() or None,
            limit=limit,
        )
    except AttendancePolicyError as exc:
        return _attendance_policy_error(exc)
    except ValueError:
        return jsonify({'error': 'limit 应为整数', 'code': 'ATTENDANCE_POLICY_INVALID'}), 400
    return jsonify([row.to_dict() for row in rows])


@hrm_bp.route('/attendance-policy/recalculate', methods=['POST'])
@jwt_required()
def attendance_policy_recalculate_route():
    denied = _attendance_policy_guard('无权限重算考勤日报')
    if denied:
        return denied
    from services.attendance_policy import AttendancePolicyError, recalculate_daily_results

    payload = request.get_json(silent=True) or {}
    try:
        result = recalculate_daily_results(
            current_tenant_id(),
            payload.get('startDate'),
            payload.get('endDate'),
            employee_id=(str(payload.get('employeeId') or '').strip() or None),
        )
        db.session.commit()
    except LookupError:
        db.session.rollback()
        return jsonify({'error': '员工不存在或不属于当前企业', 'code': 'EMPLOYEE_NOT_FOUND'}), 404
    except AttendancePolicyError as exc:
        return _attendance_policy_error(exc)
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': '考勤日报保存冲突，请重试', 'code': 'ATTENDANCE_POLICY_CONFLICT'}), 409
    return jsonify(result)


@hrm_bp.route('/attendance-policy/<kind>', methods=['POST'])
@jwt_required()
def create_attendance_policy_row(kind: str):
    denied = _attendance_policy_guard('无权限维护考勤制度')
    if denied:
        return denied
    if kind == 'schedules':
        from services.attendance_policy import AttendancePolicyError, upsert_schedule

        try:
            row = upsert_schedule(
                current_tenant_id(),
                request.get_json(silent=True) or {},
                actor_id=get_jwt_identity(),
            )
            db.session.commit()
        except AttendancePolicyError as exc:
            return _attendance_policy_error(exc)
        except IntegrityError:
            db.session.rollback()
            return jsonify({'error': '日排班保存冲突，请重试', 'code': 'ATTENDANCE_POLICY_CONFLICT'}), 409
        return jsonify(row.to_dict()), 200

    model = _attendance_policy_model(kind)
    if not model:
        return jsonify({'error': 'Unknown attendance policy resource'}), 404
    from services.attendance_policy import (
        AttendancePolicyError,
        save_group,
        save_holiday,
        save_membership,
        save_rule_set,
        save_shift,
    )

    saver = {
        'shifts': save_shift,
        'rule-sets': save_rule_set,
        'groups': save_group,
        'memberships': save_membership,
        'holidays': save_holiday,
    }[kind]
    try:
        row = saver(
            current_tenant_id(),
            request.get_json(silent=True) or {},
            actor_id=get_jwt_identity(),
        )
        db.session.commit()
    except AttendancePolicyError as exc:
        return _attendance_policy_error(exc)
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': '考勤制度保存冲突，请重试', 'code': 'ATTENDANCE_POLICY_CONFLICT'}), 409
    return jsonify(row.to_dict()), 201


@hrm_bp.route('/attendance-policy/<kind>/<row_id>', methods=['PUT'])
@jwt_required()
def update_attendance_policy_row(kind: str, row_id: str):
    denied = _attendance_policy_guard('无权限维护考勤制度')
    if denied:
        return denied
    model = _attendance_policy_model(kind)
    if not model:
        return jsonify({'error': 'Unknown attendance policy resource'}), 404
    row = model.query.filter_by(id=row_id, tenant_id=current_tenant_id()).first()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    if kind == 'schedules':
        from services.attendance_policy import AttendancePolicyError, upsert_schedule

        try:
            updated = upsert_schedule(
                current_tenant_id(),
                request.get_json(silent=True) or {},
                actor_id=get_jwt_identity(),
                existing=row,
            )
            db.session.commit()
        except AttendancePolicyError as exc:
            return _attendance_policy_error(exc)
        except IntegrityError:
            db.session.rollback()
            return jsonify({'error': '日排班保存冲突，请重试', 'code': 'ATTENDANCE_POLICY_CONFLICT'}), 409
        return jsonify(updated.to_dict())
    from services.attendance_policy import (
        AttendancePolicyError,
        save_group,
        save_holiday,
        save_membership,
        save_rule_set,
        save_shift,
    )

    saver = {
        'shifts': save_shift,
        'rule-sets': save_rule_set,
        'groups': save_group,
        'memberships': save_membership,
        'holidays': save_holiday,
    }[kind]
    try:
        updated = saver(
            current_tenant_id(),
            request.get_json(silent=True) or {},
            actor_id=get_jwt_identity(),
            existing=row,
        )
        db.session.commit()
    except AttendancePolicyError as exc:
        return _attendance_policy_error(exc)
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': '考勤制度保存冲突，请重试', 'code': 'ATTENDANCE_POLICY_CONFLICT'}), 409
    return jsonify(updated.to_dict())


@hrm_bp.route('/attendance-policy/<kind>/<row_id>', methods=['DELETE'])
@jwt_required()
def delete_attendance_policy_row(kind: str, row_id: str):
    denied = _attendance_policy_guard('无权限删除考勤制度')
    if denied:
        return denied
    model = _attendance_policy_model(kind)
    if not model:
        return jsonify({'error': 'Unknown attendance policy resource'}), 404
    from services.attendance_policy import AttendancePolicyError, remove_policy_row

    try:
        remove_policy_row(model, current_tenant_id(), row_id)
        db.session.commit()
    except LookupError:
        db.session.rollback()
        return jsonify({'error': 'Not found'}), 404
    except AttendancePolicyError as exc:
        return _attendance_policy_error(exc)
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': '考勤制度删除冲突，请重试', 'code': 'ATTENDANCE_POLICY_CONFLICT'}), 409
    return jsonify({'deleted': True, 'id': row_id})


@hrm_bp.route('/<resource>/<item_id>', methods=['GET'])
@jwt_required()
def get_resource(resource, item_id):
    cfg = get_config(resource)
    if not cfg:
        return jsonify({'error': 'Unknown resource'}), 404
    rbac_err = _check_resource_rbac(resource)
    if rbac_err: return rbac_err
    obj = cfg['model'].query.get(item_id)
    if not obj:
        return jsonify({'error': 'Not found'}), 404
    if not object_belongs_to_current_tenant(obj):
        return jsonify({'error': 'Not found'}), 404
    if cfg.get('scope_to_user'):
        user = User.query.get(get_jwt_identity())
        if user and user.role not in PRIVILEGED_ROLES and getattr(obj, 'user_id', None) != user.id:
            return jsonify({'error': 'Not found'}), 404
    if cfg.get('personal_scope') and isinstance(obj, Notification):
        user_id = get_jwt_identity()
        is_broadcast = obj.user_id is None and obj.employee_id is None
        if obj.user_id != user_id and not is_broadcast:
            return jsonify({'error': 'Not found'}), 404
    return jsonify(obj.to_dict())


def _employee_indicator_warning(employee) -> str | None:
    """员工标记参与考核但 部门+岗位 未维护指标时给出提示。"""
    if not isinstance(employee, Employee) or not employee.performance_participant:
        return None
    dept_name = None
    if employee.department_id:
        dept = db.session.get(Department, employee.department_id)
        dept_name = dept.name if dept else None
    position_name = employee.job_title or (employee.position.title if employee.position else None)
    try:
        from services.performance_indicators import indicators_for

        indicators = indicators_for(employee.tenant_id, dept_name, position_name)
    except Exception:  # noqa: BLE001
        return None
    if indicators:
        return None
    return (
        f'该员工已标记「参与绩效考核」，但「{dept_name or "（未设部门）"} / {position_name or "（未设岗位）"}」'
        '尚未维护考核指标，生成考核表时会被跳过。请到「绩效管理 → 考核指标」补充。'
    )


@hrm_bp.route('/<resource>', methods=['POST'])
@jwt_required()
def create_resource(resource):
    cfg = get_config(resource)
    if not cfg:
        return jsonify({'error': 'Unknown resource'}), 404
    rbac_err = _check_resource_rbac(resource, write=True)
    if rbac_err: return rbac_err
    if cfg.get('read_only') or cfg.get('read_only_create'):
        return jsonify({'error': 'This resource cannot be created here'}), 400
    data = request.get_json() or {}
    model = cfg['model']
    limit_error = enforce_create_limit(model)
    if limit_error:
        return limit_error
    # 输入校验：必填字段非空
    ok, err = _validate_required(data, cfg['fields'], model)
    if not ok:
        return jsonify({'error': err}), 400
    if model is Notification and data.get('userId') == '':
        data = {**data, 'userId': None}
    obj = model(id=new_id())
    assign_tenant(obj)
    apply_fields(obj, data, cfg['fields'])
    try:
        storage.assert_storage_references_belong_to_tenant(
            _record_storage_references(obj),
            tenant_id=obj.tenant_id,
        )
    except storage.StorageTenantBindingError as exc:
        db.session.rollback()
        return jsonify(exc.to_payload()), 400
    current_user_id = get_jwt_identity()
    # Feedback 自动绑定提交者
    if isinstance(obj, Feedback):
        current_user = User.query.get(current_user_id)
        if not obj.user_id or not current_user or current_user.role not in PRIVILEGED_ROLES:
            obj.user_id = current_user_id
    if hasattr(obj, 'created_by') and not getattr(obj, 'created_by', None):
        obj.created_by = current_user_id
    if hasattr(obj, 'updated_by') and not getattr(obj, 'updated_by', None):
        obj.updated_by = current_user_id
    if isinstance(obj, Employee) and not obj.employee_no:
        obj.employee_no = generate_employee_no()
    if isinstance(obj, Employee) and obj.hire_date and obj.probation_months and not obj.probation_end_date:
        obj.probation_end_date = add_months(obj.hire_date, obj.probation_months)
    if isinstance(obj, Offer) and not obj.title:
        candidate = Candidate.query.get(obj.candidate_id) if obj.candidate_id else None
        job = Job.query.get(obj.job_id) if obj.job_id else None
        obj.title = f'{candidate.name if candidate else "候选人"} - {job.title if job else "Offer"}'
    if isinstance(obj, ExamPaper):
        paper_error = _validate_exam_paper(obj)
        if paper_error:
            return jsonify({'error': paper_error}), 400
    if isinstance(obj, PayrollRecord):
        calculate_payroll(obj)
    db.session.add(obj)
    db.session.flush()
    if isinstance(obj, Employee):
        ensure_employee_portal_account(obj)
    if isinstance(obj, EmployeeChange):
        apply_employee_change(obj)
    if isinstance(obj, EmployeeRequest) and obj.status == 'pending':
        approval = create_approval('employee_request', obj.id, f'{obj.employee.name if obj.employee else "员工"}{obj.request_type}申请')
        obj.approval_id = approval.id
    log_operation(resource, 'create', obj.id)
    db.session.commit()
    response = obj.to_dict()
    warning = _employee_indicator_warning(obj)
    if warning:
        response['performanceIndicatorWarning'] = warning
    return jsonify(response), 201


@hrm_bp.route('/<resource>/<item_id>', methods=['PUT'])
@jwt_required()
def update_resource(resource, item_id):
    cfg = get_config(resource)
    if not cfg:
        return jsonify({'error': 'Unknown resource'}), 404
    rbac_err = _check_resource_rbac(resource, write=True)
    if rbac_err: return rbac_err
    if cfg.get('read_only'):
        return jsonify({'error': 'This resource is read only'}), 400
    obj = cfg['model'].query.get(item_id)
    if not obj:
        return jsonify({'error': 'Not found'}), 404
    if not object_belongs_to_current_tenant(obj):
        return jsonify({'error': 'Not found'}), 404
    if cfg.get('scope_to_user'):
        user = User.query.get(get_jwt_identity())
        if user and user.role not in PRIVILEGED_ROLES and getattr(obj, 'user_id', None) != user.id:
            return jsonify({'error': 'Not found'}), 404
    if cfg.get('personal_scope') and isinstance(obj, Notification):
        user_id = get_jwt_identity()
        is_broadcast = obj.user_id is None and obj.employee_id is None
        if obj.user_id != user_id and not is_broadcast:
            return jsonify({'error': 'Not found'}), 404
    old_storage_references = _record_storage_references(obj)
    data = request.get_json() or {}
    if isinstance(obj, Employee):
        from services.oa_employee_sync import oa_managed_field_conflicts
        conflicts = oa_managed_field_conflicts(obj, data)
        if conflicts:
            return jsonify({
                'error': '该员工由外部主数据管理，以下字段请在来源系统修改后等待同步',
                'code': 'OA_MANAGED_FIELDS_READ_ONLY',
                'fields': conflicts,
            }), 409
    old_status = getattr(obj, 'status', None)
    apply_fields(obj, data, cfg['fields'])
    new_storage_references = _record_storage_references(obj)
    try:
        storage.assert_storage_references_belong_to_tenant(
            new_storage_references - old_storage_references,
            tenant_id=obj.tenant_id,
        )
    except storage.StorageTenantBindingError as exc:
        db.session.rollback()
        return jsonify(exc.to_payload()), 400
    if hasattr(obj, 'updated_by'):
        obj.updated_by = get_jwt_identity()
    if hasattr(obj, 'updated_at'):
        obj.updated_at = datetime.utcnow()
    if isinstance(obj, Employee) and obj.hire_date and obj.probation_months and not obj.probation_end_date:
        obj.probation_end_date = add_months(obj.hire_date, obj.probation_months)
    if isinstance(obj, Employee):
        ensure_employee_portal_account(obj, reset_password=False)
    if isinstance(obj, ExamPaper):
        paper_error = _validate_exam_paper(obj)
        if paper_error:
            db.session.rollback()
            return jsonify({'error': paper_error}), 400
    if isinstance(obj, PayrollRecord):
        calculate_payroll(obj)
    if isinstance(obj, EmployeeChange):
        apply_employee_change(obj)
    # Feedback 状态变更：自动填写处理人和处理时间
    if isinstance(obj, Feedback):
        if old_status in ('resolved', 'closed') and obj.status == 'pending':
            error_response = _record_feedback_reopen(obj, old_status, data)
            if error_response:
                db.session.rollback()
                return error_response
        if obj.status in ('in_progress', 'resolved', 'closed') and not obj.handler_id:
            obj.handler_id = get_jwt_identity()
        if obj.status in ('resolved', 'closed') and not obj.handled_at:
            obj.handled_at = datetime.utcnow()
        if old_status != 'resolved' and obj.status == 'resolved':
            _notify_feedback_resolved(obj)
    if isinstance(obj, Notification) and obj.status == 'read' and not obj.read_at:
        obj.read_at = datetime.utcnow()
    log_operation(resource, 'update', item_id)
    db.session.commit()
    _release_unreferenced_storage(
        old_storage_references - new_storage_references,
        tenant_id=obj.tenant_id,
    )
    response = obj.to_dict()
    warning = _employee_indicator_warning(obj)
    if warning:
        response['performanceIndicatorWarning'] = warning
    return jsonify(response)


@hrm_bp.route('/<resource>/<item_id>', methods=['DELETE'])
@jwt_required()
def delete_resource(resource, item_id):
    cfg = get_config(resource)
    if not cfg:
        return jsonify({'error': 'Unknown resource'}), 404
    rbac_err = _check_resource_rbac(resource, write=True)
    if rbac_err: return rbac_err
    if cfg.get('read_only'):
        return jsonify({'error': 'This resource is read only'}), 400
    obj = cfg['model'].query.get(item_id)
    if not obj:
        return jsonify({'error': 'Not found'}), 404
    if not object_belongs_to_current_tenant(obj):
        return jsonify({'error': 'Not found'}), 404
    if cfg.get('scope_to_user'):
        user = User.query.get(get_jwt_identity())
        if user and user.role not in PRIVILEGED_ROLES and getattr(obj, 'user_id', None) != user.id:
            return jsonify({'error': 'Not found'}), 404
    if cfg.get('personal_scope') and isinstance(obj, Notification):
        user_id = get_jwt_identity()
        is_broadcast = obj.user_id is None and obj.employee_id is None
        if obj.user_id != user_id and not is_broadcast:
            return jsonify({'error': 'Not found'}), 404
    storage_references = _record_storage_references(obj, include_descendants=True)
    tenant_id = obj.tenant_id
    db.session.delete(obj)
    log_operation(resource, 'delete', item_id)
    db.session.commit()
    _release_unreferenced_storage(storage_references, tenant_id=tenant_id)
    return jsonify({'removed': True})


# ============================================================
# 反馈附件上传：图片或文档
# 单独路由避免与通用 /<resource>/<item_id> 路由冲突
# ============================================================
FEEDBACK_ALLOWED_EXTENSIONS = {
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'tiff',  # 图片
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv',  # 文档
    'log', 'md', 'json', 'zip',  # 日志/其他
}
FEEDBACK_MAX_SIZE = 10 * 1024 * 1024  # 10MB


def _feedback_allowed(filename):
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in FEEDBACK_ALLOWED_EXTENSIONS


@hrm_bp.route('/feedback-attachments', methods=['POST'])
@jwt_required()
def upload_feedback_attachment():
    """上传单个反馈附件，返回文件元信息（前端再附在 attachments 字段提交）。"""
    if 'file' not in request.files:
        return jsonify({'error': '未上传文件'}), 400
    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'error': '未选择文件'}), 400

    original_name = file.filename
    if not _feedback_allowed(original_name):
        return jsonify({'error': '不支持的文件类型'}), 400

    # 大小校验（流式读取避免占内存）
    file.stream.seek(0, 2)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > FEEDBACK_MAX_SIZE:
        return jsonify({'error': f'文件超出大小限制（10MB），当前 {round(size / 1024 / 1024, 1)}MB'}), 400
    if size == 0:
        return jsonify({'error': '文件为空'}), 400

    # 使用 UUID 作为文件名，原始名仅用于显示
    ext = original_name.rsplit('.', 1)[1].lower()
    file_id = str(uuid.uuid4())
    stored_name = f'feedback_{file_id}.{ext}'
    from services.storage import save_local_upload
    object_key = save_local_upload(file, f'feedback/{stored_name}')

    file_url = f'/uploads/{object_key}'
    is_image = ext in {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'tiff'}

    return jsonify({
        'name': original_name,
        'url': file_url,
        'size': size,
        'type': 'image' if is_image else 'document',
        'ext': ext,
    }), 201


# ============================================================
# 日考勤明细（OA 排班 + 打卡机）与人工校对
# ============================================================
@hrm_bp.route('/attendance-punches', methods=['GET'])
@jwt_required()
def list_attendance_punches():
    """原始打卡流水：每次刷卡一条记录，不做任何汇总。"""
    denied = require_roles(ORG_READ_ROLES | PAYROLL_READ_ROLES, '无权限查看原始打卡')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404

    page = max(1, int(request.args.get('page', '1')))
    size = max(1, min(int(request.args.get('size', '50')), 200))
    tenant_id = current_tenant_id()

    mappings = {
        str(person.external_user_id): person
        for person in AttendanceExternalPerson.query.filter_by(
            tenant_id=tenant_id, mapping_status='confirmed',
        ).all()
        if person.external_user_id is not None
    }
    employee_ids = {person.employee_id for person in mappings.values() if person.employee_id}
    employees = {
        employee.id: employee
        for employee in Employee.query.filter(Employee.id.in_(employee_ids)).all()
    } if employee_ids else {}

    query = AttendanceRawPunch.query.filter(
        AttendanceRawPunch.tenant_id == tenant_id,
    )
    month = (request.args.get('month') or '').strip()
    date_str = (request.args.get('date') or '').strip()
    start_date = (request.args.get('startDate') or '').strip()
    end_date = (request.args.get('endDate') or '').strip()

    if date_str:
        try:
            target = datetime.strptime(date_str, '%Y-%m-%d').date()
            next_day = target + timedelta(days=1)
            query = query.filter(
                AttendanceRawPunch.check_time >= target,
                AttendanceRawPunch.check_time < next_day,
            )
        except ValueError:
            return jsonify({'error': '日期格式应为 YYYY-MM-DD'}), 400
    elif start_date or end_date:
        try:
            if start_date:
                query = query.filter(
                    AttendanceRawPunch.check_time >= datetime.strptime(start_date, '%Y-%m-%d').date(),
                )
            if end_date:
                end_target = datetime.strptime(end_date, '%Y-%m-%d').date() + timedelta(days=1)
                query = query.filter(AttendanceRawPunch.check_time < end_target)
        except ValueError:
            return jsonify({'error': '日期格式应为 YYYY-MM-DD'}), 400
    elif month:
        try:
            year, mon = (int(part) for part in month.split('-'))
            from datetime import date as _date, timedelta as _timedelta
            start = _date(year, mon, 1)
            end = _date(year + (1 if mon == 12 else 0), 1 if mon == 12 else mon + 1, 1)
            query = query.filter(
                AttendanceRawPunch.check_time >= start,
                AttendanceRawPunch.check_time < end,
            )
        except ValueError:
            return jsonify({'error': '月份格式应为 YYYY-MM'}), 400
    employee_id = (request.args.get('employeeId') or '').strip()
    keyword = (request.args.get('keyword') or '').strip()

    if employee_id:
        matching_external = [
            str(person.external_user_id)
            for person in mappings.values() if person.employee_id == employee_id
        ]
        if matching_external:
            query = query.filter(AttendanceRawPunch.external_user_id.in_(matching_external))
        else:
            return jsonify({'items': [], 'total': 0, 'page': page, 'size': size, 'pages': 0})
    elif keyword:
        kw = keyword.lower()
        matched_external_ids = []
        for ext_id, person in mappings.items():
            employee = employees.get(person.employee_id) if person.employee_id else None
            if employee:
                if kw in employee.name.lower() or kw in (employee.employee_no or '').lower():
                    matched_external_ids.append(ext_id)
        if matched_external_ids:
            query = query.filter(AttendanceRawPunch.external_user_id.in_(matched_external_ids))
        else:
            return jsonify({'items': [], 'total': 0, 'page': page, 'size': size, 'pages': 0})

    query = query.order_by(AttendanceRawPunch.check_time.desc())
    total = query.count()
    rows = query.offset((page - 1) * size).limit(size).all()

    items = []
    for punch in rows:
        person = mappings.get(str(punch.external_user_id))
        employee = employees.get(person.employee_id) if person and person.employee_id else None
        items.append({
            'id': punch.id,
            'employeeId': employee.id if employee else None,
            'employeeName': employee.name if employee else f'未匹配({punch.external_user_id})',
            'employeeNo': employee.employee_no if employee else None,
            'checkTime': punch.check_time.isoformat() if punch.check_time else None,
            'checkDate': punch.check_time.strftime('%Y-%m-%d') if punch.check_time else None,
            'checkTimeOnly': punch.check_time.strftime('%H:%M:%S') if punch.check_time else None,
            'checkType': punch.check_type,
            'sensorId': punch.sensor_id,
        })
    return jsonify({
        'items': items,
        'total': total,
        'page': page,
        'size': size,
        'pages': (total + size - 1) // size,
    })


@hrm_bp.route('/attendance-timesheet', methods=['GET'])
@jwt_required()
def list_attendance_timesheet():
    denied = require_roles(ORG_READ_ROLES | PAYROLL_READ_ROLES, '无权限查看考勤明细')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from services.attendance_timesheet import list_timesheets

    page_value = (request.args.get('page') or '').strip()
    try:
        page = int(page_value) if page_value else None
        size = int((request.args.get('size') or '50').strip() or 50)
    except ValueError:
        return jsonify({'error': '分页参数应为整数'}), 400

    def _bool_arg(name):
        raw = (request.args.get(name) or '').strip()
        if raw in ('1', 'true', 'True'):
            return True
        if raw in ('0', 'false', 'False'):
            return False
        return None

    try:
        work_date = parse_date(request.args.get('date'))
    except ValueError:
        return jsonify({'error': '日期格式应为 YYYY-MM-DD'}), 400

    min_work_hours = None
    raw_min = (request.args.get('minWorkHours') or '').strip()
    if raw_min:
        try:
            min_work_hours = float(raw_min)
        except ValueError:
            return jsonify({'error': 'minWorkHours 应为数字'}), 400

    result = list_timesheets(
        current_tenant_id(),
        month=(request.args.get('month') or '').strip() or None,
        employee_id=(request.args.get('employeeId') or '').strip() or None,
        keyword=(request.args.get('keyword') or '').strip() or None,
        department_id=(request.args.get('departmentId') or '').strip() or None,
        status=(request.args.get('status') or '').strip() or None,
        work_date=work_date,
        employee_type=(request.args.get('employeeType') or '').strip() or None,
        has_overtime=_bool_arg('hasOvertime'),
        has_leave=_bool_arg('hasLeave'),
        has_event=_bool_arg('hasEvent'),
        min_work_hours=min_work_hours,
        page=page,
        size=size,
    )
    if isinstance(result, tuple):
        items, total, resolved_page, resolved_size = result
        return jsonify({
            'items': [row.to_dict() for row in items],
            'total': total,
            'page': resolved_page,
            'size': resolved_size,
            'pages': (total + resolved_size - 1) // resolved_size,
        })
    return jsonify([row.to_dict() for row in result])


@hrm_bp.route('/attendance-timesheet/export', methods=['GET'])
@jwt_required()
def export_attendance_timesheet():
    denied = require_roles(ORG_READ_ROLES | PAYROLL_READ_ROLES, '无权限导出考勤明细')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from io import BytesIO

    from flask import send_file
    from openpyxl import Workbook
    from services.attendance_timesheet import list_timesheets

    def _bool_arg(name):
        raw = (request.args.get(name) or '').strip()
        if raw in ('1', 'true', 'True'):
            return True
        if raw in ('0', 'false', 'False'):
            return False
        return None

    month = (request.args.get('month') or '').strip() or datetime.utcnow().strftime('%Y-%m')
    try:
        work_date = parse_date(request.args.get('date'))
    except ValueError:
        return jsonify({'error': '日期格式应为 YYYY-MM-DD'}), 400
    raw_min = (request.args.get('minWorkHours') or '').strip()
    try:
        min_work_hours = float(raw_min) if raw_min else None
    except ValueError:
        return jsonify({'error': 'minWorkHours 应为数字'}), 400

    rows = list_timesheets(
        current_tenant_id(),
        month=month,
        keyword=(request.args.get('keyword') or '').strip() or None,
        department_id=(request.args.get('departmentId') or '').strip() or None,
        status=(request.args.get('status') or '').strip() or None,
        work_date=work_date,
        employee_type=(request.args.get('employeeType') or '').strip() or None,
        has_overtime=_bool_arg('hasOvertime'),
        has_leave=_bool_arg('hasLeave'),
        has_event=_bool_arg('hasEvent'),
        min_work_hours=min_work_hours,
        page=None,
        limit=50000,
    )

    status_labels = {
        'normal': '正常', 'missing_card': '缺卡', 'absent': '旷工',
        'leave': '请假', 'rest': '休息',
    }

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '考勤明细'
    sheet.append(['员工', '日期', '类型', '上班', '下班', '当天打卡', '正常工时', '加班', '请假', '应打卡', '实打卡', '状态', '单据'])
    for row in rows:
        data = row.to_dict()
        punches = data.get('punchTimes') or []
        punch_text = ' '.join(
            f"{(p.get('t') or '')[11:16]}{'补' if p.get('fix') else ''}" for p in punches if p.get('t')
        )
        sheet.append([
            data.get('employeeName') or data.get('employeeId'),
            data.get('workDate'),
            data.get('employeeType'),
            (data.get('checkIn') or '')[11:16],
            (data.get('checkOut') or '')[11:16],
            punch_text,
            float(data.get('workHours') or 0),
            float(data.get('overtimeHours') or 0),
            float(data.get('leaveHours') or 0),
            data.get('expectedPunches'),
            data.get('actualPunches'),
            status_labels.get(data.get('status'), data.get('status')),
            data.get('eventSummary') or '',
        ])

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'考勤明细_{month}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


@hrm_bp.route('/attendance-timesheet/generate', methods=['POST'])
@jwt_required()
def generate_attendance_timesheet():
    denied = require_roles(ORG_WRITE_ROLES, '无权限生成考勤明细')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from services.attendance_timesheet import generate_timesheets
    from services.oa_employee_sync import OaSyncDisabled

    payload = request.get_json(silent=True) or {}
    month = (str(payload.get('month') or '').strip()) or datetime.utcnow().strftime('%Y-%m')
    try:
        result = generate_timesheets(
            current_tenant_id(),
            month,
            overwrite_manual=bool(payload.get('overwriteManual')),
        )
    except OaSyncDisabled as exc:
        return jsonify({'error': str(exc), 'code': 'OA_SYNC_DISABLED'}), 503
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'code': 'ATTENDANCE_TIMESHEET_INVALID'}), 400
    db.session.commit()
    return jsonify(result)


@hrm_bp.route('/attendance-timesheet/<detail_id>/correct', methods=['POST'])
@jwt_required()
def correct_attendance_timesheet(detail_id):
    denied = require_roles(ORG_WRITE_ROLES, '无权限校对考勤明细')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from services.attendance_timesheet import correct_timesheet

    payload = request.get_json(silent=True) or {}
    try:
        row = correct_timesheet(
            detail_id,
            tenant_id=current_tenant_id(),
            check_in=payload.get('checkIn'),
            check_out=payload.get('checkOut'),
            status=(str(payload.get('status')).strip() if payload.get('status') else None),
            work_hours=payload.get('workHours'),
            remark=payload.get('remark'),
            actor_user_id=get_jwt_identity(),
        )
        db.session.commit()
    except LookupError:
        db.session.rollback()
        return jsonify({'error': 'Not found'}), 404
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'code': 'ATTENDANCE_TIMESHEET_INVALID'}), 400
    return jsonify(row.to_dict())


@hrm_bp.route('/attendance-summary', methods=['GET'])
@jwt_required()
def attendance_summary_route():
    denied = require_roles(ORG_READ_ROLES | PAYROLL_READ_ROLES, '无权限查看考勤汇总')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from services.attendance_summary import monthly_summary

    month = (request.args.get('month') or '').strip() or datetime.utcnow().strftime('%Y-%m')
    try:
        rows = monthly_summary(
            current_tenant_id(),
            month,
            department_id=(request.args.get('departmentId') or '').strip() or None,
            employee_id=(request.args.get('employeeId') or '').strip() or None,
            keyword=(request.args.get('keyword') or '').strip() or None,
        )
    except ValueError:
        return jsonify({'error': '月份格式应为 YYYY-MM', 'code': 'ATTENDANCE_SUMMARY_INVALID'}), 400
    return jsonify({'month': month, 'items': rows})


@hrm_bp.route('/attendance-summary/notify', methods=['POST'])
@jwt_required()
def attendance_summary_notify():
    denied = require_roles(ORG_WRITE_ROLES, '无权限推送月度工时')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from models import Department
    from services.attendance_summary import monthly_summary
    from services.notify import notify_many

    tenant_id = current_tenant_id()
    payload = request.get_json(silent=True) or {}
    month = (str(payload.get('month') or '').strip()) or datetime.utcnow().strftime('%Y-%m')
    department_ids = payload.get('departmentIds') or []

    dept_query = Department.query.filter(Department.tenant_id == tenant_id)
    if department_ids:
        dept_query = dept_query.filter(Department.id.in_(department_ids))
    departments = [d for d in dept_query.all() if d.manager_id]
    if not departments:
        return jsonify({'month': month, 'pushed': 0, 'detail': []})

    pushed = 0
    detail = []
    for dept in departments:
        rows = monthly_summary(tenant_id, month, department_id=dept.id)
        work = sum(float(r.get('workHours') or 0) for r in rows)
        overtime = sum(float(r.get('overtimeHours') or 0) for r in rows)
        absent = sum(int(r.get('absentDays') or 0) for r in rows)
        result = notify_many(
            ['station'],
            [{'employeeId': dept.manager_id}],
            tenant_id=tenant_id,
            title=f'{month} 部门月度工时（{dept.name}）',
            content=(
                f'本月部门 {len(rows)} 人，工时合计 {round(work, 1)}h，加班 {round(overtime, 1)}h，'
                f'旷工 {absent} 天。请到「考勤明细」查看。'
            ),
            notice_type='attendance_summary',
            link_url='/attendance-timesheet',
        )
        pushed += result['sent']
        detail.append({'departmentId': dept.id, 'departmentName': dept.name,
                       'managerId': dept.manager_id, 'sent': result['sent']})
    db.session.commit()
    return jsonify({'month': month, 'pushed': pushed, 'detail': detail})


@hrm_bp.route('/performance-reviews/<review_id>/notify', methods=['POST'])
@jwt_required()
def performance_review_notify(review_id: str):
    denied = require_roles(ORG_WRITE_ROLES, '无权限推送考核结果')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from models import PerformanceReview
    from services.notify import notify_many

    tenant_id = current_tenant_id()
    review = PerformanceReview.query.filter_by(id=review_id, tenant_id=tenant_id).first()
    if review is None:
        return jsonify({'error': 'Not found'}), 404
    payload = request.get_json(silent=True) or {}
    targets = payload.get('targets') or ['self', 'manager']

    receivers = []
    if 'self' in targets and review.employee_id:
        receivers.append({'employeeId': review.employee_id})
    if 'manager' in targets and review.manager_id:
        receivers.append({'employeeId': review.manager_id})
    score = review.final_score if review.final_score is not None else review.auto_score
    result = notify_many(
        ['station'], receivers, tenant_id=tenant_id,
        title='绩效考核结果通知',
        content=f'您的绩效考核已完成：最终分 {score if score is not None else "-"}，等级 {review.grade or "-"}。请到「绩效考核中心」查看。',
        notice_type='performance_result',
        link_url='/performance-center',
    )
    db.session.commit()
    return jsonify({'reviewId': review.id, 'targets': targets, 'sent': result['sent']})


@hrm_bp.route('/attendance-events', methods=['GET'])
@jwt_required()
def list_attendance_events():
    denied = require_roles(ORG_READ_ROLES | PAYROLL_READ_ROLES, '无权限查看考勤单据')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from services.attendance_events import list_events

    page_value = (request.args.get('page') or '').strip()
    try:
        page = int(page_value) if page_value else None
        size = int((request.args.get('size') or '50').strip() or 50)
    except ValueError:
        return jsonify({'error': '分页参数应为整数'}), 400

    try:
        start_date = parse_date(request.args.get('startDate'))
        end_date = parse_date(request.args.get('endDate'))
    except ValueError:
        return jsonify({'error': '日期格式应为 YYYY-MM-DD', 'code': 'ATTENDANCE_EVENT_INVALID'}), 400

    result = list_events(
        current_tenant_id(),
        month=(request.args.get('month') or '').strip() or None,
        event_type=(request.args.get('eventType') or '').strip() or None,
        keyword=(request.args.get('keyword') or '').strip() or None,
        employee_id=(request.args.get('employeeId') or '').strip() or None,
        start_date=start_date,
        end_date=end_date,
        page=page,
        size=size,
    )
    if isinstance(result, tuple):
        items, total, resolved_page, resolved_size = result
        return jsonify({
            'items': [row.to_dict() for row in items],
            'total': total,
            'page': resolved_page,
            'size': resolved_size,
            'pages': (total + resolved_size - 1) // resolved_size,
        })
    return jsonify([row.to_dict() for row in result])


@hrm_bp.route('/attendance-events/sync', methods=['POST'])
@jwt_required()
def sync_attendance_events_route():
    denied = require_roles(ORG_WRITE_ROLES, '无权限同步考勤单据')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from services.attendance_events import sync_attendance_events
    from services.oa_employee_sync import OaSyncDisabled

    payload = request.get_json(silent=True) or {}
    months = int(payload.get('months') or 12)
    try:
        result = sync_attendance_events(current_tenant_id(), months=months)
    except OaSyncDisabled as exc:
        return jsonify({'error': str(exc), 'code': 'OA_SYNC_DISABLED'}), 503
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'code': 'ATTENDANCE_EVENTS_INVALID'}), 400
    db.session.commit()
    return jsonify(result)


@hrm_bp.route('/performance-participants', methods=['GET'])
@jwt_required()
def list_performance_participants():
    denied = require_roles(ORG_READ_ROLES, '无权限查看参与考核人员')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from services.performance_participation import list_participants

    items = list_participants(
        current_tenant_id(),
        department_name=(request.args.get('departmentName') or '').strip() or None,
        keyword=(request.args.get('keyword') or '').strip() or None,
    )
    return jsonify({'items': items})


@hrm_bp.route('/performance-participants', methods=['POST'])
@jwt_required()
def update_performance_participants():
    denied = require_roles(ORG_WRITE_ROLES, '无权限维护参与考核人员')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from services.performance_participation import set_participants

    payload = request.get_json(silent=True) or {}
    try:
        result = set_participants(
            current_tenant_id(),
            payload.get('employeeIds') or [],
            bool(payload.get('participant')),
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'code': 'PERFORMANCE_PARTICIPANT_INVALID'}), 400
    return jsonify(result)


@hrm_bp.route('/performance-indicators', methods=['GET'])
@jwt_required()
def list_performance_indicators():
    denied = require_roles(ORG_READ_ROLES, '无权限查看考核指标')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from models import PerformanceIndicator, PerformanceScoreRule

    tenant_id = current_tenant_id()
    query = PerformanceIndicator.query.filter_by(tenant_id=tenant_id, status='active')
    department_name = (request.args.get('departmentName') or '').strip()
    position_name = (request.args.get('positionName') or '').strip()
    if department_name:
        query = query.filter(PerformanceIndicator.department_name == department_name)
    if position_name:
        query = query.filter(PerformanceIndicator.position_name == position_name)
    indicators = query.order_by(
        PerformanceIndicator.department_name.asc(),
        PerformanceIndicator.position_name.asc(),
        PerformanceIndicator.seq.asc(),
    ).all()

    rules = {
        rule.indicator_code: rule
        for rule in PerformanceScoreRule.query.filter_by(tenant_id=tenant_id).all()
    }
    from services.performance_scoring import METRIC_SOURCE_NOTES, METRIC_LABELS

    payload = []
    for indicator in indicators:
        item = indicator.to_dict()
        rule = rules.get(indicator.id)
        item['scoringRuleConfigured'] = bool(rule)
        item['dataSourceNote'] = (
            METRIC_SOURCE_NOTES.get(rule.metric or '', '数据来源：系统取数') if rule else None
        )
        item['metricLabel'] = (
            METRIC_LABELS.get(rule.metric or '', rule.metric or '') if rule else None
        )
        item['rule'] = rule.to_dict() if rule else None
        payload.append(item)
    return jsonify(payload)


@hrm_bp.route('/performance-indicators', methods=['POST'])
@jwt_required()
def create_performance_indicator():
    denied = require_roles(ORG_WRITE_ROLES, '无权限维护考核指标')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from services.performance_indicator_admin import save_indicator

    try:
        row = save_indicator(current_tenant_id(), request.get_json(silent=True) or {})
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'code': 'PERFORMANCE_INDICATOR_INVALID'}), 400
    return jsonify(row.to_dict()), 201


@hrm_bp.route('/performance-indicators/<indicator_id>', methods=['PUT'])
@jwt_required()
def update_performance_indicator(indicator_id: str):
    denied = require_roles(ORG_WRITE_ROLES, '无权限维护考核指标')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from services.performance_indicator_admin import save_indicator

    try:
        row = save_indicator(
            current_tenant_id(),
            request.get_json(silent=True) or {},
            indicator_id=indicator_id,
        )
        db.session.commit()
    except LookupError:
        db.session.rollback()
        return jsonify({'error': 'Not found'}), 404
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'code': 'PERFORMANCE_INDICATOR_INVALID'}), 400
    return jsonify(row.to_dict())


@hrm_bp.route('/performance-indicators/<indicator_id>', methods=['DELETE'])
@jwt_required()
def delete_performance_indicator(indicator_id: str):
    denied = require_roles(ORG_WRITE_ROLES, '无权限维护考核指标')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from models import PerformanceIndicator, PerformanceScoreRule

    row = PerformanceIndicator.query.filter_by(
        id=indicator_id, tenant_id=current_tenant_id(),
    ).first()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    PerformanceScoreRule.query.filter_by(
        tenant_id=current_tenant_id(), indicator_code=row.id,
    ).delete(synchronize_session=False)
    db.session.delete(row)
    db.session.commit()
    return jsonify({'removed': True, 'id': indicator_id})


@hrm_bp.route('/performance-reviews/generate', methods=['POST'])
@jwt_required()
def performance_reviews_generate():
    denied = require_roles(ORG_WRITE_ROLES, '无权限生成考核表')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from services.performance_indicators import generate_reviews

    payload = request.get_json(silent=True) or {}
    month = (str(payload.get('month') or '').strip()) or datetime.utcnow().strftime('%Y-%m')
    try:
        result = generate_reviews(
            current_tenant_id(),
            month=month,
            department_names=payload.get('departmentNames'),
            employee_ids=payload.get('employeeIds'),
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'code': 'PERFORMANCE_GENERATE_INVALID'}), 400
    return jsonify(result)


@hrm_bp.route('/performance-reviews/overview', methods=['GET'])
@jwt_required()
def performance_reviews_overview():
    denied = require_roles(ORG_READ_ROLES, '无权限查看考核表')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from models import PerformanceReviewItem

    month = (request.args.get('month') or '').strip() or datetime.utcnow().strftime('%Y-%m')
    tenant_id = current_tenant_id()
    cycle = PerformanceCycle.query.filter_by(
        tenant_id=tenant_id, name=month, cycle_type='月度',
    ).first()
    if not cycle:
        return jsonify({'month': month, 'cycleId': None, 'items': []})

    reviews = PerformanceReview.query.filter_by(
        tenant_id=tenant_id, cycle_id=cycle.id,
    ).order_by(PerformanceReview.created_at.asc()).all()
    review_ids = [review.id for review in reviews]
    items_by_review: dict[str, list] = {}
    if review_ids:
        for item in PerformanceReviewItem.query.filter(
            PerformanceReviewItem.review_id.in_(review_ids)
        ).order_by(PerformanceReviewItem.sort_order.asc()).all():
            items_by_review.setdefault(item.review_id, []).append(item.to_dict())

    return jsonify({
        'month': month,
        'cycleId': cycle.id,
        'items': [
            {**review.to_dict(), 'items': items_by_review.get(review.id, [])}
            for review in reviews
        ],
    })


@hrm_bp.route('/performance-reviews/<review_id>/auto-score', methods=['POST'])
@jwt_required()
def performance_review_auto_score(review_id: str):
    denied = require_roles(ORG_WRITE_ROLES, '无权限执行绩效评分')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from services.performance_scoring import auto_score_review

    payload = request.get_json(silent=True) or {}
    month = (str(payload.get('month') or '').strip()) or datetime.utcnow().strftime('%Y-%m')
    try:
        result = auto_score_review(
            review_id,
            tenant_id=current_tenant_id(),
            month=month,
            use_ai=bool(payload.get('useAi')),
        )
        db.session.commit()
    except LookupError:
        db.session.rollback()
        return jsonify({'error': 'Not found'}), 404
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'code': 'PERFORMANCE_SCORE_INVALID'}), 400
    return jsonify(result)


def _actor_role_and_employee():
    from models import User

    user = db.session.get(User, get_jwt_identity())
    if user is None:
        return None, None
    return user.role, user.employee_id


@hrm_bp.route('/performance-reviews/<review_id>', methods=['GET'])
@jwt_required()
def performance_review_detail(review_id: str):
    denied = require_roles(ORG_READ_ROLES, '无权限查看考核表')
    if denied:
        return denied
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from services.performance_review import get_review_detail

    role, actor_employee_id = _actor_role_and_employee()
    detail = get_review_detail(
        review_id, current_tenant_id(),
        role=role, actor_employee_id=actor_employee_id,
    )
    if detail is None:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(detail)


@hrm_bp.route('/performance-reviews/<review_id>/scores', methods=['POST'])
@jwt_required()
def performance_review_save_scores(review_id: str):
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from services.performance_review import ReviewPermissionError, save_scores

    role, actor_employee_id = _actor_role_and_employee()
    try:
        result = save_scores(
            review_id, current_tenant_id(),
            request.get_json(silent=True) or {},
            role=role, actor_employee_id=actor_employee_id, actor_user_id=get_jwt_identity(),
        )
        db.session.commit()
    except LookupError:
        db.session.rollback()
        return jsonify({'error': 'Not found'}), 404
    except ReviewPermissionError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'code': 'PERFORMANCE_REVIEW_FORBIDDEN'}), 403
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'code': 'PERFORMANCE_REVIEW_INVALID'}), 400
    return jsonify(result)


@hrm_bp.route('/performance-reviews/<review_id>/confirm', methods=['POST'])
@jwt_required()
def performance_review_confirm(review_id: str):
    if not current_tenant():
        return jsonify({'error': 'Not found'}), 404
    from services.performance_review import ReviewPermissionError, confirm_review

    role, _ = _actor_role_and_employee()
    try:
        result = confirm_review(
            review_id, current_tenant_id(),
            request.get_json(silent=True) or {},
            role=role, actor_user_id=get_jwt_identity(),
        )
        db.session.commit()
    except LookupError:
        db.session.rollback()
        return jsonify({'error': 'Not found'}), 404
    except ReviewPermissionError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'code': 'PERFORMANCE_REVIEW_FORBIDDEN'}), 403
    return jsonify(result)
