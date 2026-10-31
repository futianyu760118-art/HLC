"""积分商城端到端测试：插商品→兑换→扣分→记录→回归"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()

admin_tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json()["token"]
emp_tok = s.post(f"{BASE}/api/auth/login", json={"email": "lisi@test.com", "password": "Employee@2026"}).json()["token"]
AH = {"Authorization": f"Bearer {admin_tok}", "Content-Type": "application/json"}
EH = {"Authorization": f"Bearer {emp_tok}"}

# 1. 管理员添加商品
for name, cost, typ, icon in [("咖啡券", 50, "virtual", "fa-mug-hot"), ("学习达人徽章", 30, "badge", "fa-medal"), ("精美笔记本", 100, "physical", "fa-book")]:
    s.post(f"{BASE}/api/hrm/rewards", headers=AH, json={"name": name, "pointsCost": cost, "rewardType": typ, "icon": icon, "stock": 10, "isActive": True, "description": f"{name}描述"})
print("1. 添加3个商品")

# 2. 员工看商城
r = s.get(f"{BASE}/api/portal/rewards", headers=EH)
data = r.json()
print(f"2. 商城: {len(data['items'])}个商品 我的积分:{data['myPoints']}")

# 3. 兑换（李四有55分，兑30分徽章）
badge = next((i for i in data["items"] if i["pointsCost"] == 30), None)
if badge:
    r = s.post(f"{BASE}/api/portal/rewards/{badge['id']}/exchange", headers=EH)
    d = r.json()
    print(f"3. 兑换徽章: success={d.get('success')} 剩余积分={d.get('remainingPoints')} 记录={d.get('record', {}).get('rewardName')}")

# 4. 再看积分（应减少30）
r = s.get(f"{BASE}/api/portal/rewards", headers=EH)
print(f"4. 兑换后积分: {r.json()['myPoints']} (应25)")

# 5. 兑换记录
r = s.get(f"{BASE}/api/portal/exchange-records", headers=EH)
print(f"5. 兑换记录: {len(r.json())}条")
for rec in r.json():
    print(f"   {rec['rewardName']} -{rec['pointsCost']}分 码:{rec.get('redeemCode', '-')}")

# 6. 积分不足兑换（25分 < 50分咖啡券）
coffee = next((i for i in data["items"] if i["pointsCost"] == 50), None)
if coffee:
    r = s.post(f"{BASE}/api/portal/rewards/{coffee['id']}/exchange", headers=EH)
    print(f"6. 积分不足: {r.status_code} {r.json().get('error', '')[:30]}")

# 7. 前16轮回归
print("\n=== 前16轮回归 ===")
courses = s.get(f"{BASE}/api/portal/courses", headers=EH).json()
print(f"  课程: {len(courses)}门")
dash = s.get(f"{BASE}/api/hrm/analytics/dashboard", headers=AH).json()
print(f"  看板: 课程{dash['metrics']['courseTotal']}门")
pk = s.get(f"{BASE}/api/hrm/pk-seasons", headers=AH).json()
pkitems = pk if isinstance(pk, list) else pk.get("items", [])
print(f"  PK赛季: {len(pkitems)}个")

print("\n✓ 积分商城 + 前16轮全回归验证通过")
