from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import Flask

from models import (
    Employee,
    PerformanceCycle,
    PerformanceReview,
    PerformanceReviewItem,
    PerformanceScoreRule,
    PerformanceTemplate,
    Tenant,
    db,
)


@pytest.fixture()
def perf_app():
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
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_performance_models_roundtrip(perf_app):
    with perf_app.app_context():
        employee = Employee(
            id=str(uuid.uuid4()), tenant_id='tenant-1', employee_no='A001',
            name='张三', status='active', employee_type='车间', performance_participant=True,
        )
        manager = Employee(
            id=str(uuid.uuid4()), tenant_id='tenant-1', employee_no='A002',
            name='李四', status='active', employee_type='后勤',
        )
        cycle = PerformanceCycle(
            id=str(uuid.uuid4()), tenant_id='tenant-1', name='2026-09', cycle_type='月度',
            start_date=date(2026, 9, 1), end_date=date(2026, 9, 30), status='draft',
        )
        template = PerformanceTemplate(
            id=str(uuid.uuid4()), tenant_id='tenant-1', name='车间通用', indicators=['出勤', '效率'],
        )
        db.session.add_all([employee, manager, cycle, template])
        db.session.flush()

        review = PerformanceReview(
            id=str(uuid.uuid4()), tenant_id='tenant-1', employee_id=employee.id,
            cycle_id=cycle.id, template_id=template.id, manager_id=manager.id,
            status='draft', auto_score=88,
        )
        db.session.add(review)
        db.session.flush()

        item = PerformanceReviewItem(
            id=str(uuid.uuid4()), tenant_id='tenant-1', review_id=review.id,
            indicator_code='attendance', indicator_name='出勤', weight=30,
            data_source='attendance', metric='late_count', auto_score=30,
        )
        rule = PerformanceScoreRule(
            id=str(uuid.uuid4()), tenant_id='tenant-1', indicator_code='attendance',
            indicator_name='出勤', data_source='attendance', metric='late_count',
            operator='<=', threshold=2, score=30, weight=30, status='active',
        )
        db.session.add_all([item, rule])
        db.session.commit()

        assert employee.to_dict()['employeeType'] == '车间'
        assert employee.to_dict()['performanceParticipant'] is True
        assert review.to_dict()['managerId'] == manager.id
        assert review.to_dict()['autoScore'] == 88.0
        assert item.to_dict()['indicatorCode'] == 'attendance'
        assert rule.to_dict()['threshold'] == 2.0
        assert cycle.to_dict()['tenantId'] == 'tenant-1'

        assert PerformanceReviewItem.query.filter_by(review_id=review.id).count() == 1
        assert PerformanceScoreRule.query.filter_by(indicator_code='attendance').count() == 1
