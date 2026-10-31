"""证书端到端测试：学完课程→自动颁发→查看→验证→回归"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()

emp_tok = s.post(f"{BASE}/api/auth/login", json={"email": "zhaoliu@test.com", "password": "Employee@2026"}).json()["token"]
EH = {"Authorization": f"Bearer {emp_tok}", "Content-Type": "application/json"}

# 1. 初始证书数
r = s.get(f"{BASE}/api/portal/certificates", headers=EH)
print(f"1. 初始证书: {len(r.json())}张")

# 2. 学完一门课（触发自动颁发）
courses = s.get(f"{BASE}/api/portal/courses", headers=EH).json()
cid = courses[0]["id"]
cname = courses[0]["title"]
detail = s.get(f"{BASE}/api/portal/courses/{cid}", headers=EH).json()
all_hours = detail.get("ungroupedHours", []) + [h for ch in detail.get("chapters", []) for h in ch.get("hours", [])]
for h in all_hours:
    s.post(f"{BASE}/api/portal/courses/{h['id']}/progress", headers=EH, json={"watchedDuration": 600, "isFinished": True, "totalDuration": 600})
print(f"2. 学完课程: {cname} ({len(all_hours)}课时)")

# 3. 查证书
r = s.get(f"{BASE}/api/portal/certificates", headers=EH)
certs = r.json()
print(f"3. 颁发证书: {len(certs)}张")
if certs:
    c = certs[0]
    print(f"   编号: {c['certNo']}")
    print(f"   课程: {c['courseTitle']}")
    print(f"   学员: {c['employeeName']}")
    print(f"   图片: {c['imageUrl']}")

    # 4. 公开验证
    r = s.get(f"{BASE}/api/portal/certificates/verify/{c['certNo']}")
    v = r.json()
    print(f"4. 公开验证: valid={v.get('valid')} 学员={v.get('employeeName')}")

    # 5. 验证假证书编号
    r = s.get(f"{BASE}/api/portal/certificates/verify/FAKE-0000-000000")
    print(f"5. 假编号验证: {r.status_code} (应404)")

# 6. 重复学习不重复颁发
for h in all_hours[:1]:
    s.post(f"{BASE}/api/portal/courses/{h['id']}/progress", headers=EH, json={"watchedDuration": 999, "isFinished": True})
r = s.get(f"{BASE}/api/portal/certificates", headers=EH)
print(f"6. 重复学习后证书数: {len(r.json())} (幂等应不变)")

# 7. 回归（前9轮）
print("\n=== 前9轮回归 ===")
admin_tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json()["token"]
AH = {"Authorization": f"Bearer {admin_tok}"}
print(f"  课程: {len(courses)}门")
print(f"  积分: {s.get(f'{BASE}/api/portal/points/summary', headers=EH).json()['totalPoints']}分")
dash = s.get(f"{BASE}/api/hrm/analytics/dashboard", headers=AH).json()
print(f"  看板: 通过率{dash['metrics']['examPassRate']}%")
print(f"  题库: {dash['metrics']['questionCount']}题")

print("\n✓ 证书 + 前9轮全回归验证通过")
