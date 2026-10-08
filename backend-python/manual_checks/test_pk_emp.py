"""PK竞赛员工端验证"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()
tok = s.post(f"{BASE}/api/auth/login", json={"email": "wangwu@test.com", "password": "Employee@2026"}).json()["token"]
r = s.get(f"{BASE}/api/portal/pk-seasons/active", headers={"Authorization": f"Bearer {tok}"})
print(f"PK状态: {r.status_code}")
if r.status_code == 200:
    d = r.json()
    print(f"  赛季数: {len(d)}")
    for s0 in d:
        name = s0.get("name", "?")
        rank = s0.get("myDeptRank")
        pts = s0.get("myPoints")
        print(f"  {name} 我的部门排名:#{rank} 我的贡献:{pts}")
else:
    print(f"  错误: {r.text[:100]}")
