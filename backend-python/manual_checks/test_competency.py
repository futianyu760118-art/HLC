"""胜任力测评端到端测试：建模型→员工自评→短板→课程推荐→回归"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()

admin_tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json()["token"]
emp_tok = s.post(f"{BASE}/api/auth/login", json={"email": "zhangsan@test.com", "password": "Employee@2026"}).json()["token"]
AH = {"Authorization": f"Bearer {admin_tok}", "Content-Type": "application/json"}
EH = {"Authorization": f"Bearer {emp_tok}"}

# 1. 管理员建胜任力模型
model_body = {
    "name": "前端工程师胜任力",
    "description": "前端岗位所需核心能力",
    "dimensions": [
        {"key": "html", "name": "HTML/CSS", "requiredLevel": 4, "description": "页面布局与样式"},
        {"key": "js", "name": "JavaScript", "requiredLevel": 4, "description": "编程能力"},
        {"key": "frame", "name": "框架应用", "requiredLevel": 3, "description": "React/Vue"},
        {"key": "comm", "name": "沟通协作", "requiredLevel": 3, "description": "团队沟通"},
        {"key": "exec", "name": "执行力", "requiredLevel": 4, "description": "任务交付"},
    ],
    "status": "active",
}
r = s.post(f"{BASE}/api/hrm/competency-models", headers=AH, json=model_body)
mid = r.json()["id"]
print(f"1. 建模型: {r.status_code} id={mid} 维度数={r.json()['dimensionCount']}")

# 2. 员工查看可用模型
r = s.get(f"{BASE}/api/portal/competency/models", headers=EH)
print(f"2. 可用模型: {len(r.json())}个, 第一个='{r.json()[0]['name']}'")

# 3. 员工自评（故意 JS 和框架打低分制造短板）
scores = {"html": 4, "js": 2, "frame": 1, "comm": 3, "exec": 3}
r = s.post(f"{BASE}/api/portal/competency/self-assess/{mid}", headers={"Authorization": f"Bearer {emp_tok}", "Content-Type": "application/json"}, json={"scores": scores})
result = r.json()
print(f"3. 自评提交: 达标率={result['overallScore']}%")
print(f"   分数: {result['scores']}")
print(f"   差距: {result['gaps']}")
print(f"   短板: {result['weakestDims']}")

# 4. 看短板推荐课程
r = s.get(f"{BASE}/api/hrm/competency-assessments/{result['id']}/recommendations", headers=EH)
rec = r.json()
print(f"4. 短板维度: {rec['weakDimensions']}")
print(f"   推荐课程: {len(rec['recommendedCourses'])}门")
for c in rec["recommendedCourses"]:
    print(f"   - {c['title']}")

# 5. 看测评历史
r = s.get(f"{BASE}/api/portal/competency/my-assessments", headers=EH)
print(f"5. 测评历史: {len(r.json())}条")

# 6. 重新测评（提升短板后）
scores2 = {"html": 4, "js": 4, "frame": 3, "comm": 3, "exec": 4}
r = s.post(f"{BASE}/api/portal/competency/self-assess/{mid}", headers={"Authorization": f"Bearer {emp_tok}", "Content-Type": "application/json"}, json={"scores": scores2})
print(f"6. 重新测评: 达标率={r.json()['overallScore']}% 短板={r.json()['weakestDims']}")

# 7. 回归
print("\n=== 回归验证 ===")
print(f"   员工课程: {len(s.get(f'{BASE}/api/portal/courses', headers=EH).json())}门")
print(f"   错题本: {s.get(f'{BASE}/api/portal/wrong-questions', headers=EH).json()['stats']['total']}题")
print(f"   学习路径: {len(s.get(f'{BASE}/api/portal/learning-paths', headers=EH).json())}条")
print(f"   题库: {len(s.get(f'{BASE}/api/hrm/exam-questions', headers=AH).json() if isinstance(s.get(f'{BASE}/api/hrm/exam-questions', headers=AH).json(), list) else s.get(f'{BASE}/api/hrm/exam-questions', headers=AH).json().get('items', []))}题")
print("\n✓ 胜任力测评全链路验证完成")
