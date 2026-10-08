"""绩效考核取数与自动评分。

取数：从考勤月度汇总等来源收集员工当月数据。
评分：优先按可配置规则（PerformanceScoreRule）计算；可选调用 AI 生成分析。
"""

from __future__ import annotations

from datetime import datetime

from models import PerformanceReview, PerformanceReviewItem, PerformanceScoreRule, db
from services.attendance_summary import monthly_summary

OPERATORS = {
    '>=': lambda a, b: a >= b,
    '<=': lambda a, b: a <= b,
    '>': lambda a, b: a > b,
    '<': lambda a, b: a < b,
    '==': lambda a, b: a == b,
}

METRIC_LABELS = {
    'workHours': '月工时(小时)',
    'presentDays': '出勤天数',
    'expectedDays': '应出勤天数',
    'absentDays': '旷工天数',
    'missingCardDays': '缺卡天数',
    'attendanceRate': '出勤率',
    'orderAmount': '接单金额(ERP)',
    'orderCount': '订单数(ERP)',
    'grossMargin': '销售毛利率(ERP出库)',
    'grossProfit': '销售毛利额(ERP出库)',
    'salesAmount': '销售出库金额(ERP)',
    'costAmount': '销售出库成本(ERP)',
    'newProductAmount': '新产品接单金额(ERP)',
    'newProductCount': '新产品数(ERP)',
}

# 数据来源说明书（大白话，给业务看）
METRIC_SOURCE_NOTES = {
    'workHours': '数据来源：考勤月度汇总（OA排班 + 考勤机打卡自动计算出的当月工时合计）',
    'presentDays': '数据来源：考勤月度汇总（当月正常出勤 + 缺卡的天数）',
    'expectedDays': '数据来源：考勤月度汇总（当月按 OA 排班应出勤的天数）',
    'absentDays': '数据来源：考勤月度汇总（当月已排班但没有任何打卡的天数）',
    'missingCardDays': '数据来源：考勤月度汇总（当月打卡次数不齐的天数）',
    'attendanceRate': '数据来源：考勤月度汇总（出勤天数 ÷ 应出勤天数）',
    'orderAmount': '数据来源：金蝶ERP 当月已审核销售订单的金额合计',
    'orderCount': '数据来源：金蝶ERP 当月已审核销售订单的数量',
    'grossMargin': '数据来源：金蝶ERP 当月已审核销售出库（按出库口径，非接单口径）的(销售额-成本)/销售额',
    'grossProfit': '数据来源：金蝶ERP 当月已审核销售出库的销售额-成本',
    'salesAmount': '数据来源：金蝶ERP 当月已审核销售出库的销售额合计',
    'costAmount': '数据来源：金蝶ERP 当月已审核销售出库的成本合计',
    'newProductAmount': '数据来源：金蝶ERP 当月首次接单的新产品在当月的销售订单金额合计',
    'newProductCount': '数据来源：金蝶ERP 当月首次接单的新产品数量',
}


def collect_employee_month(tenant_id: str, employee_id: str, month: str) -> dict:
    """收集员工当月考核数据（考勤月度汇总 + K3 ERP 取数，ERP 失败不影响主流程）。"""
    rows = monthly_summary(tenant_id, month, employee_id=employee_id)
    attendance = rows[0] if rows else {}

    erp = None
    try:
        from services.k3_erp import fetch_order_amount, fetch_new_product_order_amount

        erp = fetch_order_amount(month)
        try:
            newp = fetch_new_product_order_amount(month)
            erp['newProductAmount'] = newp['amount']
            erp['newProductCount'] = newp['newProductCount']
        except Exception:
            pass
    except Exception:
        erp = None

    erp_margin = None
    try:
        from services.k3_erp import fetch_outbound_margin

        erp_margin = fetch_outbound_margin(month)
    except Exception:
        erp_margin = None

    return {
        'month': month,
        'attendance': {
            'workHours': attendance.get('workHours'),
            'presentDays': attendance.get('presentDays'),
            'expectedDays': attendance.get('expectedDays'),
            'absentDays': attendance.get('absentDays'),
            'missingCardDays': attendance.get('missingCardDays'),
            'attendanceRate': attendance.get('attendanceRate'),
        },
        'erp': erp,
        'erpMargin': erp_margin,
    }


def _metric_value(data: dict, metric: str):
    if not metric:
        return None
    if metric in data.get('attendance', {}):
        return data['attendance'][metric]
    if metric == 'orderAmount' and data.get('erp'):
        return data['erp'].get('amount')
    if metric == 'orderCount' and data.get('erp'):
        return data['erp'].get('orderCount')
    if metric in ('newProductAmount', 'newProductCount') and data.get('erp'):
        return data['erp'].get(metric)
    if metric in ('grossMargin', 'grossProfit', 'salesAmount', 'costAmount') and data.get('erpMargin'):
        return data['erpMargin'].get(metric)
    return None


def _effective_threshold(rule: PerformanceScoreRule, month: str):
    """返回 (阈值, 来源说明)。OA 月度目标优先于规则里的固定阈值。"""
    if (rule.target_source or 'fixed') == 'oa_monthly' and rule.target_oa_department_id:
        try:
            from services.oa_monthly_targets import fetch_month_target

            wan = fetch_month_target(rule.target_oa_department_id, month)
            if wan is not None:
                return float(wan) * 10000.0, f'OA月度目标(部门{rule.target_oa_department_id})={wan}万'
        except Exception:
            pass
    if rule.threshold is None:
        return None, '未设置目标值'
    return float(rule.threshold), '规则目标值'


def _dept_name_for_rule(rule: PerformanceScoreRule, tenant_id: str) -> str | None:
    """规则若用 OA 月度目标，则实际值也按同一部门（HRM 部门 code=OA-<id>）过滤。"""
    if (rule.target_source or 'fixed') == 'oa_monthly' and rule.target_oa_department_id:
        from models import Department

        dept = Department.query.filter_by(
            tenant_id=tenant_id, code=f'OA-{rule.target_oa_department_id}',
        ).first()
        if dept and dept.name:
            return dept.name
    return None


def _resolve_metric_value(rule: PerformanceScoreRule, data: dict, month: str, tenant_id: str, cache: dict):
    """取指标值；接单金额/新产品金额在指定部门时按 K3 部门过滤。"""
    metric = rule.metric
    dept_name = _dept_name_for_rule(rule, tenant_id)
    if dept_name and metric in ('orderAmount', 'newProductAmount'):
        key = (metric, dept_name, month)
        if key not in cache:
            try:
                from services.k3_erp import fetch_order_amount, fetch_new_product_order_amount

                if metric == 'orderAmount':
                    cache[key] = fetch_order_amount(month, dept_name=dept_name)['amount']
                else:
                    cache[key] = fetch_new_product_order_amount(month, dept_name=dept_name)['amount']
            except Exception:
                cache[key] = None
        return cache[key]
    return _metric_value(data, metric)


def _rule_score(rule: PerformanceScoreRule, value, threshold):
    if value is None or threshold is None or rule.score is None:
        return None
    try:
        numeric_value = float(value)
        numeric_threshold = float(threshold)
    except (TypeError, ValueError):
        return None
    weight_score = float(rule.score)

    if (rule.scoring_mode or 'threshold') == 'achievement':
        if numeric_threshold == 0:
            return None
        ratio = numeric_value / numeric_threshold
        if ratio < 0.6:
            return 0.0
        return round(min(ratio * weight_score, weight_score + 10), 2)

    operator = rule.operator or '>='
    compare = OPERATORS.get(operator)
    if compare is None:
        return None
    return weight_score if compare(numeric_value, numeric_threshold) else 0.0


def auto_score_review(
    review_id: str,
    *,
    tenant_id: str,
    month: str,
    use_ai: bool = False,
) -> dict:
    """对一张考核表自动取数并评分。"""
    review = PerformanceReview.query.filter_by(id=review_id, tenant_id=tenant_id).first()
    if review is None:
        raise LookupError('REVIEW_NOT_FOUND')

    data = collect_employee_month(tenant_id, review.employee_id, month)
    items = PerformanceReviewItem.query.filter_by(review_id=review.id).order_by(
        PerformanceReviewItem.sort_order
    ).all()

    rules = {
        rule.indicator_code: rule
        for rule in PerformanceScoreRule.query.filter_by(tenant_id=tenant_id, status='active').all()
    }

    scored = 0
    total = 0.0
    value_cache: dict = {}
    for item in items:
        rule = rules.get(item.indicator_code)
        if rule is None:
            item.comment = '未配置取数规则，需人工录入实际值后打分'
            continue
        threshold, target_note = _effective_threshold(rule, month)
        value = _resolve_metric_value(rule, data, month, tenant_id, value_cache)
        score = _rule_score(rule, value, threshold)
        source_note = METRIC_SOURCE_NOTES.get(rule.metric or '', '数据来源：系统取数')
        label = METRIC_LABELS.get(rule.metric or '', rule.metric or '')
        if score is None:
            item.auto_score = None
            if value is not None and threshold is None:
                item.comment = (
                    f'{source_note}；本次实际 {value}，但{target_note}，待补齐目标后自动评分'
                )
            elif value is not None:
                item.comment = f'{source_note}；已取到实际值 {value}，评分规则不完整，需人工确认'
            else:
                item.comment = f'{source_note}；但本次未取到数据，需人工确认'
            continue
        item.auto_score = score
        total += score
        scored += 1
        if (rule.scoring_mode or 'threshold') == 'achievement':
            ratio = (float(value) / float(threshold)) if threshold else 0.0
            weight_score = float(rule.score or 0)
            if score == 0:
                item.comment = (
                    f'{source_note}；本次实际 {value}，目标 {threshold}（{target_note}），'
                    f'达成率 {ratio * 100:.1f}% ＜60% → 0 分'
                )
            else:
                item.comment = (
                    f'{source_note}；本次实际 {value}，目标 {threshold}（{target_note}），'
                    f'达成率 {ratio * 100:.1f}% → 得分 {score}（达成率×权重{weight_score}，上限 {weight_score + 10}）'
                )
        else:
            achieved = '达标' if score > 0 else '未达标'
            item.comment = (
                f'{source_note}；本次实际 {value}，目标 {threshold}（{target_note}），'
                f'判定「{label} {rule.operator} {threshold}」→ {achieved}，得 {score} 分'
            )

    review.auto_score = round(total, 2)
    ai_used = False
    if use_ai:
        ai_text = _try_ai_analysis(review, items, data)
        if ai_text:
            review.result = ai_text
            ai_used = True

    review.updated_at = datetime.utcnow()
    return {
        'reviewId': review.id,
        'month': month,
        'scoredItems': scored,
        'totalItems': len(items),
        'autoScore': float(review.auto_score or 0),
        'aiUsed': ai_used,
        'data': data,
    }


def _try_ai_analysis(review, items, data) -> str | None:
    """可选：调用受控 AI 生成一段分析说明；失败则返回 None（不阻断）。"""
    try:
        from services.assistant_core import llm_client

        indicator_lines = '\n'.join(
            f"- {item.indicator_name}（权重{item.weight}，自动分{item.auto_score}）"
            for item in items
        )
        prompt = (
            f'请根据以下数据对员工做简要绩效分析（150字内，中文）：\n'
            f'员工：{review.employee.name if review.employee else ""}\n'
            f'周期：{data.get("month")}\n'
            f'考勤数据：{data.get("attendance")}\n'
            f'考核指标：\n{indicator_lines}\n'
        )
        result = llm_client.json_chat_profile(
            'standard',
            [
                {'role': 'system', 'content': '你是HR绩效分析助手，请输出简洁中文分析。'},
                {'role': 'user', 'content': prompt},
            ],
            temperature=0.3,
            max_tokens=500,
            timeout=30,
            use_case='performance_scoring',
            resource_domain='performance_ai',
        )
        if not result:
            return None
        if isinstance(result, dict):
            return result.get('analysis') or result.get('summary') or str(result)
        return str(result)
    except Exception:
        return None
