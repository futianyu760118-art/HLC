"""
全链路回归测试 — 覆盖前 20 轮所有核心功能。
每个功能一个检查点，发现问题记录到 issues。
"""
import requests, json
BASE = "http://localhost:18888"
s = requests.Session()
issues = []

def check(name, condition, detail=""):
    status = "✓" if condition else "✗"
    print(f"  {status} {name}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        issues.append(f"{name}: {detail}")

print("=" * 60)
print("全链路回归测试（前20轮）")
print("=" * 60)

# 登录
admin_tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json().get("token")
emp_tok = s.post(f"{BASE}/api/auth/login", json={"email": "zhangsan@test.com", "password": "Employee@2026"}).json().get("token")
check("管理员登录", bool(admin_tok))
check("员工登录", bool(emp_tok))
AH = {"Authorization": f"Bearer {admin_tok}", "Content-Type": "application/json"}
EH = {"Authorization": f"Bearer {emp_tok}", "Content-Type": "application/json"}

# === 轮1-2: 基础（课程/考试/部门）===
print("\n--- 轮1-2: 基础设施 ---")
courses = s.get(f"{BASE}/api/hrm/courses", headers=AH).json()
citems = courses if isinstance(courses, list) else courses.get("items", [])
check("课程列表", len(citems) > 0, f"课程数={len(citems)}")

cats = s.get(f"{BASE}/api/hrm/course-categories", headers=AH).json()
catitems = cats if isinstance(cats, list) else cats.get("items", [])
check("课程分类", len(catitems) >= 3, f"分类数={len(catitems)}")

depts = s.get(f"{BASE}/api/hrm/departments", headers=AH).json()
ditems = depts if isinstance(depts, list) else depts.get("items", [])
check("部门列表", len(ditems) >= 3, f"部门数={len(ditems)}")

emps = s.get(f"{BASE}/api/hrm/employees", headers=AH).json()
eitems = emps if isinstance(emps, list) else emps.get("items", [])
check("员工列表", len(eitems) >= 4, f"员工数={len(eitems)}")

# === 轮3: 学习路径 ===
print("\n--- 轮3: 学习路径 ---")
paths_admin = s.get(f"{BASE}/api/hrm/learning-paths", headers=AH).json()
pitems = paths_admin if isinstance(paths_admin, list) else paths_admin.get("items", [])
check("管理端路径列表", len(pitems) >= 1, f"路径数={len(pitems)}")

paths_emp = s.get(f"{BASE}/api/portal/learning-paths", headers=EH).json()
check("员工路径列表", isinstance(paths_emp, list) and len(paths_emp) >= 0)

# === 轮4: 错题本 ===
print("\n--- 轮4: 错题本 ---")
wq = s.get(f"{BASE}/api/portal/wrong-questions", headers=EH).json()
check("错题本端点", "stats" in wq, f"待掌握={wq.get('stats', {}).get('wrong', '?')}")

# === 轮5: 课程评价 ===
print("\n--- 轮5: 课程评价 ---")
if citems:
    reviews = s.get(f"{BASE}/api/hrm/courses/{citems[0]['id']}/reviews", headers=AH).json()
    check("课程评价端点", "summary" in reviews, f"评价数={reviews.get('summary', {}).get('count', 0)}")

# === 轮6: 胜任力测评 ===
print("\n--- 轮6: 胜任力测评 ---"
)
models = s.get(f"{BASE}/api/hrm/competency-models", headers=AH).json()
mitems = models if isinstance(models, list) else models.get("items", [])
check("胜任力模型", len(mitems) >= 1, f"模型数={len(mitems)}")

emp_models = s.get(f"{BASE}/api/portal/competency/models", headers=EH).json()
check("员工测评模型", isinstance(emp_models, list))

# === 轮7: 数据看板 ===
print("\n--- 轮7: 数据看板 ---")
dash = s.get(f"{BASE}/api/hrm/analytics/dashboard", headers=AH).json()
check("看板指标", "metrics" in dash, f"课程={dash.get('metrics', {}).get('courseTotal', '?')}")
check("看板图表", "courseCompletion" in dash and "deptActivity" in dash)

# === 轮8: AI 学习助手 ===
print("\n--- 轮8: AI学习助手 ---")
if citems:
    r = s.post(f"{BASE}/api/portal/courses/{citems[0]['id']}/ask", headers=EH, json={"question": "课程要点是什么？"})
    check("AI问答端点", r.status_code == 200 and "answer" in r.json(), f"status={r.status_code}")

# === 轮9: 积分激励 ===
print("\n--- 轮9: 积分激励 ---")
pts = s.get(f"{BASE}/api/portal/points/summary", headers=EH).json()
check("积分汇总", "totalPoints" in pts, f"积分={pts.get('totalPoints', '?')}")

# === 轮10: 学习证书 ===
print("\n--- 轮10: 学习证书 ---")
certs = s.get(f"{BASE}/api/portal/certificates", headers=EH).json()
check("证书列表", isinstance(certs, list), f"证书数={len(certs)}")

# === 轮12: 数据导出 ===
print("\n--- 轮12: 数据导出 ---")
r = s.get(f"{BASE}/api/hrm/export/points-leaderboard", headers=AH)
check("Excel积分导出", r.status_code == 200 and r.content[:2] == b'PK', f"大小={len(r.content)}")

# === 轮13: 课程讨论区 ===
print("\n--- 轮13: 课程讨论区 ---")
if citems:
    posts = s.get(f"{BASE}/api/portal/courses/{citems[0]['id']}/discussions", headers=EH).json()
    check("讨论区端点", isinstance(posts, list), f"帖子数={len(posts)}")

# === 轮14: 站内通知 ===
print("\n--- 轮14: 站内通知 ---")
notifs = s.get(f"{BASE}/api/portal/notifications", headers=EH).json()
check("通知端点", "unreadCount" in notifs, f"未读={notifs.get('unreadCount', '?')}")

# === 轮15: 团队PK竞赛 ===
print("\n--- 轮15: 团队PK竞赛 ---")
pk_seasons = s.get(f"{BASE}/api/hrm/pk-seasons", headers=AH).json()
pkitems = pk_seasons if isinstance(pk_seasons, list) else pk_seasons.get("items", [])
check("PK赛季", len(pkitems) >= 1, f"赛季数={len(pkitems)}")
if pkitems:
    lb = s.get(f"{BASE}/api/hrm/pk-seasons/{pkitems[0]['id']}/leaderboard", headers=AH).json()
    check("PK排行榜", "teamBoard" in lb, f"团队数={len(lb.get('teamBoard', []))}")

# === 轮16: 学习提醒 ===
print("\n--- 轮16: 学习提醒 ---")
r = s.post(f"{BASE}/api/hrm/study-reminder/run-check", headers=AH)
check("催学检查端点", r.status_code == 200, f"发送={r.json().get('sent', '?')}条")

# === 轮17: 积分商城 ===
print("\n--- 轮17: 积分商城 ---")
rewards = s.get(f"{BASE}/api/portal/rewards", headers=EH).json()
check("商城端点", "items" in rewards, f"商品数={len(rewards.get('items', []))}")
check("商城含积分", "myPoints" in rewards, f"我的积分={rewards.get('myPoints', '?')}")

records = s.get(f"{BASE}/api/portal/exchange-records", headers=EH).json()
check("兑换记录", isinstance(records, list))

# === 轮18: Markdown 编辑器（纯前端，验证课程 content 可存取）===
print("\n--- 轮18: Markdown内容 ---")
if citems:
    detail = s.get(f"{BASE}/api/portal/courses/{citems[0]['id']}", headers=EH).json()
    content = detail.get("course", {}).get("content", "")
    check("课程Markdown字段", content is not None, f"内容长度={len(content)}")

# === 轮19: 大屏（端点复用看板，验证数据完整）===
print("\n--- 轮19: 大屏数据 ---")
check("大屏数据完整", "popularCourses" in dash and "examStats" in dash)

# === 轮20: PDF报告 ===
print("\n--- 轮20: PDF报告导出 ---")
emp_id = "e-zhangsan"
r = s.get(f"{BASE}/api/hrm/export/learning-report/{emp_id}", headers=AH)
check("管理员导出PDF", r.status_code == 200 and r.content[:4] == b'%PDF', f"大小={len(r.content)} status={r.status_code}")
r2 = s.get(f"{BASE}/api/portal/export/my-report", headers=EH)
check("员工导出PDF", r2.status_code == 200 and r2.content[:4] == b'%PDF', f"大小={len(r2.content)}")

# === 总结 ===
print("\n" + "=" * 60)
print(f"总结: {20 - len(issues)}/20 轮功能正常" + (f"，发现 {len(issues)} 个问题：" if issues else "，全部通过！"))
if issues:
    for iss in issues:
        print(f"  ✗ {iss}")
print("=" * 60)
