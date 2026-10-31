import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

test('portal layout does not poll management notifications for employee portal accounts', () => {
  const layout = readFileSync('src/components/Layout.tsx', 'utf8');
  const callbackStart = layout.indexOf('const refreshUnreadCount = useCallback');
  const effectEnd = layout.indexOf('}, [refreshUnreadCount]);', callbackStart);
  assert.notEqual(callbackStart, -1);
  assert.notEqual(effectEnd, -1);
  const effectText = layout.slice(callbackStart, effectEnd);

  assert.match(effectText, /isPortalAccount\s*\|\|\s*isPortalRoute\s*\|\|\s*user\?\.isPlatformAdmin/);
  assert.match(effectText, /setUnreadCount\(0\)/);
  assert.match(effectText, /hrmApi\.list\('notifications'/);
  assert.match(effectText, /window\.setInterval\(refreshUnreadCount, 60000\)/);
});

test('portal layout hides the management notification link for employee portal accounts', () => {
  const layout = readFileSync('src/components/Layout.tsx', 'utf8');
  const notificationLink = layout.indexOf('to="/notifications"');
  assert.notEqual(notificationLink, -1);
  const surrounding = layout.slice(Math.max(0, notificationLink - 160), notificationLink + 180);

  assert.match(surrounding, /!isPortalAccount/);
});
