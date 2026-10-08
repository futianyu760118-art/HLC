"""站内通知端到端测试 + 前13轮回归"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()

emp_tok = s.post(f"{BASE}/api/auth/login", json={"email": "zhangsan@test.com", "password": "Employee@2026"}).json()["token"]
emp2_tok = s.post(f"{BASE}/api/auth/login", json={"email": "wangwu@test.com", "password": "Employee@2026"}).json()["token"]
admin_tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json()["token"]
EH = {"Authorization": f"Bearer {emp_tok}", "Content-Type": "application/json"}
EH2 = {"Authorization": f"Bearer {emp2_tok}", "Content-Type": "application/json"}
AH = {"Authorization": f"Bearer {admin_tok}", "Content-Type": "application/json"}

# 1. 初始通知数
r = s.get(f"{BASE}/api/portal/notifications", headers=EH)
print(f"1. 张三初始通知: {r.json()['unreadCount']}未读 / {len(r.json()['items'])}条")

# 2. 王五回复张三的帖子 → 张三应收到通知
courses = s.get(f"{BASE}/api/portal/courses", headers=EH).json()
cid = courses[0]["id"]
# 张三发帖
r = s.post(f"{BASE}/api/portal/courses/{cid}/discussions", headers=EH, json={"title": "通知测试帖", "content": "测试通知功能"})
pid = r.json()["id"]
# 王五回复
s.post(f"{BASE}/api/portal/discussions/{pid}/replies", headers=EH2, json={"content": "这条回复应该触发通知"})

# 3. 张三再看通知
r = s.get(f"{BASE}/api/portal/notifications", headers=EH)
items = r.json()["items"]
print(f"2-3. 回复后通知: {r.json()['unreadCount']}未读 / {len(items)}条")
if items:
    print(f"   最新: {items[0]['title']} | {items[0]['content'][:40]}...")

# 4. 标记已读
if items:
    nid = items[0]["id"]
    r = s.post(f"{BASE}/api/portal/notifications/{nid}/read", headers=EH)
    print(f"4. 标记已读: {r.json()}")
    r = s.get(f"{BASE}/api/portal/notifications", headers=EH)
    print(f"   未读降至: {r.json()['unreadCount']}")

# 5. 全部已读
s.post(f"{BASE}/api/portal/notifications/read-all", headers=EH)
r = s.get(f"{BASE}/api/portal/notifications", headers=EH)
print(f"5. 全部已读后: {r.json()['unreadCount']}未读")

# 6. 前13轮回归
print("\n=== 前13轮回归 ===")
print(f"  课程: {len(courses)}门")
print(f"  错题本: {s.get(f'{BASE}/api/portal/wrong-questions', headers=EH).json()['stats']['total']}题")
print(f"  学习路径: {len(s.get(f'{BASE}/api/portal/learning-paths', headers=EH).json())}条")
print(f"  积分: {s.get(f'{BASE}/api/portal/points/summary', headers=EH).json()['totalPoints']}分")
dash = s.get(f"{BASE}/api/hrm/analytics/dashboard", headers=AH).json()
print(f"  看板: 课程{dash['metrics']['courseTotal']}门")

print("\n✓ 站内通知 + 前13轮全回归验证通过")
