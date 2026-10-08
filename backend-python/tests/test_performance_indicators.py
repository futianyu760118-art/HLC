from __future__ import annotations

import uuid

import pytest
from flask import Flask

from models import (
    Department,
    Employee,
    PerformanceCycle,
    PerformanceIndicator,
    PerformanceReview,
    PerformanceReviewItem,
    Tenant,
    db,
)
from services.performance_indicators import (
    generate_reviews,
    indicators_for,
    replace_indicators,
)

SHEN_INDICATORS = [
    {'name': '接单金额', 'targetValue': '按月分解', 'scoringRule': '<60% 0分；≥60% 达成率×权重', 'weight': 15, 'evaluatorDepartment': '总经办'},
    {'name': '新产品开发接单金额达成', 'targetValue': '按月分解', 'scoringRule': '≥60% 达成率×权重', 'weight': 15, 'evaluatorDepartment': '总经办'},
    {'name': '销售毛利率', 'targetValue': '0.25', 'scoringRule': '≥60% 达成率×权重', 'weight': 15, 'evaluatorDepartment': '总经办'},
]


@pytest.fixture()
def indicator_app():
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
        db.session.add_all([
            Department(id='dept-sales1', tenant_id='tenant-1', name='销售一部', status='active'),
            Department(id='dept-fin', tenant_id='tenant-1', name='财务部', status='active'),
        ])
        db.session.add_all([
            Employee(
                id='emp-shen', tenant_id='tenant-1', employee_no='3', name='沈旭日',
                status='active', department_id='dept-sales1', job_title='副总',
                performance_participant=True,
            ),
            Employee(
                id='emp-hong', tenant_id='tenant-1', employee_no='595', name='洪香',
                status='active', department_id='dept-fin', job_title='财务经理',
                performance_participant=True,
            ),
            Employee(
                id='emp-not', tenant_id='tenant-1', employee_no='999', name='不考核',
                status='active', department_id='dept-sales1', job_title='副总',
                performance_participant=False,
            ),
        ])
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_replace_and_read_indicators(indicator_app):
    with indicator_app.app_context():
        assert replace_indicators(
            'tenant-1', department_name='销售一部', position_name='副总',
            indicators=SHEN_INDICATORS,
        ) == 3

        rows = indicators_for('tenant-1', '销售一部', '副总')
        assert [row.name for row in rows] == ['接单金额', '新产品开发接单金额达成', '销售毛利率']
        assert float(rows[0].weight) == 15.0
        assert rows[0].scoring_rule.startswith('<60%')

        # 再次导入应替换而不是追加
        replace_indicators(
            'tenant-1', department_name='销售一部', position_name='副总',
            indicators=SHEN_INDICATORS[:1],
        )
        assert PerformanceIndicator.query.filter_by(tenant_id='tenant-1').count() == 1


def test_generate_reviews_matches_department_and_position(indicator_app):
    with indicator_app.app_context():
        replace_indicators(
            'tenant-1', department_name='销售一部', position_name='副总',
            indicators=SHEN_INDICATORS,
        )

        result = generate_reviews('tenant-1', month='2026-09')

        assert result['created'] == 1
        assert result['withoutIndicators'] == ['洪香']

        review = PerformanceReview.query.filter_by(employee_id='emp-shen').one()
        assert review.tenant_id == 'tenant-1'
        assert review.status == 'draft'
        items = PerformanceReviewItem.query.filter_by(review_id=review.id).order_by(
            PerformanceReviewItem.sort_order
        ).all()
        assert [item.indicator_name for item in items] == [
            '接单金额', '新产品开发接单金额达成', '销售毛利率',
        ]
        assert sum(float(item.weight) for item in items) == 45.0

        # 不参与考核的员工不生成
        assert PerformanceReview.query.filter_by(employee_id='emp-not').count() == 0

        cycle = PerformanceCycle.query.filter_by(tenant_id='tenant-1', name='2026-09').one()
        assert review.cycle_id == cycle.id


def test_generate_reviews_is_idempotent(indicator_app):
    with indicator_app.app_context():
        replace_indicators(
            'tenant-1', department_name='销售一部', position_name='副总',
            indicators=SHEN_INDICATORS,
        )
        first = generate_reviews('tenant-1', month='2026-09')
        second = generate_reviews('tenant-1', month='2026-09')

        assert first['created'] == 1
        assert second['created'] == 0
        assert second['skipped'] == 1
        assert PerformanceReview.query.filter_by(employee_id='emp-shen').count() == 1
