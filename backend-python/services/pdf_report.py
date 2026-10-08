"""学习总结 PDF 报告生成（Pillow 渲染多页 A4 PDF）。

内容：员工信息 + 课程完成统计 + 考试成绩 + 积分 + 证书 + 能力测评。
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from models import (
    Certificate,
    CompetencyAssessment,
    Course,
    Department,
    Employee,
    ExamAssignment,
    ExamAttempt,
    ExamPaper,
    ExamTask,
    db,
)

logger = logging.getLogger('hengpintong.pdf_report')

# A4 尺寸（像素，150dpi）
W, H = 1240, 1754


def _font(size, bold=False):
    candidates = [
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc' if bold else '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc' if bold else '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ]
    for p in candidates:
        import os
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def generate_learning_report(employee_id: str) -> io.BytesIO:
    """生成员工学习总结 PDF。返回 BytesIO。"""
    emp = db.session.get(Employee, employee_id)
    if not emp:
        raise ValueError('员工不存在')

    dept = Department.query.get(emp.department_id) if emp.department_id else None

    # 汇总数据
    from services.course_progress import employee_course_progress_map

    # Use the same canonical rows as the employee portal.  Historical
    # concurrent reports must not duplicate a course in an exported report.
    course_progress = list(employee_course_progress_map(employee_id).values())
    courses_finished = sum(1 for p in course_progress if p['isFinished'])
    courses_total = len(course_progress)
    attempts = ExamAttempt.query.filter_by(employee_id=employee_id, status='submitted').all()
    assignment_ids = {attempt.assignment_id for attempt in attempts if attempt.assignment_id}
    assignments = (
        ExamAssignment.query.filter(ExamAssignment.id.in_(assignment_ids)).all()
        if assignment_ids else []
    )
    assignment_map = {assignment.id: assignment for assignment in assignments}
    task_ids = {attempt.task_id for attempt in attempts if attempt.task_id}
    task_ids.update(assignment.task_id for assignment in assignments if assignment.task_id)
    tasks = ExamTask.query.filter(ExamTask.id.in_(task_ids)).all() if task_ids else []
    task_map = {task.id: task for task in tasks}
    paper_ids = {attempt.paper_id for attempt in attempts if attempt.paper_id}
    paper_ids.update(task.paper_id for task in tasks if task.paper_id)
    papers = ExamPaper.query.filter(ExamPaper.id.in_(paper_ids)).all() if paper_ids else []
    paper_map = {paper.id: paper for paper in papers}

    exam_records = {}
    for attempt in attempts:
        assignment = assignment_map.get(attempt.assignment_id)
        task_id = attempt.task_id or (assignment.task_id if assignment else None)
        task = task_map.get(task_id) if task_id else None
        paper_id = attempt.paper_id or (task.paper_id if task else None)
        paper = paper_map.get(paper_id) if paper_id else None
        ref_id = task_id or paper_id or attempt.id
        score = float(attempt.score or 0)
        row = exam_records.setdefault(ref_id, {
            'name': task.title if task else (paper.title if paper else '考试'),
            'bestScore': score,
            'totalScore': float(attempt.total_score or 0),
            'passed': bool(attempt.passed),
        })
        if score > row['bestScore']:
            row['bestScore'] = score
            row['totalScore'] = float(attempt.total_score or 0)
        row['passed'] = row['passed'] or bool(attempt.passed)

    unique_exams = list(exam_records.values())
    exams_passed = sum(1 for row in unique_exams if row['passed'])
    exam_avg = round(
        sum(row['bestScore'] for row in unique_exams) / len(unique_exams), 1
    ) if unique_exams else 0

    from services.points import get_employee_total_points
    total_points = get_employee_total_points(employee_id)

    certs = Certificate.query.filter_by(employee_id=employee_id).all()

    assessments = CompetencyAssessment.query.filter_by(employee_id=employee_id).all()

    # 渲染 PDF
    images = []
    img = Image.new('RGB', (W, H), 'white')
    draw = ImageDraw.Draw(img)
    y = 0

    f_title = _font(40, bold=True)
    f_h = _font(28, bold=True)
    f_body = _font(22)
    f_small = _font(18)
    f_label = _font(20, bold=True)

    # ===== 页1：标题 + 基本信息 + 统计 =====
    # 顶部色带
    draw.rectangle([0, 0, W, 80], fill='#2563eb')
    draw.text((60, 18), '学习发展总结报告', fill='white', font=f_title)
    y = 120

    # 基本信息
    draw.text((60, y), '基本信息', fill='#1e293b', font=f_h); y += 40
    info = [
        f'姓名：{emp.name or "-"}',
        f'工号：{emp.employee_no or "-"}',
        f'部门：{dept.name if dept else "-"}',
        f'岗位：{emp.job_title or "-"}',
        f'生成日期：{datetime.now().strftime("%Y年%m月%d日")}',
    ]
    for line in info:
        draw.text((80, y), line, fill='#334155', font=f_body); y += 32
    y += 20

    # 核心统计（2列卡片）
    draw.text((60, y), '学习数据总览', fill='#1e293b', font=f_h); y += 40
    stats = [
        ('已完成课程', f'{courses_finished} 门', '#2563eb'),
        ('考试参加', f'{len(unique_exams)} 次', '#16a34a'),
        ('考试通过', f'{exams_passed} 次', '#10b981'),
        ('平均分', f'{exam_avg}', '#d97706'),
        ('累计积分', f'{total_points}', '#7c3aed'),
        ('获得证书', f'{len(certs)} 张', '#dc2626'),
    ]
    for i, (label, val, color) in enumerate(stats):
        col = i % 3; row = i // 3
        cx = 80 + col * 380; cy = y + row * 100
        draw.rounded_rectangle([cx, cy, cx + 340, cy + 80], radius=10, outline='#e2e8f0', width=1)
        draw.text((cx + 16, cy + 12), val, fill=color, font=_font(32, bold=True))
        draw.text((cx + 16, cy + 50), label, fill='#64748b', font=f_small)
    y += 220 + 20

    # 课程完成明细
    draw.text((60, y), '课程完成明细', fill='#1e293b', font=f_h); y += 36
    draw.line([(60, y), (W - 60, y)], fill='#e2e8f0', width=1); y += 8
    if course_progress:
        course_ids = {p['courseId'] for p in course_progress if p.get('courseId')}
        course_map = {
            course.id: course for course in Course.query.filter(Course.id.in_(course_ids)).all()
        } if course_ids else {}
        for p in course_progress[:15]:
            course = course_map.get(p['courseId'])
            name = course.title if course else '-'
            status = '✓ 已完成' if p['isFinished'] else f"{p['progress']}%"
            color = '#10b981' if p['isFinished'] else '#d97706'
            draw.text((80, y), f'• {name[:30]}', fill='#334155', font=f_body)
            bbox = draw.textbbox((0, 0), status, font=f_body)
            draw.text((W - 80 - (bbox[2] - bbox[0]), y), status, fill=color, font=f_body)
            y += 30
    else:
        draw.text((80, y), '暂无课程学习记录', fill='#94a3b8', font=f_body); y += 30

    images.append(img)

    # ===== 页2：考试成绩 + 证书 + 能力测评 =====
    img2 = Image.new('RGB', (W, H), 'white')
    draw2 = ImageDraw.Draw(img2)
    y = 60

    draw2.text((60, y), '考试成绩明细', fill='#1e293b', font=f_h); y += 40
    draw2.line([(60, y), (W - 60, y)], fill='#e2e8f0', width=1); y += 8
    if unique_exams:
        for record in unique_exams[:15]:
            name = record['name']
            score = f"{record['bestScore']}/{record['totalScore']}"
            result = '通过' if record['passed'] else '未通过'
            color = '#10b981' if record['passed'] else '#ef4444'
            draw2.text((80, y), f'• {name[:30]}', fill='#334155', font=f_body)
            draw2.text((W - 280, y), score, fill='#64748b', font=f_body)
            draw2.text((W - 100, y), result, fill=color, font=f_body)
            y += 30
    else:
        draw2.text((80, y), '暂无考试记录', fill='#94a3b8', font=f_body); y += 30
    y += 30

    # 证书
    draw2.text((60, y), '获得证书', fill='#1e293b', font=f_h); y += 40
    draw2.line([(60, y), (W - 60, y)], fill='#e2e8f0', width=1); y += 8
    if certs:
        for c in certs[:10]:
            draw2.text((80, y), f'🏆 {c.course_title} | 编号：{c.cert_no}', fill='#334155', font=f_body)
            y += 30
    else:
        draw2.text((80, y), '暂无证书', fill='#94a3b8', font=f_body); y += 30
    y += 30

    # 能力测评
    draw2.text((60, y), '能力测评结果', fill='#1e293b', font=f_h); y += 40
    draw2.line([(60, y), (W - 60, y)], fill='#e2e8f0', width=1); y += 8
    if assessments:
        for a in assessments[:10]:
            model_name = a.model.name if a.model else '-'
            draw2.text((80, y), f'• {model_name} | 达标率：{a.overall_score}%', fill='#334155', font=f_body)
            y += 30
    else:
        draw2.text((80, y), '暂无测评记录', fill='#94a3b8', font=f_body); y += 30

    # 页脚
    y = H - 60
    draw2.line([(60, y), (W - 60, y)], fill='#e2e8f0', width=1)
    draw2.text((60, y + 10), f'恒聘通 HRM · 学习发展模块 · 生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")}',
               fill='#94a3b8', font=f_small)

    images.append(img2)

    # 存 PDF
    buf = io.BytesIO()
    images[0].save(buf, 'PDF', save_all=True, append_images=images[1:])
    buf.seek(0)
    # 释放 Image 内存（A4@150dpi 约 6.5MB/张）
    for im in images:
        im.close()
    return buf
