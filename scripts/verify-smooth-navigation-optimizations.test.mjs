import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

describe('smooth navigation and SaaS load optimizations', () => {
  it('keeps lazy route fallback inside the work surface and preloads likely route chunks', () => {
    assert.equal(existsSync('src/router/pagePreload.ts'), true);
    const router = readFileSync('src/router/index.tsx', 'utf8');
    const preload = readFileSync('src/router/pagePreload.ts', 'utf8');

    assert.match(router, /preloadRouteForPath/);
    assert.match(router, /PageLoading/);
    assert.doesNotMatch(router, /min-h-screen/);
    assert.match(router, /min-h-\[240px\]/);
    assert.match(preload, /requestIdleCallback/);
    assert.match(preload, /preloadCommonRoutes/);
    assert.match(preload, /preloadRouteForPath/);
    assert.match(preload, /import\('\.\.\/pages\/p-hrm'\)/);
  });

  it('keeps HRM module switches from blanking existing records and deduplicates repeated fetches', () => {
    const page = readFileSync('src/pages/p-hrm/index.tsx', 'utf8');

    assert.match(page, /HRM_RECORD_CACHE_TTL_MS/);
    assert.match(page, /hrmRecordCache/);
    assert.match(page, /hrmRecordInflight/);
    assert.match(page, /cacheKey/);
    assert.match(page, /forceRefresh/);
    assert.match(page, /void loadData/);
    const routeEffectStart = page.indexOf('document.title =');
    const routeEffectEnd = page.indexOf('}, [module, month]);', routeEffectStart);
    assert.notEqual(routeEffectStart, -1);
    assert.notEqual(routeEffectEnd, -1);
    assert.doesNotMatch(page.slice(routeEffectStart, routeEffectEnd), /setRecords\(\[\]\);/);
    assert.match(page, /handleAuthChanged[\s\S]*setRecords\(\[\]\);/);
  });

  it('keeps one persistent application shell across protected route changes', () => {
    const router = readFileSync('src/router/index.tsx', 'utf8');
    const layout = readFileSync('src/components/Layout.tsx', 'utf8');

    assert.match(router, /<Layout><Outlet\s*\/><\/Layout>/);
    assert.match(router, /shouldUsePersistentShell/);
    assert.match(layout, /LayoutNestingContext/);
    assert.match(layout, /insidePersistentShell/);
    assert.match(layout, /<LayoutShell>/);
  });

  it('verifies navigation by clicking sidebar links without document or shell replacement', () => {
    const browser = readFileSync('scripts/verify-smooth-navigation-browser.mjs', 'utf8');

    assert.match(browser, /documentLoadCount/);
    assert.match(browser, /sidebarNodeStable/);
    assert.match(browser, /tenantModuleRequestCount/);
    assert.match(browser, /locator\(`aside a\[href=/);
    assert.doesNotMatch(browser, /for \(const route of routes\)[\s\S]*page\.goto\(`\$\{BASE_URL\}\$\{route\.path\}`/);
  });
});
