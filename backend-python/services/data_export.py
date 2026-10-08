"""学习数据导出（Excel）。

用 openpyxl 生成 .xlsx，返回 BytesIO 流给 Flask send_file。
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import List

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

from models import (db, Course, Department, Employee, ExamAttempt, ExamTask,
                    ExamPaper, UserCourseProgress, UserHourProgress, PointLog)


HEAD_FONT = Font(bold=True, color='FFFFFF', size=11)
HEAD_FILL = PatternFill(start_color='2563EB', end_color='2563EB', fill_type='solid')
CENTER = Alignment(horizontal='center', vertical='center')


def _style_header(ws, ncols: int):
    for col in range(1, ncols + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = HEAD_FONT
        cell.fill = HEAD_FILL
        cell.alignment = CENTER
    ws.row_dimensions[1].height = 24
    # 列宽自适应（粗略）
    for col in range(1, ncols + 1):
        ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = 18


def export_exam_results(task_id: str) -> io.BytesIO:
    """导出某场考试的成绩单。"""
    from sqlalchemy import func
    task = ExamTask.query.get(task_id)
    wb = Workbook()
    ws = wb.active
    ws.title = '成绩单'
    headers = ['工号', '姓名', '部门', '岗位', '最高分', '总分', '是否通过', '考试次数', '提交时间']
    ws.append(headers)
    _style_header(ws, len(headers))

    attempts = ExamAttempt.query.filter_by(task_id=task_id, status='submitted').all()
    # 每员工取最高分
    best = {}
    for a in attempts:
        emp_id = a.employee_id
        if emp_id not in best or float(a.score or 0) > float(best[emp_id].score or 0):
            best[emp_id] = a

    paper = ExamPaper.query.get(task.paper_id) if task else None
    total_score = float(paper.total_score) if paper else 100

    for emp_id, a in best.items():
        emp = Employee.query.get(emp_id)
        dept = Department.query.get(emp.department_id) if emp and emp.department_id else None
        ws.append([
            emp.employee_no if emp else '', emp.name if emp else '',
            dept.name if dept else '', emp.job_title if emp else '',
            float(a.score or 0), total_score, '是' if a.passed else '否',
            len([x for x in attempts if x.employee_id == emp_id]),
            a.submitted_at.strftime('%Y-%m-%d %H:%M') if a.submitted_at else '',
        ])
    ws.append([])
    ws.append([f'导出时间：{datetime.now().strftime("%Y-%m-%d %H:%M")} | 考试：{task.title if task else ""} | 参考人数：{len(best)}'])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def export_course_progress(course_id: str) -> io.BytesIO:
    """导出某课程的学习进度。"""
    from services.course_access import course_assigned_employee_ids
    course = Course.query.get(course_id)
    assigned = course_assigned_employee_ids(course_id)
    total_hours = UserHourProgress.query.filter_by(course_id=course_id).count()

    wb = Workbook()
    ws = wb.active
    ws.title = '学习进度'
    headers = ['工号', '姓名', '部门', '岗位', '学习进度(%)', '已完成课时', '总课时', '累计学习(分钟)', '状态', '完成时间']
    ws.append(headers)
    _style_header(ws, len(headers))

    progress_map = {p.employee_id: p for p in UserCourseProgress.query.filter_by(course_id=course_id).all()}
    from sqlalchemy import func as F
    dur_rows = db.session.query(
        UserHourProgress.employee_id,
        F.coalesce(F.sum(UserHourProgress.watched_duration), 0),
    ).filter_by(course_id=course_id).group_by(UserHourProgress.employee_id).all()
    dur_map = {r[0]: int(r[1]) for r in dur_rows}

    for emp_id in assigned:
        emp = Employee.query.get(emp_id)
        dept = Department.query.get(emp.department_id) if emp and emp.department_id else None
        p = progress_map.get(emp_id)
        ws.append([
            emp.employee_no if emp else '', emp.name if emp else '',
            dept.name if dept else '', emp.job_title if emp else '',
            p.progress if p else 0,
            p.finished_count if p else 0,
            p.hour_count if p else 0,
            round(dur_map.get(emp_id, 0) / 60),
            '已完成' if (p and p.is_finished) else '学习中' if p else '未开始',
            p.finished_at.strftime('%Y-%m-%d') if (p and p.finished_at) else '',
        ])
    ws.append([])
    ws.append([f'导出时间：{datetime.now().strftime("%Y-%m-%d %H:%M")} | 课程：{course.title if course else ""} | 指派人数：{len(assigned)}'])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def export_points_leaderboard() -> io.BytesIO:
    """导出积分排行榜。"""
    from sqlalchemy import func as F
    wb = Workbook()
    ws = wb.active
    ws.title = '积分排行榜'
    headers = ['排名', '工号', '姓名', '部门', '岗位', '总积分', '最近获奖时间']
    ws.append(headers)
    _style_header(ws, len(headers))

    rows = db.session.query(
        PointLog.employee_id,
        F.sum(PointLog.points).label('total'),
        F.max(PointLog.created_at).label('last'),
    ).filter(
        PointLog.action != 'wrong_question_mastered',
    ).group_by(PointLog.employee_id).order_by(F.sum(PointLog.points).desc()).all()

    for i, (emp_id, total, last) in enumerate(rows):
        emp = Employee.query.get(emp_id)
        dept = Department.query.get(emp.department_id) if emp and emp.department_id else None
        ws.append([
            i + 1, emp.employee_no if emp else '', emp.name if emp else '',
            dept.name if dept else '', emp.job_title if emp else '',
            int(total or 0),
            last.strftime('%Y-%m-%d %H:%M') if last else '',
        ])
    ws.append([])
    ws.append([f'导出时间：{datetime.now().strftime("%Y-%m-%d %H:%M")} | 总人数：{len(rows)}'])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
