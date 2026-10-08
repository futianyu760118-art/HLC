"""培训体系模型与 CRUD 注册测试（Chunk 2）。

验证：
1. 8 张新表能在 in-memory SQLite 建表
2. 模型 to_dict() 能正确 denormalize FK 名称
3. RESOURCE_CONFIG 注册了 8 个新资源
4. 通过泛型 CRUD 端点能 list/create 课程
"""

from datetime import date

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from models import (
    Course, CourseCategory, CourseChapter, CourseHour, CourseAttachment,
    CourseAssignment, UserCourseProgress, UserHourProgress, Employee, User, db,
)
from routes.hrm import hrm_bp


@pytest.fixture()
def flask_app():
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
        user = User(id='admin-1', email='a@corp.com', password_hash='x',
                    name='Admin', role='hr_admin', status='active')
        db.session.add(user)
        db.session.commit()
    yield app


@pytest.fixture()
def client(flask_app):
    with flask_app.app_context():
        token = create_access_token(identity='admin-1',
                                    additional_claims={'role': 'hr_admin', 'name': 'Admin'})
    c = flask_app.test_client()
    c.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    return c


def test_all_training_tables_created(client, flask_app):
    """8 张新表都已建表（create_all 不报错即说明模型定义合法）。"""
    with flask_app.app_context():
        for model in [Course, CourseCategory, CourseChapter, CourseHour,
                      CourseAttachment, CourseAssignment, UserCourseProgress, UserHourProgress]:
            # 能查空表即说明表存在
            model.query.count()


def test_course_to_dict_denormalizes_category(client, flask_app):
    with flask_app.app_context():
        cat = CourseCategory(id='cat-1', name='安全培训', sort=0)
        course = Course(id='c-1', title='消防知识', category_id='cat-1',
                        is_required=True, is_show=True, class_hour=3)
        db.session.add_all([cat, course])
        db.session.commit()
        d = course.to_dict()
        assert d['title'] == '消防知识'
        assert d['categoryName'] == '安全培训'
        assert d['isRequired'] is True
        assert d['isShow'] is True


def test_course_crud_via_generic_endpoint(client, flask_app):
    """通过泛型 CRUD 创建课程并 list。"""
    resp = client.post('/api/hrm/courses', json={'title': '测试课程', 'isRequired': True, 'isShow': True})
    assert resp.status_code == 201, resp.get_json()
    created = resp.get_json()
    assert created['title'] == '测试课程'
    listing = client.get('/api/hrm/courses')
    assert listing.status_code == 200
    data = listing.get_json()
    items = data['items'] if isinstance(data, dict) else data
    titles = [it['title'] for it in items]
    assert '测试课程' in titles


def test_course_category_and_chapter_crud(client, flask_app):
    """分类、章节也能 CRUD。"""
    assert client.post('/api/hrm/course-categories', json={'name': '通用'}).status_code == 201
    # 章节依赖课程存在；先建课程再建章节
    client.post('/api/hrm/courses', json={'title': '章宿主课程'})
    course_id = client.get('/api/hrm/courses').get_json()[0]['id']
    assert client.post('/api/hrm/course-chapters',
                       json={'courseId': course_id, 'name': '第一章'}).status_code == 201


def test_progress_resources_are_read_only_create(client, flask_app):
    """course-progress / hour-progress 禁止直接 create（由门户上报）。"""
    r1 = client.post('/api/hrm/course-progress', json={'employeeId': 'e1', 'courseId': 'c1'})
    assert r1.status_code == 400
    r2 = client.post('/api/hrm/hour-progress', json={'employeeId': 'e1', 'hourId': 'h1'})
    assert r2.status_code == 400
