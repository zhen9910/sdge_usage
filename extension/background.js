// EVSmart SDGE Connector — background service worker
// Watches for SDGE login, captures cookies, uploads to EVSmart backend.

// Change to 'https://evsmart.com' before publishing to Web Store.
const API_BASE = 'http://127.0.0.1:5000';

// ── On install: generate a UUID for this browser ──────────────────────────────
chrome.runtime.onInstalled.addListener(async () => {
  const { uuid } = await chrome.storage.local.get(['uuid']);
  if (!uuid) {
    const newUuid = crypto.randomUUID();
    await chrome.storage.local.set({ uuid: newUuid });
    console.log('[EVSmart] Generated UUID:', newUuid.slice(0, 8) + '...');
  }
});

// ── Cookie watcher ────────────────────────────────────────────────────────────
// Debounce uploads: wait 2 s after the last cookie change before uploading.
// This ensures all cookies are set before we capture them.
let _uploadTimer = null;

chrome.cookies.onChanged.addListener((changeInfo) => {
  const domain = changeInfo.cookie.domain || '';
  if (!domain.includes('sdge.com') && !domain.includes('myenergycenter.com')) return;
  if (changeInfo.removed) return;

  clearTimeout(_uploadTimer);
  _uploadTimer = setTimeout(uploadSession, 2000);
});

// ── Upload session to EVSmart ─────────────────────────────────────────────────
async function uploadSession() {
  const { uuid } = await chrome.storage.local.get(['uuid']);
  if (!uuid) return;

  // Collect all cookies for both SDGE domains
  const [sdgeCookies, portalCookies] = await Promise.all([
    chrome.cookies.getAll({ domain: 'sdge.com' }),
    chrome.cookies.getAll({ domain: 'myenergycenter.com' }),
  ]);
  const allCookies = [...sdgeCookies, ...portalCookies];
  if (allCookies.length === 0) return;

  try {
    const response = await fetch(`${API_BASE}/api/session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uuid, cookies: allCookies }),
    });

    if (response.ok) {
      const syncTime = new Date().toISOString();
      await chrome.storage.local.set({ status: 'connected', lastSync: syncTime });

      // Plant the extension's UUID as a browser cookie on the dashboard domain
      // so Flask reads the same UUID when the user visits the site.
      await chrome.cookies.set({
        url: API_BASE,
        name: 'uuid',
        value: uuid,
        path: '/',
        httpOnly: true,
        sameSite: 'lax',
        expirationDate: Math.floor(Date.now() / 1000) + 365 * 24 * 3600,
      });

      chrome.action.setBadgeText({ text: '✓' });
      chrome.action.setBadgeBackgroundColor({ color: '#22c55e' });
      console.log('[EVSmart] Session uploaded at', syncTime);
    } else {
      await chrome.storage.local.set({ status: 'error', lastSync: null });
      chrome.action.setBadgeText({ text: '!' });
      chrome.action.setBadgeBackgroundColor({ color: '#ef4444' });
      console.warn('[EVSmart] Upload returned', response.status);
    }
  } catch (err) {
    console.error('[EVSmart] Upload failed:', err);
  }
}

// ── Periodic status check (every 30 min) ─────────────────────────────────────
async function checkStatus() {
  const { uuid } = await chrome.storage.local.get(['uuid']);
  if (!uuid) return;

  try {
    const response = await fetch(`${API_BASE}/api/session/status?uuid=${uuid}`);
    const data = await response.json();
    if (!data.connected) {
      await chrome.storage.local.set({ status: 'expired' });
      chrome.action.setBadgeText({ text: '!' });
      chrome.action.setBadgeBackgroundColor({ color: '#ef4444' });
    }
  } catch (_) {
    // Network error — don't change status
  }
}

// Run on startup and every 30 minutes
checkStatus();
const THIRTY_MINUTES = 30 * 60 * 1000;
setInterval(checkStatus, THIRTY_MINUTES);
