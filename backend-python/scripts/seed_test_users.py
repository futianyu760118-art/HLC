"""补齐测试数据：部门 + 员工 + 用户绑定，让门户全链路可测"""
import os, sys
sys.path.insert(0, '/app')
from app import create_app
from models import db, Department, Employee, User
from datetime import date

app = create_app()
with app.app_context():
    # 1. 建部门树
    dept_data = [
        ('d-root', '总部', None),
        ('d-eng', '研发部', 'd-root'),
        ('d-sales', '销售部', 'd-root'),
        ('d-hr', '人力资源部', 'd-root'),
    ]
    for did, name, pid in dept_data:
        if not Department.query.get(did):
            db.session.add(Department(id=did, name=name, parent_id=pid))
    db.session.commit()

    # 2. 建测试员工（分散在不同部门）
    emp_data = [
        ('e-zhangsan', 'E10002', '张三', 'zhangsan@test.com', 'd-eng', '前端工程师'),
        ('e-lisi', 'E10003', '李四', 'lisi@test.com', 'd-sales', '销售经理'),
        ('e-wangwu', 'E10004', '王五', 'wangwu@test.com', 'd-eng', '后端工程师'),
        ('e-zhaoliu', 'E10005', '赵六', 'zhaoliu@test.com', 'd-hr', 'HR专员'),
    ]
    for eid, no, name, email, dept, title in emp_data:
        if not Employee.query.get(eid):
            db.session.add(Employee(
                id=eid, employee_no=no, name=name, email=email,
                status='active', hire_date=date(2025, 1, 1),
                department_id=dept, job_title=title,
            ))
    db.session.commit()

    # 3. 为员工创建登录账号 + 绑定
    import bcrypt
    pwd_hash = bcrypt.hashpw(b'Employee@2026', bcrypt.gensalt()).decode()
    for eid, no, name, email, dept, title in emp_data:
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(id=f'u-{eid}', email=email, password_hash=pwd_hash,
                     name=name, role='employee', status='active', employee_id=eid)
            db.session.add(u)
        else:
            u.employee_id = eid
            u.role = 'employee'
    db.session.commit()

    # 4. 给所有课程指派到总部（全员可见）
    from models import Course, CourseAssignment
    courses = Course.query.all()
    for c in courses:
        existing = CourseAssignment.query.filter_by(course_id=c.id).count()
        if existing == 0:
            db.session.add(CourseAssignment(
                id=os.urandom(16).hex(), course_id=c.id,
                target_type='dept', target_id='d-root',
            ))
    db.session.commit()

    # 5. 给考试任务指派研发部（让研发员工能考试）
    from models import ExamTask
    tasks = ExamTask.query.filter_by(status='draft').all()
    for t in tasks:
        t.target_type = 'dept'
        t.target_ids = ['d-eng']
    db.session.commit()

    print('=== 测试数据补齐完成 ===')
    print(f'部门: {Department.query.count()} 个')
    print(f'员工: {Employee.query.count()} 个')
    print(f'用户: {User.query.count()} 个（已绑员工）')
    print(f'课程指派: {CourseAssignment.query.count()} 条')
    print(f'考试任务指派: 研发部')
    print('\n测试账号:')
    for eid, no, name, email, dept, title in emp_data:
        print(f'  {email} / Employee@2026 ({name}, {title})')
