"""学习路径端到端测试"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()

# 管理员登录
r = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"})
tok = r.json()["token"]
H = {"Authorization": f"Bearer {tok}"}

# 取课程
courses = s.get(f"{BASE}/api/hrm/courses", headers=H).json()
items = courses if isinstance(courses, list) else courses.get("items", [])
cmap = {c["title"]: c["id"] for c in items}
print("课程:", list(cmap.keys()))

# 创建路径
body = {
    "name": "研发工程师成长路径",
    "description": "从入职基础到岗位技能的体系化学习路径",
    "targetPosition": "研发工程师",
    "targetDepartmentId": "d-eng",
    "stages": [
        {"name": "入职基础", "courseIds": [cmap.get("新员工入职指南", items[0]["id"])]},
        {"name": "安全合规", "courseIds": [cmap.get("消防安全知识培训", items[0]["id"])], "examTaskId": "0503c54b-13b5-2093-e501-96cd9eaacc4e"},
        {"name": "技能进阶", "courseIds": [cmap.get("Excel 数据分析实战", items[0]["id"])]},
    ],
    "status": "published",
}
r = s.post(f"{BASE}/api/hrm/learning-paths", headers={**H, "Content-Type": "application/json"}, json=body)
d = r.json()
print("创建:", r.status_code, d.get("id") or str(d)[:150])
pid = d.get("id")
if not pid:
    raise SystemExit("创建失败")

# 发布
r = s.post(f"{BASE}/api/hrm/learning-paths/{pid}/publish", headers=H)
print("发布:", r.json())

# 员工张三视角
r2 = s.post(f"{BASE}/api/auth/login", json={"email": "zhangsan@test.com", "password": "Employee@2026"})
etok = r2.json()["token"]
r = s.get(f"{BASE}/api/portal/learning-paths", headers={"Authorization": f"Bearer {etok}"})
paths = r.json()
print(f"\n张三可见路径: {len(paths)}")
for p in paths:
    name = p["name"]; prog = p["progress"]; cur = p["currentStage"]; tot = p["stageCount"]
    print(f"  路径: {name} 进度:{prog}% 当前阶段:{cur}/{tot}")
    for st in p["stages"]:
        idx = st["index"]; sn = st["name"]
        status = "完成" if st["completed"] else ("解锁" if st["unlocked"] else "锁定")
        nc = len(st["courses"])
        print(f"    阶段{idx+1} {sn} [{status}] 课程数:{nc}")

# 验证旧功能没坏
print("\n=== 回归验证（不破坏其他模块）===")
r = s.get(f"{BASE}/api/portal/courses", headers={"Authorization": f"Bearer {etok}"})
print("员工课程:", len(r.json()), "门")
r = s.get(f"{BASE}/api/portal/exams", headers={"Authorization": f"Bearer {etok}"})
print("员工考试:", len(r.json()), "场")
r = s.get(f"{BASE}/api/hrm/exam-questions", headers=H)
qs = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
print("题库:", len(qs), "题")
print("\n✓ 学习路径全链路验证完成")
