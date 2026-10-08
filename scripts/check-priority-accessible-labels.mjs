import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

const rules = [
  {
    file: 'src/pages/p-job_create/index.tsx',
    checks: [
      ['新建岗位岗位名称输入框需要可读名称', 'aria-label="岗位名称"'],
      ['新建岗位岗位描述输入框需要可读名称', 'aria-label="岗位描述"'],
      ['新建岗位任职要求输入框需要可读名称', 'aria-label="任职要求"'],
      ['新建岗位薪资范围输入框需要可读名称', 'aria-label="薪资范围"'],
      ['新建岗位工作地点输入框需要可读名称', 'aria-label="工作地点"'],
      ['新建岗位工作类型选择框需要可读名称', 'aria-label="工作类型"'],
      ['AI 评分权重滑块需要按评分项命名', 'aria-label={`${criterion.name}权重滑块`}'],
      ['AI 评分权重数值框需要按评分项命名', 'aria-label={`${criterion.name}权重数值`}'],
    ],
  },
  {
    file: 'src/pages/p-hrm/index.tsx',
    checks: [
      ['HRM 通用表单文本域需要使用字段标签作为可读名称', 'aria-label={field.label}'],
      ['HRM 通用表单选择框需要使用字段标签作为可读名称', 'aria-label={field.label}'],
      ['HRM 通用表单输入框需要使用字段标签作为可读名称', 'aria-label={field.label}'],
    ],
  },
  {
    file: 'src/pages/p-resume_manage/index.tsx',
    checks: [
      ['简历开始日期筛选需要可读名称', 'aria-label="简历筛选开始日期"'],
      ['简历结束日期筛选需要可读名称', 'aria-label="简历筛选结束日期"'],
      ['简历列表全选框需要可读名称', 'aria-label="选择当前页简历"'],
      ['简历行选择框需要包含候选人姓名', 'aria-label={`选择简历 ${resume.candidateName}`}'],
      ['简历分页上一页按钮需要可读名称', 'aria-label="上一页简历"'],
      ['简历分页下一页按钮需要可读名称', 'aria-label="下一页简历"'],
    ],
  },
  {
    file: 'src/pages/p-system_settings/index.tsx',
    checks: [
      ['系统设置 Toggle 组件需要 label 入参', 'label: string'],
      ['系统设置 Toggle 按钮需要 aria-label', 'aria-label={`切换${label}`}'],
      ['系统设置 Toggle 按钮需要暴露开关状态', 'aria-pressed={checked}'],
    ],
  },
  {
    file: 'src/pages/p-platform-tenants/index.tsx',
    checks: [
      ['平台企业搜索框需要可读名称', 'aria-label="搜索企业客户"'],
      ['平台企业状态筛选需要可读名称', 'aria-label="筛选企业状态"'],
      ['平台模块开关需要按模块名称命名', 'aria-label={`切换${moduleLabels[module.moduleKey] || module.moduleKey}模块`}'],
    ],
  },
  {
    file: 'src/pages/p-exam-generate/index.tsx',
    checks: [
      ['智能出题数量输入框需要可读名称', 'aria-label="题目数量"'],
      ['智能出题题型复选框需要按题型命名', 'aria-label={`选择${TYPE_LABELS[t]}题型`}'],
    ],
  },
];

function stripComments(text) {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1');
}

export function checkPriorityAccessibleLabels({ root = ROOT } = {}) {
  const findings = [];
  for (const rule of rules) {
    const fullPath = resolve(root, rule.file);
    const text = stripComments(readFileSync(fullPath, 'utf8'));
    for (const [message, needle] of rule.checks) {
      if (!text.includes(needle)) {
        findings.push({ file: rule.file, message, expected: needle });
      }
    }
  }
  return { ok: findings.length === 0, findings };
}

function main() {
  const result = checkPriorityAccessibleLabels();
  if (!result.ok) {
    console.error('Priority accessible labels: FAILED');
    for (const finding of result.findings) {
      console.error(`- ${finding.file}: ${finding.message}`);
    }
    process.exit(1);
  }
  console.log('Priority accessible labels: OK');
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main();
}
