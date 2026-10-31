"""只读诊断：学习门户积分排行榜与最高分员工积分构成（不写任何数据）。"""
import statistics
import sys
from collections import Counter, defaultdict

sys.path.insert(0, '/app')

from models import (
    Certificate,
    Employee,
    ExamAttempt,
    PointLog,
    POINT_RULES,
    Reward,
    UserCourseProgress,
    db,
)
from app import create_app
from services.points import get_employee_total_points, get_leaderboard, _summarize_logs


def short(eid):
    return (eid or '')[:8]


app = create_app()
with app.app_context():
    board = get_leaderboard(limit=20)
    print('== LEADERBOARD (portal logic, deduped) ==')
    for row in board:
        print(
            f"  {row['rank']:>2}. {row['employeeName']} "
            f"id={short(row['employeeId'])} dept={row['department']} "
            f"total={row['totalPoints']} last={row['lastAwardAt']}"
        )

    logs_all = PointLog.query.all()
    totals, _ = _summarize_logs(logs_all)
    vals = sorted((summary['total'] for summary in totals.values()), reverse=True)
    print(f"\n== DISTRIBUTION == employees_with_points={len(vals)} raw_rows={len(logs_all)}")
    print('top15 totals:', vals[:15])
    if vals:
        p90 = vals[int(len(vals) * 0.9) - 1] if len(vals) >= 10 else vals[-1]
        print(
            f"mean={sum(vals) / len(vals):.1f} "
            f"median={statistics.median(vals)} p90={p90} max={vals[0]}"
        )

    print('\n== ABNORMAL AMOUNTS (POINT_RULES action with wrong points) ==')
    bad = [
        log for log in logs_all
        if log.action in POINT_RULES and int(log.points or 0) != POINT_RULES[log.action]
    ]
    print(f'count={len(bad)}')
    for log in bad[:30]:
        print(
            f"  emp={short(log.employee_id)} {log.action} points={log.points} "
            f"ref={short(log.ref_id)} {log.created_at}"
        )

    exchanges = [log for log in logs_all if log.action == 'reward_exchange']
    print(f'\n== EXCHANGES (reward_exchange) == count={len(exchanges)}')
    for log in exchanges[:20]:
        print(
            f"  emp={short(log.employee_id)} points={log.points} "
            f"detail={log.detail} {log.created_at}"
        )

    if board:
        top = board[0]
        emp_id = top['employeeId']
        emp = db.session.get(Employee, emp_id)
        logs = (
            PointLog.query.filter_by(employee_id=emp_id)
            .order_by(PointLog.created_at.asc())
            .all()
        )
        print(
            f"\n== TOP EMPLOYEE {emp.name if emp else '?'} "
            f"no={emp.employee_no if emp else '?'} id={short(emp_id)} =="
        )
        print(
            f"portal_total(deduped)={get_employee_total_points(emp_id)} "
            f"raw_sum={sum(int(log.points or 0) for log in logs)} rows={len(logs)}"
        )
        print('rows_by_action:', dict(Counter(log.action for log in logs)))
        by_action_pts = defaultdict(int)
        for log in logs:
            by_action_pts[log.action] += int(log.points or 0)
        print('points_by_action:', dict(by_action_pts))
        by_month = defaultdict(int)
        for log in logs:
            by_month[str(log.created_at)[:7]] += int(log.points or 0)
        print('points_by_month:', dict(sorted(by_month.items())))

        attempts = ExamAttempt.query.filter_by(employee_id=emp_id).all()
        submitted = [attempt for attempt in attempts if attempt.status == 'submitted']
        passed = [attempt for attempt in submitted if attempt.passed]
        print(
            f'exam_attempt_rows={len(attempts)} submitted={len(submitted)} '
            f'passed={len(passed)}'
        )
        task_counts = Counter(
            (attempt.task_id or attempt.paper_id or attempt.assignment_id)
            for attempt in submitted
        )
        repeated = {k: v for k, v in task_counts.items() if v > 1}
        print('submitted_attempts_grouped(>1):', {short(k): v for k, v in repeated.items()})

        progress = UserCourseProgress.query.filter_by(employee_id=emp_id).all()
        print(
            f'course_progress_rows={len(progress)} '
            f'finished_courses={sum(1 for p in progress if p.is_finished)}'
        )
        certs = Certificate.query.filter_by(employee_id=emp_id).all()
        print(f'certificates={len(certs)}')

        ref_groups = Counter((log.action, log.ref_id) for log in logs)
        dup = {k: v for k, v in ref_groups.items() if v > 1}
        print('duplicate (action,ref_id) groups:', {f'{k[0]}:{short(k[1])}': v for k, v in dup.items()})
