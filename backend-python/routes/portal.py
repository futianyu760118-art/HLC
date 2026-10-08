"""个人学习门户蓝图（/api/portal/*）。

已绑定 employee_id 的账号使用的学习/考试入口：
- /me                  我的员工信息
- /courses             我的课程（按可见性过滤 + 进度）
- /courses/<course_id> 课程详情（章节/课时/附件 + 我的进度）
- /courses/<hour_id>/progress  上报观看进度
"""

from __future__ import annotations

import uuid
import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import bcrypt
from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from sqlalchemy import distinct, func, or_

from models import (
    Course, CourseAttachment, CourseChapter, CourseHour, CourseAssignment,
    Employee, UserCourseProgress, UserHourProgress, db, Department,
    ExamTask, ExamPaper, ExamQuestion, ExamAssignment, ExamAttempt,
    LearningPath, LearningPathAssignment, WrongQuestion, CourseReview,
    CompetencyModel, CompetencyAssessment, PKSeason, PointLog,
    EmployeePortalAccount,
)
from services.course_access import can_see_course, employee_visible_courses
from services.current_user_helper import current_employee, require_employee
from services.tenancy import DEFAULT_TENANT_SLUG, find_tenant_by_slug, tenant_claims_for
from services.learning_path_progress import compute_assignment_progress, _is_course_completed, _stage_completed
from services.course_progress import (
    CourseProgressLockTimeout,
    course_progress_lock,
    employee_course_progress_map,
    employee_hour_progress_map,
    merge_course_progress_rows,
    merge_hour_progress_rows,
)
from services.ai_resource_governance import AIResourceDenied, assert_ai_resource_allowed
from services.tenant_storage_quota import register_storage_quota_error_handler
from routes.auth import (
    FAILED_DELAY_SEC,
    _clear_failures,
    _is_throttled,
    _password_policy_error,
    _record_failure,
)


def _collect_wrong_questions(employee_id, attempt, grading_details):
    """提交考试后自动采集错题。去重累加 wrong_count。"""
    snapshot_map = {str(q.get('id')): q for q in (attempt.paper_snapshot or [])}
    answers = attempt.answers or {}
    now = datetime.utcnow()
    for d in (grading_details or []):
        if d.get('correct'):
            continue  # 只采集错题
        qid = str(d.get('questionId'))
        snap = snapshot_map.get(qid)
        if not snap:
            continue
        # 查已有记录（员工+题目去重）
        existing = WrongQuestion.query.filter_by(
            employee_id=employee_id, question_id=qid
        ).first()
        if existing:
            existing.wrong_count = (existing.wrong_count or 0) + 1
            existing.user_answer = answers.get(qid, [])
            existing.last_wrong_at = now
            existing.mastery = 'wrong'  # 又错了，重置为未掌握
            existing.snapshot = snap  # 更新快照
        else:
            # 取题目分类/课程
            eq = ExamQuestion.query.get(qid)
            db.session.add(WrongQuestion(
                id=str(uuid.uuid4()),
                employee_id=employee_id, question_id=qid,
                snapshot=snap, user_answer=answers.get(qid, []),
                course_id=eq.course_id if eq else None,
                category=eq.category if eq else None,
                wrong_count=1, mastery='wrong', last_wrong_at=now,
            ))

portal_bp = Blueprint('portal', __name__)
register_storage_quota_error_handler(portal_bp)


def _ai_error_response(exc: AIResourceDenied):
    payload, status = exc.to_response()
    return jsonify(payload), status


def _attempt_exam_metadata(attempt, assignment_map=None, task_map=None, paper_map=None):
    """Resolve a stable business identity and display names for an exam attempt."""
    assignment_map = assignment_map or {}
    task_map = task_map or {}
    paper_map = paper_map or {}

    assignment = assignment_map.get(attempt.assignment_id) if attempt.assignment_id else None
    if assignment is None and attempt.assignment_id:
        assignment = db.session.get(ExamAssignment, attempt.assignment_id)

    task_id = attempt.task_id or (assignment.task_id if assignment else None)
    task = task_map.get(task_id) if task_id else None
    if task is None and task_id:
        task = db.session.get(ExamTask, task_id)

    paper_id = attempt.paper_id or (task.paper_id if task else None)
    paper = paper_map.get(paper_id) if paper_id else None
    if paper is None and paper_id:
        paper = db.session.get(ExamPaper, paper_id)

    ref_id = task_id or paper_id or attempt.id
    title = task.title if task else (paper.title if paper else '未命名考试')
    return {
        'refId': ref_id,
        'taskId': task_id,
        'taskTitle': title,
        'paperId': paper_id,
        'paperTitle': paper.title if paper else None,
    }


def _portal_token_for_account(account: EmployeePortalAccount) -> str:
    employee = account.employee
    tenant = find_tenant_by_slug(DEFAULT_TENANT_SLUG)
    tenant_id = getattr(account, 'tenant_id', None) or (getattr(employee, 'tenant_id', None) if employee else None)
    if tenant_id:
        from models import Tenant
        tenant = db.session.get(Tenant, tenant_id)
    return create_access_token(
        identity=account.id,
        additional_claims={
            'account_type': 'employee_portal',
            'role': 'employee',
            'name': employee.name if employee else '',
            'employee_id': account.employee_id,
            'employee_no': employee.employee_no if employee else None,
            'must_change_password': bool(account.must_change_password),
            **tenant_claims_for(tenant, is_platform_admin=False),
        },
    )


@portal_bp.route('/auth/login', methods=['POST'])
def portal_login():
    data = request.get_json(silent=True) or {}
    identifier = (data.get('employeeNo') or data.get('identifier') or '').strip()
    password = data.get('password') or ''
    tenant = find_tenant_by_slug(data.get('tenantSlug') or DEFAULT_TENANT_SLUG)

    if not identifier or not password:
        return jsonify({'error': '员工编号或密码不能为空'}), 400
    if not tenant:
        return jsonify({'error': '企业编码不存在'}), 404
    if getattr(tenant, 'status', 'active') != 'active':
        return jsonify({'error': '企业服务已停用或到期，请联系平台管理员', 'code': 'TENANT_INACTIVE'}), 403

    remote = request.headers.get('X-Forwarded-For', request.remote_addr) or 'unknown'
    fail_key = f'portal:{remote}:{tenant.slug}:{identifier.lower()}'
    if _is_throttled(fail_key):
        time.sleep(FAILED_DELAY_SEC)

    employee = Employee.query.filter(
        or_(
            func.lower(Employee.employee_no) == identifier.lower(),
            func.lower(Employee.oa_login_id) == identifier.lower(),
            func.lower(Employee.oa_person_id) == identifier.lower(),
        ),
        Employee.tenant_id == tenant.id,
    ).first()
    account = EmployeePortalAccount.query.filter_by(employee_id=employee.id, tenant_id=tenant.id).first() if employee else None

    dummy_hash = b'$2b$12$00000000000000000000000000000000000000000000000000000'
    candidate_hash = (account.password_hash.encode('utf-8') if account else dummy_hash)
    try:
        is_valid = bcrypt.checkpw(password.encode('utf-8'), candidate_hash)
    except (ValueError, TypeError):
        is_valid = False

    if not employee or not account or not is_valid:
        _record_failure(fail_key)
        return jsonify({'error': '员工编号或密码错误'}), 401

    if account.status != 'active':
        return jsonify({'error': '员工门户账号已停用，请联系管理员'}), 403

    account.last_login_at = datetime.utcnow()
    if not getattr(account, 'tenant_id', None):
        account.tenant_id = tenant.id
    db.session.commit()
    _clear_failures(fail_key)
    payload = account.to_dict()
    payload.update({'tenantId': tenant.id, 'tenantSlug': tenant.slug, 'tenantName': tenant.name})
    return jsonify({'token': _portal_token_for_account(account), 'user': payload})


@portal_bp.route('/auth/change-password', methods=['POST'])
@jwt_required()
def portal_change_password():
    data = request.get_json(silent=True) or {}
    current_password = data.get('currentPassword') or data.get('oldPassword') or ''
    new_password = data.get('newPassword') or ''

    if not current_password or not new_password:
        return jsonify({'error': '当前密码和新密码均为必填'}), 400

    account = db.session.get(EmployeePortalAccount, get_jwt_identity())
    if not account:
        return jsonify({'error': '请使用员工门户账号修改密码'}), 403
    if account.status != 'active':
        return jsonify({'error': '员工门户账号已停用，请联系管理员'}), 403

    try:
        current_ok = bcrypt.checkpw(current_password.encode('utf-8'), account.password_hash.encode('utf-8'))
    except (ValueError, TypeError):
        current_ok = False
    if not current_ok:
        return jsonify({'error': '当前密码不正确'}), 401

    policy_error = _password_policy_error(new_password, current_password=current_password)
    if policy_error:
        return jsonify({'error': policy_error}), 400

    account.password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    account.must_change_password = False
    account.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'token': _portal_token_for_account(account), 'user': account.to_dict()})


@portal_bp.route('/me', methods=['GET'])
@jwt_required()
def me():
    emp = current_employee()
    if not emp:
        return jsonify({'employee': None, 'bound': False}), 200
    return jsonify({'employee': emp.to_dict(), 'bound': True})


@portal_bp.route('/courses', methods=['GET'])
@jwt_required()
def my_courses():
    """我的课程列表（含进度）。可选 ?status=all|learning|finished。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    courses = employee_visible_courses(emp)
    # 批量取进度。历史并发上报可能留下同一课程多行，按稳定课程身份合并，
    # 完成态/最高进度优先，避免字典覆盖到任意一条 0% 记录。
    progress_map = employee_course_progress_map(emp.id, [c.id for c in courses])
    # 批量取分类名（消除 to_dict 内 self.category 懒加载 N+1）
    from models import CourseCategory
    cat_ids = {c.category_id for c in courses if c.category_id}
    cat_map = {}
    if cat_ids:
        for cat in CourseCategory.query.filter(CourseCategory.id.in_(cat_ids)).all():
            cat_map[cat.id] = cat.name
    status_filter = request.args.get('status', 'all')
    result = []
    for c in courses:
        p = progress_map.get(c.id)
        progress_val = p['progress'] if p else 0
        is_finished = bool(p and p['isFinished'])
        if status_filter == 'learning' and is_finished:
            continue
        if status_filter == 'finished' and not is_finished:
            continue
        d = c.to_dict()
        d['categoryName'] = cat_map.get(c.category_id) if c.category_id else None
        d['progress'] = progress_val
        d['isFinished'] = is_finished
        d['finishedAt'] = p['finishedAt'].isoformat() if (p and p['finishedAt']) else None
        result.append(d)
    return jsonify(result)


@portal_bp.route('/courses/<course_id>', methods=['GET'])
@jwt_required()
def course_detail(course_id):
    """课程详情：章节/课时/附件/我的进度。先校验可见性。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    course = db.session.get(Course, course_id)
    if not course:
        return jsonify({'error': '课程不存在'}), 404
    if not can_see_course(emp, course):
        return jsonify({'error': '无权限访问该课程'}), 403

    chapters = CourseChapter.query.filter_by(course_id=course_id).order_by(
        CourseChapter.sort.asc(), CourseChapter.created_at.asc()
    ).all()
    hours = CourseHour.query.filter_by(course_id=course_id).order_by(
        CourseHour.sort.asc(), CourseHour.created_at.asc()
    ).all()
    attachments = CourseAttachment.query.filter_by(course_id=course_id).order_by(
        CourseAttachment.sort.asc()
    ).all()

    # 我的课时/课程进度。历史重复上报按 hour_id/course_id 合并，完成态优先。
    hour_progress_map = employee_hour_progress_map(emp.id, course_id)
    course_progress = employee_course_progress_map(emp.id, [course_id]).get(course_id)

    # 给每个课时附预签名视频 URL（直接构造 dict，不走 to_dict 的懒加载 N+1）
    from services import storage
    course_title = course.title
    chapter_names = {ch.id: ch.name for ch in chapters}
    hours_out = []
    for h in hours:
        d = {
            'id': h.id, 'courseId': h.course_id, 'courseTitle': course_title,
            'chapterId': h.chapter_id, 'chapterName': chapter_names.get(h.chapter_id),
            'title': h.title, 'type': h.type, 'sort': h.sort,
            'videoKey': h.video_key, 'duration': h.duration,
            'createdAt': h.created_at.isoformat() if h.created_at else None,
            'updatedAt': h.updated_at.isoformat() if h.updated_at else None,
        }
        d['videoUrl'] = storage.presigned_url(h.video_key) if h.video_key else None
        hp = hour_progress_map.get(h.id)
        d['watchedDuration'] = hp['watchedDuration'] if hp else 0
        d['isFinished'] = bool(hp and hp['isFinished'])
        hours_out.append(d)

    # 按章节分组（同样直接构造，不走 to_dict）
    chapters_out = []
    for ch in chapters:
        chapters_out.append({
            'id': ch.id, 'courseId': ch.course_id, 'courseTitle': course_title,
            'name': ch.name, 'sort': ch.sort,
            'createdAt': ch.created_at.isoformat() if ch.created_at else None,
            'updatedAt': ch.updated_at.isoformat() if ch.updated_at else None,
            'hours': [h for h in hours_out if h.get('chapterId') == ch.id],
        })
    # 无章节的课时归到「未分组」
    ungrouped = [h for h in hours_out if not h.get('chapterId')]

    course_out = course.to_dict()
    # Keep the nested course shape compatible with existing clients while the
    # top-level progress fields remain the canonical course-detail contract.
    course_out['isFinished'] = bool(course_progress and course_progress['isFinished'])

    return jsonify({
        'course': course_out,
        'chapters': chapters_out,
        'ungroupedHours': ungrouped,
        'attachments': [a.to_dict() for a in attachments],
        'progress': course_progress['progress'] if course_progress else 0,
        'isFinished': bool(course_progress and course_progress['isFinished']),
        'finishedCount': course_progress['finishedCount'] if course_progress else 0,
        'totalHours': len(hours),
    })


@portal_bp.route('/hours/<hour_id>', methods=['GET'])
@jwt_required()
def get_hour_detail(hour_id):
    """直接查课时信息（含视频URL），避免前端遍历所有课程找课时。

    视频返回短期签名 URL（/api/media/<key>?exp=&sig=）：
    - 不要求请求带 Authorization（<video> 标签无法带 header）
    - 支持 Range 请求，可流式播放/拖动进度
    - 短期有效（2 小时），签名绑定 SECRET_KEY，不可伪造
    """
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    hour = db.session.get(CourseHour, hour_id)
    if not hour:
        return jsonify({'error': '课时不存在'}), 404
    course = db.session.get(Course, hour.course_id)
    if not course or not can_see_course(emp, course):
        return jsonify({'error': '无权限'}), 403
    video_url = _signed_media_url(hour.video_key) if hour.video_key else None
    # 附带员工对该课时的进度（同一课时的历史重复行取最大观看时长/完成态）。
    hour_prog_map = employee_hour_progress_map(emp.id, hour.course_id)
    hp = hour_prog_map.get(hour_id)
    course_progress = employee_course_progress_map(emp.id, [hour.course_id]).get(hour.course_id)
    # 课程整体进度 + 全部课时列表（带完成态），供学习页展示整体进度和课时大纲
    all_hours = CourseHour.query.filter_by(course_id=hour.course_id) \
        .order_by(CourseHour.sort, CourseHour.created_at).all()
    total_hours = len(all_hours)
    finished_count = sum(1 for h in all_hours if hour_prog_map.get(h.id) and hour_prog_map[h.id]['isFinished'])

    def _hour_brief(h):
        return {
            'id': h.id,
            'title': h.title,
            'duration': h.duration,
            'isFinished': bool(hour_prog_map.get(h.id) and hour_prog_map[h.id]['isFinished']),
        }

    # 按章节分组（与课程详情页结构一致），未分章节的课时归入 ungrouped
    chapters_raw = CourseChapter.query.filter_by(course_id=hour.course_id) \
        .order_by(CourseChapter.sort, CourseChapter.created_at).all()
    chapters_list = []
    ungrouped = []
    for ch in chapters_raw:
        ch_hours = [h for h in all_hours if h.chapter_id == ch.id]
        if ch_hours:
            chapters_list.append({
                'id': ch.id, 'name': ch.name,
                'hours': [_hour_brief(h) for h in ch_hours],
            })
    ungrouped = [_hour_brief(h) for h in all_hours if not h.chapter_id]

    return jsonify({
        'hour': {
            'id': hour.id,
            'title': hour.title,
            'duration': hour.duration,
            'videoUrl': video_url,
            'watchedDuration': hp['watchedDuration'] if hp else 0,
            'isFinished': bool(hp and hp['isFinished']),
        },
        'course': {
            'id': course.id,
            'title': course.title,
            'progress': course_progress['progress'] if course_progress else (
                int(finished_count / total_hours * 100) if total_hours else 0
            ),
            'finishedCount': course_progress['finishedCount'] if course_progress else finished_count,
            'totalHours': total_hours,
            'chapters': chapters_list,
            'ungroupedHours': ungrouped,
        },
    })


# ---------------------------------------------------------------------------
# 受保护媒体签名 URL（视频/大文件流式播放，支持 Range）
# 生成逻辑统一放 services.portal_media_auth，校验在 app.py /api/media/<key>。
# ---------------------------------------------------------------------------

def _signed_media_url(video_key: str) -> str:
    """生成短期 HMAC 签名的媒体访问 URL，供 <video> 直接播放。"""
    from services.portal_media_auth import build_signed_url
    return build_signed_url(video_key) if video_key else ''


@portal_bp.route('/courses/<hour_id>/progress', methods=['POST'])
@jwt_required()
def report_progress(hour_id):
    """上报单课时观看进度。body: {watchedDuration, isFinished, totalDuration?}"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    hour = db.session.get(CourseHour, hour_id)
    if not hour:
        return jsonify({'error': '课时不存在'}), 404
    course = db.session.get(Course, hour.course_id)
    if not course or not can_see_course(emp, course):
        return jsonify({'error': '无权限'}), 403

    data = request.get_json() or {}
    try:
        watched = int(data.get('watchedDuration', 0) or 0)
    except (TypeError, ValueError):
        return jsonify({'error': 'watchedDuration 须为数字'}), 400
    if watched < 0:
        watched = 0
    is_finished = bool(data.get('isFinished', False))
    try:
        total_duration = int(data.get('totalDuration') or hour.duration or 0)
    except (TypeError, ValueError):
        total_duration = hour.duration or 0
    if total_duration < 0:
        total_duration = 0

    # Cache scalar identity values before ending the authentication read
    # transaction.  Accessing an expired ORM object after commit would open a
    # fresh snapshot before the advisory lock is acquired.
    employee_id = emp.id
    course_id = hour.course_id
    hour_title = hour.title

    # ``require_employee`` performs read queries and may leave a MySQL
    # REPEATABLE READ snapshot open.  End that read-only transaction before
    # waiting on the per-course advisory lock; otherwise a waiter could still
    # read the pre-lock snapshot and insert a duplicate first-progress row.
    db.session.commit()

    try:
        # 旧表没有复合唯一索引；MySQL advisory lock 先把同一员工/课程的
        # 并发上报串行化，历史重复行则在本事务内取最强状态而不删除。
        with course_progress_lock(employee_id, course_id):
            hp_rows = UserHourProgress.query.filter_by(
                employee_id=employee_id, course_id=course_id, hour_id=hour_id
            ).all()
            hp_merged = merge_hour_progress_rows(hp_rows)
            hp = hp_merged['_row'] if hp_merged else None
            existing_hour_finished = bool(hp_merged and hp_merged['isFinished'])

            # 重算前按课程身份聚合，不能让任意一条旧 0% 行覆盖完成态。
            cp_before = employee_course_progress_map(
                employee_id, [course_id]
            ).get(course_id)
            was_finished = bool(cp_before and cp_before['isFinished'])

            now = datetime.utcnow()
            if not hp:
                hp = UserHourProgress(
                    id=str(uuid.uuid4()),
                    employee_id=employee_id, course_id=course_id, hour_id=hour_id,
                    total_duration=total_duration, watched_duration=0, is_finished=False,
                )
                db.session.add(hp)
            previous_watched = hp_merged['watchedDuration'] if hp_merged else 0
            previous_total = hp_merged['totalDuration'] if hp_merged else 0
            hp.watched_duration = max(previous_watched, hp.watched_duration or 0, watched)
            hp.total_duration = max(previous_total, hp.total_duration or 0, total_duration)
            # 完成态只前进不回退，避免迟到的暂停请求把已完成课时改回未完成。
            hp.is_finished = bool(existing_hour_finished or hp.is_finished or is_finished)
            if hp.is_finished:
                hp.finished_at = (
                    hp.finished_at
                    or (hp_merged and hp_merged['finishedAt'])
                    or now
                )

            if is_finished and not existing_hour_finished:
                # 积分：完成课时（积分服务自身还有唯一边界兜底）。
                from services.points import award_points
                award_points(employee_id, 'course_hour_finished', ref_id=hour_id, detail=hour_title)

            # 让新行在重算查询前进入当前事务。
            db.session.flush()
            _recompute_course_progress(employee_id, course_id)

            # 仅在“本次上报导致课程从未完成→完成”时发放奖励和证书（一次性）。
            cp_after = employee_course_progress_map(
                employee_id, [course_id]
            ).get(course_id)
            if cp_after and cp_after['isFinished'] and not was_finished:
                from services.points import award_points
                course_obj = db.session.get(Course, course_id)
                award_points(
                    employee_id, 'course_completed', ref_id=course_id,
                    detail=course_obj.title if course_obj else None,
                )
                from services.certificate import generate_certificate
                generate_certificate(employee_id, course_id)
            db.session.commit()

            return jsonify({
                'hourFinished': bool(hp.is_finished),
                'courseProgress': cp_after['progress'] if cp_after else 0,
                'courseFinished': bool(cp_after and cp_after['isFinished']),
            })
    except CourseProgressLockTimeout:
        db.session.rollback()
        return jsonify({'error': '学习进度正在保存，请稍后重试', 'code': 'COURSE_PROGRESS_BUSY'}), 503


def _recompute_course_progress(employee_id: str, course_id: str) -> None:
    """根据所有课时进度重算课程级进度（不 commit，由调用方提交）。"""
    total_hours = CourseHour.query.filter_by(course_id=course_id).count()
    actual_hour_ids = {
        row.id for row in CourseHour.query.filter_by(course_id=course_id).all()
    }
    hour_progress_map = employee_hour_progress_map(employee_id, course_id)
    # 只按 distinct hour_id 计数，重复上报不能把课程进度抬高。
    finished_hours = sum(
        1 for hour_id, progress in hour_progress_map.items()
        if hour_id in actual_hour_ids and progress['isFinished']
    )
    progress = int(finished_hours / total_hours * 100) if total_hours else 0
    is_finished = total_hours > 0 and finished_hours >= total_hours

    cp_rows = UserCourseProgress.query.filter_by(
        employee_id=employee_id, course_id=course_id
    ).all()
    cp_merged = merge_course_progress_rows(
        cp_rows, total_hours=total_hours, finished_count=finished_hours,
    )
    cp = cp_merged['_row'] if cp_merged else None
    now = datetime.utcnow()
    if not cp:
        cp = UserCourseProgress(
            id=str(uuid.uuid4()),
            employee_id=employee_id, course_id=course_id,
            hour_count=total_hours, finished_count=0,
            progress=0, is_finished=False,
        )
        db.session.add(cp)
    cp.hour_count = total_hours
    cp.finished_count = finished_hours
    # 课程完成态沿用历史行为：一旦完成不回退；重复行中的完成态也要保留。
    previously_finished = bool(cp_merged and cp_merged['isFinished'])
    cp.progress = 100 if (previously_finished or is_finished) else progress
    cp.is_finished = bool(previously_finished or is_finished)
    if cp.is_finished and not cp.finished_at:
        cp.finished_at = (cp_merged and cp_merged['finishedAt']) or now


# ===========================================================================
# 考试门户端点
# ===========================================================================

def _distributed_scores(total_score, count):
    if count <= 0:
        return []
    total = Decimal(str(total_score or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    total_cents = int((total * 100).to_integral_value(rounding=ROUND_HALF_UP))
    base = total_cents // count
    remainder = total_cents % count
    return [float(Decimal(base + (1 if idx < remainder else 0)) / Decimal('100')) for idx in range(count)]


def _build_paper_snapshot(paper: ExamPaper):
    """根据试卷配置构建提交时刻快照（含答案，判分用）。"""
    qids = [str(qid).strip() for qid in (paper.question_ids or []) if str(qid or '').strip()]
    if not qids:
        return [], '试卷没有配置题目'

    questions = {
        q.id: q for q in ExamQuestion.query.filter(ExamQuestion.id.in_(qids)).all()
        if q.review_status == 'approved'
    }
    ordered_ids = [qid for qid in qids if qid in questions]
    if not ordered_ids:
        return [], '试卷没有有效题目'

    question_mode = str(getattr(paper, 'question_mode', 'fixed') or 'fixed').strip().lower()
    selected_ids = list(ordered_ids)
    if question_mode == 'random':
        draw_count = int(getattr(paper, 'draw_count', 0) or 0)
        if draw_count <= 0:
            return [], '随机试卷未配置抽题数量'
        if draw_count > len(ordered_ids):
            return [], '随机试卷题池数量不足'
        import random
        sampled_ids = set(random.sample(ordered_ids, draw_count))
        selected_ids = [qid for qid in ordered_ids if qid in sampled_ids]

    score_plan = {}
    if question_mode == 'random':
        distributed = _distributed_scores(getattr(paper, 'total_score', 0), len(selected_ids))
        score_plan = {qid: distributed[idx] for idx, qid in enumerate(selected_ids)}

    snapshot = []
    for qid in selected_ids:
        q = questions[qid]
        snapshot.append({
            'id': q.id,
            'type': q.type,
            'stem': q.stem,
            'options': q.options or [],
            'answer': q.answer or [],
            'score': score_plan.get(qid, float(q.score or 0)),
            'explanation': q.explanation,
            'difficulty': q.difficulty,
        })
    return snapshot, None


def _strip_answer_for_client(snapshot: list) -> list:
    """给前端的题目不含 answer/explanation（防作弊基础）。"""
    return [
        {k: v for k, v in q.items() if k not in ('answer', 'explanation')}
        for q in snapshot
    ]


@portal_bp.route('/exams', methods=['GET'])
@jwt_required()
def my_exams():
    """我的考试列表。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    assignments = ExamAssignment.query.filter_by(employee_id=emp.id).all()
    now = datetime.utcnow()
    # 批量预加载 task + paper（消除循环内逐条 query.get 的 N+1）
    task_ids = {a.task_id for a in assignments if a.task_id}
    task_map = {t.id: t for t in ExamTask.query.filter(ExamTask.id.in_(task_ids)).all()} if task_ids else {}
    paper_ids = {t.paper_id for t in task_map.values() if t.paper_id}
    paper_map = {p.id: p for p in ExamPaper.query.filter(ExamPaper.id.in_(paper_ids)).all()} if paper_ids else {}

    result = []
    for a in assignments:
        task = task_map.get(a.task_id)
        if not task:
            continue
        paper = paper_map.get(task.paper_id) if task.paper_id else None
        question_ids = list((paper.question_ids or []) if paper else [])
        question_mode = str(getattr(paper, 'question_mode', 'fixed') or 'fixed').strip().lower() if paper else 'fixed'
        draw_count = int(getattr(paper, 'draw_count', 0) or 0) if paper else 0
        question_count = draw_count if question_mode == 'random' and draw_count > 0 else len(question_ids)
        in_window = True
        if task.start_time and now < task.start_time:
            in_window = False
        if task.end_time and now > task.end_time:
            in_window = False
        remaining_attempts = (task.max_attempts or 1) - (a.attempts_used or 0)
        result.append({
            'taskId': task.id,
            'title': task.title,
            'description': task.description,
            'paperTitle': paper.title if paper else None,
            'questionMode': question_mode,
            'drawCount': draw_count or None,
            'poolCount': len(question_ids),
            'questionCount': question_count,
            'totalScore': float(paper.total_score) if paper else None,
            'passScore': float(paper.pass_score) if paper else None,
            'durationMinutes': paper.duration_minutes if paper else None,
            'startTime': task.start_time.isoformat() if task.start_time else None,
            'endTime': task.end_time.isoformat() if task.end_time else None,
            'maxAttempts': task.max_attempts,
            'attemptsUsed': a.attempts_used,
            'remainingAttempts': max(0, remaining_attempts),
            'status': a.status,
            'inWindow': in_window,
        })
    return jsonify(result)


@portal_bp.route('/exams/<task_id>/start', methods=['POST'])
@jwt_required()
def start_exam(task_id):
    """开始考试：校验授权/次数/时间窗，创建 doing 状态的 ExamAttempt。

    返回给前端的题目不含 answer（防作弊）。
    """
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    task = ExamTask.query.get(task_id)
    if not task:
        return jsonify({'error': '考试任务不存在'}), 404
    if task.status != 'published':
        return jsonify({'error': '考试未开放'}), 400

    now = datetime.utcnow()
    if task.start_time and now < task.start_time:
        return jsonify({'error': '考试尚未开始'}), 400
    if task.end_time and now > task.end_time:
        return jsonify({'error': '考试已结束'}), 400

    assignment = ExamAssignment.query.filter_by(
        task_id=task_id, employee_id=emp.id
    ).first()
    if not assignment:
        return jsonify({'error': '未被指派参加本次考试'}), 403

    remaining = (task.max_attempts or 1) - (assignment.attempts_used or 0)
    if remaining <= 0:
        return jsonify({'error': '考试次数已用完'}), 400

    paper = ExamPaper.query.get(task.paper_id) if task.paper_id else None
    if not paper:
        return jsonify({'error': '试卷配置错误'}), 500

    snapshot, snapshot_error = _build_paper_snapshot(paper)
    if snapshot_error:
        return jsonify({'error': snapshot_error}), 400

    # shuffle 题序（可选）
    if paper.shuffle:
        import random
        snapshot = list(snapshot)
        random.shuffle(snapshot)

    attempt = ExamAttempt(
        id=str(uuid.uuid4()),
        assignment_id=assignment.id,
        employee_id=emp.id,
        task_id=task_id,
        paper_id=paper.id,
        paper_snapshot=snapshot,
        answers={},
        status='doing',
        pass_score=float(paper.pass_score or 0),
        started_at=now,
    )
    db.session.add(attempt)
    assignment.attempts_used = (assignment.attempts_used or 0) + 1
    db.session.commit()

    # 计算总分（来自快照）
    total_score = sum(q['score'] for q in snapshot)
    return jsonify({
        'attemptId': attempt.id,
        'taskId': task_id,
        'title': task.title,
        'durationMinutes': paper.duration_minutes,
        'totalScore': total_score,
        'passScore': float(paper.pass_score or 0),
        'questions': _strip_answer_for_client(snapshot),
    })


@portal_bp.route('/exams/<attempt_id>/attempt', methods=['GET'])
@jwt_required()
def get_in_progress_attempt(attempt_id):
    """获取进行中的考试作答信息（用于刷新/直链恢复答题页）。

    返回与 start 相同结构的 meta（题目不含 answer），前端据此重建答题页。
    仅对 status='doing' 的 attempt 有效；已提交的返回 410，引导去结果页。
    """
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    attempt = ExamAttempt.query.get(attempt_id)
    if not attempt:
        return jsonify({'error': '答题记录不存在'}), 404
    if attempt.employee_id != emp.id:
        return jsonify({'error': '无权限'}), 403
    if attempt.status == 'submitted':
        # 已交卷：前端应跳结果页
        return jsonify({'error': '已提交', 'submitted': True}), 410
    if attempt.status != 'doing':
        return jsonify({'error': '考试状态异常'}), 400

    snapshot = attempt.paper_snapshot or []
    paper = ExamPaper.query.get(attempt.paper_id) if attempt.paper_id else None
    task = ExamTask.query.get(attempt.task_id) if attempt.task_id else None
    total_score = sum(q['score'] for q in snapshot)
    return jsonify({
        'attemptId': attempt.id,
        'taskId': attempt.task_id,
        'title': task.title if task else '考试',
        'durationMinutes': paper.duration_minutes if paper else None,
        'totalScore': total_score,
        'passScore': float(attempt.pass_score or 0),
        'startedAt': attempt.started_at.isoformat() if attempt.started_at else None,
        'questions': _strip_answer_for_client(snapshot),
    })


@portal_bp.route('/exams/<attempt_id>/submit', methods=['POST'])
@jwt_required()
def submit_exam(attempt_id):
    """提交考试：判分、写成绩、更新 assignment 状态。

    幂等：已提交的 attempt 直接返回已有结果。
    """
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    attempt = ExamAttempt.query.get(attempt_id)
    if not attempt:
        return jsonify({'error': '答题记录不存在'}), 404
    if attempt.employee_id != emp.id:
        return jsonify({'error': '无权限'}), 403
    if attempt.status == 'submitted':
        # 幂等：返回已有结果
        return jsonify(_format_attempt_result(attempt))

    data = request.get_json() or {}
    answers = data.get('answers') or {}

    from services.exam_grading import grade_attempt, is_passed
    grading = grade_attempt(attempt.paper_snapshot or [], answers)
    passed = is_passed(grading['score'], float(attempt.pass_score or 0))

    attempt.answers = answers
    attempt.score = grading['score']
    attempt.total_score = grading['totalScore']
    attempt.passed = passed
    attempt.status = 'submitted'
    attempt.submitted_at = datetime.utcnow()

    # 更新 assignment 状态（取更优结果）
    if attempt.assignment_id:
        assignment = ExamAssignment.query.get(attempt.assignment_id)
        if assignment:
            if passed:
                assignment.status = 'passed'
            elif assignment.status != 'passed':
                assignment.status = 'failed'

    # 自动采集错题到错题本（判分 details 里 correct=False 的题）
    _collect_wrong_questions(emp.id, attempt, grading['details'])
    # 积分：按考试任务而非答题记录去重，兼容旧数据中 task_id 为空的记录。
    from services.points import award_points
    exam_meta = _attempt_exam_metadata(attempt)
    award_points(
        emp.id,
        'exam_attempted',
        ref_id=exam_meta['refId'],
        detail=exam_meta['taskTitle'],
    )
    if passed:
        award_points(
            emp.id,
            'exam_passed',
            ref_id=exam_meta['refId'],
            detail=exam_meta['taskTitle'],
        )
    db.session.commit()
    return jsonify(_format_attempt_result(attempt, grading_details=grading['details']))


@portal_bp.route('/exams/<attempt_id>/result', methods=['GET'])
@jwt_required()
def exam_result(attempt_id):
    """查看考试结果（含正确答案与解析，仅提交后可见）。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    attempt = ExamAttempt.query.get(attempt_id)
    if not attempt:
        return jsonify({'error': '答题记录不存在'}), 404
    if attempt.employee_id != emp.id:
        return jsonify({'error': '无权限'}), 403
    if attempt.status != 'submitted':
        return jsonify({'error': '考试尚未提交'}), 400
    return jsonify(_format_attempt_result(attempt))


def _format_attempt_result(attempt: ExamAttempt, grading_details=None) -> dict:
    """组装结果响应。grading_details 为 None 时重新判分。"""
    from services.exam_grading import grade_attempt, is_passed
    if grading_details is None and attempt.paper_snapshot is not None:
        grading = grade_attempt(attempt.paper_snapshot, attempt.answers or {})
        grading_details = grading['details']
    passed = attempt.passed
    if passed is None and attempt.score is not None:
        passed = is_passed(float(attempt.score), float(attempt.pass_score or 0))
    # 合并快照 + 答案 + 判分详情，供前端展示对错与解析
    detail_map = {str(d['questionId']): d for d in (grading_details or [])}
    answers = attempt.answers or {}
    questions_with_review = []
    for q in (attempt.paper_snapshot or []):
        qid = str(q.get('id'))
        d = detail_map.get(qid, {})
        questions_with_review.append({
            **q,
            'userAnswer': answers.get(qid, []),
            'correct': d.get('correct'),
            'awarded': d.get('awarded'),
        })
    return {
        'attemptId': attempt.id,
        'score': float(attempt.score) if attempt.score is not None else None,
        'totalScore': float(attempt.total_score) if attempt.total_score is not None else None,
        'passScore': float(attempt.pass_score) if attempt.pass_score is not None else None,
        'passed': passed,
        'status': attempt.status,
        'startedAt': attempt.started_at.isoformat() if attempt.started_at else None,
        'submittedAt': attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        'questions': questions_with_review,
    }


# ===========================================================================
# 学习路径门户端点
# ===========================================================================

@portal_bp.route('/learning-paths', methods=['GET'])
@jwt_required()
def my_learning_paths():
    """我的学习路径列表（含进度 + 阶段解锁状态）。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    assignments = LearningPathAssignment.query.filter_by(employee_id=emp.id).all()

    # === 批量预加载所有需要的课程和进度（消除 N+1）===
    all_course_ids = set()
    for a in assignments:
        if a.path:
            for stage in (a.path.stages or []):
                for cid in (stage.get('courseIds') or []):
                    all_course_ids.add(cid)

    # 一次性查出所有课程
    course_map = {}
    if all_course_ids:
        for c in Course.query.filter(Course.id.in_(all_course_ids)).all():
            course_map[c.id] = c

    # 同一课程的历史重复进度行按稳定课程身份合并后再标记完成态。
    progress_map = employee_course_progress_map(emp.id, all_course_ids)
    finished_course_ids = {
        course_id for course_id, progress in progress_map.items()
        if progress['isFinished']
    }

    result = []
    for a in assignments:
        compute_assignment_progress(a)
        path = a.path
        if not path:
            continue
        stages = path.stages or []
        stages_out = []
        for i, stage in enumerate(stages):
            unlocked = i <= a.current_stage
            courses_in = []
            for cid in (stage.get('courseIds') or []):
                c = course_map.get(cid)
                courses_in.append({
                    'id': cid,
                    'title': c.title if c else None,
                    'coverUrl': c.cover_url if c else None,
                    'isFinished': cid in finished_course_ids,
                })
            stages_out.append({
                'index': i,
                'name': stage.get('name'),
                'courses': courses_in,
                'unlocked': unlocked,
                'completed': _stage_completed(emp.id, stage),
                'hasExam': bool(stage.get('examTaskId')),
            })
        db.session.commit()
        result.append({
            'pathId': path.id,
            'name': path.name,
            'description': path.description,
            'coverUrl': path.cover_url,
            'targetPosition': path.target_position,
            'stageCount': len(stages),
            'currentStage': a.current_stage,
            'progress': a.progress,
            'isCompleted': a.is_completed,
            'completedAt': a.completed_at.isoformat() if a.completed_at else None,
            'stages': stages_out,
        })
    return jsonify(result)


@portal_bp.route('/learning-paths/<path_id>/progress', methods=['POST'])
@jwt_required()
def refresh_path_progress(path_id):
    """手动触发路径进度刷新（员工学完课程后调用）。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    a = LearningPathAssignment.query.filter_by(path_id=path_id, employee_id=emp.id).first()
    if not a:
        return jsonify({'error': '未分配该路径'}), 404
    compute_assignment_progress(a)
    db.session.commit()
    return jsonify({'progress': a.progress, 'currentStage': a.current_stage, 'isCompleted': a.is_completed})


@portal_bp.route('/my-profile', methods=['GET'])
@jwt_required()
def my_profile():
    """我的学习档案：按课程和考试任务聚合，不按答题次数重复统计。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]

    from models import Certificate
    from services.points import get_employee_total_points

    # 课程/课时进度都按稳定业务身份合并。历史并发上报留下的重复行不能
    # 重复计数，也不能让一条 0% 行覆盖同课程的完成行。
    course_progress_map = employee_course_progress_map(emp.id)
    course_progress = list(course_progress_map.values())
    courses_finished = sum(1 for p in course_progress if p['isFinished'])
    courses_in_progress = sum(
        1 for p in course_progress
        if not p['isFinished'] and p['progress'] > 0
    )
    total_watched = sum(
        hour['watchedDuration']
        for course in course_progress
        for hour in course.get('hourProgress', {}).values()
    )

    attempts = ExamAttempt.query.filter_by(
        employee_id=emp.id, status='submitted'
    ).order_by(ExamAttempt.submitted_at.desc()).all()

    assignment_ids = {a.assignment_id for a in attempts if a.assignment_id}
    assignments = ExamAssignment.query.filter(ExamAssignment.id.in_(assignment_ids)).all() if assignment_ids else []
    assignment_map = {row.id: row for row in assignments}
    task_ids = {a.task_id for a in attempts if a.task_id}
    task_ids.update(row.task_id for row in assignments if row.task_id)
    tasks = ExamTask.query.filter(ExamTask.id.in_(task_ids)).all() if task_ids else []
    task_map = {row.id: row for row in tasks}
    paper_ids = {a.paper_id for a in attempts if a.paper_id}
    paper_ids.update(row.paper_id for row in tasks if row.paper_id)
    papers = ExamPaper.query.filter(ExamPaper.id.in_(paper_ids)).all() if paper_ids else []
    paper_map = {row.id: row for row in papers}

    exam_groups = {}
    for attempt in attempts:
        meta = _attempt_exam_metadata(attempt, assignment_map, task_map, paper_map)
        key = meta['refId']
        score = float(attempt.score) if attempt.score is not None else None
        total_score = float(attempt.total_score) if attempt.total_score is not None else None
        if key not in exam_groups:
            exam_groups[key] = {
                'attemptId': attempt.id,
                'latestAttemptId': attempt.id,
                'taskId': meta['taskId'],
                'taskTitle': meta['taskTitle'],
                'paperId': meta['paperId'],
                'paperTitle': meta['paperTitle'],
                'score': score,
                'latestScore': score,
                'totalScore': total_score,
                'bestScore': score,
                'bestAttemptId': attempt.id,
                'passed': bool(attempt.passed),
                'attemptCount': 1,
                'submittedAt': attempt.submitted_at.isoformat() if attempt.submitted_at else None,
            }
            continue

        group = exam_groups[key]
        group['attemptCount'] += 1
        group['passed'] = group['passed'] or bool(attempt.passed)
        if score is not None and (group['bestScore'] is None or score > group['bestScore']):
            group['bestScore'] = score
            group['bestAttemptId'] = attempt.id

    recent_exams = list(exam_groups.values())
    exams_passed = sum(1 for row in recent_exams if row['passed'])

    course_ids = {row['courseId'] for row in course_progress if row.get('courseId')}
    course_map = {
        row.id: row for row in Course.query.filter(Course.id.in_(course_ids)).all()
    } if course_ids else {}
    recent_courses = sorted(
        course_progress,
        key=lambda row: row.get('finishedAt') or row.get('updatedAt')
        or row.get('createdAt') or datetime.min,
        reverse=True,
    )
    certificates = Certificate.query.filter_by(employee_id=emp.id).order_by(
        Certificate.issued_at.desc()
    ).all()
    path_assignments = LearningPathAssignment.query.filter_by(employee_id=emp.id).all()

    course_total = len(course_progress)
    exam_total = len(recent_exams)

    return jsonify({
        'employee': emp.to_dict(),
        'stats': {
            'coursesFinished': courses_finished,
            'coursesInProgress': courses_in_progress,
            'coursesTotal': course_total,
            'courseCompletionRate': round(courses_finished / course_total * 100) if course_total else 0,
            'totalWatchedSeconds': int(total_watched),
            'totalWatchedMinutes': int(total_watched // 60),
            'examsTaken': exam_total,
            'examsPassed': exams_passed,
            'examPassRate': round(exams_passed / exam_total * 100) if exam_total else 0,
            'certificatesEarned': len(certificates),
            'totalPoints': get_employee_total_points(emp.id),
            'learningPaths': len(path_assignments),
            'learningPathsCompleted': sum(1 for row in path_assignments if row.is_completed),
        },
        'recentCourses': [
            {
                'courseId': row['courseId'],
                'courseTitle': course_map.get(row['courseId']).title
                if course_map.get(row['courseId']) else None,
                'progress': int(row['progress'] or 0),
                'finishedCount': int(row['finishedCount'] or 0),
                'hourCount': int(row['hourCount'] or 0),
                'isFinished': bool(row['isFinished']),
                'finishedAt': row['finishedAt'].isoformat() if row['finishedAt'] else None,
                'updatedAt': row['updatedAt'].isoformat() if row['updatedAt'] else None,
            }
            for row in recent_courses[:8]
        ],
        'recentExams': recent_exams[:10],
        'certificates': [row.to_dict() for row in certificates[:5]],
        'learningPaths': [row.to_dict() for row in path_assignments[:5]],
    })


# ===========================================================================
# 错题本（错题回顾 + 收藏 + 重练掌握）
# ===========================================================================

@portal_bp.route('/wrong-questions', methods=['GET'])
@jwt_required()
def my_wrong_questions():
    """我的错题本。支持 ?mastery=wrong|mastered|all&category=&favorited=1 筛选。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    q = WrongQuestion.query.filter_by(employee_id=emp.id)
    mastery = request.args.get('mastery', 'wrong')
    if mastery != 'all':
        q = q.filter_by(mastery=mastery)
    cat = request.args.get('category')
    if cat:
        q = q.filter_by(category=cat)
    if request.args.get('favorited') == '1':
        q = q.filter_by(is_favorited=True)
    rows = q.order_by(WrongQuestion.last_wrong_at.desc()).all()
    # 统计
    all_rows = WrongQuestion.query.filter_by(employee_id=emp.id).all()
    stats = {
        'total': len(all_rows),
        'wrong': sum(1 for r in all_rows if r.mastery == 'wrong'),
        'mastered': sum(1 for r in all_rows if r.mastery == 'mastered'),
        'favorited': sum(1 for r in all_rows if r.is_favorited),
    }
    return jsonify({'items': [r.to_dict() for r in rows], 'stats': stats})


@portal_bp.route('/wrong-questions/<wq_id>/favorite', methods=['POST'])
@jwt_required()
def toggle_favorite_wrong_question(wq_id):
    """收藏/取消收藏错题。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    wq = WrongQuestion.query.get(wq_id)
    if not wq or wq.employee_id != emp.id:
        return jsonify({'error': '错题不存在'}), 404
    wq.is_favorited = not wq.is_favorited
    db.session.commit()
    return jsonify({'id': wq_id, 'isFavorited': wq.is_favorited})


@portal_bp.route('/wrong-questions/<wq_id>/master', methods=['POST'])
@jwt_required()
def mark_wrong_question_mastered(wq_id):
    """标记错题为已掌握（移出错题本主列表）。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    wq = WrongQuestion.query.get(wq_id)
    if not wq or wq.employee_id != emp.id:
        return jsonify({'error': '错题不存在'}), 404
    wq.mastery = 'mastered' if wq.mastery == 'wrong' else 'wrong'
    db.session.commit()
    return jsonify({'id': wq_id, 'mastery': wq.mastery})


@portal_bp.route('/wrong-questions/practice', methods=['POST'])
@jwt_required()
def practice_wrong_questions():
    """错题重练：抽取错题作答，判分后答对的自动标记已掌握。

    body: {answers: {wrongQuestionId: [idx,...]}}
    返回每题对错 + 是否自动掌握。
    """
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    data = request.get_json() or {}
    answers = data.get('answers') or {}
    from services.exam_grading import grade_attempt
    # 构造临时 paper_snapshot 供判分
    wq_ids = list(answers.keys())
    wq_rows = WrongQuestion.query.filter(
        WrongQuestion.id.in_(wq_ids), WrongQuestion.employee_id == emp.id
    ).all()
    snapshot = []
    wq_map = {}
    for wq in wq_rows:
        snap = wq.snapshot or {}
        snap['id'] = wq.id  # 用错题记录 id 作判分 key
        snapshot.append(snap)
        wq_map[wq.id] = wq
    grading = grade_attempt(snapshot, answers)
    # 答对的标记已掌握
    mastered_ids = []
    for d in grading['details']:
        if d.get('correct'):
            wq = wq_map.get(d['questionId'])
            if wq and wq.mastery == 'wrong':
                wq.mastery = 'mastered'
                mastered_ids.append(wq.id)
    # 错题本不再计分（2026-08-13 收紧规则），仅更新掌握状态。
    db.session.commit()
    return jsonify({
        'score': grading['score'],
        'totalScore': grading['totalScore'],
        'mastered': mastered_ids,
        'details': grading['details'],
    })


# ===========================================================================
# 课程评价（学完后评分 + 维度 + 反馈）
# ===========================================================================

@portal_bp.route('/courses/<course_id>/review', methods=['POST'])
@jwt_required()
def submit_course_review(course_id):
    """提交/更新课程评价。仅学完课程的员工可评。一人一课一评价（覆盖式）。

    body: {rating: 1-5, contentQuality?, clarity?, practicality?, comment?}
    """
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    course = db.session.get(Course, course_id)
    if not course:
        return jsonify({'error': '课程不存在'}), 404
    # 必须学完才能评价
    progress = employee_course_progress_map(emp.id, [course_id]).get(course_id)
    if not progress or not progress['isFinished']:
        return jsonify({'error': '请先完成课程学习后再评价'}), 403

    data = request.get_json() or {}
    rating = int(data.get('rating') or 0)
    if rating < 1 or rating > 5:
        return jsonify({'error': '评分需在 1-5 之间'}), 400

    # 覆盖式更新
    review = CourseReview.query.filter_by(course_id=course_id, employee_id=emp.id).first()
    if not review:
        review = CourseReview(id=str(uuid.uuid4()), course_id=course_id, employee_id=emp.id)
        db.session.add(review)
    review.rating = rating
    review.content_quality = int(data['contentQuality']) if data.get('contentQuality') else None
    review.clarity = int(data['clarity']) if data.get('clarity') else None
    review.practicality = int(data['practicality']) if data.get('practicality') else None
    review.comment = (data.get('comment') or '').strip() or None
    # 积分：提交课程评价
    from services.points import award_points
    award_points(emp.id, 'review_submitted', ref_id=course_id)
    db.session.commit()
    return jsonify(review.to_dict())


@portal_bp.route('/courses/<course_id>/review', methods=['GET'])
@jwt_required()
def get_my_course_review(course_id):
    """查看我对某课程的评价（用于编辑回填）。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    course = db.session.get(Course, course_id)
    if not course or not can_see_course(emp, course):
        return jsonify({'error': '无权限'}), 403
    review = CourseReview.query.filter_by(course_id=course_id, employee_id=emp.id).first()
    return jsonify(review.to_dict() if review else None)


@portal_bp.route('/courses/<course_id>/reviews', methods=['GET'])
@jwt_required()
def list_course_reviews(course_id):
    """查看某课程的所有评价 + 汇总。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    course = db.session.get(Course, course_id)
    if not course or not can_see_course(emp, course):
        return jsonify({'error': '无权限'}), 403
    from sqlalchemy import func
    reviews = CourseReview.query.filter_by(course_id=course_id).order_by(
        CourseReview.updated_at.desc()
    ).all()
    # 批量预加载评价人姓名（消除 to_dict 内逐条 self.employee 懒加载 N+1）
    emp_ids = {r.employee_id for r in reviews if r.employee_id}
    emp_name_map = {}
    if emp_ids:
        for eid, nm in Employee.query.filter(Employee.id.in_(emp_ids)).with_entities(Employee.id, Employee.name).all():
            emp_name_map[eid] = nm
    course_title = course.title
    # 汇总
    summary = {'count': len(reviews), 'avgRating': 0, 'avgContent': 0, 'avgClarity': 0, 'avgPracticality': 0}
    if reviews:
        summary['avgRating'] = round(sum(r.rating for r in reviews) / len(reviews), 1)
        dims = ['content_quality', 'clarity', 'practicality']
        keys = ['avgContent', 'avgClarity', 'avgPracticality']
        for dim, key in zip(dims, keys):
            vals = [getattr(r, dim) for r in reviews if getattr(r, dim)]
            summary[key] = round(sum(vals) / len(vals), 1) if vals else 0
    out = []
    for r in reviews:
        d = r.to_dict()
        d['employeeName'] = emp_name_map.get(r.employee_id)
        d['courseTitle'] = course_title
        out.append(d)
    return jsonify({
        'summary': summary,
        'reviews': out,
    })


# ===========================================================================
# 胜任力测评（员工自评 + 看短板推荐）
# ===========================================================================

@portal_bp.route('/competency/models', methods=['GET'])
@jwt_required()
def available_competency_models():
    """可用的胜任力模型列表（员工选做测评）。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    models = CompetencyModel.query.filter_by(status='active').all()
    # 批量预加载员工在各模型的最新测评（消除循环内逐模型 query 的 N+1）
    model_ids = [m.id for m in models]
    assess_map = {}
    if model_ids:
        rows = CompetencyAssessment.query.filter(
            CompetencyAssessment.employee_id == emp.id,
            CompetencyAssessment.model_id.in_(model_ids),
        ).order_by(CompetencyAssessment.created_at.desc()).all()
        for a in rows:
            # 取每个 model 的首条（已按 created_at desc）
            if a.model_id not in assess_map:
                assess_map[a.model_id] = a
    result = []
    for m in models:
        d = m.to_dict()
        a = assess_map.get(m.id)
        d['assessed'] = a is not None
        d['lastOverall'] = a.overall_score if a else None
        result.append(d)
    return jsonify(result)


@portal_bp.route('/competency/self-assess/<model_id>', methods=['POST'])
@jwt_required()
def self_assess_competency(model_id):
    """员工自评胜任力。body: {scores: {dimKey: level}}"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    model = CompetencyModel.query.get(model_id)
    if not model:
        return jsonify({'error': '模型不存在'}), 404
    data = request.get_json() or {}
    scores = data.get('scores') or {}

    # 算 gap + 短板（与管理员端同样逻辑）
    dims = model.dimensions or []
    gaps = {}
    for dim in dims:
        key = dim.get('key')
        required = int(dim.get('requiredLevel') or 0)
        actual = int(scores.get(key, 0) or 0)
        gaps[key] = max(0, required - actual)
    total_required = sum(int(d.get('requiredLevel') or 0) for d in dims)
    total_actual = sum(min(int(scores.get(d.get('key'), 0) or 0), int(d.get('requiredLevel') or 0)) for d in dims)
    overall = int(total_actual / total_required * 100) if total_required else 0
    weak = sorted([(d.get('key'), gaps[d.get('key')]) for d in dims if gaps.get(d.get('key'), 0) > 0], key=lambda x: -x[1])[:3]
    weakest = [k for k, _ in weak]

    existing = CompetencyAssessment.query.filter_by(employee_id=emp.id, model_id=model_id).first()
    a = existing or CompetencyAssessment(id=str(uuid.uuid4()), employee_id=emp.id, model_id=model_id)
    if not existing:
        db.session.add(a)
    a.scores = scores
    a.gaps = gaps
    a.overall_score = overall
    a.weakest_dims = weakest
    a.assessor = None  # 自评
    # 积分：完成胜任力测评
    from services.points import award_points
    award_points(emp.id, 'competency_assessed', ref_id=model_id)
    db.session.commit()
    return jsonify(a.to_dict(include_model=True))


@portal_bp.route('/competency/my-assessments', methods=['GET'])
@jwt_required()
def my_competency_assessments():
    """我的测评历史。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    rows = CompetencyAssessment.query.filter_by(employee_id=emp.id).order_by(
        CompetencyAssessment.created_at.desc()
    ).all()
    return jsonify([a.to_dict(include_model=True) for a in rows])


# ===========================================================================
# AI 课程学习助手（RAG 问答）
# ===========================================================================

@portal_bp.route('/courses/<course_id>/ask', methods=['POST'])
@jwt_required()
def ask_course_question(course_id):
    """员工针对课程内容向 AI 提问。body: {question}"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    course = db.session.get(Course, course_id)
    if not course or not can_see_course(emp, course):
        return jsonify({'error': '课程不存在或无权限'}), 404
    data = request.get_json() or {}
    question = (data.get('question') or '').strip()
    if not question or len(question) > 500:
        return jsonify({'error': '请输入 1-500 字的问题'}), 400

    try:
        assert_ai_resource_allowed(
            tenant_id=getattr(emp, 'tenant_id', None),
            user_id=get_jwt_identity(),
            resource_domain='training_ai',
            use_case='course_qa',
        )
    except AIResourceDenied as exc:
        return _ai_error_response(exc)

    from services.course_qa import answer_course_question
    result = answer_course_question(course_id, question)
    return jsonify(result)


# ===========================================================================
# 积分激励（我的积分 + 明细 + 排行榜）
# ===========================================================================

@portal_bp.route('/points/summary', methods=['GET'])
@jwt_required()
def my_points_summary():
    """我的积分汇总 + 明细 + 排名。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    from services.points import (
        get_employee_point_logs,
        get_employee_total_points,
        get_leaderboard,
        get_total_learners,
    )
    total = get_employee_total_points(emp.id)
    logs = get_employee_point_logs(emp.id, limit=20)
    board = get_leaderboard(limit=20)
    # 我的排名
    my_rank = next((r['rank'] for r in board if r['employeeId'] == emp.id), None)
    return jsonify({
        'totalPoints': total,
        'rank': my_rank,
        'employeeId': emp.id,
        'totalLearners': get_total_learners(),
        'logs': logs,
        'leaderboard': board[:10],
    })


# ===========================================================================
# 学习证书
# ===========================================================================

@portal_bp.route('/certificates', methods=['GET'])
@jwt_required()
def my_certificates():
    """我的证书列表。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    from models import Certificate
    certs = Certificate.query.filter_by(employee_id=emp.id).order_by(
        Certificate.issued_at.desc()
    ).all()
    return jsonify([c.to_dict() for c in certs])


@portal_bp.route('/certificates/<cert_id>', methods=['GET'])
@jwt_required()
def view_certificate(cert_id):
    """查看某张证书（员工自己的 或 凭 cert_no 公开验证）。"""
    from models import Certificate
    cert = db.session.get(Certificate, cert_id)
    if not cert:
        return jsonify({'error': '证书不存在'}), 404
    # 员工只能看自己的（管理员可看任意）
    emp = current_employee()
    user_id = get_jwt_identity()
    from models import User
    actor = db.session.get(User, user_id)
    if actor and actor.role in ('admin', 'hr_admin'):
        pass  # 管理员可查看任意
    elif not emp or emp.id != cert.employee_id:
        return jsonify({'error': '无权限'}), 403
    return jsonify(cert.to_dict())


@portal_bp.route('/certificates/verify/<cert_no>', methods=['GET'])
def verify_certificate(cert_no):
    """公开验证证书（无需登录，凭编号查真伪）。"""
    from models import Certificate
    cert = Certificate.query.filter_by(cert_no=cert_no).first()
    if not cert:
        return jsonify({'valid': False, 'error': '证书编号不存在'}), 404
    return jsonify({
        'valid': True,
        'certNo': cert.cert_no,
        'employeeName': cert.employee_name,
        'courseTitle': cert.course_title,
        'issuedAt': cert.issued_at.isoformat() if cert.issued_at else None,
    })


# ===========================================================================
# 课程讨论区（学习社区）
# ===========================================================================

@portal_bp.route('/courses/<course_id>/discussions', methods=['GET'])
@jwt_required()
def list_discussions(course_id):
    """课程讨论帖列表。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    from models import Discussion
    course = db.session.get(Course, course_id)
    if not course or not can_see_course(emp, course):
        return jsonify({'error': '无权限'}), 403
    posts = Discussion.query.filter_by(course_id=course_id).order_by(
        Discussion.is_pinned.desc(), Discussion.updated_at.desc()
    ).all()
    # 批量预加载发帖人姓名（消除 to_dict 内 self.employee 懒加载 N+1）
    emp_ids = {p.employee_id for p in posts if p.employee_id}
    emp_name_map = {}
    if emp_ids:
        for e in Employee.query.filter(Employee.id.in_(emp_ids)).with_entities(Employee.id, Employee.name).all():
            emp_name_map[e[0]] = e[1]
    out = []
    for p in posts:
        d = p.to_dict()
        d['employeeName'] = emp_name_map.get(p.employee_id)
        out.append(d)
    return jsonify(out)


@portal_bp.route('/courses/<course_id>/discussions', methods=['POST'])
@jwt_required()
def create_discussion(course_id):
    """发帖。body: {title, content}"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    from models import Discussion
    course = db.session.get(Course, course_id)
    if not course or not can_see_course(emp, course):
        return jsonify({'error': '无权限'}), 403
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    if not title or not content:
        return jsonify({'error': '标题和内容不能为空'}), 400
    post = Discussion(
        id=str(uuid.uuid4()), course_id=course_id, employee_id=emp.id,
        title=title[:200], content=content,
    )
    db.session.add(post)
    # 积分：发帖奖励（复用 review 的 5 分规则避免新增）
    db.session.commit()
    return jsonify(post.to_dict())


@portal_bp.route('/discussions/<post_id>', methods=['GET'])
@jwt_required()
def get_discussion(post_id):
    """查看帖子详情（含回复）。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    post = Discussion.query.get(post_id)
    if not post:
        return jsonify({'error': '帖子不存在'}), 404
    course = db.session.get(Course, post.course_id)
    if not course or not can_see_course(emp, course):
        return jsonify({'error': '无权限'}), 403
    # 预加载发帖人姓名（消除 to_dict 内 self.employee 懒加载；回复人姓名在 include_replies 内批量取）
    post_name_map = {}
    if post.employee_id:
        row = Employee.query.filter_by(id=post.employee_id).with_entities(Employee.name).first()
        if row:
            post_name_map[post.employee_id] = row[0]
    return jsonify(post.to_dict(include_replies=True, name_map=post_name_map))


@portal_bp.route('/discussions/<post_id>/replies', methods=['POST'])
@jwt_required()
def reply_discussion(post_id):
    """回复帖子。body: {content}"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    from models import Discussion, DiscussionReply
    post = Discussion.query.get(post_id)
    if not post:
        return jsonify({'error': '帖子不存在'}), 404
    course = db.session.get(Course, post.course_id)
    if not course or not can_see_course(emp, course):
        return jsonify({'error': '无权限'}), 403
    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'error': '回复内容不能为空'}), 400
    reply = DiscussionReply(
        id=str(uuid.uuid4()), discussion_id=post_id, employee_id=emp.id,
        content=content,
    )
    db.session.add(reply)
    post.reply_count = (post.reply_count or 0) + 1
    post.updated_at = datetime.utcnow()
    # 通知帖主（回复者不是帖主时）
    if post.employee_id != emp.id:
        from services.training_notify import notify_employee
        notify_employee(post.employee_id, f'{emp.name} 回复了你的帖子',
                        f'「{post.title}」有新回复：{content[:50]}',
                        notice_type='discussion', link_url=f'/portal/course/{post.course_id}')
    db.session.commit()
    return jsonify(reply.to_dict())


@portal_bp.route('/discussions/like', methods=['POST'])
@jwt_required()
def toggle_like():
    """点赞/取消赞。body: {targetType: post|reply, targetId}

    去重一致性：DiscussionLike 表有 UniqueConstraint(employee_id, target_type, target_id)，
    数据库层保证不会产生重复点赞记录。并发竞态下第二个插入会触发 IntegrityError，
    此处捕获后回滚并视为"已点赞"返回（幂等），避免 500。
    """
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    from models import Discussion, DiscussionReply, DiscussionLike
    from sqlalchemy.exc import IntegrityError
    data = request.get_json() or {}
    target_type = data.get('targetType')
    target_id = data.get('targetId')
    if target_type not in ('post', 'reply') or not target_id:
        return jsonify({'error': '参数错误'}), 400
    existing = DiscussionLike.query.filter_by(
        employee_id=emp.id, target_type=target_type, target_id=target_id
    ).first()
    if existing:
        # 取消赞
        db.session.delete(existing)
        if target_type == 'post':
            p = Discussion.query.get(target_id)
            if p: p.like_count = max(0, (p.like_count or 0) - 1)
        else:
            r = DiscussionReply.query.get(target_id)
            if r: r.like_count = max(0, (r.like_count or 0) - 1)
        liked = False
    else:
        db.session.add(DiscussionLike(
            id=str(uuid.uuid4()), employee_id=emp.id,
            target_type=target_type, target_id=target_id,
        ))
        if target_type == 'post':
            p = Discussion.query.get(target_id)
            if p: p.like_count = (p.like_count or 0) + 1
        else:
            r = DiscussionReply.query.get(target_id)
            if r: r.like_count = (r.like_count or 0) + 1
        liked = True
    try:
        db.session.commit()
    except IntegrityError:
        # 并发竞态：另一个请求已插入相同点赞记录
        db.session.rollback()
        liked = True  # 视为已点赞（幂等）
    return jsonify({'liked': liked})


# ===========================================================================
# 站内通知（培训相关）
# ===========================================================================

@portal_bp.route('/notifications', methods=['GET'])
@jwt_required()
def my_notifications():
    """我的培训通知。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    from models import Notification
    rows = Notification.query.filter_by(employee_id=emp.id).order_by(
        Notification.created_at.desc()
    ).limit(30).all()
    unread = Notification.query.filter_by(employee_id=emp.id, status='unread').count()
    return jsonify({'items': [n.to_dict() for n in rows], 'unreadCount': unread})


@portal_bp.route('/notifications/<nid>/read', methods=['POST'])
@jwt_required()
def mark_notification_read(nid):
    """标记通知已读。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    from models import Notification
    n = Notification.query.get(nid)
    if not n:
        return jsonify({'error': '通知不存在'}), 404
    if n.employee_id != emp.id:
        return jsonify({'error': '无权限'}), 403
    n.status = 'read'
    n.read_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'id': nid, 'status': 'read'})


@portal_bp.route('/notifications/read-all', methods=['POST'])
@jwt_required()
def read_all_notifications():
    """全部标记已读。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    from models import Notification
    Notification.query.filter_by(employee_id=emp.id, status='unread').update(
        {'status': 'read', 'read_at': datetime.utcnow()}
    )
    db.session.commit()
    return jsonify({'read': 'all'})


# ===========================================================================
# 团队 PK 竞赛（员工看活跃赛季排行）
# ===========================================================================

@portal_bp.route('/pk-seasons/active', methods=['GET'])
@jwt_required()
def active_pk_seasons():
    """当前活跃的 PK 赛季列表 + 排行（员工视角）。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    now = datetime.utcnow()
    seasons = PKSeason.query.filter_by(status='active').all()

    # === 批量预加载：所有员工按部门分组（消除赛季循环内的逐部门查员工 N+1）===
    all_emps = Employee.query.filter(Employee.status.in_(['active', 'pending_onboard', 'probation'])).all()
    emp_by_dept = {}
    for e in all_emps:
        emp_by_dept.setdefault(e.department_id, []).append(e)

    # === 批量预加载所有部门（消除循环内重复 Department.query 的 N+1）===
    all_depts = {d.id: d for d in Department.query.all()}
    all_dept_ids = set(all_depts.keys())

    result = []
    for s in seasons:
        from services.points import get_points_by_employee
        emp_points = get_points_by_employee(s.start_date, s.end_date)

        # 复用预加载的部门字典（按赛季参赛部门过滤）
        dept_ids = all_dept_ids if not s.participant_dept_ids else set(s.participant_dept_ids or [])
        depts = [all_depts[did] for did in dept_ids if did in all_depts]
        board = []
        my_dept_rank = None
        my_dept_id = emp.department_id
        for d in depts:
            dept_emps = emp_by_dept.get(d.id, [])
            emp_ids = [e.id for e in dept_emps]
            total = sum(emp_points.get(eid, 0) for eid in emp_ids)
            avg = round(total / len(emp_ids), 1) if emp_ids else 0
            score = total if s.metric == 'total_points' else avg
            board.append({'deptId': d.id, 'deptName': d.name, 'memberCount': len(emp_ids),
                          'totalPoints': total, 'avgPoints': avg, 'score': score})
        board.sort(key=lambda x: -x['score'])
        for i, t in enumerate(board):
            t['rank'] = i + 1
            if t['deptId'] == my_dept_id:
                my_dept_rank = i + 1

        my_points = emp_points.get(emp.id, 0)
        result.append({
            'seasonId': s.id, 'name': s.name, 'description': s.description,
            'startDate': s.start_date.isoformat(), 'endDate': s.end_date.isoformat(),
            'metric': s.metric,
            'teamBoard': board,
            'myDeptRank': my_dept_rank,
            'myPoints': my_points,
        })
    return jsonify(result)


# ===========================================================================
# 积分商城（兑换奖品 + 我的兑换记录）
# ===========================================================================

@portal_bp.route('/rewards', methods=['GET'])
@jwt_required()
def list_rewards():
    """积分商城商品列表。"""
    from models import Reward
    rewards = Reward.query.filter_by(is_active=True).order_by(Reward.points_cost.asc()).all()
    # 附带员工当前积分
    emp, err = require_employee()
    from services.points import get_employee_total_points
    my_points = get_employee_total_points(emp.id) if emp else 0
    return jsonify({
        'items': [r.to_dict() for r in rewards],
        'myPoints': my_points,
    })


@portal_bp.route('/rewards/<reward_id>/exchange', methods=['POST'])
@jwt_required()
def exchange_reward(reward_id):
    """兑换商品（扣分 + 库存-1 + 记录）。

    并发安全：对 reward 行加 FOR UPDATE 行锁，防止超卖（两个请求同时通过库存检查）。
    """
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    from models import Reward, ExchangeRecord
    from services.points import get_employee_total_points
    import uuid as _uuid
    # 行锁：防止并发兑换导致库存超卖 / 积分超扣
    reward = Reward.query.with_for_update().get(reward_id)
    if not reward or not reward.is_active:
        return jsonify({'error': '商品不存在或已下架'}), 404
    if reward.stock != -1 and reward.stock <= 0:
        return jsonify({'error': '库存不足'}), 400
    my_points = get_employee_total_points(emp.id)
    if my_points < reward.points_cost:
        return jsonify({'error': f'积分不足，需要 {reward.points_cost}，当前 {my_points}'}), 400

    record_id = str(_uuid.uuid4())
    # 扣分使用兑换记录 id 作为业务流水，允许同一商品按库存重复兑换。
    from models import PointLog
    db.session.add(PointLog(
        id=str(_uuid.uuid4()), employee_id=emp.id,
        action='reward_exchange', points=-reward.points_cost,
        ref_id=record_id, detail=f'兑换：{reward.name}',
    ))
    # 库存
    if reward.stock != -1:
        reward.stock -= 1
    reward.exchanged_count = (reward.exchanged_count or 0) + 1
    # 兑换码（虚拟奖品自动生成）
    code = None
    if reward.reward_type == 'virtual':
        code = f'RDM-{_uuid.uuid4().hex[:8].upper()}'
    # 记录
    record = ExchangeRecord(
        id=record_id, employee_id=emp.id,
        reward_id=reward_id, reward_name=reward.name,
        points_cost=reward.points_cost,
        redeem_code=code,
    )
    db.session.add(record)
    # 通知
    from services.training_notify import notify_employee
    notify_employee(emp.id, f'兑换成功：{reward.name}',
                    f'您用 {reward.points_cost} 积分兑换了「{reward.name}」' +
                    (f'，兑换码：{code}' if code else ''),
                    notice_type='reward')
    db.session.commit()
    return jsonify({
        'success': True,
        'record': record.to_dict(),
        'remainingPoints': my_points - reward.points_cost,
    })


@portal_bp.route('/exchange-records', methods=['GET'])
@jwt_required()
def my_exchange_records():
    """我的兑换记录。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    from models import ExchangeRecord
    records = ExchangeRecord.query.filter_by(employee_id=emp.id).order_by(
        ExchangeRecord.created_at.desc()
    ).all()
    return jsonify([r.to_dict() for r in records])


@portal_bp.route('/export/my-report', methods=['GET'])
@jwt_required()
def export_my_report():
    """员工导出自己的学习总结 PDF。"""
    emp, err = require_employee()
    if err:
        return jsonify(err[0]), err[1]
    from services.pdf_report import generate_learning_report
    buf = generate_learning_report(emp.id)
    filename = f'学习总结_{emp.name}_{datetime.utcnow().strftime("%Y%m%d")}.pdf'
    from flask import send_file as _sf
    return _sf(buf, as_attachment=True, download_name=filename, mimetype='application/pdf')
