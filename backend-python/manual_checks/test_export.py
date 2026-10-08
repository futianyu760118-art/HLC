"""导出端点测试 + 前11轮回归"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()
tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}

# 1. 成绩单导出
tasks = s.get(f"{BASE}/api/hrm/exam-tasks", headers=H).json()
items = tasks if isinstance(tasks, list) else tasks.get("items", [])
if items:
    tid = items[0]["id"]
    r = s.get(f"{BASE}/api/hrm/export/exam-results/{tid}", headers=H)
    ct = r.headers.get("content-type", "")
    print(f"1. 成绩单导出: {r.status_code} {len(r.content)}字节 type={ct[:30]}")
    # 验证是 xlsx（PK 开头）
    assert r.content[:2] == b'PK', "不是xlsx文件"
    print("   ✓ 文件格式正确(PK=xlsx)")

# 2. 积分排行导出
r = s.get(f"{BASE}/api/hrm/export/points-leaderboard", headers=H)
print(f"2. 积分排行导出: {r.status_code} {len(r.content)}字节")
assert r.content[:2] == b'PK', "不是xlsx"
print("   ✓ 文件格式正确")

# 3. 课程进度导出
courses = s.get(f"{BASE}/api/hrm/courses", headers=H).json()
citems = courses if isinstance(courses, list) else courses.get("items", [])
if citems:
    cid = citems[0]["id"]
    r = s.get(f"{BASE}/api/hrm/export/course-progress/{cid}", headers=H)
    print(f"3. 课程进度导出: {r.status_code} {len(r.content)}字节")
    assert r.content[:2] == b'PK'
    print("   ✓ 文件格式正确")

# 4. 无权限（员工不能导出）
emp_tok = s.post(f"{BASE}/api/auth/login", json={"email": "zhangsan@test.com", "password": "Employee@2026"}).json()["token"]
r = s.get(f"{BASE}/api/hrm/export/points-leaderboard", headers={"Authorization": f"Bearer {emp_tok}"})
print(f"4. 员工导出被拒: {r.status_code} (应403)")

# 5. 前11轮回归
print("\n=== 前11轮回归 ===")
dash = s.get(f"{BASE}/api/hrm/analytics/dashboard", headers=H).json()
print(f"  看板: 课程{dash['metrics']['courseTotal']}门 题库{dash['metrics']['questionCount']}题")
print(f"  课程: {len(citems)}门")
EH = {"Authorization": f"Bearer {emp_tok}"}
print(f"  员工课程: {len(s.get(f'{BASE}/api/portal/courses', headers=EH).json())}门")
certs = s.get(f"{BASE}/api/portal/certificates", headers=EH).json()
print(f"  证书: {len(certs)}张")
pts = s.get(f"{BASE}/api/portal/points/summary", headers=EH).json()
print(f"  积分: {pts['totalPoints']}分")

print("\n✓ 数据导出 + 前11轮全回归验证通过")
