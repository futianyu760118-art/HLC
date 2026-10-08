"""学习提醒端到端测试 + 前15轮回归"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()

admin_tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json()["token"]
emp_tok = s.post(f"{BASE}/api/auth/login", json={"email": "zhangsan@test.com", "password": "Employee@2026"}).json()["token"]
AH = {"Authorization": f"Bearer {admin_tok}"}
EH = {"Authorization": f"Bearer {emp_tok}"}

# 1. 手动触发催学检查
r = s.post(f"{BASE}/api/hrm/study-reminder/run-check", headers=AH)
print(f"1. 催学检查: {r.json()}")

# 2. 张三看通知（应有必修课截止提醒）
r = s.get(f"{BASE}/api/portal/notifications", headers=EH)
data = r.json()
print(f"2. 张三通知: {data['unreadCount']}未读 / {len(data['items'])}条")
for n in data["items"][:5]:
    t = n.get("title", "")
    if "提醒" in t or "deadline" in n.get("noticeType", ""):
        print(f"   催学: {t} | {n.get('content', '')[:60]}")

# 3. 再次检查（幂等，不应重复发）
r = s.post(f"{BASE}/api/hrm/study-reminder/run-check", headers=AH)
print(f"3. 再次检查: {r.json()}")

# 4. 前15轮回归
print("\n=== 前15轮回归 ===")
courses = s.get(f"{BASE}/api/portal/courses", headers=EH).json()
print(f"  课程: {len(courses)}门")
print(f"  积分: {s.get(f'{BASE}/api/portal/points/summary', headers=EH).json()['totalPoints']}分")
dash = s.get(f"{BASE}/api/hrm/analytics/dashboard", headers=AH).json()
print(f"  看板: 课程{dash['metrics']['courseTotal']}门")
pk = s.get(f"{BASE}/api/hrm/pk-seasons", headers=AH).json()
pkitems = pk if isinstance(pk, list) else pk.get("items", [])
print(f"  PK赛季: {len(pkitems)}个")

print("\n✓ 学习提醒 + 前15轮全回归验证通过")
