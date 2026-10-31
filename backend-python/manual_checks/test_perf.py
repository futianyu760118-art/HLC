"""验证看板+课程详情性能"""
import requests, time
BASE = "http://localhost:18888"
s = requests.Session()
tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}

# 看板
t0 = time.time()
r = s.get(f"{BASE}/api/hrm/analytics/dashboard", headers=H)
t1 = time.time()
d = r.json()
cc = len(d.get("courseCompletion", []))
da = len(d.get("deptActivity", []))
pc = len(d.get("popularCourses", []))
es = len(d.get("examStats", []))
print(f"看板: {r.status_code} 耗时:{round((t1-t0)*1000)}ms 课程{cc}/部门{da}/热门{pc}/考试{es}")

# 课程详情（员工视角）
emp_tok = s.post(f"{BASE}/api/auth/login", json={"email": "zhangsan@test.com", "password": "Employee@2026"}).json()["token"]
EH = {"Authorization": f"Bearer {emp_tok}"}
courses = s.get(f"{BASE}/api/portal/courses", headers=EH).json()
if courses:
    t0 = time.time()
    r = s.get(f"{BASE}/api/portal/courses/{courses[0]['id']}", headers=EH)
    t1 = time.time()
    detail = r.json()
    th = detail.get("totalHours", 0)
    print(f"课程详情: {r.status_code} 耗时:{round((t1-t0)*1000)}ms 课时{th}")

# 回归
r = s.get(f"{BASE}/api/portal/learning-paths", headers=EH)
print(f"学习路径: {r.status_code}")
r = s.get(f"{BASE}/api/portal/pk-seasons/active", headers=EH)
print(f"PK: {r.status_code}")
print("\n✓ 验证完成")
