"""为 55 名员工配置 SPC 中台培训考试。

- 课程：SPC供应链中台培训（已存在，全员可见，无需分配）
- 试卷：paper-spc-training-50（已存在，50题随机抽20，100分/及格80/60分钟）
- 考试任务：新建，时间窗 2026-06-23 18:48 ~ 2026-06-30 18:48，max_attempts=1
- 授权：55 名员工（按姓名匹配 employee.id）

用法（容器内）：python /app/scripts/assign_spc_training.py
"""
import os
import sys
import uuid
from datetime import datetime

sys.path.insert(0, '/app')
from models import db, Employee, ExamTask, ExamAssignment, Course, CourseAssignment
from app import create_app

PAPER_ID = 'paper-spc-training-50'
COURSE_ID = '741e093b-f314-4e90-b1d8-4ea0fc958335'
START = datetime(2026, 6, 23, 18, 48, 0)
END = datetime(2026, 6, 30, 18, 48, 0)

NAMES = ['沈旭日','朱梦倩','孔令军','洪香','付天宇','戎双娇','管丽艳','虞周峰','廖新平',
         '沈旭挺','李玉英','金辉','田鹏','马雅雯','沈意玲','陈梦霞','吴建英','陈建婷',
         '包跃','姚勇','孙周杰','宓曙','朱文祥','蒋旭东','沈建凯','王栌鑫','汪华正',
         '徐蓉','李朦','严纯洁','黄梦蝶','侯莉雅','魏晨晨','蒋哲斌','刘媛媛','徐盼',
         '贾靓','陈文钰','宋海跃','江蜜','赵申','朱鑫森','楼松杰','王静','裘丹迪',
         '邓秋瑶','邓桃院','丁亚君','方燕红','朱燕迪','黎成友','韦恩栋','李硕',
         '贺承娇','柴妙琳']

TASK_ID = 'task-spc-training-2026'


def main():
    app = create_app()
    with app.app_context():
        # 1) 匹配 55 名员工
        emps = Employee.query.filter(Employee.name.in_(NAMES)).all()
        matched_names = {e.name for e in emps}
        missing = [n for n in NAMES if n not in matched_names]
        print(f'匹配员工: {len(emps)} / {len(NAMES)}')
        if missing:
            print(f'!! 未匹配: {missing}')
        emp_ids = [e.id for e in emps]

        now = datetime.utcnow()

        # 2) 考试任务（幂等：已存在则更新 target/时间）
        task = ExamTask.query.get(TASK_ID)
        if not task:
            task = ExamTask(
                id=TASK_ID,
                paper_id=PAPER_ID,
                title='SPC 中台培训考试',
                description='供应链中台全模块培训考核（50题随机抽20，100分/及格80/60分钟）',
                start_time=START,
                end_time=END,
                max_attempts=1,
                target_type='user',
                target_ids=emp_ids,
                status='published',
                created_by=None,
                created_at=now,
                updated_at=now,
            )
            db.session.add(task)
            print(f'创建考试任务: {task.title} ({TASK_ID})')
        else:
            task.paper_id = PAPER_ID
            task.start_time = START
            task.end_time = END
            task.max_attempts = 1
            task.target_type = 'user'
            task.target_ids = emp_ids
            task.status = 'published'
            task.updated_at = now
            print(f'更新考试任务: {task.title}')

        # 3) 考试授权（幂等：已存在的跳过）
        existing = {a.employee_id for a in ExamAssignment.query.filter_by(task_id=TASK_ID).all()}
        new_count = 0
        for eid in emp_ids:
            if eid not in existing:
                db.session.add(ExamAssignment(
                    id=str(uuid.uuid4()),
                    task_id=TASK_ID,
                    employee_id=eid,
                    attempts_used=0,
                    status='assigned',
                    created_at=now,
                    updated_at=now,
                ))
                new_count += 1
        print(f'考试授权: 新增 {new_count} 人, 共 {len(emp_ids)} 人')

        # 4) 课程分配（确保这55人能看到 SPC 课程）。
        #    注：若课程当前无任何 assignment（全员可见），这里给 55 人加 user 指派后，
        #    课程变为"仅指派可见"——其他人将看不到。如果希望课程保持全员公开，
        #    注释掉这段即可。这里按"给这些人配置"理解为专属指派。
        existing_ca = {(a.target_id) for a in CourseAssignment.query.filter_by(
            course_id=COURSE_ID, target_type='user').all()}
        ca_new = 0
        for eid in emp_ids:
            if eid not in existing_ca:
                db.session.add(CourseAssignment(
                    id=str(uuid.uuid4()),
                    course_id=COURSE_ID,
                    target_type='user',
                    target_id=eid,
                    created_at=now,
                ))
                ca_new += 1
        print(f'课程指派: 新增 {ca_new} 人')

        db.session.commit()
        print('\n完成。')
        print(f'  课程: SPC供应链中台培训（指派 {len(emp_ids)} 人可见）')
        print(f'  考试: {task.title}（{START} ~ {END}，授权 {len(emp_ids)} 人，最多1次）')


if __name__ == '__main__':
    main()
