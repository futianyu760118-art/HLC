"""验证 p-portal-learn 新端点"""
import requests, time
BASE = "http://localhost:18888"
s = requests.Session()
tok = s.post(f"{BASE}/api/auth/login", json={"email": "zhangsan@test.com", "password": "Employee@2026"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}

# 取一个课时ID
courses = s.get(f"{BASE}/api/portal/courses", headers=H).json()
cid = courses[0]["id"]
detail = s.get(f"{BASE}/api/portal/courses/{cid}", headers=H).json()
all_hours = detail.get("ungroupedHours", []) + [h for ch in detail.get("chapters", []) for h in ch.get("hours", [])]
if all_hours:
    hid = all_hours[0]["id"]
    t0 = time.time()
    r = s.get(f"{BASE}/api/portal/hours/{hid}", headers=H)
    t1 = time.time()
    print(f"GET /hours/: {r.status_code} 耗时:{round((t1-t0)*1000)}ms")
    if r.status_code == 200:
        d = r.json()
        ht = d["hour"]["title"]
        has_video = bool(d["hour"].get("videoUrl"))
        ct = d["course"]["title"]
        print(f"  课时: {ht} 视频URL存在: {has_video}")
        print(f"  课程: {ct}")
    else:
        print(f"  错误: {r.text[:100]}")
else:
    print("无课时")

# 回归
print("\n=== 回归 ===")
r = s.get(f"{BASE}/api/portal/learning-paths", headers=H)
print(f"学习路径: {r.status_code}")
r = s.get(f"{BASE}/api/portal/pk-seasons/active", headers=H)
print(f"PK竞赛: {r.status_code}")
r = s.get(f"{BASE}/api/portal/courses", headers=H)
print(f"课程: {len(r.json())}门")
print("\n✓ 验证完成")
