from __future__ import annotations

import pytest
from flask import Flask

from models import Employee, Notification, Tenant, db
from services.notify import notify, notify_many


@pytest.fixture()
def notify_app():
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
        db.session.add(Employee(id='emp-1', tenant_id='tenant-1', employee_no='001',
                                name='张三', status='active'))
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_station_notification_creates_row(notify_app):
    with notify_app.app_context():
        ok = notify('station', tenant_id='tenant-1', employee_id='emp-1',
                    title='考勤提醒', content='你本月工时已生成', notice_type='attendance_summary')
        db.session.commit()
        assert ok is True
        row = Notification.query.filter_by(tenant_id='tenant-1').one()
        assert row.title == '考勤提醒'
        assert row.employee_id == 'emp-1'
        assert row.status == 'unread'


def test_wecom_is_placeholder(notify_app):
    with notify_app.app_context():
        ok = notify('wecom', tenant_id='tenant-1', employee_id='emp-1', title='t', content='c')
        assert ok is False
        assert Notification.query.count() == 0


def test_notify_many_counts(notify_app):
    with notify_app.app_context():
        result = notify_many(
            ['station', 'wecom'],
            [{'employeeId': 'emp-1'}, {'employeeId': None}],
            tenant_id='tenant-1', title='汇总', content='内容',
        )
        db.session.commit()
        assert result['sent'] == 1
        assert result['skipped'] == 1
        assert Notification.query.count() == 1


def test_notify_rejects_unknown_channel(notify_app):
    with notify_app.app_context():
        with pytest.raises(ValueError):
            notify('sms', tenant_id='tenant-1', employee_id='emp-1', title='t', content='c')
