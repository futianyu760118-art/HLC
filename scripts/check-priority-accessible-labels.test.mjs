import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';

import { checkPriorityAccessibleLabels } from './check-priority-accessible-labels.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

describe('priority accessible label guard', () => {
  it('keeps priority commercial pages free of known unlabeled controls', () => {
    const result = checkPriorityAccessibleLabels({ root });

    assert.deepEqual(result.findings, []);
  });

  it('does not accept required labels that only appear in comments', () => {
    const tempRoot = mkdtempSync(resolve(tmpdir(), 'hrm-priority-labels-'));
    const files = [
      'src/pages/p-job_create/index.tsx',
      'src/pages/p-hrm/index.tsx',
      'src/pages/p-resume_manage/index.tsx',
      'src/pages/p-system_settings/index.tsx',
      'src/pages/p-platform-tenants/index.tsx',
      'src/pages/p-exam-generate/index.tsx',
    ];

    try {
      for (const file of files) {
        const fullPath = resolve(tempRoot, file);
        mkdirSync(dirname(fullPath), { recursive: true });
        writeFileSync(fullPath, '/* aria-label="岗位名称" aria-label="岗位描述" aria-label="任职要求" aria-label="薪资范围" aria-label="工作地点" aria-label="工作类型" aria-label={field.label} aria-label={`${criterion.name}权重滑块`} aria-label={`${criterion.name}权重数值`} aria-label="简历筛选开始日期" aria-label="简历筛选结束日期" aria-label="选择当前页简历" aria-label={`选择简历 ${resume.candidateName}`} aria-label="上一页简历" aria-label="下一页简历" label: string aria-label={`切换${label}`} aria-pressed={checked} aria-label="搜索企业客户" aria-label="筛选企业状态" aria-label={`切换${moduleLabels[module.moduleKey] || module.moduleKey}模块`} aria-label="题目数量" aria-label={`选择${TYPE_LABELS[t]}题型`} */\n', 'utf8');
      }

      const result = checkPriorityAccessibleLabels({ root: tempRoot });

      assert.notEqual(result.findings.length, 0);
    } finally {
      rmSync(tempRoot, { recursive: true, force: true });
    }
  });
});
