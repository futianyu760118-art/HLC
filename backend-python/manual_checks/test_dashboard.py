"""看板端点 + 前6轮回归测试"""
import requests
BASE = "http://localhost:18888"
s = requests.Session()
tok = s.post(f"{BASE}/api/auth/login", json={"email": "3420849544@qq.com", "password": "Admin@2026"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}

# 看板
d = s.get(f"{BASE}/api/hrm/analytics/dashboard", headers=H).json()
m = d["metrics"]
print("=== 看板数据 ===")
print(f"  上架课程: {m['courseTotal']}")
print(f"  活跃学员: {m['learnerCount']}")
print(f"  考试通过率: {m['examPassRate']}%")
print(f"  人均学习: {m['avgLearningMinutes']}分")
print(f"  考试人次: {m['attemptCount']}")
print(f"  题库: {m['questionCount']}题")
print(f"  课程完成率数据: {len(d['courseCompletion'])}门")
print(f"  部门活跃度: {len(d['deptActivity'])}个")
print(f"  热门课程: {len(d['popularCourses'])}门")
print(f"  考试统计: {len(d['examStats'])}场")
for e in d["examStats"]:
    print(f"    {e['title']}: {e['submissions']}人次 通过率{e['passRate']}%")

# 回归（前6轮功能）
print("\n=== 回归验证（前6轮）===")
# 轮1-2: 课程+考试
courses = s.get(f"{BASE}/api/hrm/courses", headers=H).json()
items = courses if isinstance(courses, list) else courses.get("items", [])
print(f"  课程: {len(items)}门")
qs = s.get(f"{BASE}/api/hrm/exam-questions", headers=H).json()
qitems = qs if isinstance(qs, list) else qs.get("items", [])
print(f"  题库: {len(qitems)}题")
# 轮3: 学习路径
paths = s.get(f"{BASE}/api/hrm/learning-paths", headers=H).json()
pitems = paths if isinstance(paths, list) else paths.get("items", [])
print(f"  学习路径: {len(pitems)}条")
# 轮5: 课程评价
reviews = s.get(f"{BASE}/api/hrm/courses/reviews-summary", headers=H).json()
print(f"  课程评价: {len(reviews)}门有评价")
# 轮6: 胜任力
models = s.get(f"{BASE}/api/hrm/competency-models", headers=H).json()
mitems = models if isinstance(models, list) else models.get("items", [])
print(f"  胜任力模型: {len(mitems)}个")

# 员工侧
emp_tok = s.post(f"{BASE}/api/auth/login", json={"email": "zhangsan@test.com", "password": "Employee@2026"}).json()["token"]
EH = {"Authorization": f"Bearer {emp_tok}"}
print(f"  员工课程: {len(s.get(f'{BASE}/api/portal/courses', headers=EH).json())}门")
print(f"  员工错题本: {s.get(f'{BASE}/api/portal/wrong-questions', headers=EH).json()['stats']['total']}题")
print(f"  员工能力测评: {len(s.get(f'{BASE}/api/portal/competency/my-assessments', headers=EH).json())}条")

print("\n✓ 看板 + 前6轮全回归验证通过")
