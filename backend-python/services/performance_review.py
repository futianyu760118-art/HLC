"""绩效考核人工复核：详情读取、评分保存（按角色）、确认归档。

分数维度：
- self_score    本人自评
- manager_score 直属上级评分
- final_score   HR/管理员最终分（复核）
评分表最终分默认取各指标 final 求和，其次 manager，再次 auto。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from models import (
    AttendanceTimesheet,
    Employee,
    OperationLog,
    PerformanceReview,
    PerformanceReviewItem,
    db,
)

SCORE_FIELDS = ('self_score', 'manager_score', 'final_score')
HR_ROLES = {'admin', 'hr_admin'}


class ReviewPermissionError(PermissionError):
    pass


def _decimal(value):
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise ValueError('分值必须是数字') from exc


def _grade(score) -> str | None:
    if score is None:
        return None
    value = float(score)
    if value >= 90:
        return 'A'
    if value >= 80:
        return 'B'
    if value >= 70:
        return 'C'
    if value >= 60:
        return 'D'
    return 'E'


def _actor_flags(review: PerformanceReview, *, role: str | None, actor_employee_id: str | None):
    is_hr = (role or '') in HR_ROLES
    is_self = bool(actor_employee_id) and actor_employee_id == review.employee_id
    is_manager = bool(actor_employee_id) and actor_employee_id == review.manager_id
    allowed = set()
    if is_hr:
        allowed.update(SCORE_FIELDS)
    if is_self:
        allowed.add('self_score')
    if is_manager:
        allowed.add('manager_score')
    return {'allowedFields': sorted(allowed), 'isHr': is_hr, 'isSelf': is_self, 'isManager': is_manager}


def get_review_detail(
    review_id: str,
    tenant_id: str,
    *,
    role: str | None = None,
    actor_employee_id: str | None = None,
) -> dict | None:
    review = PerformanceReview.query.filter_by(id=review_id, tenant_id=tenant_id).first()
    if review is None:
        return None
    items = PerformanceReviewItem.query.filter_by(review_id=review.id).order_by(
        PerformanceReviewItem.sort_order
    ).all()
    employee = db.session.get(Employee, review.employee_id) if review.employee_id else None
    manager = db.session.get(Employee, review.manager_id) if review.manager_id else None
    detail = review.to_dict()
    detail['items'] = [item.to_dict() for item in items]
    detail['employeeName'] = employee.name if employee else None
    detail['managerName'] = manager.name if manager else None
    detail['permissions'] = _actor_flags(review, role=role, actor_employee_id=actor_employee_id)
    return detail


def save_scores(
    review_id: str,
    tenant_id: str,
    payload: dict,
    *,
    role: str | None = None,
    actor_employee_id: str | None = None,
    actor_user_id: str | None = None,
) -> dict:
    review = PerformanceReview.query.filter_by(id=review_id, tenant_id=tenant_id).first()
    if review is None:
        raise LookupError('REVIEW_NOT_FOUND')
    flags = _actor_flags(review, role=role, actor_employee_id=actor_employee_id)
    allowed = set(flags['allowedFields'])
    if not allowed:
        raise ReviewPermissionError('无权评分')

    items = PerformanceReviewItem.query.filter_by(review_id=review.id).all()
    by_id = {item.id: item for item in items}
    changes = []
    for entry in payload.get('items') or []:
        item = by_id.get(str(entry.get('id')))
        if item is None:
            continue
        for field, key in (('self_score', 'selfScore'), ('manager_score', 'managerScore'), ('final_score', 'finalScore')):
            if key not in entry:
                continue
            if field not in allowed:
                raise ReviewPermissionError(f'无权修改 {field}')
            new_value = _decimal(entry.get(key))
            old_value = getattr(item, field)
            if new_value == old_value:
                continue
            setattr(item, field, new_value)
            item.updated_at = datetime.utcnow()
            changes.append({
                'itemId': item.id, 'indicator': item.indicator_name,
                'field': field,
                'from': float(old_value) if old_value is not None else None,
                'to': float(new_value) if new_value is not None else None,
            })

    _recompute_review(review, items)
    if 'self_score' in allowed:
        review.self_submitted_at = datetime.utcnow()
    if 'manager_score' in allowed:
        review.manager_scored_at = datetime.utcnow()
    review.updated_at = datetime.utcnow()

    if changes:
        db.session.add(OperationLog(
            id=_uuid(),
            tenant_id=tenant_id,
            user_id=actor_user_id,
            module='performance',
            action='review_score',
            target_id=review.id,
            detail={'changes': changes},
        ))
    db.session.flush()
    return {'reviewId': review.id, 'changes': changes, 'autoScore': _f(review.auto_score),
            'managerScore': _f(review.manager_score), 'finalScore': _f(review.final_score),
            'grade': review.grade}


def confirm_review(
    review_id: str,
    tenant_id: str,
    payload: dict,
    *,
    role: str | None = None,
    actor_user_id: str | None = None,
) -> dict:
    if (role or '') not in HR_ROLES:
        raise ReviewPermissionError('只有 HR/管理员可以确认考核结果')
    review = PerformanceReview.query.filter_by(id=review_id, tenant_id=tenant_id).first()
    if review is None:
        raise LookupError('REVIEW_NOT_FOUND')
    items = PerformanceReviewItem.query.filter_by(review_id=review.id).all()
    _recompute_review(review, items)
    override = _decimal(payload.get('finalScore'))
    if override is not None:
        review.final_score = override
        review.grade = _grade(override)
    review.remark = payload.get('remark') if payload.get('remark') is not None else review.remark
    review.status = 'confirmed'
    review.confirmed_at = datetime.utcnow()
    review.updated_at = datetime.utcnow()
    db.session.add(OperationLog(
        id=_uuid(),
        tenant_id=tenant_id,
        user_id=actor_user_id,
        module='performance',
        action='review_confirm',
        target_id=review.id,
        detail={'finalScore': _f(review.final_score), 'grade': review.grade},
    ))
    db.session.flush()
    return {'reviewId': review.id, 'finalScore': _f(review.final_score), 'grade': review.grade,
            'status': review.status}


def _recompute_review(review: PerformanceReview, items: list) -> None:
    def total(field):
        values = [getattr(item, field) for item in items if getattr(item, field) is not None]
        return sum(values, Decimal('0')) if values else None

    self_total = total('self_score')
    manager_total = total('manager_score')
    final_total = total('final_score')
    if self_total is not None:
        review.self_score = self_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if manager_total is not None:
        review.manager_score = manager_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    effective = final_total if final_total is not None else (manager_total if manager_total is not None else review.auto_score)
    if effective is not None:
        review.final_score = Decimal(effective).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        review.grade = _grade(effective)


def _f(value):
    return float(value) if value is not None else None


def _uuid() -> str:
    import uuid as _uuid_module

    return str(_uuid_module.uuid4())
