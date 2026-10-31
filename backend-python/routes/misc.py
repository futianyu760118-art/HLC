from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime

from models import db, User, Job, Resume, Interview, TenantSetting, Employee, Offer, AttendanceRecord, EmployeeRequest, PerformanceReview, PayrollRecord
from services.tenancy import current_tenant_id
from services.todo_service import TodoService

misc_bp = Blueprint('misc', __name__)

_PRIVILEGED = {'admin', 'hr_admin', 'manager', 'executive'}

def _require_privileged():
    user = User.query.get(get_jwt_identity())
    if not user or user.role not in _PRIVILEGED:
        return jsonify({'error': '无权限'}), 403
    return None

@misc_bp.route('/report/summary', methods=['GET'])
@jwt_required()
def get_summary():
    err = _require_privileged()
    if err: return err
    totals = {
        'jobs': Job.query.count(),
        'openJobs': Job.query.filter(Job.status == 'open').count(),
        'resumes': Resume.query.count(),
        'interviews': Interview.query.count(),
        'users': User.query.count(),
        'employees': Employee.query.count(),
        'activeEmployees': Employee.query.filter(Employee.status.in_(['probation', 'active'])).count(),
        'pendingOnboard': Employee.query.filter(Employee.status == 'pending_onboard').count(),
        'offers': Offer.query.count(),
        'attendanceExceptions': AttendanceRecord.query.filter(AttendanceRecord.status != 'normal').count(),
        'requests': EmployeeRequest.query.count(),
        'performanceReviews': PerformanceReview.query.count(),
        'payrollRecords': PayrollRecord.query.count(),
    }
    return jsonify({'totals': totals})

@misc_bp.route('/recent-activities', methods=['GET'])
@jwt_required()
def get_recent_activities():
    err = _require_privileged()
    if err: return err
    activities = []

    # 最近的简历
    recent_resumes = Resume.query.order_by(Resume.created_at.desc()).limit(5).all()
    # 批量预加载岗位（消除循环内逐条 Job.query.get 的 N+1）
    resume_job_ids = {r.job_id for r in recent_resumes if r.job_id}
    resume_job_map = {j.id: j for j in Job.query.filter(Job.id.in_(resume_job_ids)).all()} if resume_job_ids else {}
    for resume in recent_resumes:
        job = resume_job_map.get(resume.job_id)
        ai_analysis = resume.ai_analysis or {}
        activities.append({
            'type': 'resume_upload',
            'icon': 'upload',
            'iconColor': 'primary',
            'title': '上传了简历',
            'description': f'{resume.candidate_name} 应聘 {job.title if job else "未知岗位"}',
            'detail': f'AI评分: {ai_analysis.get("score", 0)}分, 匹配度: {ai_analysis.get("matchDegree", 0)}%' if ai_analysis else '',
            'timestamp': resume.created_at.isoformat()
        })

    # 最近的面试
    recent_interviews = Interview.query.order_by(Interview.created_at.desc()).limit(5).all()
    # 批量预加载简历 + 岗位（消除循环内逐条 query.get 的 N+1）
    iv_resume_ids = {i.resume_id for i in recent_interviews if i.resume_id}
    iv_job_ids = {i.job_id for i in recent_interviews if i.job_id}
    iv_resume_map = {r.id: r for r in Resume.query.filter(Resume.id.in_(iv_resume_ids)).all()} if iv_resume_ids else {}
    iv_job_map = {j.id: j for j in Job.query.filter(Job.id.in_(iv_job_ids)).all()} if iv_job_ids else {}
    for interview in recent_interviews:
        resume = iv_resume_map.get(interview.resume_id)
        job = iv_job_map.get(interview.job_id)
        activities.append({
            'type': 'interview',
            'icon': 'calendar',
            'iconColor': 'warning',
            'title': '安排了面试',
            'description': f'{resume.candidate_name if resume else "候选人"} - {job.title if job else "未知岗位"}',
            'detail': f'面试时间: {interview.scheduled_at.strftime("%Y-%m-%d %H:%M")}',
            'timestamp': interview.created_at.isoformat()
        })
    
    # 最近的岗位
    recent_jobs = Job.query.order_by(Job.created_at.desc()).limit(3).all()
    for job in recent_jobs:
        activities.append({
            'type': 'job_create',
            'icon': 'plus',
            'iconColor': 'info',
            'title': '创建了岗位',
            'description': job.title,
            'detail': f'状态: {"招聘中" if job.status == "open" else "已关闭"}',
            'timestamp': job.created_at.isoformat()
        })
    
    # 最近Offer
    recent_offers = Offer.query.order_by(Offer.created_at.desc()).limit(5).all()
    for offer in recent_offers:
        activities.append({
            'type': 'offer',
            'icon': 'file-signature',
            'iconColor': 'success',
            'title': '创建/更新了Offer',
            'description': offer.title,
            'detail': f'状态: {offer.status}',
            'timestamp': offer.created_at.isoformat() if offer.created_at else datetime.now().isoformat()
        })

    # 最近员工
    recent_employees = Employee.query.order_by(Employee.created_at.desc()).limit(5).all()
    for employee in recent_employees:
        activities.append({
            'type': 'employee',
            'icon': 'id-card',
            'iconColor': 'primary',
            'title': '新增了员工档案',
            'description': employee.name,
            'detail': f'状态: {employee.status}',
            'timestamp': employee.created_at.isoformat() if employee.created_at else datetime.now().isoformat()
        })

    # 按时间排序，返回最近10条
    activities.sort(key=lambda x: x['timestamp'], reverse=True)
    return jsonify({'activities': activities[:10]})

@misc_bp.route('/settings', methods=['GET'])
@jwt_required()
def get_settings():
    err = _require_privileged()
    if err: return err
    tenant_id = current_tenant_id()
    settings = TenantSetting.query.filter_by(tenant_id=tenant_id).all()
    result = {}
    for setting in settings:
        result[setting.key] = setting.value
    return jsonify(result)

@misc_bp.route('/settings', methods=['POST'])
@jwt_required()
def update_settings():
    err = _require_privileged()
    if err: return err
    data = request.get_json()
    
    tenant_id = current_tenant_id()
    if not isinstance(data, dict):
        return jsonify({'error': '设置格式无效'}), 400

    existing = {
        s.key: s
        for s in TenantSetting.query.filter(
            TenantSetting.tenant_id == tenant_id,
            TenantSetting.key.in_(list(data.keys())),
        ).all()
    } if data else {}
    for key, value in data.items():
        setting = existing.get(key)
        if value is None:
            if setting:
                db.session.delete(setting)
            continue
        if setting:
            setting.value = value
        else:
            setting = TenantSetting(
                id=str(__import__('uuid').uuid4()),
                tenant_id=tenant_id,
                key=key,
                value=value,
            )
            db.session.add(setting)

    db.session.commit()

    settings = TenantSetting.query.filter_by(tenant_id=tenant_id).all()
    result = {}
    for setting in settings:
        result[setting.key] = setting.value
    return jsonify(result)



# ===== 待办事项 API =====

@misc_bp.route('/todos', methods=['GET'])
@jwt_required()
def get_todos():
    """获取当前用户的待办事项列表"""
    user_id = get_jwt_identity()
    tenant_id = current_tenant_id()
    
    if not tenant_id:
        return jsonify({'error': '租户信息缺失'}), 400
    
    todos = TodoService.get_user_todos(user_id, tenant_id)
    count = TodoService.get_todo_count(user_id, tenant_id)
    
    return jsonify({
        'todos': todos,
        'count': count
    })


@misc_bp.route('/todos/count', methods=['GET'])
@jwt_required()
def get_todo_count():
    """获取待办数量（用于顶部导航红点）"""
    user_id = get_jwt_identity()
    tenant_id = current_tenant_id()
    
    if not tenant_id:
        return jsonify({'count': 0})
    
    count = TodoService.get_todo_count(user_id, tenant_id)
    
    return jsonify({'count': count})
