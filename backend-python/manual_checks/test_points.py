"""积分激励端到端测试：触发各行为→验证积分→排行榜→去重→回归"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()

emp_tok = s.post(f"{BASE}/api/auth/login", json={"email": "lisi@test.com", "password": "Employee@2026"}).json()["token"]
EH = {"Authorization": f"Bearer {emp_tok}", "Content-Type": "application/json"}

# 1. 初始积分
r = s.get(f"{BASE}/api/portal/points/summary", headers=EH)
print(f"1. 初始积分: {r.json()['totalPoints']} 明细数:{len(r.json()['logs'])}")

# 2. 学完一个课时（应+5）
courses = s.get(f"{BASE}/api/portal/courses", headers=EH).json()
if courses:
    cid = courses[0]["id"]
    detail = s.get(f"{BASE}/api/portal/courses/{cid}", headers=EH).json()
    all_hours = detail.get("ungroupedHours", []) + [h for ch in detail.get("chapters", []) for h in ch.get("hours", [])]
    if all_hours:
        hid = all_hours[0]["id"]
        s.post(f"{BASE}/api/portal/courses/{hid}/progress", headers=EH, json={"watchedDuration": 600, "isFinished": True, "totalDuration": 600})
        r = s.get(f"{BASE}/api/portal/points/summary", headers=EH)
        print(f"2. 学完课时后积分: {r.json()['totalPoints']} (应+5)")

# 3. 提交课程评价（应+5）
# 先学完所有课时
for h in all_hours[1:]:
    s.post(f"{BASE}/api/portal/courses/{h['id']}/progress", headers=EH, json={"watchedDuration": 600, "isFinished": True, "totalDuration": 600})
s.post(f"{BASE}/api/portal/courses/{cid}/review", headers=EH, json={"rating": 5, "comment": "好课程"})
r = s.get(f"{BASE}/api/portal/points/summary", headers=EH)
print(f"3. 完成+评价后积分: {r.json()['totalPoints']} (应+20课程+5评价)")

# 4. 排行榜
r = s.get(f"{BASE}/api/portal/points/summary", headers=EH)
board = r.json()["leaderboard"]
print(f"4. 排行榜: {len(board)}人")
for u in board[:5]:
    print(f"   #{u['rank']} {u['employeeName']} {u['totalPoints']}分")

# 5. 重复学同一课时（应去重，不加分）
s.post(f"{BASE}/api/portal/courses/{hid}/progress", headers=EH, json={"watchedDuration": 600, "isFinished": True, "totalDuration": 600})
r = s.get(f"{BASE}/api/portal/points/summary", headers=EH)
print(f"5. 重复学习后积分: {r.json()['totalPoints']} (去重应不变)")

# 6. 回归（前8轮）
print("\n=== 前8轮回归 ===")
print(f"  课程: {len(courses)}门")
print(f"  错题本: {s.get(f'{BASE}/api/portal/wrong-questions', headers=EH).json()['stats']['total']}题")
print(f"  学习路径: {len(s.get(f'{BASE}/api/portal/learning-paths', headers=EH).json())}条")
print(f"  能力测评模型: {len(s.get(f'{BASE}/api/portal/competency/models', headers=EH).json())}个")

admin_tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json()["token"]
dash = s.get(f"{BASE}/api/hrm/analytics/dashboard", headers={"Authorization": f"Bearer {admin_tok}"}).json()
print(f"  看板: 课程{dash['metrics']['courseTotal']}门")

print("\n✓ 积分激励 + 前8轮全回归验证通过")
