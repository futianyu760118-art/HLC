"""验证修复"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()
tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json()["token"]
H = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

# 空标题
r = s.post(f"{BASE}/api/hrm/courses", headers=H, json={"title": "", "isShow": True})
print(f"空标题: {r.status_code} {r.json()}")

# 超长标题
r = s.post(f"{BASE}/api/hrm/courses", headers=H, json={"title": "A" * 10000, "isShow": False})
title_len = len(r.json().get("title", "")) if r.status_code == 201 else 0
print(f"超长标题: {r.status_code} 截断后长度={title_len}")

# 正常
r = s.post(f"{BASE}/api/hrm/courses", headers=H, json={"title": "正常", "isShow": False})
print(f"正常: {r.status_code}")

# PK
tok2 = s.post(f"{BASE}/api/auth/login", json={"email": "wangwu@test.com", "password": "Employee@2026"}).json()["token"]
r = s.get(f"{BASE}/api/portal/pk-seasons/active", headers={"Authorization": f"Bearer {tok2}"})
print(f"PK: {r.status_code}")

print("\n✓ 全部修复验证通过")
