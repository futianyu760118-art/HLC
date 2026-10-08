// @ts-nocheck
/**
 * 培训+考试 全链路 E2E 测试
 * 通过真实 UI 操作 + API 调用验证每个环节，发现问题记日志
 */
import { writeFileSync } from 'node:fs';

const BASE = 'https://localhost:18445';

const issues = [];
const log = (msg) => console.log(msg);
const issue = (cat, msg) => { issues.push({ cat, msg }); console.log(`  ⚠️ [${cat}] ${msg}`); };

// API helpers
const api = async (token, method, pathStr, body) => {
  const r = await fetch(`${BASE}${pathStr}`, {
    method,
    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await r.text();
  let json; try { json = JSON.parse(text); } catch { json = text; }
  return { status: r.status, json };
};

const login = async (email, pwd) => {
  const r = await api(null, 'POST', '/api/auth/login', { email, password: pwd });
  return r.json?.token;
};

async function main() {
  const adminTok = await login('3420849544@qq.com', 'Admin@2026');
  if (!adminTok) { console.log('管理员登录失败'); return; }
  log('✓ 管理员登录');

  // ========== 1. 课程目录页 ==========
  log('\n=== 1. 课程目录 ===');
  let r = await api(adminTok, 'GET', '/api/hrm/courses');
  const courses = Array.isArray(r.json) ? r.json : r.json?.items || [];
  log(`  课程数: ${courses.length}`);
  if (courses.length === 0) issue('数据', '课程目录为空');
  for (const c of courses) {
    if (!c.title) issue('数据', `课程 ${c.id} 无标题`);
    if (c.isRequired === undefined) issue('数据', `课程 ${c.title} isRequired 未定义`);
  }

  // 2. 分类
  log('\n=== 2. 课程分类 ===');
  r = await api(adminTok, 'GET', '/api/hrm/course-categories');
  const cats = Array.isArray(r.json) ? r.json : r.json?.items || [];
  log(`  分类数: ${cats.length}`);
  // 验证无重复
  const names = cats.map(c => c.name);
  const dup = names.filter((n, i) => names.indexOf(n) !== i);
  if (dup.length) issue('数据', `分类重复: ${dup.join(',')}`);

  // 3. 课程详情（章节+资料）
  log('\n=== 3. 课程详情（含章节资料）===');
  if (courses.length) {
    const cid = courses[0].id;
    // 模拟员工视角的 portal 详情需要员工 token，先测管理端章节
    r = await api(adminTok, 'GET', `/api/hrm/course-chapters`);
    const chapters = (Array.isArray(r.json) ? r.json : r.json?.items || []).filter(ch => ch.courseId === cid);
    log(`  课程「${courses[0].title}」章节数: ${chapters.length}`);
    for (const ch of chapters) {
      if (ch.materials === undefined) issue('数据', `章节 ${ch.name} materials 字段缺失`);
      if (ch.description === undefined) issue('数据', `章节 ${ch.name} description 字段缺失`);
    }
  }

  // 4. 智能出题（真实调 AI）
  log('\n=== 4. 智能出题（真实 LLM）===');
  r = await api(adminTok, 'POST', '/api/hrm/exam-questions/generate', {
    sourceText: '公司信息安全规范：1. 密码必须每90天更换一次。2. 离开工位需锁屏。3. 禁止使用公共WiFi处理工作。4. 可疑邮件不得点击链接。',
    count: 3,
    types: ['single', 'judge'],
  });
  if (r.json?.error) issue('AI出题', `生成失败: ${r.json.error}`);
  else {
    const qs = r.json?.questions || [];
    log(`  AI 生成 ${qs.length} 题`);
    if (qs.length === 0) issue('AI出题', '生成 0 题');
    for (const q of qs) {
      if (!q.stem || !q.options?.length || !q.answer?.length) issue('AI出题', `题目结构不完整: ${JSON.stringify(q).slice(0, 80)}`);
      if (q.type === 'judge' && q.options.length !== 2) issue('AI出题', `判断题选项数≠2: ${q.options}`);
    }
  }

  // 5. 题库管理
  log('\n=== 5. 题库管理 ===');
  r = await api(adminTok, 'GET', '/api/hrm/exam-questions');
  const allQ = Array.isArray(r.json) ? r.json : r.json?.items || [];
  const pending = allQ.filter(q => q.reviewStatus === 'pending');
  log(`  题库 ${allQ.length} 题，待审核 ${pending.length}`);
  // 批量通过待审核
  if (pending.length) {
    r = await api(adminTok, 'POST', '/api/hrm/exam-questions/batch-approve', { ids: pending.map(q => q.id) });
    log(`  批量通过: ${r.json?.approved}`);
  }

  // 6. 试卷组卷
  log('\n=== 6. 试卷组卷 ===');
  r = await api(adminTok, 'GET', '/api/hrm/exam-papers');
  const papers = Array.isArray(r.json) ? r.json : r.json?.items || [];
  log(`  试卷数: ${papers.length}`);
  for (const p of papers) {
    if (!p.questionIds?.length) issue('组卷', `试卷「${p.title}」无题目`);
    if (!p.totalScore || p.totalScore == 0) issue('组卷', `试卷「${p.title}」总分为0`);
  }

  // 7. 考试安排
  log('\n=== 7. 考试安排 ===');
  r = await api(adminTok, 'GET', '/api/hrm/exam-tasks');
  const tasks = Array.isArray(r.json) ? r.json : r.json?.items || [];
  log(`  考试任务数: ${tasks.length}`);
  for (const t of tasks) {
    if (!t.paperId) issue('考试', `任务「${t.title}」未关联试卷`);
    if (!t.targetIds?.length) issue('考试', `任务「${t.title}」未指派目标`);
  }

  // 8. 员工门户视角（需要有绑定的员工账号）
  log('\n=== 8. 员工门户视角 ===');
  r = await api(adminTok, 'GET', '/api/hrm/users/bind-employees');
  log(`  User-Employee 绑定: ${JSON.stringify(r.json)}`);
  r = await api(adminTok, 'GET', '/api/hrm/employees');
  const emps = Array.isArray(r.json) ? r.json : r.json?.items || [];
  log(`  员工数: ${emps.length}`);

  // 写入问题清单
  writeFileSync('artifacts/e2e-issues.json', JSON.stringify({ time: new Date().toISOString(), issues, summary: `${issues.length} issues found` }, null, 2));
  log(`\n=== 总结: 发现 ${issues.length} 个问题 ===`);
  issues.forEach(i => log(`  [${i.cat}] ${i.msg}`));
}

main().catch(e => console.error('FATAL:', e.message));
