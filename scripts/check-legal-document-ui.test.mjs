import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';

const readSource = (relativePath) => {
  const url = new URL(relativePath, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
};

const router = readSource('../src/router/index.tsx');
const legalPage = readSource('../src/pages/p-legal-document/index.tsx');
const loginPage = readSource('../src/pages/p-login/index.tsx');
const platformLoginPage = readSource('../src/pages/p-platform-login/index.tsx');
const enterpriseApplicationPage = readSource('../src/pages/p-enterprise-application/index.tsx');
const termsMarkdown = readSource('../docs/compliance/terms-of-service.md');
const privacyMarkdown = readSource('../docs/compliance/privacy-policy.md');

test('terms and privacy are shellless independent routes', () => {
  assert.match(router, /import P_legal_document from ['"]\.\.\/pages\/p-legal-document['"]/);
  assert.match(router, /\^\\\/legal\(\?:\\\/\|\$\)\//);
  assert.match(router, /path:\s*['"]\/legal\/terms['"][\s\S]{0,220}<P_legal_document type=['"]terms['"]\s*\/>/);
  assert.match(router, /path:\s*['"]\/legal\/privacy['"][\s\S]{0,220}<P_legal_document type=['"]privacy['"]\s*\/>/);
});

test('legal page fetches and safely renders the published markdown', () => {
  assert.match(legalPage, /terms-of-service\.md/);
  assert.match(legalPage, /privacy-policy\.md/);
  assert.match(legalPage, /fetch\(document\.source/);
  assert.match(legalPage, /ReactMarkdown/);
  assert.match(legalPage, /remarkPlugins=\{\[remarkGfm\]\}/);
  assert.match(legalPage, /rehypePlugins=\{\[rehypeSanitize\]\}/);
  assert.match(legalPage, /正在加载协议正文/);
  assert.match(legalPage, /协议正文加载失败/);
  assert.match(legalPage, /返回登录/);
});

test('public entry points open legal pages without downloading markdown', () => {
  for (const page of [loginPage, platformLoginPage]) {
    assert.match(page, /href=['"]\/legal\/terms['"]\s+target=['"]_blank['"]\s+rel=['"]noreferrer['"]/);
    assert.match(page, /href=['"]\/legal\/privacy['"]\s+target=['"]_blank['"]\s+rel=['"]noreferrer['"]/);
    assert.doesNotMatch(page, /\/docs\/compliance\/(?:terms-of-service|privacy-policy)\.md/);
  }

  assert.match(enterpriseApplicationPage, /href=['"]\/legal\/privacy['"]\s+target=['"]_blank['"]\s+rel=['"]noreferrer['"]/);
  assert.doesNotMatch(enterpriseApplicationPage, /\/docs\/compliance\/privacy-policy\.md/);
  assert.doesNotMatch(termsMarkdown, /\]\([^)]*\.md(?:[?#][^)]*)?\)/);
  assert.doesNotMatch(privacyMarkdown, /\]\([^)]*\.md(?:[?#][^)]*)?\)/);
});
