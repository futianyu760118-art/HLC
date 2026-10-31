from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from flask import Flask

from models import (
    AttendanceTimesheet,
    Department,
    Employee,
    PerformanceReview,
    PerformanceReviewItem,
    PerformanceScoreRule,
    Tenant,
    db,
)
from services.attendance_summary import monthly_summary
from services.performance_scoring import auto_score_review, collect_employee_month


@pytest.fixture()
def scoring_app():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        db.session.add(Tenant(id='tenant-1', slug='t1', name='T1', status='active'))
        db.session.add(Department(id='dept-1', tenant_id='tenant-1', name='销售中心', status='active'))
        db.session.add(Employee(
            id='emp-1', tenant_id='tenant-1', employee_no='3', name='沈旭日',
            status='active', department_id='dept-1', job_title='副总', employee_type='后勤',
        ))
        rows = []
        cursor = date(2026, 9, 1)
        for _ in range(20):
            rows.append(AttendanceTimesheet(
                id=str(uuid.uuid4()), tenant_id='tenant-1', employee_id='emp-1',
                department_id='dept-1', work_date=cursor, status='normal',
                work_hours=Decimal('8.00'), check_in=datetime(2026, 9, 1, 8, 0),
                check_out=datetime(2026, 9, 1, 17, 0),
            ))
            cursor += timedelta(days=1)
        for _ in range(2):
            rows.append(AttendanceTimesheet(
                id=str(uuid.uuid4()), tenant_id='tenant-1', employee_id='emp-1',
                department_id='dept-1', work_date=cursor, status='absent', work_hours=Decimal('0'),
            ))
            cursor += timedelta(days=1)
        rows.append(AttendanceTimesheet(
            id=str(uuid.uuid4()), tenant_id='tenant-1', employee_id='emp-1',
            department_id='dept-1', work_date=cursor, status='missing_card', work_hours=Decimal('4.00'),
        ))
        db.session.add_all(rows)

        review = PerformanceReview(
            id='review-1', tenant_id='tenant-1', employee_id='emp-1', status='draft',
        )
        db.session.add(review)
        db.session.add(PerformanceReviewItem(
            id='item-1', tenant_id='tenant-1', review_id='review-1',
            indicator_code='ind1', indicator_name='考勤纪律', weight=10, sort_order=1,
        ))
        db.session.add(PerformanceScoreRule(
            id='rule-1', tenant_id='tenant-1', indicator_code='ind1',
            data_source='attendance', metric='missingCardDays', operator='<=', threshold=1,
            score=10, weight=10, status='active',
        ))
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_monthly_summary_aggregates_statuses(scoring_app):
    with scoring_app.app_context():
        rows = monthly_summary('tenant-1', '2026-09')
        assert len(rows) == 1
        row = rows[0]
        assert row['employeeName'] == '沈旭日'
        assert row['expectedDays'] == 23
        assert row['normalDays'] == 20
        assert row['missingCardDays'] == 1
        assert row['absentDays'] == 2
        assert row['presentDays'] == 21
        assert row['workHours'] == 164.0
        assert row['attendanceRate'] == round(21 / 23, 4)


def test_auto_score_uses_rules_and_attendance_data(scoring_app):
    with scoring_app.app_context():
        data = collect_employee_month('tenant-1', 'emp-1', '2026-09')
        assert data['attendance']['missingCardDays'] == 1

        result = auto_score_review(
            'review-1', tenant_id='tenant-1', month='2026-09', use_ai=False,
        )
        db.session.commit()

        assert result['scoredItems'] == 1
        assert result['autoScore'] == 10.0

        item = db.session.get(PerformanceReviewItem, 'item-1')
        assert float(item.auto_score) == 10.0
        assert '数据来源' in (item.comment or '')

        review = db.session.get(PerformanceReview, 'review-1')
        assert float(review.auto_score) == 10.0


def test_auto_score_missing_review_raises(scoring_app):
    with scoring_app.app_context():
        with pytest.raises(LookupError):
            auto_score_review('nope', tenant_id='tenant-1', month='2026-09')


def test_effective_threshold_prefers_oa_monthly(monkeypatch):
    from decimal import Decimal as D
    from types import SimpleNamespace
    from services.performance_scoring import _effective_threshold
    import services.oa_monthly_targets as targets

    monkeypatch.setattr(targets, 'fetch_month_target', lambda dept, month: D('274.00'))
    rule = SimpleNamespace(
        target_source='oa_monthly', target_oa_department_id='37',
        threshold=D('500000'), metric='orderAmount',
    )
    threshold, note = _effective_threshold(rule, '2026-09')
    assert threshold == 2740000.0
    assert 'OA' in note

    rule_fixed = SimpleNamespace(
        target_source='fixed', target_oa_department_id=None,
        threshold=D('500000'), metric='orderAmount',
    )
    threshold, note = _effective_threshold(rule_fixed, '2026-09')
    assert threshold == 500000.0


def test_rule_score_achievement_mode():
    from decimal import Decimal as D
    from types import SimpleNamespace
    from services.performance_scoring import _rule_score

    rule = SimpleNamespace(
        scoring_mode='achievement', score=D('15'), operator='>=',
        threshold=None, metric='orderAmount',
    )
    # 达成率 <60% → 0
    assert _rule_score(rule, 726357.69, 2740000.0) == 0.0
    # 达成率 =60% → 0.6 * 15 = 9
    assert _rule_score(rule, 1644000.0, 2740000.0) == 9.0
    # 达成率 =100% → 15
    assert _rule_score(rule, 2740000.0, 2740000.0) == 15.0
    # 远超 → 封顶 权重+10 = 25
    assert _rule_score(rule, 5000000.0, 2740000.0) == 25.0


def test_rule_score_threshold_mode_still_works():
    from decimal import Decimal as D
    from types import SimpleNamespace
    from services.performance_scoring import _rule_score

    rule = SimpleNamespace(
        scoring_mode='threshold', score=D('15'), operator='>=',
        threshold=D('500000'), metric='orderAmount',
    )
    assert _rule_score(rule, 600000.0, 500000.0) == 15.0
    assert _rule_score(rule, 400000.0, 500000.0) == 0.0

