"""课程可见性判定（参照 PlayEdu UserBus.canSeeCourse 平移到 HRM）。

规则：
1. 课程未上架(is_show=False) → 不可见
2. 课程无任何指派 → 全员可见（公开课）
3. 否则：
   a. 课程有 target_type='user' 且 target_id == employee.id → 可见
   b. 课程有 target_type='dept'，且员工部门或其祖先链命中 → 可见

部门祖先链：HRM 现有 Department 只有 parent_id（无 parent_chain），
故向上递归查询（部门层级通常 <5 层，性能可接受）。
"""

from __future__ import annotations

from typing import Set

from models import (
    Course, CourseAssignment, Department, Employee, UserCourseProgress, db,
)


def department_ancestor_ids(dept_id: str | None) -> Set[str]:
    """返回 dept_id 及其所有祖先 id（含自身）。无 dept_id 返回空集。"""
    result: Set[str] = set()
    if not dept_id:
        return result
    visited: Set[str] = set()
    current_id = dept_id
    while current_id and current_id not in visited:
        visited.add(current_id)
        result.add(current_id)
        dept = db.session.get(Department, current_id)
        if not dept:
            break
        current_id = dept.parent_id
    return result


def _assignment_index(course_id: str) -> dict:
    """返回 { 'dept_ids': set, 'user_ids': set, 'has_any': bool }。"""
    rows = CourseAssignment.query.filter_by(course_id=course_id).all()
    dept_ids, user_ids = set(), set()
    for a in rows:
        if a.target_type == 'dept':
            dept_ids.add(a.target_id)
        elif a.target_type == 'user':
            user_ids.add(a.target_id)
    return {'dept_ids': dept_ids, 'user_ids': user_ids, 'has_any': bool(rows)}


def can_see_course(employee: Employee, course: Course) -> bool:
    """单个课程可见性判定。"""
    if not course or not course.is_show:
        return False
    idx = _assignment_index(course.id)
    if not idx['has_any']:
        return True  # 无指派 = 全员可见
    if employee.id in idx['user_ids']:
        return True
    # 部门命中：员工部门或其祖先在指派部门集合内
    ancestor_ids = department_ancestor_ids(employee.department_id)
    if idx['dept_ids'] & ancestor_ids:
        return True
    return False


def employee_visible_courses(employee: Employee):
    """返回员工可见的课程列表（已上架）。

    批量预加载所有指派记录，避免逐课程 _assignment_index 的 N+1。
    """
    courses = Course.query.filter_by(is_show=True).all()
    if not courses:
        return []
    course_ids = [c.id for c in courses]
    # 一次性加载所有相关指派
    all_assignments = CourseAssignment.query.filter(
        CourseAssignment.course_id.in_(course_ids)
    ).all()
    # 按 course_id 建索引：{cid: {'dept_ids': set, 'user_ids': set, 'has_any': bool}}
    assign_index: dict[str, dict] = {}
    for a in all_assignments:
        idx = assign_index.setdefault(a.course_id, {'dept_ids': set(), 'user_ids': set(), 'has_any': False})
        idx['has_any'] = True
        if a.target_type == 'dept':
            idx['dept_ids'].add(a.target_id)
        elif a.target_type == 'user':
            idx['user_ids'].add(a.target_id)

    ancestor_ids = department_ancestor_ids(employee.department_id)
    emp_id = employee.id
    result = []
    for c in courses:
        idx = assign_index.get(c.id)
        if not idx or not idx['has_any']:
            result.append(c)  # 无指派 = 全员可见
            continue
        if emp_id in idx['user_ids']:
            result.append(c)
            continue
        if idx['dept_ids'] & ancestor_ids:
            result.append(c)
    return result


def course_assigned_employee_ids(course_id: str) -> Set[str]:
    """展开课程指派为具体员工 id 集合（进度统计/管理用）。

    - target_type='user' → 直接收
    - target_type='dept' → 该部门及其子部门所有在职员工（含部门树子孙）
    """
    idx = _assignment_index(course_id)
    if not idx['has_any']:
        # 全员可见：返回所有在职员工
        rows = Employee.query.filter(Employee.status.in_(
            ['active', 'pending_onboard', 'probation']
        )).with_entities(Employee.id).all()
        return {r[0] for r in rows}
    result: Set[str] = set(idx['user_ids'])
    for dept_id in idx['dept_ids']:
        # dept 及其子孙部门的员工
        descendant_ids = _department_descendant_ids(dept_id)
        if descendant_ids:
            rows = Employee.query.filter(
                Employee.department_id.in_(descendant_ids)
            ).with_entities(Employee.id).all()
            result.update(r[0] for r in rows)
    return result


def _department_descendant_ids(dept_id: str) -> Set[str]:
    """返回 dept_id 及其所有子孙部门 id（含自身）。"""
    result = {dept_id}
    # 子部门逐层下查（层级通常浅）
    pending = [dept_id]
    visited: Set[str] = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        children = Department.query.filter_by(parent_id=current).with_entities(Department.id).all()
        for (cid,) in children:
            if cid not in result:
                result.add(cid)
                pending.append(cid)
    return result
