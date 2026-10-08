"""只读深挖：最高分员工错题积分来源与全站错题掌握分布（不写任何数据）。"""
import sys
from collections import Counter, defaultdict

sys.path.insert(0, '/app')

from models import (
    Employee,
    ExamAttempt,
    PointLog,
    WrongQuestion,
    db,
)
from app import create_app

def short(value):
    return (value or '')[:8]


app = create_app()
with app.app_context():
    # 全站 wrong_question_mastered 分布
    mastered_logs = PointLog.query.filter_by(action='wrong_question_mastered').all()
    per_emp = Counter(log.employee_id for log in mastered_logs)
    print('== wrong_question_mastered 全站分布 ==')
    print('counts_by_employee:', sorted(per_emp.items(), key=lambda kv: -kv[1])[:15])

    top_emp = Employee.query.filter_by(name='王静').first()
    if top_emp is None:
        raise SystemExit('王静不存在')
    emp = top_emp
    top_id = emp.id
    print(f"\n== 王静 {emp.employee_no} id={short(top_id)} ==")
    wq_rows = WrongQuestion.query.filter_by(employee_id=top_id).all()
    print(f'wrong_questions_rows={len(wq_rows)}')
    question_counts = Counter(row.question_id for row in wq_rows)
    dup_questions = {q: c for q, c in question_counts.items() if c > 1}
    print(
        f'distinct_question_ids={len(question_counts)} '
        f'duplicate_question_ids={len(dup_questions)}'
    )
    if dup_questions:
        print('duplicate question_ids:', {short(k): v for k, v in dup_questions.items()})
    mastery = Counter(row.mastery for row in wq_rows)
    print('mastery_status:', dict(mastery))

    mastered_wq = [row for row in wq_rows if row.mastery == 'mastered']
    print(f'mastered_rows={len(mastered_wq)}')
    # 每条 mastered 错题的 point_log ref_id 对应
    mastered_refs = {row.id for row in mastered_wq}
    m_logs = PointLog.query.filter_by(
        employee_id=top_id, action='wrong_question_mastered'
    ).all()
    print(f'wrong_question_mastered logs={len(m_logs)}')
    log_refs = {log.ref_id for log in m_logs}
    missing = log_refs - mastered_refs
    extra = mastered_refs - log_refs
    print(f'logs_without_wq_row={len(missing)} wq_mastered_without_log={len(extra)}')
    # created_at 时间跨度
    times = sorted(log.created_at for log in m_logs)
    if times:
        print(f'mastered_log_first={times[0]} last={times[-1]}')

    # 考试与得分（解释错题来源）
    attempts = (
        ExamAttempt.query.filter_by(employee_id=top_id)
        .order_by(ExamAttempt.submitted_at.asc())
        .all()
    )
    print('\n== 王静考试记录 ==')
    for attempt in attempts:
        print(
            f"  task={short(attempt.task_id)} paper={short(attempt.paper_id)} "
            f"score={attempt.score} total={attempt.total_score} pass={attempt.pass_score} "
            f"passed={attempt.passed} status={attempt.status} "
            f"submitted_at={attempt.submitted_at}"
        )

    # 对比：其他高分段员工（马雅雯 355）
    for other_name in ['马雅雯', '贾靓']:
        emp2 = Employee.query.filter_by(name=other_name).first()
        if emp2 is None:
            print(f'\n== {other_name}: employee not found by prefix (skip) ==')
            continue
        logs2 = PointLog.query.filter_by(employee_id=emp2.id).all()
        by_action = Counter(log.action for log in logs2)
        print(f"\n== {other_name} ({emp2.employee_no}) id={short(emp2.id)} ==")
        print('  rows_by_action:', dict(by_action))
        wq2 = WrongQuestion.query.filter_by(employee_id=emp2.id).all()
        print(f'  wrong_questions_rows={len(wq2)} distinct_questions={len(set(r.question_id for r in wq2))}')
