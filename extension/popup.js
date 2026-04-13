// Change to 'https://evsmart.com' before publishing to Web Store.
const API_BASE = 'http://127.0.0.1:5000';

const SDGE_LOGIN_URL = 'https://myenergycenter.com/portal';

function applyStatus(status, lastSync, uuid) {
  const dot        = document.getElementById('dot');
  const label      = document.getElementById('label');
  const hint       = document.getElementById('hint');
  const link       = document.getElementById('link');
  const connectBtn = document.getElementById('connect-btn');

  link.href = uuid ? `${API_BASE}/?uuid=${uuid}` : API_BASE;

  if (status === 'connected') {
    dot.className     = 'dot connected';
    label.textContent = 'Connected ✓';
    hint.textContent  = lastSync
      ? `Last synced: ${new Date(lastSync).toLocaleDateString()}`
      : 'Session active';
  } else if (status === 'expired') {
    dot.className     = 'dot disconnected';
    label.textContent = 'Session expired';
    hint.textContent  = 'Log in to SDGE again to reconnect.';
    connectBtn.style.display = 'block';
  } else if (status === 'error') {
    dot.className     = 'dot disconnected';
    label.textContent = 'Connection error';
    hint.textContent  = 'Could not reach EVSmart server';
  } else {
    dot.className     = 'dot unknown';
    label.textContent = 'Not connected';
    hint.textContent  = 'Click below to log in to SDGE.';
    connectBtn.style.display = 'block';
  }

  document.getElementById('connect-btn').addEventListener('click', () => {
    chrome.tabs.create({ url: SDGE_LOGIN_URL });
  });
}

async function render() {
  const stored = await chrome.storage.local.get(['status', 'lastSync', 'uuid']);
  const uuid = stored.uuid;

  // Show cached status immediately, then verify live.
  applyStatus(stored.status, stored.lastSync, uuid);

  // Poll the backend to catch disconnect or expiry that happened since last sync.
  if (uuid) {
    try {
      const resp = await fetch(`${API_BASE}/api/session/status?uuid=${uuid}`);
      const data = await resp.json();
      if (!data.connected && stored.status === 'connected') {
        await chrome.storage.local.set({ status: 'expired', lastSync: null });
        chrome.action.setBadgeText({ text: '!' });
        chrome.action.setBadgeBackgroundColor({ color: '#ef4444' });
        applyStatus('expired', null, uuid);
      }
    } catch (_) {
      // Server unreachable — keep cached status.
    }
  }
}

render();
