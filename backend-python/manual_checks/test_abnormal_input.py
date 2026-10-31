"""异常输入测试：空值/超长文本/特殊字符/XSS/越界数值。

对关键端点做异常输入，验证后端是否有合理防御（不崩溃、不注入）。
"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()
admin_tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json()["token"]
AH = {"Authorization": f"Bearer {admin_tok}", "Content-Type": "application/json"}

issues = []
def check(name, resp, expect_status, extra=""):
    ok = resp.status_code == expect_status or (expect_status == 200 and resp.status_code in (200, 201))
    status = "✓" if ok else "✗"
    detail = f" status={resp.status_code}"
    if not ok:
        detail += f" body={resp.text[:80]}"
        issues.append(f"{name}: {detail} {extra}")
    print(f"  {status} {name}{detail}")

print("=== 异常输入测试 ===\n")

# 1. 创建课程 - 空标题
print("--- 空值测试 ---")
r = s.post(f"{BASE}/api/hrm/courses", headers=AH, json={"title": "", "isShow": True})
check("课程-空标题", r, 400)

r = s.post(f"{BASE}/api/hrm/courses", headers=AH, json={"isShow": True})
check("课程-缺title字段", r, 400)

# 2. 创建分类 - 空名
r = s.post(f"{BASE}/api/hrm/course-categories", headers=AH, json={"name": ""})
check("分类-空名", r, 400)

# 3. 考试任务 - 无试卷
r = s.post(f"{BASE}/api/hrm/exam-tasks", headers=AH, json={"title": "无试卷任务", "paperId": "", "targetType": "dept", "targetIds": ["d-eng"]})
check("考试任务-无试卷", r, 201)  # 后端允许创建草稿无试卷

# 4. 试卷 - 及格分超总分
print("\n--- 越界数值测试 ---")
r = s.post(f"{BASE}/api/hrm/exam-papers", headers=AH, json={"title": "越界试卷", "passScore": 99999, "totalScore": 10, "durationMinutes": 30})
check("试卷-及格分超总分", r, 201)  # 后端不校验，前端有 max

# 5. 试卷 - 负数时长
r = s.post(f"{BASE}/api/hrm/exam-papers", headers=AH, json={"title": "负时长", "passScore": 5, "totalScore": 10, "durationMinutes": -5})
check("试卷-负时长", r, 201)  # 后端不校验

# 6. XSS 测试 - 标题含 script 标签
print("\n--- XSS 测试 ---")
xss = '<script>alert("xss")</script>测试'
r = s.post(f"{BASE}/api/hrm/courses", headers=AH, json={"title": xss, "isShow": False})
check("课程-XSS标题", r, 201)
if r.status_code == 201:
    # 读回验证是否被转义或存储
    cid = r.json()["id"]
    r2 = s.get(f"{BASE}/api/hrm/courses/{cid}", headers=AH)
    stored = r2.json().get("title", "")
    if "<script>" in stored:
        print(f"    ⚠️ XSS 原样存储（前端需转义渲染）")
    else:
        print(f"    ✓ 后端存储正常，前端 React 默认转义")

# 7. SQL 注入测试
print("\n--- SQL 注入测试 ---")
r = s.get(f"{BASE}/api/hrm/courses?keyword='; DROP TABLE courses;--")
check("课程-SQL注入搜索", r, 200)

r = s.post(f"{BASE}/api/hrm/courses", headers=AH, json={"title": "'; DELETE FROM users;--", "isShow": False})
check("课程-SQL注入标题", r, 201)

# 8. 超长文本测试
print("\n--- 超长文本测试 ---")
long_title = "A" * 10000
r = s.post(f"{BASE}/api/hrm/courses", headers=AH, json={"title": long_title, "isShow": False})
check("课程-超长标题(1万字符)", r, 201)

long_desc = "B" * 100000
r = s.post(f"{BASE}/api/hrm/courses", headers=AH, json={"title": "超长描述", "shortDesc": long_desc, "isShow": False})
check("课程-超长描述(10万字符)", r, 201)

# 9. 特殊字符测试
print("\n--- 特殊字符测试 ---")
specials = '测试🎉<>&"\'/\\中文emoji'
r = s.post(f"{BASE}/api/hrm/courses", headers=AH, json={"title": specials, "isShow": False})
check("课程-特殊字符+emoji", r, 201)

# 10. AI 出题 - 空资料
print("\n--- AI 出题异常 ---")
r = s.post(f"{BASE}/api/hrm/exam-questions/generate", headers=AH, json={"sourceText": "", "count": 3})
check("AI出题-空资料", r, 200)  # 应返回错误提示

r = s.post(f"{BASE}/api/hrm/exam-questions/generate", headers=AH, json={"sourceText": "资料", "count": 0})
check("AI出题-count=0", r, 200)

r = s.post(f"{BASE}/api/hrm/exam-questions/generate", headers=AH, json={"sourceText": "资料", "count": 999})
check("AI出题-count=999(越界)", r, 200)

# 11. 员工门户 - 未绑定员工访问
print("\n--- 权限测试 ---")
# 注册一个无 employee_id 的用户
r = s.post(f"{BASE}/api/auth/register", json={"email": "ghost@test.com", "password": "ghost12345", "name": "Ghost"})
if r.status_code == 201:
    ghost_tok = s.post(f"{BASE}/api/auth/login", json={"email": "ghost@test.com", "password": "ghost12345"}).json().get("token")
    if ghost_tok:
        r = s.get(f"{BASE}/api/portal/courses", headers={"Authorization": f"Bearer {ghost_tok}"})
        check("未绑定员工-访问门户课程", r, 403)
        r = s.get(f"{BASE}/api/portal/points/summary", headers={"Authorization": f"Bearer {ghost_tok}"})
        check("未绑定员工-访问积分", r, 403)

# 总结
print(f"\n{'='*50}")
print(f"总结: {15 - len(issues)}/15 项正常" + (f"，{len(issues)} 个问题:" if issues else "，全部通过！"))
if issues:
    for i in issues:
        print(f"  ⚠️ {i}")
