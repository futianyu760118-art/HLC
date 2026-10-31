import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';


async function importTypeScript(relativePath) {
  const url = new URL(relativePath, import.meta.url);
  const source = await readFile(url, 'utf8');
  const output = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ES2022,
    },
    fileName: url.pathname,
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`);
}


test('UTC and datetime-local conversion is symmetric for an UTC+8 browser', async () => {
  const helpers = await importTypeScript('../src/utils/enterpriseApplications.ts');

  assert.equal(
    helpers.utcIsoToLocalInput('2026-07-23T01:30:00Z', -480),
    '2026-07-23T09:30',
  );
  assert.equal(
    helpers.localInputToUtcIso('2026-07-23T09:30', -480),
    '2026-07-23T01:30:00.000Z',
  );
});


test('conversion waits for explicit confirmation, names the target, and supports cancel', async () => {
  const helpers = await importTypeScript('../src/utils/enterpriseApplications.ts');
  let resolveConfirmation;
  let options;
  let conversions = 0;
  const pending = helpers.runConfirmedEnterpriseConversion({
    applicationCompany: '星海智造有限公司',
    targetTenantName: 'Alpha 公司',
    confirm: (received) => {
      options = received;
      return new Promise(resolve => { resolveConfirmation = resolve; });
    },
    convert: async () => {
      conversions += 1;
      return { status: 'converted' };
    },
  });

  await Promise.resolve();
  assert.equal(conversions, 0, 'first click may only open confirmation');
  assert.match(options.message, /星海智造有限公司/);
  assert.match(options.message, /Alpha 公司/);
  assert.match(options.message, /终态/);
  resolveConfirmation(false);
  assert.equal(await pending, undefined);
  assert.equal(conversions, 0, 'cancel must not call conversion API');

  const confirmed = await helpers.runConfirmedEnterpriseConversion({
    applicationCompany: '星海智造有限公司',
    targetTenantName: 'Alpha 公司',
    confirm: async () => true,
    convert: async () => {
      conversions += 1;
      return { status: 'converted' };
    },
  });
  assert.deepEqual(confirmed, { status: 'converted' });
  assert.equal(conversions, 1, 'only the confirmed action calls conversion API');
});


test('list normalization enforces a PII-free allowlist at runtime', async () => {
  const helpers = await importTypeScript('../src/utils/enterpriseApplications.ts');
  const safe = helpers.normalizeEnterpriseApplicationListItem({
    id: 'application-1',
    applicationNo: 'ESA-1',
    companyName: '星海智造有限公司',
    status: 'new',
    ownerName: '平台管理员',
    createdAt: '2026-07-23T01:30:00Z',
    contactName: '林女士',
    mobile: '13800138000',
    email: 'lin@example.com',
    notes: '私人需求',
    internalNote: '内部备注',
  });

  for (const key of ['contactName', 'mobile', 'email', 'notes', 'internalNote']) {
    assert.equal(Object.hasOwn(safe, key), false, `${key} must not survive list normalization`);
  }
  assert.equal(safe.applicationNo, 'ESA-1');
});


test('latest request gate rejects stale filters, stale targets, and invalidated writes', async () => {
  const { LatestRequestGate } = await importTypeScript('../src/utils/enterpriseApplications.ts');
  const gate = new LatestRequestGate();
  const oldList = gate.begin('status=new');
  const newList = gate.begin('status=qualified');

  assert.equal(gate.isCurrent(oldList, 'status=new'), false);
  assert.equal(gate.isCurrent(newList, 'status=qualified'), true);
  assert.equal(gate.isCurrent(newList, 'status=new'), false);

  gate.invalidate();
  assert.equal(gate.isCurrent(newList, 'status=qualified'), false);
});


test('submission idempotency key is stable for retries and rotates after semantic edits', async () => {
  const { SubmissionIdempotencyKey } = await importTypeScript('../src/utils/enterpriseApplications.ts');
  const key = new SubmissionIdempotencyKey();
  let sequence = 0;
  const create = () => `request-key-${++sequence}`;

  assert.equal(key.getOrCreate(create), 'request-key-1');
  assert.equal(key.getOrCreate(create), 'request-key-1');
  key.invalidate();
  assert.equal(key.getOrCreate(create), 'request-key-2');
});


test('public form validation returns Chinese field-level errors', async () => {
  const form = await importTypeScript('../src/pages/p-enterprise-application/form.ts');
  const errors = form.validateEnterpriseApplicationForm({
    companyName: 'A',
    contactName: '',
    mobile: '12345',
    email: 'not-an-email',
    privacyConsent: false,
  });

  assert.match(errors.companyName, /企业名称/);
  assert.match(errors.contactName, /联系人/);
  assert.match(errors.mobile, /手机/);
  assert.match(errors.email, /邮箱/);
  assert.match(errors.privacyConsent, /隐私政策/);
});
