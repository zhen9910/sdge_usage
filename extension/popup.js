// Change to 'https://evsmart.com' before publishing to Web Store.
const API_BASE = 'http://127.0.0.1:5000';

const SDGE_LOGIN_URL = 'https://myenergycenter.com/portal';

async function render() {
  const { status, lastSync } = await chrome.storage.local.get(['status', 'lastSync']);

  const dot        = document.getElementById('dot');
  const label      = document.getElementById('label');
  const hint       = document.getElementById('hint');
  const link       = document.getElementById('link');
  const connectBtn = document.getElementById('connect-btn');

  link.href = API_BASE;

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

  connectBtn.addEventListener('click', () => {
    chrome.tabs.create({ url: SDGE_LOGIN_URL });
  });
}

render();
