"""只读核验：错题本不计分规则下的排行榜与目标员工积分。"""
import sys

sys.path.insert(0, '/app')

from models import Employee, PointLog, db
from app import create_app
from services.points import get_employee_total_points, get_leaderboard


app = create_app()
with app.app_context():
    print('== LEADERBOARD (new rule, wrong_question_mastered excluded) ==')
    for row in get_leaderboard(limit=15):
        print(
            f"  {row['rank']:>2}. {row['employeeName']} ({row['department']}) "
            f"total={row['totalPoints']} last={row['lastAwardAt']}"
        )
    mastery_rows = PointLog.query.filter_by(action='wrong_question_mastered').count()
    print(f'wrong_question_mastered_rows_remaining={mastery_rows}')
    for name in ['王静', '马雅雯', '贾靓']:
        emp = Employee.query.filter_by(name=name).first()
        if emp is None:
            print(f'{name}: not found')
            continue
        print(
            f'{name} ({emp.employee_no}): total={get_employee_total_points(emp.id)} '
            f'raw_sum='
            f'{sum(int(l.points or 0) for l in PointLog.query.filter_by(employee_id=emp.id).all())}'
        )
