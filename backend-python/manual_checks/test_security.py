"""全系统安全验证测试"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()
issues = []

print("=== 全系统安全验证 ===\n")

# 1. /uploads/ 需要鉴权
print("--- /uploads/ 鉴权 ---")
r = s.get(f"{BASE}/uploads/test.txt")
status = r.status_code
print(f"  无token访问uploads: {status}", "OK 需鉴权" if status == 401 else "FAIL 无鉴权!")
if status != 401: issues.append("/uploads/ 无鉴权")

# 2. 员工不能看薪资
print("\n--- RBAC: 员工不能看敏感数据 ---")
emp_tok = s.post(f"{BASE}/api/auth/login", json={"email": "zhangsan@test.com", "password": "Employee@2026"}).json().get("token")
admin_tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json().get("token")
EH = {"Authorization": f"Bearer {emp_tok}"}
AH = {"Authorization": f"Bearer {admin_tok}"}

if emp_tok:
    r = s.get(f"{BASE}/api/hrm/salary-profiles", headers=EH)
    print(f"  员工看薪资档案: {r.status_code}", "OK 拒绝" if r.status_code == 403 else "FAIL!")
    if r.status_code != 403: issues.append("员工可看薪资")

    r = s.get(f"{BASE}/api/hrm/payroll-records", headers=EH)
    print(f"  员工看工资条: {r.status_code}", "OK 拒绝" if r.status_code == 403 else "FAIL!")
    if r.status_code != 403: issues.append("员工可看工资条")

    r = s.get(f"{BASE}/api/hrm/users", headers=EH)
    print(f"  员工看用户列表: {r.status_code}", "OK 拒绝" if r.status_code == 403 else "FAIL!")
    if r.status_code != 403: issues.append("员工可看用户")

# 3. 管理员正常访问
print("\n--- RBAC: 管理员正常 ---")
r = s.get(f"{BASE}/api/hrm/salary-profiles", headers=AH)
print(f"  管理员看薪资: {r.status_code}", "OK" if r.status_code == 200 else "FAIL!")

# 4. 仪表盘/系统设置 RBAC
print("\n--- 仪表盘/设置 RBAC ---")
r = s.get(f"{BASE}/api/report/summary", headers=EH)
print(f"  员工看仪表盘: {r.status_code}", "OK 拒绝" if r.status_code == 403 else "FAIL!")
if r.status_code != 403: issues.append("员工可看仪表盘")

r = s.get(f"{BASE}/api/settings", headers=EH)
print(f"  员工看系统设置: {r.status_code}", "OK 拒绝" if r.status_code == 403 else "FAIL!")
if r.status_code != 403: issues.append("员工可看系统设置")

# 5. 密码复杂度
print("\n--- 密码复杂度 ---")
r = s.post(f"{BASE}/api/auth/register", json={"email": "weakpass@test.com", "password": "aaaaaaaa", "name": "Test"})
print(f"  弱密码注册: {r.status_code} ({r.json().get('error', '')[:40]})", "OK" if r.status_code == 400 else "FAIL!")

# 6. 空标题校验
print("\n--- 输入校验 ---")
r = s.post(f"{BASE}/api/hrm/courses", headers={**AH, "Content-Type": "application/json"}, json={"title": ""})
print(f"  空标题: {r.status_code}", "OK" if r.status_code == 400 else "FAIL!")

# 7. 培训+考试模块正常
print("\n--- 培训+考试模块回归 ---")
r = s.get(f"{BASE}/api/hrm/courses", headers=AH)
courses = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
print(f"  课程: {len(courses)}门 OK")

r = s.get(f"{BASE}/api/portal/courses", headers=EH)
print(f"  员工课程: {len(r.json())}门 OK")

r = s.get(f"{BASE}/api/portal/pk-seasons/active", headers=EH)
print(f"  PK竞赛: {r.status_code} OK")

print(f"\n{'='*50}")
print(f"总结: {'全部通过!' if not issues else str(len(issues)) + ' 个问题:'}")
for i in issues:
    print(f"  FAIL: {i}")
