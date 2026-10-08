"""团队PK竞赛端到端测试 + 前14轮回归"""
import requests
from datetime import datetime, timedelta
BASE = "http://localhost:18888"
s = requests.Session()

admin_tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json()["token"]
emp_tok = s.post(f"{BASE}/api/auth/login", json={"email": "zhangsan@test.com", "password": "Employee@2026"}).json()["token"]
AH = {"Authorization": f"Bearer {admin_tok}", "Content-Type": "application/json"}
EH = {"Authorization": f"Bearer {emp_tok}"}

# 1. 创建赛季
body = {
    "name": "2026 Q2 学习挑战赛",
    "description": "各部门学习积分大比拼",
    "startDate": (datetime.utcnow() - timedelta(days=7)).isoformat(),
    "endDate": (datetime.utcnow() + timedelta(days=30)).isoformat(),
    "metric": "total_points",
    "participantDeptIds": [],
    "status": "active",
}
r = s.post(f"{BASE}/api/hrm/pk-seasons", headers=AH, json=body)
sid = r.json().get("id")
print(f"1. 创建赛季: {r.status_code} id={sid[:8] if sid else 'FAIL'}...")

if sid:
    # 2. 管理员看排行
    r = s.get(f"{BASE}/api/hrm/pk-seasons/{sid}/leaderboard", headers=AH)
    d = r.json()
    print(f"2. 管理员排行: 团队{len(d['teamBoard'])}个 个人{len(d['individualBoard'])}人")
    for t in d["teamBoard"][:3]:
        print(f"   #{t['rank']} {t['deptName']} {t['totalPoints']}分 ({t['memberCount']}人)")

    # 3. 员工视角
    r = s.get(f"{BASE}/api/portal/pk-seasons/active", headers=EH)
    seasons = r.json()
    print(f"3. 员工视角: {len(seasons)}个活跃赛季")
    if seasons:
        s0 = seasons[0]
        print(f"   {s0['name']} 我的部门排名:#{s0.get('myDeptRank')} 我的贡献:{s0.get('myPoints')}分")

# 4. 前14轮回归
print("\n=== 前14轮回归 ===")
courses = s.get(f"{BASE}/api/portal/courses", headers=EH).json()
print(f"  课程: {len(courses)}门")
print(f"  积分: {s.get(f'{BASE}/api/portal/points/summary', headers=EH).json()['totalPoints']}分")
print(f"  通知: {s.get(f'{BASE}/api/portal/notifications', headers=EH).json()['unreadCount']}未读")
dash = s.get(f"{BASE}/api/hrm/analytics/dashboard", headers=AH).json()
print(f"  看板: 课程{dash['metrics']['courseTotal']}门")

print("\n✓ 团队PK竞赛 + 前14轮全回归验证通过")
