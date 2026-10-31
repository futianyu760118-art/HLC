from __future__ import annotations

from decimal import Decimal

import pytest
from flask import Flask

from models import (
    Department,
    Employee,
    OperationLog,
    PerformanceReview,
    PerformanceReviewItem,
    Tenant,
    db,
)
from services.performance_review import (
    ReviewPermissionError,
    confirm_review,
    get_review_detail,
    save_scores,
)


@pytest.fixture()
def review_app():
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
        db.session.add_all([
            Employee(id='emp-self', tenant_id='tenant-1', employee_no='001', name='沈旭日',
                     status='active', department_id='dept-1', job_title='副总'),
            Employee(id='emp-mgr', tenant_id='tenant-1', employee_no='002', name='主管',
                     status='active', department_id='dept-1'),
        ])
        review = PerformanceReview(
            id='rev-1', tenant_id='tenant-1', employee_id='emp-self', manager_id='emp-mgr',
            status='draft', auto_score=Decimal('15'),
        )
        db.session.add(review)
        db.session.add_all([
            PerformanceReviewItem(id='item-1', tenant_id='tenant-1', review_id='rev-1',
                                  indicator_code='code-1', indicator_name='接单金额',
                                  weight=Decimal('15'), auto_score=Decimal('15'), sort_order=1),
            PerformanceReviewItem(id='item-2', tenant_id='tenant-1', review_id='rev-1',
                                  indicator_code='code-2', indicator_name='毛利率',
                                  weight=Decimal('15'), auto_score=Decimal('0'), sort_order=2),
        ])
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_detail_permissions_per_role(review_app):
    with review_app.app_context():
        hr = get_review_detail('rev-1', 'tenant-1', role='admin', actor_employee_id=None)
        assert set(hr['permissions']['allowedFields']) == {'self_score', 'manager_score', 'final_score'}

        self_view = get_review_detail('rev-1', 'tenant-1', role='employee', actor_employee_id='emp-self')
        assert self_view['permissions']['allowedFields'] == ['self_score']

        mgr_view = get_review_detail('rev-1', 'tenant-1', role='employee', actor_employee_id='emp-mgr')
        assert mgr_view['permissions']['allowedFields'] == ['manager_score']

        outsider = get_review_detail('rev-1', 'tenant-1', role='employee', actor_employee_id='emp-x')
        assert outsider['permissions']['allowedFields'] == []


def test_manager_scores_and_hr_finalizes(review_app):
    with review_app.app_context():
        result = save_scores(
            'rev-1', 'tenant-1',
            {'items': [{'id': 'item-1', 'managerScore': 14}, {'id': 'item-2', 'managerScore': 10}]},
            role='employee', actor_employee_id='emp-mgr', actor_user_id='user-mgr',
        )
        db.session.commit()
        assert result['managerScore'] == 24.0
        assert result['finalScore'] == 24.0  # 无 final 时取 manager
        assert OperationLog.query.filter_by(action='review_score').count() == 1

        hr = save_scores(
            'rev-1', 'tenant-1',
            {'items': [{'id': 'item-1', 'finalScore': 15}, {'id': 'item-2', 'finalScore': 12}]},
            role='admin', actor_employee_id=None, actor_user_id='user-hr',
        )
        db.session.commit()
        assert hr['finalScore'] == 27.0
        assert hr['grade'] == 'E'

        confirmed = confirm_review('rev-1', 'tenant-1', {}, role='admin', actor_user_id='user-hr')
        db.session.commit()
        assert confirmed['status'] == 'confirmed'
        assert confirmed['finalScore'] == 27.0


def test_manager_cannot_edit_self_or_final(review_app):
    with review_app.app_context():
        with pytest.raises(ReviewPermissionError):
            save_scores(
                'rev-1', 'tenant-1',
                {'items': [{'id': 'item-1', 'finalScore': 10}]},
                role='employee', actor_employee_id='emp-mgr', actor_user_id='user-mgr',
            )


def test_confirm_requires_hr(review_app):
    with review_app.app_context():
        with pytest.raises(ReviewPermissionError):
            confirm_review('rev-1', 'tenant-1', {}, role='employee', actor_user_id='user-mgr')
