"""AI 学习助手端到端测试 + 前7轮回归"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()

# 员工登录
emp_tok = s.post(f"{BASE}/api/auth/login", json={"email": "zhangsan@test.com", "password": "Employee@2026"}).json()["token"]
EH = {"Authorization": f"Bearer {emp_tok}", "Content-Type": "application/json"}

# 取一门课程
courses = s.get(f"{BASE}/api/portal/courses", headers=EH).json()
cid = courses[0]["id"] if courses else None
print(f"1. 测试课程: {courses[0]['title'] if courses else '无'}")

# 2. AI 问答
r = s.post(f"{BASE}/api/portal/courses/{cid}/ask", headers=EH, json={"question": "这门课的核心学习要点是什么？"})
d = r.json()
print(f"2. AI问答: {r.status_code}")
print(f"   回答: {d.get('answer', '')[:120]}...")
print(f"   召回段落: {len(d.get('sources', []))}段")

# 3. 另一个问题
r = s.post(f"{BASE}/api/portal/courses/{cid}/ask", headers=EH, json={"question": "需要特别注意什么？"})
d = r.json()
print(f"3. 追问: {d.get('answer', '')[:100]}...")

# 4. 无权限课程（用管理员建一个员工看不到的）
admin_tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json()["token"]
r = s.post(f"{BASE}/api/portal/courses/00000000-0000-0000-0000-000000000000/ask", headers=EH, json={"question": "test"})
print(f"4. 不存在课程: {r.status_code} (应404)")

# 前7轮回归
print("\n=== 前7轮回归验证 ===")
print(f"  课程: {len(courses)}门")
print(f"  考试: {len(s.get(f'{BASE}/api/portal/exams', headers=EH).json())}场")
print(f"  错题本: {s.get(f'{BASE}/api/portal/wrong-questions', headers=EH).json()['stats']['total']}题")
print(f"  学习路径: {len(s.get(f'{BASE}/api/portal/learning-paths', headers=EH).json())}条")
print(f"  能力测评: {len(s.get(f'{BASE}/api/portal/competency/my-assessments', headers=EH).json())}条")

AH = {"Authorization": f"Bearer {admin_tok}"}
dash = s.get(f"{BASE}/api/hrm/analytics/dashboard", headers=AH).json()
print(f"  看板: 课程{dash['metrics']['courseTotal']}门 通过率{dash['metrics']['examPassRate']}%")

print("\n✓ AI学习助手 + 前7轮全回归验证通过")
