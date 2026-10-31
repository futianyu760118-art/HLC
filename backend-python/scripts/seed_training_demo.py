"""插入培训+考试演示数据。幂等：基于固定 uuid，重复运行不重复插入。"""
import uuid
from datetime import datetime, timedelta
from app import create_app
from models import (db, CourseCategory, Course, CourseChapter, CourseHour,
                    CourseAttachment, CourseAssignment, ExamQuestion, ExamPaper,
                    ExamTask, Department, Employee)


def fixed(prefix, n=8):
    """生成基于 prefix 的确定性 uuid（36字符标准格式）。"""
    import hashlib
    h = hashlib.md5(prefix.encode('utf-8')).hexdigest()
    return f'{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}'


def run():
    app = create_app()
    with app.app_context():
        # 分类
        cats = {}
        for name in ['新员工入职', '岗位技能', '安全合规']:
            cid = fixed(f'cat-{name}')
            if not CourseCategory.query.get(cid):
                db.session.add(CourseCategory(id=cid, name=name, sort=0))
                db.session.commit()
            cats[name] = cid

        # 课程数据（带封面占位 URL 用渐变即可，留空让前端生成）
        courses_data = [
            {
                'title': '新员工入职指南', 'cat': '新员工入职', 'required': True,
                'short_desc': '了解公司文化、制度与福利，快速融入团队',
                'content': '本课程涵盖公司发展历程、组织架构、考勤制度、薪酬福利、职业发展通道等内容，帮助新员工快速了解公司并融入工作。',
                'chapters': [
                    ('公司介绍', ['公司发展历程', '组织架构与团队', '企业文化与价值观']),
                    ('规章制度', ['考勤与请假制度', '薪酬福利体系', '绩效考核说明']),
                ],
            },
            {
                'title': 'Excel 数据分析实战', 'cat': '岗位技能', 'required': False,
                'short_desc': '从零掌握 VLOOKUP、数据透视表、图表制作',
                'content': '本课程系统讲解 Excel 在工作中的实际应用，包括常用函数、数据透视表、条件格式、图表制作与自动化。',
                'chapters': [
                    ('基础函数', ['常用函数 SUM/AVERAGE/IF', 'VLOOKUP 与 INDEX-MATCH', '文本与日期函数']),
                    ('数据分析', ['数据透视表入门', '条件格式与数据验证', '图表制作技巧']),
                ],
            },
            {
                'title': '消防安全知识培训', 'cat': '安全合规', 'required': True,
                'short_desc': '掌握火灾预防、灭火器使用与应急疏散',
                'content': '消防安全是每位员工的必修课。本课程讲解火灾预防、灭火器种类与使用、应急疏散流程与报警规范。',
                'chapters': [
                    ('火灾预防', ['常见火灾隐患', '用电安全规范', '易燃物品管理']),
                    ('应急处置', ['灭火器使用方法', '应急疏散路线', '火警电话与报警流程']),
                ],
            },
            {
                'title': '商务邮件写作规范', 'cat': '岗位技能', 'required': False,
                'short_desc': '专业、清晰的职场邮件写作技巧',
                'content': '职场邮件是日常沟通的重要工具。本课程讲解邮件结构、称谓礼仪、表达技巧与常见场景模板。',
                'chapters': [
                    ('邮件基础', ['邮件结构与格式', '称谓与落款礼仪', '主题行写作']),
                ],
            },
        ]

        course_ids = []
        for cd in courses_data:
            cid = fixed(f'course-{cd["title"]}')
            course_ids.append(cid)
            if Course.query.get(cid):
                continue
            c = Course(id=cid, title=cd['title'], category_id=cats[cd['cat']],
                       is_required=cd['required'], is_show=True, short_desc=cd['short_desc'],
                       content=cd['content'], class_hour=sum(len(ch[1]) for ch in cd['chapters']))
            db.session.add(c)
            db.session.flush()
            for ci, (ch_name, hours) in enumerate(cd['chapters']):
                chid = fixed(f'ch-{cid}-{ci}')
                db.session.add(CourseChapter(id=chid, course_id=cid, name=ch_name, sort=ci))
                db.session.flush()
                for hi, h_title in enumerate(hours):
                    hid = fixed(f'h-{cid}-{ci}-{hi}')
                    db.session.add(CourseHour(id=hid, course_id=cid, chapter_id=chid,
                                              title=h_title, type='VIDEO', sort=hi,
                                              duration=600 + hi * 120))
        db.session.commit()

        # 题库（围绕消防/Excel/入职出题）
        questions_data = [
            ('single', '火警电话是多少？', ['110', '119', '120', '122'], [1], 10, 1, '火警电话是119。'),
            ('judge', '发现火情应先扑救再报警。', ['正确', '错误'], [1], 10, 2, '应先报警再扑救，报警越早损失越小。'),
            ('multiple', '下列哪些是常见的火灾隐患？', ['私拉乱接电线', '下班关闭电源', '楼道堆放杂物', '定期检查灭火器'], [0, 2], 20, 3, '私拉电线和堆放杂物是隐患；关闭电源和检查灭火器是正确做法。'),
            ('single', 'VLOOKUP 函数的第4个参数为 FALSE 表示？', ['精确匹配', '近似匹配', '反向查找', '忽略'], [0], 10, 2, 'FALSE/0 表示精确匹配。'),
            ('judge', '数据透视表可以动态汇总大量数据。', ['正确', '错误'], [0], 10, 1, '数据透视表是 Excel 强大的数据汇总工具。'),
            ('multiple', '职场邮件的基本结构包含哪些？', ['称呼', '正文', '表情包', '落款'], [0, 1, 3], 20, 2, '邮件应有称呼、正文、落款，不宜用表情包。'),
            ('single', '公司新员工入职应首先完成？', ['领取工牌', '消防安全培训', '选择工位', '认识同事'], [1], 10, 1, '安全培训是入职首要必修。'),
            ('judge', 'Excel 中 $A$1 是绝对引用。', ['正确', '错误'], [0], 10, 2, '$ 符号锁定行列，为绝对引用。'),
        ]
        q_ids = []
        for i, (qtype, stem, opts, ans, score, diff, expl) in enumerate(questions_data):
            qid = fixed(f'q-{i}-{stem[:6]}')
            q_ids.append(qid)
            if not ExamQuestion.query.get(qid):
                db.session.add(ExamQuestion(
                    id=qid, type=qtype, stem=stem, options=opts, answer=ans,
                    score=score, explanation=expl, difficulty=diff,
                    review_status='approved', source='manual',
                ))
        db.session.commit()

        # 试卷
        paper_id = fixed('paper-安全入职测验')
        if not ExamPaper.query.get(paper_id):
            db.session.add(ExamPaper(
                id=paper_id, title='安全合规与入职测验',
                description='涵盖消防安全、入职规范与基础办公技能',
                question_ids=q_ids[:6], total_score=80, pass_score=48,
                duration_minutes=20, status='published',
            ))
        db.session.commit()

        paper2_id = fixed('paper-Excel专项')
        if not ExamPaper.query.get(paper2_id):
            db.session.add(ExamPaper(
                id=paper2_id, title='Excel 技能测验',
                description='VLOOKUP、数据透视表等核心技能',
                question_ids=q_ids[3:5] + q_ids[7:8], total_score=30, pass_score=18,
                duration_minutes=15, status='draft',
            ))
        db.session.commit()

        # 考试任务（草稿，需管理员手动发布）
        task_id = fixed('task-月度安全测验')
        if not ExamTask.query.get(task_id):
            db.session.add(ExamTask(
                id=task_id, paper_id=paper_id, title='2026年6月安全合规测验',
                description='全员必修，请在本月底前完成',
                start_time=datetime.utcnow() - timedelta(days=1),
                end_time=datetime.utcnow() + timedelta(days=14),
                max_attempts=2, target_type='dept', target_ids=['d-eng'], status='draft',
            ))
        db.session.commit()

        print('=== 演示数据插入完成 ===')
        print(f'分类: {CourseCategory.query.count()} 个')
        print(f'课程: {Course.query.count()} 门')
        print(f'章节: {CourseChapter.query.count()} 个')
        print(f'课时: {CourseHour.query.count()} 个')
        print(f'题库: {ExamQuestion.query.count()} 题（已审核 {ExamQuestion.query.filter_by(review_status="approved").count()}）')
        print(f'试卷: {ExamPaper.query.count()} 份')
        print(f'考试任务: {ExamTask.query.count()} 个')


if __name__ == '__main__':
    run()
