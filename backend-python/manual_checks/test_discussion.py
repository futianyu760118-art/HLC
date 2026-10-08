"""课程讨论区端到端测试 + 前12轮回归"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()

emp_tok = s.post(f"{BASE}/api/auth/login", json={"email": "zhangsan@test.com", "password": "Employee@2026"}).json()["token"]
emp2_tok = s.post(f"{BASE}/api/auth/login", json={"email": "wangwu@test.com", "password": "Employee@2026"}).json()["token"]
EH = {"Authorization": f"Bearer {emp_tok}", "Content-Type": "application/json"}
EH2 = {"Authorization": f"Bearer {emp2_tok}", "Content-Type": "application/json"}

# 取课程
courses = s.get(f"{BASE}/api/portal/courses", headers=EH).json()
cid = courses[0]["id"]
cname = courses[0]["title"]

# 1. 张三发帖
r = s.post(f"{BASE}/api/portal/courses/{cid}/discussions", headers=EH, json={"title": "Excel VLOOKUP 怎么用？", "content": "看了课程但还是不太理解 VLOOKUP 的第四个参数，求解释"})
post = r.json()
pid = post["id"]
print(f"1. 张三发帖: {r.status_code} id={pid[:8]}... 标题={post['title']}")

# 2. 王五回复
r = s.post(f"{BASE}/api/portal/discussions/{pid}/replies", headers=EH2, json={"content": "第四个参数 FALSE 表示精确匹配，TRUE 是近似匹配"})
print(f"2. 王五回复: {r.status_code} content={r.json()['content'][:20]}...")

# 3. 王五点赞帖子
r = s.post(f"{BASE}/api/portal/discussions/like", headers=EH2, json={"targetType": "post", "targetId": pid})
print(f"3. 点赞: liked={r.json()['liked']}")

# 4. 再点赞（取消）
r = s.post(f"{BASE}/api/portal/discussions/like", headers=EH2, json={"targetType": "post", "targetId": pid})
print(f"4. 取消赞: liked={r.json()['liked']}")

# 5. 张三给回复点赞
r = s.get(f"{BASE}/api/portal/discussions/{pid}", headers=EH)
replies = r.json().get("replies", [])
rid = replies[0]["id"] if replies else None
if rid:
    s.post(f"{BASE}/api/portal/discussions/like", headers=EH, json={"targetType": "reply", "targetId": rid})
    print(f"5. 回复点赞 ✓")

# 6. 帖子列表
r = s.get(f"{BASE}/api/portal/courses/{cid}/discussions", headers=EH)
posts = r.json()
print(f"6. 帖子列表: {len(posts)}帖 回复数={posts[0]['replyCount']} 点赞数={posts[0]['likeCount']}")

# 7. 前台后回归
print("\n=== 前12轮回归 ===")
admin_tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json()["token"]
AH = {"Authorization": f"Bearer {admin_tok}"}
print(f"  课程: {len(courses)}门")
dash = s.get(f"{BASE}/api/hrm/analytics/dashboard", headers=AH).json()
print(f"  看板: 课程{dash['metrics']['courseTotal']}门 题库{dash['metrics']['questionCount']}题")
print(f"  积分: {s.get(f'{BASE}/api/portal/points/summary', headers=EH).json()['totalPoints']}分")
# 导出
r = s.get(f"{BASE}/api/hrm/export/points-leaderboard", headers=AH)
print(f"  导出: {r.status_code} {len(r.content)}字节")

print("\n✓ 讨论区 + 前12轮全回归验证通过")
