# EVSmart SaaS — Design Spec

**Date:** 2026-04-12
**Status:** Approved

---

## Context

The current SDGE Usage MVP is a local Flask app (localhost:5000) for solar + EV owners on SDGE's TOU-DR1 rate plan. It automatically fetches billing data, identifies solar surplus periods, and recommends optimal EV charging windows. It works well technically but is inaccessible to non-technical users who don't know Python, terminals, or localhost URLs.

The goal is to make this available as a public SaaS at a real domain (e.g. evsmart.com) with no installation of Python or technical setup required.

**Key constraint:** SDGE has no public OAuth API. Login is reCAPTCHA-protected, which means the user must authenticate in their own browser on their own machine — the cloud server cannot do this on their behalf without streaming a browser (complex, costly) or official Green Button Connect approval (pending).

**Chosen solution:** A Chrome/Edge browser extension acts as the bridge — it captures SDGE session cookies after the user logs in naturally on sdge.com, and sends them to the cloud SaaS. The cloud then does all data fetching headlessly using those cookies.

---

## Approach Selected: Extension + SaaS (Phase 1)

Other approaches documented for future reference (see bottom of this doc).

---

## Architecture Overview

```
User's browser (Chrome/Edge)          evsmart.com cloud (DigitalOcean)
─────────────────────────────         ──────────────────────────────────
Extension (installed once)
  │
  ├─ Watches sdge.com for login
  ├─ Captures session cookies
  ├─ Generates anonymous UUID
  └─ POST /api/session ──────────────► Flask API
                                         │
                                         ├─ Stores cookies encrypted
                                         │  in SQLite (keyed by UUID)
                                         │
                                         └─ Cron 6AM daily:
                                            Playwright headless fetch
                                            → updates data_json per UUID

User visits evsmart.com ────────────► Reads UUID from browser cookie
                                      Loads data_json for that UUID
                                      Runs get_charging_recommendation()
                                      Renders dashboard ✓
```

---

## Component 1: Browser Extension

**Platform:** Chrome Extension Manifest V3 (also works in Edge)
**Distribution:** Chrome Web Store ($5 one-time dev fee)
**Size:** ~200 lines of JavaScript

### Permissions needed
- `cookies` — read cookies for sdge.com domain
- `storage` — store anonymous UUID persistently
- `host_permissions: ["*://*.sdge.com/*"]` — detect login on SDGE

### Behavior
1. **On install:** Generate a random UUID v4, store in `chrome.storage.local`
2. **Cookie watcher:** Listen for `chrome.cookies.onChanged` events on `sdge.com`
3. **Login detection:** When key SDGE session cookies appear (e.g. `.ASPXAUTH` or equivalent), trigger upload
4. **Upload:** `POST https://evsmart.com/api/session` with `{uuid, cookies: [...]}`
5. **Badge:** Green checkmark when connected; red when session expired (detected via 401 from API)
6. **Popup UI:** Simple status — "Connected ✓ Last synced: Apr 12" or "Session expired — log into sdge.com"

### Files
```
extension/
├── manifest.json
├── background.js     (service worker: cookie watcher + upload logic)
├── popup.html        (status UI)
├── popup.js
└── icons/            (16, 48, 128px)
```

---

## Component 2: SaaS Backend

**Reuses existing code:** `sdge_usage.py`, `fetch_usage.py`, `sdge_auth.py`, `tesla_charge.py`
**New additions:** anonymous session management, multi-user database, API endpoint

### Database (SQLite for MVP)

```sql
CREATE TABLE sessions (
    uuid TEXT PRIMARY KEY,
    sdge_cookies_encrypted BLOB NOT NULL,
    last_fetched_at TEXT,
    data_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### API Endpoints (new)

| Route | Method | Purpose |
|---|---|---|
| `POST /api/session` | POST | Receive UUID + cookies from extension; store encrypted |
| `GET /api/session/status` | GET | Extension polls to check if session is still valid |

### Existing Routes (adapted for multi-user)

| Route | Method | Change |
|---|---|---|
| `GET /` | GET | Read UUID from cookie → load from DB instead of `data/current.json` |
| `GET /fetch` | GET | Fetch data for this UUID's stored session |
| `POST /schedule-tesla` | POST | Same as now, scoped to UUID |
| `GET /connect` | GET | Now shows "Install Extension" instead of login flow |
| `GET /disconnect-sdge` | GET | Deletes row for this UUID from DB |

### Session cookie flow

```python
# In POST /api/session
from cryptography.fernet import Fernet

def store_session(uuid, cookies):
    encrypted = fernet.encrypt(json.dumps(cookies).encode())
    db.execute(
        "INSERT OR REPLACE INTO sessions (uuid, sdge_cookies_encrypted, updated_at) VALUES (?, ?, ?)",
        (uuid, encrypted, datetime.utcnow().isoformat())
    )

# In fetch job
def load_session_cookies(uuid):
    row = db.execute("SELECT sdge_cookies_encrypted FROM sessions WHERE uuid=?", (uuid,)).fetchone()
    return json.loads(fernet.decrypt(row[0]))
```

### Multi-user cron job (replaces single-user `fetch_usage.py`)

```python
# fetch_all.py — runs at 6 AM daily
def fetch_all_sessions():
    uuids = db.execute("SELECT uuid FROM sessions").fetchall()
    for (uuid,) in uuids:
        try:
            cookies = load_session_cookies(uuid)
            result = save_current_billing_data(cookies=cookies)
            db.execute(
                "UPDATE sessions SET data_json=?, last_fetched_at=? WHERE uuid=?",
                (json.dumps(result), datetime.utcnow().isoformat(), uuid)
            )
        except SessionExpiredError:
            # Mark session as expired; extension will show red badge
            db.execute("UPDATE sessions SET sdge_cookies_encrypted=NULL WHERE uuid=?", (uuid,))
```

### UUID cookie flow (no accounts)

```python
# app.py — set UUID cookie on first visit
@app.before_request
def ensure_uuid():
    if 'uuid' not in request.cookies:
        g.new_uuid = str(uuid4())
    else:
        g.new_uuid = None

@app.after_request
def set_uuid_cookie(response):
    if g.get('new_uuid'):
        response.set_cookie('uuid', g.new_uuid, max_age=365*24*3600, httponly=True, samesite='Lax')
    return response
```

No user accounts for MVP. Each browser gets a random UUID stored as a cookie. If the user clears browser storage, they reconnect via the extension and get a new UUID. User accounts (email/Google/magic link) are a future enhancement.

---

## Component 3: Infrastructure

### Hosting
- **Provider:** DigitalOcean Droplet — $6/month (1 vCPU, 1GB RAM, 25GB SSD)
- **OS:** Ubuntu 22.04 LTS
- **Web server:** Nginx (reverse proxy) + Gunicorn (Flask WSGI)
- **SSL:** Let's Encrypt via Certbot (free, auto-renews)

### Domain
- **Registrar:** Cloudflare (~$10/year, includes free CDN + DDoS protection)
- **DNS:** Cloudflare nameservers pointing to DigitalOcean IP

### Cron
```
0 6 * * * cd /var/www/evsmart && python fetch_all.py >> logs/fetch.log 2>&1
```

### Estimated cost
| Item | Cost |
|---|---|
| Domain (Cloudflare) | ~$10/year |
| DigitalOcean Droplet | $6/month = $72/year |
| Chrome Web Store dev fee | $5 one-time |
| **Total Year 1** | **~$87** |

---

## Security Considerations

- SDGE session cookies encrypted at rest using Fernet (AES-128-CBC + HMAC)
- Encryption key stored as environment variable, never in code or DB
- HTTPS enforced everywhere (Nginx + Let's Encrypt)
- UUID is not guessable (UUID v4 = 122 bits of entropy)
- No passwords, no PII stored for MVP
- Extension only sends cookies over HTTPS to evsmart.com
- Cookies deleted from DB when user clicks "Disconnect"

---

## User Flow (Full)

### First-time setup (~2 minutes)
1. Visit evsmart.com → landing page with "Install Chrome Extension" button
2. Click → Chrome Web Store → "Add to Chrome" (one click)
3. Extension installed; popup shows "Not connected — log into sdge.com"
4. User opens sdge.com in any tab, logs in as normal
5. Extension detects login, captures cookies, uploads to evsmart.com
6. Extension popup turns green: "Connected ✓"
7. User visits evsmart.com → dashboard shows billing data + EV recommendation ✓

### Daily (automatic)
- 6 AM cron runs headless Playwright fetch for all active sessions
- User visits evsmart.com any time → sees fresh data

### Session expiry (~every 30 days)
- Extension badge turns red: "Session expired"
- User logs into sdge.com again → extension auto-reconnects silently

### Tesla scheduling (optional, personal use only for MVP)
- User sets up Tesla once via `save_tesla_session.py` (existing flow, unchanged for MVP)
- "Schedule Tesla Now" button on dashboard works as before
- Multi-user Tesla scheduling is a Phase 2 concern

---

## Files to Create / Modify

### New files
- `extension/manifest.json`
- `extension/background.js`
- `extension/popup.html` + `extension/popup.js`
- `extension/icons/` (16, 48, 128px PNGs)
- `db.py` — SQLite connection + session helpers
- `fetch_all.py` — multi-user cron fetcher
- `templates/landing.html` — new landing page with extension install CTA
- `.env` — FERNET_KEY + other secrets (gitignored)

### Modified files
- `app.py` — add UUID cookie logic, `/api/session` endpoint, adapt routes to use DB
- `fetch_usage.py` — accept `cookies` param instead of always loading from `.sdge_session.json`
- `sdge_auth.py` — add `load_session_cookies_from_dict(cookies)` for DB-stored sessions
- `templates/connect.html` — replace "Connect SDGE" button with extension install instructions
- `templates/dashboard.html` — minor: remove local-only elements

---

## Local Testing (Before Registering a Domain)

Everything can be tested end-to-end on your laptop before spending money on a domain or server.

### 1. Run the Flask backend locally
```bash
python app.py
# Runs at http://localhost:5000
```

### 2. Configure the extension to use localhost

In `extension/background.js`, use an environment-switchable API URL:
```js
const API_BASE = chrome.runtime.getManifest().version.includes('dev')
  ? 'http://localhost:5000'
  : 'https://evsmart.com';
```

### 3. Load the extension as "unpacked" in Chrome (no Web Store needed)
1. Open Chrome → `chrome://extensions`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked** → select the `extension/` folder
4. Extension appears in toolbar immediately — no review, no $5 fee needed for testing

### 4. Test the full local flow
1. Visit `http://localhost:5000` → should show landing page with "Install Extension" CTA
2. Log into `sdge.com` in Chrome → extension detects login → badge turns green
3. Extension POSTs cookies to `http://localhost:5000/api/session`
4. Visit `http://localhost:5000` → dashboard loads with your billing data ✓
5. Run `python fetch_all.py` manually → verify DB updated
6. Open a second Chrome profile → repeat → verify each profile sees its own data

### 5. When ready to go live
1. Register domain on Cloudflare (~$10)
2. Spin up DigitalOcean Droplet ($6/month)
3. Deploy Flask app with Gunicorn + Nginx + Let's Encrypt SSL
4. Change extension version string to remove `dev` → `API_BASE` points to production
5. Submit extension to Chrome Web Store ($5 one-time)

---

## Production Verification

1. **Extension:** Load unpacked in Chrome → log into sdge.com → verify badge turns green → check `POST /api/session` received in server logs
2. **Dashboard:** Visit evsmart.com → verify dashboard loads with correct billing data
3. **Fetch:** Manually trigger `python fetch_all.py` → verify `data_json` updated in DB
4. **Session expiry:** Delete cookies from DB → verify extension badge turns red
5. **Disconnect:** Click "Disconnect" → verify DB row deleted → dashboard redirects to landing
6. **Tesla:** Click "Schedule Tesla Now" → verify scheduled charging set on vehicle
7. **SSL:** Verify https://evsmart.com loads with valid cert
8. **Multi-user:** Two different browser profiles with different UUIDs → verify isolated dashboards

---

## Future Approaches (Documented for Reference)

### Approach 1: Browserless LiveURL
Stream a cloud browser to the user via iframe. No extension install needed. Costs $25–140/mo for Browserless. reCAPTCHA risk on datacenter IPs. Good fallback if extension approach hits Chrome Web Store friction.

### Approach 2: Green Button Connect
Official SDGE OAuth flow. Apply at https://www.sdge.com/green-button/green-button-connect-developer-application. Free, no scraping, no Playwright for auth. Apply now and migrate when approved — eliminates extension requirement entirely.

### Approach 3: Packaged Local App
PyInstaller .app/.exe wrapping current MVP. Good for friends/family who won't install an extension. No cloud needed.

### Approach 5: Mobile App (iOS/Android)
Best as a front-end layer on the existing SaaS backend (Phase 2). Push notifications for daily charge recommendations. Requires $99/yr Apple dev account.

### Approach 6: Telegram / WhatsApp Bot
Minimal UI, delivers daily recommendation via message. Great for personal circle. Combine with extension for session management.
