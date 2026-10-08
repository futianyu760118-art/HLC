from __future__ import annotations

import pytest
from flask import Flask

from models import Department, Employee, Tenant, db
from services.performance_participation import list_participants, set_participants


@pytest.fixture()
def participant_app():
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
            Department(id='dept-sales', tenant_id='tenant-1', name='销售中心', status='active'),
            Department(id='dept-fin', tenant_id='tenant-1', name='财务部', status='active'),
        ])
        db.session.add_all([
            Employee(id='emp-a', tenant_id='tenant-1', employee_no='001', name='张三',
                     status='active', department_id='dept-sales', job_title='副总'),
            Employee(id='emp-b', tenant_id='tenant-1', employee_no='002', name='李四',
                     status='active', department_id='dept-fin', job_title='会计'),
            Employee(id='emp-c', tenant_id='tenant-1', employee_no='003', name='王五',
                     status='inactive', department_id='dept-sales'),
        ])
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_list_and_filter_participants(participant_app):
    with participant_app.app_context():
        rows = list_participants('tenant-1')
        assert {r['name'] for r in rows} == {'张三', '李四'}  # inactive excluded
        assert rows[0]['participant'] is False

        sales = list_participants('tenant-1', department_name='销售中心')
        assert [r['name'] for r in sales] == ['张三']

        kw = list_participants('tenant-1', keyword='李四')
        assert [r['name'] for r in kw] == ['李四']


def test_set_participants_batch(participant_app):
    with participant_app.app_context():
        result = set_participants('tenant-1', ['emp-a', 'emp-b'], True)
        db.session.commit()
        assert result['updated'] == 2
        assert Employee.query.get('emp-a').performance_participant is True

        set_participants('tenant-1', ['emp-a'], False)
        db.session.commit()
        assert Employee.query.get('emp-a').performance_participant is False
        assert Employee.query.get('emp-b').performance_participant is True


def test_set_participants_requires_ids(participant_app):
    with participant_app.app_context():
        with pytest.raises(ValueError):
            set_participants('tenant-1', [], True)
