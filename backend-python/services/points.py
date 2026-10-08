"""积分奖励服务：在各学习行为发生时自动发放积分（去重）。"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.exc import IntegrityError

from models import POINT_RULES, Employee, PointLog, db

logger = logging.getLogger('hengpintong.points')

EXAM_POINT_ACTIONS = {'exam_attempted', 'exam_passed'}


def _exam_reference_map(logs):
    """Map legacy attempt/paper refs to the stable exam task identity."""
    from models import ExamAssignment, ExamAttempt, ExamPaper, ExamTask

    refs = {
        log.ref_id for log in logs
        if log.action in EXAM_POINT_ACTIONS and log.ref_id
    }
    if not refs:
        return {}

    tasks = ExamTask.query.filter(ExamTask.id.in_(refs)).all()
    task_map = {task.id: task for task in tasks}
    attempts = ExamAttempt.query.filter(ExamAttempt.id.in_(refs)).all()
    attempt_map = {attempt.id: attempt for attempt in attempts}
    assignment_ids = {attempt.assignment_id for attempt in attempts if attempt.assignment_id}
    assignments = (
        ExamAssignment.query.filter(ExamAssignment.id.in_(assignment_ids)).all()
        if assignment_ids else []
    )
    assignment_map = {assignment.id: assignment for assignment in assignments}
    task_ids = {
        attempt.task_id for attempt in attempts if attempt.task_id
    }
    task_ids.update(
        assignment.task_id for assignment in assignments if assignment.task_id
    )
    missing_task_ids = task_ids - set(task_map)
    if missing_task_ids:
        for task in ExamTask.query.filter(ExamTask.id.in_(missing_task_ids)).all():
            task_map[task.id] = task

    paper_ids = {
        attempt.paper_id for attempt in attempts if attempt.paper_id
    }
    paper_ids.update(task.paper_id for task in task_map.values() if task.paper_id)
    paper_ids.update(refs - set(task_map) - set(attempt_map))
    papers = ExamPaper.query.filter(ExamPaper.id.in_(paper_ids)).all() if paper_ids else []
    paper_map = {paper.id: paper for paper in papers}

    result = {}
    for ref_id in refs:
        task = task_map.get(ref_id)
        paper = paper_map.get(ref_id)
        attempt = attempt_map.get(ref_id)
        if attempt:
            assignment = assignment_map.get(attempt.assignment_id)
            task_id = attempt.task_id or (assignment.task_id if assignment else None)
            task = task_map.get(task_id) if task_id else None
            paper_id = attempt.paper_id or (task.paper_id if task else None)
            paper = paper_map.get(paper_id) if paper_id else None
        canonical_ref = task.id if task else (paper.id if paper else ref_id)
        title = task.title if task else (paper.title if paper else None)
        result[ref_id] = {'refId': canonical_ref, 'title': title}
    return result


def _summarize_logs(logs):
    exam_refs = _exam_reference_map(logs)
    totals = {}
    seen_awards = set()
    for log in logs:
        if log.action == 'wrong_question_mastered':
            # 错题本不再计分：历史「掌握错题」日志不参与任何积分汇总。
            continue
        summary = totals.setdefault(log.employee_id, {'total': 0, 'last': None})
        if log.action in POINT_RULES:
            canonical_ref = exam_refs.get(log.ref_id, {}).get('refId', log.ref_id or '')
            key = (log.employee_id, log.action, canonical_ref)
            if key in seen_awards:
                continue
            seen_awards.add(key)
        summary['total'] += int(log.points or 0)
        if log.created_at and (summary['last'] is None or log.created_at > summary['last']):
            summary['last'] = log.created_at
    return totals, exam_refs


def award_points(employee_id: str, action: str, ref_id: str = '',
                 detail: Optional[str] = None) -> bool:
    """发放积分。同 action+ref_id 只奖一次（去重）。

    返回 True=本次发放成功，False=已发过（重复行为）。
    """
    if action == 'wrong_question_mastered':
        # 错题本不再计分（2026-08-13 收紧规则，防止故意考砸后刷错题积分）。
        logger.info('wrong_question_mastery_disabled', extra={
            'employee': employee_id, 'ref': ref_id or '',
        })
        return False
    if action not in POINT_RULES:
        logger.warning('unknown_point_action', extra={'action': action})
        return False
    ref_id = ref_id or ''
    # 去重检查
    existing = PointLog.query.filter_by(
        employee_id=employee_id, action=action, ref_id=ref_id
    ).first()
    if existing:
        return False
    points = POINT_RULES[action]
    try:
        with db.session.begin_nested():
            log = PointLog(
                id=str(__import__('uuid').uuid4()),
                employee_id=employee_id, action=action, points=points,
                ref_id=ref_id, detail=detail,
            )
            db.session.add(log)
            db.session.flush()
    except IntegrityError:
        # 并发请求可能同时通过上面的查询，唯一约束是最终幂等边界。
        return False
    logger.info('point_awarded', extra={
        'employee': employee_id, 'action': action, 'points': points,
    })
    return True


def get_employee_total_points(employee_id: str) -> int:
    """员工累计积分，历史奖励日志按业务对象去重。"""
    logs = PointLog.query.filter_by(employee_id=employee_id).all()
    totals, _exam_refs = _summarize_logs(logs)
    return totals.get(employee_id, {}).get('total', 0)


def get_points_by_employee(start_at=None, end_at=None):
    """Return de-duplicated point totals keyed by employee for an optional period."""
    query = PointLog.query
    if start_at is not None:
        query = query.filter(PointLog.created_at >= start_at)
    if end_at is not None:
        query = query.filter(PointLog.created_at <= end_at)
    totals, _exam_refs = _summarize_logs(query.all())
    return {employee_id: summary['total'] for employee_id, summary in totals.items()}


def get_leaderboard(limit: int = 10):
    """积分排行榜 Top N。返回 [{employeeId, employeeName, totalPoints, rank}]"""
    from models import Department

    totals, _exam_refs = _summarize_logs(PointLog.query.all())

    rows = sorted(
        totals.items(),
        key=lambda item: (-item[1]['total'], item[0]),
    )[:limit]
    result = []
    for i, (emp_id, summary) in enumerate(rows):
        emp = Employee.query.get(emp_id)
        dept_name = None
        if emp and emp.department_id:
            dept = Department.query.get(emp.department_id)
            dept_name = dept.name if dept else None
        result.append({
            'rank': i + 1,
            'employeeId': emp_id,
            'employeeName': emp.name if emp else None,
            'department': dept_name,
            'totalPoints': summary['total'],
            'lastAwardAt': summary['last'].isoformat() if summary['last'] else None,
        })
    return result


def get_total_learners() -> int:
    """返回存在积分记录的员工数。"""
    return db.session.query(PointLog.employee_id).distinct().count()


def get_employee_point_logs(employee_id: str, limit: int = 20):
    """员工积分明细，隐藏历史重复奖励并补齐考试名称。"""
    logs = PointLog.query.filter_by(employee_id=employee_id).order_by(
        PointLog.created_at.desc()
    ).all()
    exam_refs = _exam_reference_map(logs)
    unique_logs = []
    seen_awards = set()
    for log in logs:
        if log.action == 'wrong_question_mastered':
            # 错题本不再计分：明细中不再展示「掌握错题」条目。
            continue
        if log.action in POINT_RULES:
            canonical_ref = exam_refs.get(log.ref_id, {}).get('refId', log.ref_id or '')
            key = (log.action, canonical_ref)
            if key in seen_awards:
                continue
            seen_awards.add(key)
        unique_logs.append(log)
        if len(unique_logs) >= limit:
            break

    result = []
    for log in unique_logs:
        item = log.to_dict()
        exam_ref = exam_refs.get(log.ref_id)
        if exam_ref:
            item['refId'] = exam_ref['refId']
            item['detail'] = item['detail'] or exam_ref['title']
        result.append(item)
    return result
