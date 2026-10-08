"""学习提醒定时推送（催学）。

后台线程每天检查一次：
- 必修课截止前 7/3/1 天，未完成员工 → 发催学通知
- 考试结束前 1 天，未参加员工 → 发催考通知

用 threading.Timer 实现轻量定时，不依赖 APScheduler。
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Set

from models import db, Course, CourseAssignment, ExamTask, ExamAssignment, UserCourseProgress

logger = logging.getLogger('hengpintong.study_reminder')

# 提醒节点（天）
COURSE_REMIND_DAYS = [7, 3, 1]
EXAM_REMIND_DAYS = [1]

_running = False


def _get_assigned_employees(course_id: str) -> Set[str]:
    """课程指派员工集合。"""
    from services.course_access import course_assigned_employee_ids
    return course_assigned_employee_ids(course_id)


def check_course_deadlines() -> int:
    """检查必修课截止日期，给未完成员工发提醒。返回发送条数。"""
    from services.training_notify import notify_employee
    now = datetime.utcnow()
    count = 0

    # 有 deadline 且必修且上架的课程
    courses = Course.query.filter(
        Course.is_required == True,
        Course.is_show == True,
        Course.deadline.isnot(None),
        Course.deadline > now,
    ).all()

    for c in courses:
        delta = c.deadline - now
        days_left = delta.days + (1 if delta.seconds > 0 else 0)  # 向上取整（剩余不足1天也算1天）
        if days_left not in COURSE_REMIND_DAYS:
            continue

        assigned = _get_assigned_employees(c.id)
        # 未完成的员工
        finished_ids = {p.employee_id for p in UserCourseProgress.query.filter_by(
            course_id=c.id, is_finished=True
        ).all()}
        unfinished = assigned - finished_ids

        urgency = '⚠️最后一天' if days_left == 1 else f'还有{days_left}天'
        for emp_id in unfinished:
            notify_employee(
                emp_id,
                f'必修课提醒：{c.title} {urgency}',
                f'必修课程「{c.title}」将于 {c.deadline.strftime("%m月%d日")} 截止，{urgency}，请尽快完成学习！',
                notice_type='deadline',
                link_url=f'/portal/course/{c.id}',
            )
            count += 1

    logger.info('course_deadline_check_done', extra={'sent': count})
    return count


def check_exam_deadlines() -> int:
    """检查考试截止，给未参加员工发提醒。"""
    from services.training_notify import notify_employee
    now = datetime.utcnow()
    count = 0

    tasks = ExamTask.query.filter(
        ExamTask.status == 'published',
        ExamTask.end_time.isnot(None),
        ExamTask.end_time > now,
    ).all()

    for t in tasks:
        delta = t.end_time - now
        days_left = delta.days + (1 if delta.seconds > 0 else 0)
        if days_left not in EXAM_REMIND_DAYS:
            continue

        # 未参加（attempts_used=0）的员工
        assignments = ExamAssignment.query.filter_by(task_id=t.id).all()
        not_taken = [a.employee_id for a in assignments if (a.attempts_used or 0) == 0]

        for emp_id in not_taken:
            notify_employee(
                emp_id,
                f'考试提醒：{t.title} 明天截止',
                f'考试「{t.title}」将于明天结束，您尚未参加，请尽快完成！',
                notice_type='exam_deadline',
                link_url='/portal/my-exams',
            )
            count += 1

    logger.info('exam_deadline_check_done', extra={'sent': count})
    return count


def run_daily_check():
    """执行一次每日检查（供手动触发或定时调用）。"""
    try:
        c1 = check_course_deadlines()
        c2 = check_exam_deadlines()
        logger.info('daily_reminder_done', extra={'course': c1, 'exam': c2})
        return c1 + c2
    except Exception as exc:
        logger.error('daily_reminder_failed', extra={'error': str(exc)})
        return 0


def _daily_loop(app=None):
    """后台每日循环（间隔 24 小时）。"""
    global _running
    while _running:
        if app is None:
            run_daily_check()
        else:
            with app.app_context():
                run_daily_check()
        # 等 24 小时
        for _ in range(24):
            if not _running:
                break
            threading.Event().wait(3600)  # 每小时检查一次 _running


def start_reminder_scheduler(app=None):
    """启动后台催学调度（app 启动时调用）。"""
    global _running
    if _running:
        return
    _running = True
    t = threading.Thread(target=_daily_loop, args=(app,), daemon=True, name='study-reminder')
    t.start()
    logger.info('study_reminder_scheduler_started')


def stop_reminder_scheduler():
    """停止调度（测试/关闭用）。"""
    global _running
    _running = False
