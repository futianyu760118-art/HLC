"""学习路径进度计算。

闯关式逻辑：
- 阶段按顺序，前一阶段所有课程完成 + 考试通过（如有）→ 解锁下一阶段
- 整体进度 = 已完成课程数 / 总课程数 * 100
- current_stage = 第一个未完成阶段的索引
"""
from __future__ import annotations

from datetime import datetime
from typing import List

from models import (
    Course, CourseHour, ExamAssignment, ExamAttempt, LearningPath,
    LearningPathAssignment, UserCourseProgress, db,
)
from services.course_progress import employee_course_progress_map


def _is_course_completed(employee_id: str, course_id: str) -> bool:
    """员工是否完成某课程（所有课时学完）。"""
    total = CourseHour.query.filter_by(course_id=course_id).count()
    if total == 0:
        return False
    p = employee_course_progress_map(employee_id, [course_id]).get(course_id)
    return bool(p and p['isFinished'])


def _is_exam_passed(employee_id: str, task_id: str | None) -> bool:
    """员工是否通过某考试任务（取最高分 attempt）。"""
    if not task_id:
        return True  # 阶段无考试要求，视为通过
    attempt = ExamAttempt.query.filter_by(
        employee_id=employee_id, task_id=task_id, status='submitted'
    ).order_by(ExamAttempt.score.desc()).first()
    return bool(attempt and attempt.passed)


def _stage_completed(employee_id: str, stage: dict) -> bool:
    """员工是否完成某阶段（所有课程完成 + 考试通过）。"""
    for cid in (stage.get('courseIds') or []):
        if not _is_course_completed(employee_id, cid):
            return False
    if not _is_exam_passed(employee_id, stage.get('examTaskId')):
        return False
    return True


def compute_assignment_progress(assignment: LearningPathAssignment) -> None:
    """实时计算并更新某员工的路径进度（写 assignment 字段，不 commit）。"""
    path = assignment.path
    if not path or not path.stages:
        return
    stages: List[dict] = path.stages
    employee_id = assignment.employee_id

    # 统计总课程数与已完成课程数
    all_course_ids: List[str] = []
    for s in stages:
        all_course_ids.extend(s.get('courseIds') or [])
    total_courses = len(all_course_ids)
    completed_courses = sum(
        1 for cid in all_course_ids if _is_course_completed(employee_id, cid)
    )
    assignment.progress = int(completed_courses / total_courses * 100) if total_courses else 0

    # 闯关：current_stage = 第一个未完成阶段
    current_stage = len(stages)  # 默认全部完成
    for i, stage in enumerate(stages):
        if not _stage_completed(employee_id, stage):
            current_stage = i
            break
    assignment.current_stage = current_stage

    # 是否全部完成
    all_done = current_stage >= len(stages) and total_courses > 0
    if all_done and not assignment.is_completed:
        assignment.is_completed = True
        assignment.completed_at = datetime.utcnow()
    assignment.updated_at = datetime.utcnow()
