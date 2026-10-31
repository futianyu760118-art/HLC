"""考核指标基础资料维护（新增/修改，含取数规则）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from models import PerformanceIndicator, PerformanceScoreRule, db

VALID_METRICS = {
    'orderAmount', 'orderCount', 'workHours', 'presentDays',
    'expectedDays', 'absentDays', 'missingCardDays', 'attendanceRate',
    'grossMargin', 'grossProfit', 'salesAmount', 'costAmount',
    'newProductAmount', 'newProductCount',
}
VALID_OPERATORS = {'>=', '<=', '>', '<', '=='}


def _indicator_code(indicator: PerformanceIndicator) -> str:
    """指标编码用指标自身 ID，保证跨部门/岗位唯一。"""
    return indicator.id


def save_indicator(tenant_id: str, payload: dict, *, indicator_id: str | None = None) -> PerformanceIndicator:
    name = str(payload.get('name') or '').strip()
    if not name:
        raise ValueError('指标名称不能为空')

    seq_value = payload.get('seq')
    try:
        seq = int(seq_value) if seq_value not in (None, '') else None
    except (TypeError, ValueError) as exc:
        raise ValueError('序号必须是整数') from exc

    if indicator_id:
        row = PerformanceIndicator.query.filter_by(id=indicator_id, tenant_id=tenant_id).first()
        if row is None:
            raise LookupError('INDICATOR_NOT_FOUND')
    else:
        row = None

    if seq is None:
        max_seq = db.session.query(db.func.max(PerformanceIndicator.seq)).filter(
            PerformanceIndicator.tenant_id == tenant_id,
            PerformanceIndicator.department_name == payload.get('departmentName'),
            PerformanceIndicator.position_name == payload.get('positionName'),
        ).scalar()
        seq = int(max_seq or 0) + 1

    if row is None:
        row = PerformanceIndicator(id=str(uuid.uuid4()), tenant_id=tenant_id)
        db.session.add(row)

    row.department_name = payload.get('departmentName')
    row.position_name = payload.get('positionName')
    row.seq = seq
    row.name = name
    row.target_value = payload.get('targetValue')
    row.definition = payload.get('definition')
    row.scoring_rule = payload.get('scoringRule')
    row.weight = payload.get('weight')
    row.evaluator_department = payload.get('evaluatorDepartment')
    if 'linkedToSalary' in payload:
        row.linked_to_salary = bool(payload.get('linkedToSalary'))
    row.status = 'active'
    row.updated_at = datetime.utcnow()
    db.session.flush()

    _sync_rule(tenant_id, row, payload)
    return row


def _sync_rule(tenant_id: str, indicator: PerformanceIndicator, payload: dict) -> None:
    """按指标同步取数规则（未提供 metric 则删除该规则）。"""
    code = _indicator_code(indicator)
    metric = (str(payload.get('metric') or '').strip()) or None
    rule = PerformanceScoreRule.query.filter_by(
        tenant_id=tenant_id, indicator_code=code,
    ).first()

    if not metric:
        if rule is not None:
            db.session.delete(rule)
        return

    if metric not in VALID_METRICS:
        raise ValueError(f'不支持的数据指标：{metric}')
    operator = (str(payload.get('operator') or '>=').strip())
    if operator not in VALID_OPERATORS:
        raise ValueError(f'不支持的比较符：{operator}')

    if rule is None:
        rule = PerformanceScoreRule(
            id=str(uuid.uuid4()), tenant_id=tenant_id, indicator_code=code, status='active',
        )
        db.session.add(rule)

    rule.indicator_name = indicator.name
    rule.data_source = (str(payload.get('dataSource') or '').strip()) or 'system'
    rule.metric = metric
    rule.operator = operator
    rule.threshold = payload.get('threshold')
    rule.target_source = (str(payload.get('targetSource') or '').strip()) or 'fixed'
    rule.target_oa_department_id = (str(payload.get('targetOaDepartmentId') or '').strip()) or None
    scoring_mode = (str(payload.get('scoringMode') or '').strip()) or None
    if scoring_mode not in ('threshold', 'achievement'):
        scoring_mode = 'achievement' if '达成率' in (indicator.scoring_rule or '') else 'threshold'
    rule.scoring_mode = scoring_mode
    rule.score = payload.get('score') if payload.get('score') is not None else indicator.weight
    rule.weight = indicator.weight
    rule.status = 'active'
    rule.updated_at = datetime.utcnow()
