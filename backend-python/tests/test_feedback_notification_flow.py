from datetime import datetime

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from models import db, Feedback, Notification, User
from routes.hrm import hrm_bp


@pytest.fixture()
def hrm_client():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY='test-secret',
        JWT_SECRET_KEY='test-jwt-secret',
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(hrm_bp, url_prefix='/api/hrm')

    with app.app_context():
        db.create_all()
        admin = User(
            id='admin-1',
            email='admin@example.com',
            password_hash='x',
            name='管理员',
            role='admin',
            status='active',
        )
        submitter = User(
            id='user-1',
            email='user@example.com',
            password_hash='x',
            name='提交人',
            role='employee',
            status='active',
        )
        other = User(
            id='user-2',
            email='other@example.com',
            password_hash='x',
            name='其他人',
            role='employee',
            status='active',
        )
        db.session.add_all([admin, submitter, other])
        db.session.commit()

        tokens = {
            'admin': create_access_token(identity=admin.id, additional_claims={'role': admin.role, 'name': admin.name}),
            'submitter': create_access_token(identity=submitter.id, additional_claims={'role': submitter.role, 'name': submitter.name}),
            'other': create_access_token(identity=other.id, additional_claims={'role': other.role, 'name': other.name}),
        }

    yield app.test_client(), app, tokens

    with app.app_context():
        db.session.remove()
        db.drop_all()


def auth_header(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def test_resolving_feedback_notifies_submitter_once(hrm_client):
    client, app, tokens = hrm_client
    with app.app_context():
        db.session.add(Feedback(
            id='fb-1',
            user_id='user-1',
            feedback_type='bug',
            severity='medium',
            title='语音不能用',
            content='录入语音报错',
            status='in_progress',
        ))
        db.session.commit()

    first = client.put(
        '/api/hrm/feedbacks/fb-1',
        json={'status': 'resolved', 'handlerReply': '已修复语音录入。'},
        headers=auth_header(tokens['admin']),
    )
    assert first.status_code == 200

    second = client.put(
        '/api/hrm/feedbacks/fb-1',
        json={'status': 'resolved', 'handlerReply': '补充说明：已上线。'},
        headers=auth_header(tokens['admin']),
    )
    assert second.status_code == 200

    with app.app_context():
        notices = Notification.query.filter_by(user_id='user-1', notice_type='feedback').all()
        assert len(notices) == 1
        notice = notices[0]
        assert notice.status == 'unread'
        assert notice.link_url == '/feedback?id=fb-1'
        assert '语音不能用' in notice.title
        assert '已修复语音录入' in notice.content


def test_reopening_resolved_feedback_requires_reason_and_records_context(hrm_client):
    client, app, tokens = hrm_client
    with app.app_context():
        db.session.add(Feedback(
            id='fb-2',
            user_id='user-1',
            feedback_type='bug',
            severity='high',
            title='导出失败',
            content='导出按钮报错',
            status='resolved',
            handler_id='admin-1',
            handler_reply='已修复导出接口。',
            handled_at=datetime.utcnow(),
        ))
        db.session.commit()

    missing_context = client.put(
        '/api/hrm/feedbacks/fb-2',
        json={'status': 'pending'},
        headers=auth_header(tokens['submitter']),
    )
    assert missing_context.status_code == 400
    assert '重新打开原因' in missing_context.get_json()['error']

    reopened = client.put(
        '/api/hrm/feedbacks/fb-2',
        json={
            'status': 'pending',
            'reopenReason': '导出后仍然下载到空文件。',
            'reopenCurrentState': '点击导出后浏览器下载 0KB 文件。',
        },
        headers=auth_header(tokens['submitter']),
    )
    assert reopened.status_code == 200
    body = reopened.get_json()
    assert body['status'] == 'pending'
    assert body['handlerId'] is None
    assert body['handledAt'] is None
    assert body['reopenReason'] == '导出后仍然下载到空文件。'
    assert body['reopenCurrentState'] == '点击导出后浏览器下载 0KB 文件。'
    assert body['reopenHistory'][0]['fromStatus'] == 'resolved'
    assert body['reopenHistory'][0]['reason'] == '导出后仍然下载到空文件。'


def test_resolving_reopened_feedback_notifies_submitter_again(hrm_client):
    client, app, tokens = hrm_client
    with app.app_context():
        db.session.add_all([
            Feedback(
                id='fb-3',
                user_id='user-1',
                feedback_type='bug',
                severity='high',
                title='筛选条件失效',
                content='筛选后仍显示全部数据',
                status='resolved',
                handler_id='admin-1',
                handler_reply='已修复筛选条件。',
                handled_at=datetime.utcnow(),
            ),
            Notification(
                id='n-old',
                user_id='user-1',
                title='问题反馈已修复：筛选条件失效',
                content='已修复筛选条件。',
                notice_type='feedback',
                status='read',
                link_url='/feedback?id=fb-3',
            ),
        ])
        db.session.commit()

    reopened = client.put(
        '/api/hrm/feedbacks/fb-3',
        json={
            'status': 'pending',
            'reopenReason': '筛选保存后刷新又失效。',
            'reopenCurrentState': '刷新页面后筛选条件被清空。',
        },
        headers=auth_header(tokens['submitter']),
    )
    assert reopened.status_code == 200

    resolved_again = client.put(
        '/api/hrm/feedbacks/fb-3',
        json={'status': 'resolved', 'handlerReply': '已修复刷新后筛选条件丢失的问题。'},
        headers=auth_header(tokens['admin']),
    )
    assert resolved_again.status_code == 200

    with app.app_context():
        notices = Notification.query.filter_by(user_id='user-1', notice_type='feedback', link_url='/feedback?id=fb-3').order_by(Notification.created_at.asc()).all()
        assert len(notices) == 2
        assert notices[-1].status == 'unread'
        assert '刷新后筛选条件丢失' in notices[-1].content


def test_notification_list_is_scoped_to_current_user_and_global_notices(hrm_client):
    client, app, tokens = hrm_client
    with app.app_context():
        db.session.add_all([
            Notification(id='n-1', user_id='user-1', title='你的反馈已修复', content='A', notice_type='feedback'),
            Notification(id='n-2', user_id='user-2', title='别人的通知', content='B', notice_type='feedback'),
            Notification(id='n-3', user_id=None, title='全员通知', content='C', notice_type='system'),
        ])
        db.session.commit()

    response = client.get('/api/hrm/notifications', headers=auth_header(tokens['submitter']))

    assert response.status_code == 200
    titles = {item['title'] for item in response.get_json()}
    assert titles == {'你的反馈已修复', '全员通知'}
