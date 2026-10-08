"""待办事项服务。

聚合所有需要用户处理的任务：
- 待审批事项
- 待完成的入职任务
- 待评估的绩效
- 待学习的培训
- 考勤异常待处理
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from models import (
    ApprovalInstance,
    AttendanceRecord,
    EmployeeRequest,
    OnboardingTask,
    PerformanceReview,
    TrainingRecord,
    User,
)

logger = logging.getLogger(__name__)


class TodoType:
    """待办类型"""
    APPROVAL_PENDING = 'approval_pending'  # 待审批
    ONBOARDING_TASK = 'onboarding_task'  # 入职任务
    PERFORMANCE_REVIEW = 'performance_review'  # 绩效评估
    TRAINING_COURSE = 'training_course'  # 培训课程
    ATTENDANCE_ANOMALY = 'attendance_anomaly'  # 考勤异常


class TodoPriority:
    """优先级"""
    HIGH = 'high'  # 高
    MEDIUM = 'medium'  # 中
    LOW = 'low'  # 低


class TodoService:
    """待办事项服务"""

    @staticmethod
    def _employee_id_for_user(user_id: str) -> Optional[str]:
        user = User.query.get(user_id)
        return user.employee_id if user and user.employee_id else None

    @staticmethod
    def get_user_todos(user_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        """获取用户的所有待办事项"""
        todos = []

        # 1. 待审批事项
        todos.extend(TodoService._get_pending_approvals(user_id, tenant_id))

        # 2. 待完成的入职任务
        todos.extend(TodoService._get_onboarding_tasks(user_id, tenant_id))

        # 3. 待评估的绩效
        todos.extend(TodoService._get_performance_reviews(user_id, tenant_id))

        # 4. 待学习的培训
        todos.extend(TodoService._get_training_courses(user_id, tenant_id))

        # 5. 考勤异常
        todos.extend(TodoService._get_attendance_anomalies(user_id, tenant_id))

        # 按优先级和创建时间排序
        priority_order = {TodoPriority.HIGH: 0, TodoPriority.MEDIUM: 1, TodoPriority.LOW: 2}
        todos.sort(key=lambda x: (priority_order.get(x['priority'], 3), x['created_at']))

        return todos

    @staticmethod
    def _get_pending_approvals(user_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        """获取待审批事项"""
        todos = []
        try:
            # 查询待审批的申请
            pending_instances = (
                ApprovalInstance.query
                .filter_by(tenant_id=tenant_id, approver_id=user_id, status='pending')
                .all()
            )

            for instance in pending_instances:
                # 获取关联的业务对象
                type_label = instance.title or instance.business_type or '审批事项'
                link = '/approval-center/pending'

                if instance.business_type == 'employee_request':
                    req = EmployeeRequest.query.get(instance.business_id)
                    if req:
                        type_label = req.title or req.request_type or type_label
                        link = f'/employee-requests?id={req.id}'

                # 判断优先级：超过 3 天为高优先级
                days_old = (datetime.utcnow() - instance.created_at).days
                priority = TodoPriority.HIGH if days_old >= 3 else TodoPriority.MEDIUM
                applicant_name = instance.applicant.name if instance.applicant else '申请人'

                todos.append({
                    'id': instance.id,
                    'type': TodoType.APPROVAL_PENDING,
                    'type_label': '待审批',
                    'title': f'审批：{type_label}',
                    'description': f'{applicant_name} 提交的 {type_label}',
                    'priority': priority,
                    'created_at': instance.created_at.isoformat(),
                    'deadline': None,
                    'link': link,
                    'meta': {
                        'submitter': applicant_name,
                        'business_type': instance.business_type,
                    }
                })

        except Exception as e:
            logger.error(f'Failed to get pending approvals: {e}', exc_info=True)

        return todos

    @staticmethod
    def _get_onboarding_tasks(user_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        """获取待完成的入职任务"""
        todos = []
        try:
            # 查询待完成的入职任务
            pending_tasks = (
                OnboardingTask.query
                .filter_by(tenant_id=tenant_id, owner_id=user_id, status='pending')
                .all()
            )

            for task in pending_tasks:
                # 判断优先级：已过期为高优先级，3 天内到期为中优先级
                priority = TodoPriority.LOW
                if task.due_date:
                    days_until_deadline = (task.due_date - datetime.utcnow().date()).days
                    if days_until_deadline < 0:
                        priority = TodoPriority.HIGH
                    elif days_until_deadline <= 3:
                        priority = TodoPriority.MEDIUM

                todos.append({
                    'id': task.id,
                    'type': TodoType.ONBOARDING_TASK,
                    'type_label': '入职任务',
                    'title': task.name,
                    'description': task.remark or task.task_type or '请完成此入职任务',
                    'priority': priority,
                    'created_at': task.created_at.isoformat() if task.created_at else None,
                    'deadline': task.due_date.isoformat() if task.due_date else None,
                    'link': f'/hrm/onboarding-tasks?id={task.id}',
                    'meta': {
                        'employee_name': task.employee.name if task.employee else None,
                    }
                })

        except Exception as e:
            logger.error(f'Failed to get onboarding tasks: {e}', exc_info=True)

        return todos

    @staticmethod
    def _get_performance_reviews(user_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        """获取待评估的绩效"""
        todos = []
        try:
            employee_id = TodoService._employee_id_for_user(user_id)
            if not employee_id:
                return todos

            # 查询待完成的绩效评估
            pending_reviews = (
                PerformanceReview.query
                .filter_by(tenant_id=tenant_id, employee_id=employee_id, status='draft')
                .all()
            )

            for review in pending_reviews:
                # 判断优先级
                priority = TodoPriority.MEDIUM

                cycle_name = review.cycle.name if review.cycle else '绩效评估'

                todos.append({
                    'id': review.id,
                    'type': TodoType.PERFORMANCE_REVIEW,
                    'type_label': '绩效评估',
                    'title': f'{cycle_name} - 待完成',
                    'description': '请完成您的绩效自评',
                    'priority': priority,
                    'created_at': review.created_at.isoformat() if review.created_at else None,
                    'deadline': None,
                    'link': f'/performance-review?id={review.id}',
                    'meta': {
                        'cycle_name': cycle_name,
                    }
                })

        except Exception as e:
            logger.error(f'Failed to get performance reviews: {e}', exc_info=True)

        return todos

    @staticmethod
    def _get_training_courses(user_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        """获取待学习的培训"""
        todos = []
        try:
            employee_id = TodoService._employee_id_for_user(user_id)
            if not employee_id:
                return todos

            # 查询未完成的培训记录
            pending_trainings = (
                TrainingRecord.query
                .filter(
                    TrainingRecord.tenant_id == tenant_id,
                    TrainingRecord.employee_id == employee_id,
                    TrainingRecord.status.in_(['assigned', 'registered']),
                )
                .all()
            )

            for record in pending_trainings:
                # 判断优先级
                priority = TodoPriority.LOW

                course_name = record.course.title if record.course else '培训课程'

                todos.append({
                    'id': record.id,
                    'type': TodoType.TRAINING_COURSE,
                    'type_label': '培训课程',
                    'title': f'培训：{course_name}',
                    'description': '您有新的培训课程需要完成',
                    'priority': priority,
                    'created_at': record.created_at.isoformat() if record.created_at else None,
                    'deadline': None,
                    'link': f'/hrm/training-records?id={record.id}',
                    'meta': {
                        'course_name': course_name,
                    }
                })

        except Exception as e:
            logger.error(f'Failed to get training courses: {e}', exc_info=True)

        return todos

    @staticmethod
    def _get_attendance_anomalies(user_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        """获取考勤异常"""
        todos = []
        try:
            employee_id = TodoService._employee_id_for_user(user_id)
            if not employee_id:
                return todos

            # 查询最近 30 天的考勤异常
            from datetime import timedelta
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)

            anomaly_records = (
                AttendanceRecord.query
                .filter(
                    AttendanceRecord.tenant_id == tenant_id,
                    AttendanceRecord.employee_id == employee_id,
                    AttendanceRecord.status.in_(['late', 'early_leave', 'absent']),
                    AttendanceRecord.created_at >= thirty_days_ago,
                )
                .all()
            )

            for record in anomaly_records:
                status_label = {
                    'late': '迟到',
                    'early_leave': '早退',
                    'absent': '缺勤',
                }.get(record.status, '异常')

                todos.append({
                    'id': record.id,
                    'type': TodoType.ATTENDANCE_ANOMALY,
                    'type_label': '考勤异常',
                    'title': f'{status_label}：{record.attendance_date}',
                    'description': record.remark or f'您在 {record.attendance_date} 的考勤记录为{status_label}',
                    'priority': TodoPriority.LOW,
                    'created_at': record.created_at.isoformat() if record.created_at else None,
                    'deadline': None,
                    'link': '/hrm/attendance-records',
                    'meta': {
                        'date': record.attendance_date.isoformat() if record.attendance_date else None,
                        'status': record.status,
                    }
                })

        except Exception as e:
            logger.error(f'Failed to get attendance anomalies: {e}', exc_info=True)

        return todos

    @staticmethod
    def get_todo_count(user_id: str, tenant_id: str) -> int:
        """获取待办事项数量（用于显示红点）"""
        try:
            return len(TodoService.get_user_todos(user_id, tenant_id))

        except Exception as e:
            logger.error(f'Failed to get todo count: {e}', exc_info=True)
            return 0
