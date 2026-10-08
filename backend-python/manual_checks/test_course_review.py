"""课程评价端到端测试：学完→评价→汇总→管理看板"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()

# 管理员 + 员工登录
admin_tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json()["token"]
emp_tok = s.post(f"{BASE}/api/auth/login", json={"email": "wangwu@test.com", "password": "Employee@2026"}).json()["token"]
AH = {"Authorization": f"Bearer {admin_tok}"}
EH = {"Authorization": f"Bearer {emp_tok}"}

# 取一门课程
courses = s.get(f"{BASE}/api/hrm/courses", headers=AH).json()
items = courses if isinstance(courses, list) else courses.get("items", [])
cid = items[0]["id"]
cname = items[0]["title"]
print(f"1. 测试课程: {cname} ({cid})")

# 2. 员工未学完就评价 → 应被拒
r = s.post(f"{BASE}/api/portal/courses/{cid}/review", headers=EH, json={"rating": 5})
print(f"2. 未学完评价: {r.status_code} {r.json().get('error', '通过?')}")

# 3. 员工学完课程（标记所有课时完成）
detail = s.get(f"{BASE}/api/portal/courses/{cid}", headers=EH).json()
all_hours = detail.get("ungroupedHours", []) + [h for ch in detail.get("chapters", []) for h in ch.get("hours", [])]
for h in all_hours:
    s.post(f"{BASE}/api/portal/courses/{h['id']}/progress", headers=EH, json={"watchedDuration": 600, "isFinished": True, "totalDuration": 600})
print(f"3. 学完 {len(all_hours)} 个课时")

# 4. 学完后评价
r = s.post(f"{BASE}/api/portal/courses/{cid}/review", headers=EH, json={
    "rating": 4, "contentQuality": 5, "clarity": 4, "practicality": 3,
    "comment": "内容很实用，但有些地方讲得快"
})
print(f"4. 提交评价: {r.status_code} rating={r.json().get('rating')}")

# 5. 查看课程评价汇总
r = s.get(f"{BASE}/api/portal/courses/{cid}/reviews", headers=EH)
d = r.json()
print(f"5. 评价汇总: {d['summary']}")

# 6. 修改评价（覆盖）
r = s.post(f"{BASE}/api/portal/courses/{cid}/review", headers=EH, json={"rating": 5, "comment": "重新看了一遍，确实好"})
print(f"6. 修改评价: rating={r.json().get('rating')} comment={r.json().get('comment')}")

# 7. 管理员看评分排行
r = s.get(f"{BASE}/api/hrm/courses/reviews-summary", headers=AH)
print(f"7. 管理员评分排行:")
for row in r.json():
    print(f"   {row['courseTitle']}: {row['avgRating']}星 ({row['reviewCount']}人)")

# 8. 管理员看某课程评价详情
r = s.get(f"{BASE}/api/hrm/courses/{cid}/reviews", headers=AH)
d = r.json()
print(f"8. 课程评价详情: {d['summary']}")
for rv in d["reviews"]:
    print(f"   {rv['employeeName']}: {rv['rating']}星 - {rv.get('comment', '')}")

# 9. 回归
print("\n=== 回归验证 ===")
print(f"   员工课程: {len(s.get(f'{BASE}/api/portal/courses', headers=EH).json())}门")
print(f"   错题本: {s.get(f'{BASE}/api/portal/wrong-questions', headers=EH).json()['stats']}")
print(f"   学习路径: {len(s.get(f'{BASE}/api/portal/learning-paths', headers=EH).json())}条")
print("\n✓ 课程评价全链路验证完成")
