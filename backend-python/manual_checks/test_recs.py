"""重测推荐：先重新自评制造短板，再看推荐"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()
tok = s.post(f"{BASE}/api/auth/login", json={"email": "zhangsan@test.com", "password": "Employee@2026"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}

asmts = s.get(f"{BASE}/api/portal/competency/my-assessments", headers=H).json()
if not asmts:
    print("无测评记录"); raise SystemExit()
mid = asmts[0]["modelId"]
# 重新自评制造短板
s.post(f"{BASE}/api/portal/competency/self-assess/{mid}",
       headers={**H, "Content-Type": "application/json"},
       json={"scores": {"html": 4, "js": 2, "frame": 1, "comm": 3, "exec": 3}})

asmts = s.get(f"{BASE}/api/portal/competency/my-assessments", headers=H).json()
aid = asmts[0]["id"]
r = s.get(f"{BASE}/api/hrm/competency-assessments/{aid}/recommendations", headers=H)
rec = r.json()
print("短板维度:", rec["weakDimensions"])
print("推荐课程:", len(rec["recommendedCourses"]), "门")
for c in rec["recommendedCourses"]:
    print("  -", c["title"])
