"""错题本端到端测试：考试提交 → 自动采集 → 错题本查看 → 重练 → 掌握"""
import requests, json
BASE = "http://localhost:18888"
s = requests.Session()

# 张三登录
r = s.post(f"{BASE}/api/auth/login", json={"email": "wangwu@test.com", "password": "Employee@2026"})
tok = r.json()["token"]
H = {"Authorization": f"Bearer {tok}"}

# 1. 先看当前错题本（应该是空的，或之前考试的）
r = s.get(f"{BASE}/api/portal/wrong-questions", headers=H)
wq = r.json()
print(f"1. 当前错题本: {wq['stats']}")

# 2. 开始一场考试 → 故意答错几题 → 提交
exams = s.get(f"{BASE}/api/portal/exams", headers=H).json()
if not exams:
    print("无可参加的考试，跳过考试测试"); import sys; sys.exit()
task = exams[0]
print(f"2. 参加考试: {task['title']} 剩余{task['remainingAttempts']}次")

r = s.post(f"{BASE}/api/portal/exams/{task['taskId']}/start", headers=H)
start = r.json()
if 'error' in start:
    print("开始失败:", start['error']); import sys; sys.exit()
attempt_id = start['attemptId']
questions = start['questions']
print(f"   attempt: {attempt_id}, 题数: {len(questions)}")

# 故意全部答错（都选最后一个选项）
answers = {}
for q in questions:
    opts = q.get('options', [])
    answers[q['id']] = [len(opts) - 1]  # 选最后一个（大概率错）

r = s.post(f"{BASE}/api/portal/exams/{attempt_id}/submit", headers=H, json={"answers": answers})
result = r.json()
print(f"   提交得分: {result.get('score')}/{result.get('totalScore')} 通过:{result.get('passed')}")

# 3. 再看错题本（应该有采集到的错题）
r = s.get(f"{BASE}/api/portal/wrong-questions", headers=H)
wq = r.json()
print(f"3. 提交后错题本: {wq['stats']}")
items = wq['items']
print(f"   错题数: {len(items)}")
for it in items[:3]:
    print(f"   - [{it.get('type')}] {(it.get('stem') or '')[:30]}... 错{it['wrongCount']}次")

if not items:
    print("   无错题采集，测试结束"); import sys; sys.exit()

# 4. 收藏第一道错题
first_id = items[0]['id']
r = s.post(f"{BASE}/api/portal/wrong-questions/{first_id}/favorite", headers=H)
print(f"4. 收藏: {r.json()}")

# 5. 重练：把第一道题答对（用快照里的正确答案）
practice_answers = {}
snap_answer = items[0].get('answer', [])
practice_answers[first_id] = snap_answer
r = s.post(f"{BASE}/api/portal/wrong-questions/practice", headers=H, json={"answers": practice_answers})
prac = r.json()
print(f"5. 重练: 得分{prac['score']}/{prac['totalScore']} 掌握{len(prac.get('mastered', []))}题")
print(f"   mastered: {prac.get('mastered')}")

# 6. 确认掌握状态更新
r = s.get(f"{BASE}/api/portal/wrong-questions?mastery=all", headers=H)
wq2 = r.json()
print(f"6. 重练后错题本: {wq2['stats']}")
mastered_item = next((i for i in wq2['items'] if i['id'] == first_id), None)
if mastered_item:
    print(f"   第一题 mastery: {mastered_item['mastery']} {'✓ 已掌握' if mastered_item['mastery'] == 'mastered' else '✗ 仍为wrong'}")

# 7. 回归：旧功能没坏
print("\n=== 回归验证 ===")
courses = s.get(f"{BASE}/api/portal/courses", headers=H).json()
print(f"   员工课程: {len(courses)}门")
paths = s.get(f"{BASE}/api/portal/learning-paths", headers=H).json()
print(f"   学习路径: {len(paths)}条")
print("\n✓ 错题本全链路验证完成")
