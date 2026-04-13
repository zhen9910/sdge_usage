# EVSmart SaaS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the single-user local Flask app into a multi-user SaaS backed by a Chrome extension that bridges SDGE authentication.

**Architecture:** A Chrome Manifest V3 extension watches sdge.com for login, captures session cookies, and POSTs them with an anonymous UUID to the Flask backend. The backend encrypts and stores cookies in SQLite, runs daily headless Playwright fetches for all users, and serves personalized dashboards keyed by a UUID cookie in the browser.

**Tech Stack:** Python/Flask (existing), `sqlite3` (stdlib), `cryptography` (Fernet AES), `python-dotenv`, Chrome Extension Manifest V3 (JavaScript)

---

## File Map

```
New files:
  db.py                                     SQLite session CRUD + Fernet encryption
  fetch_all.py                              Multi-user cron fetcher (replaces single-user fetch_usage.py __main__)
  test_db.py                                Unit tests for db.py
  extension/manifest.json                   Chrome extension config (Manifest V3)
  extension/background.js                   Service worker: UUID gen, cookie watcher, upload to backend
  extension/popup.html                      Extension popup status UI
  extension/popup.js                        Popup rendering logic
  extension/icons/icon16.png                Placeholder icon (green square)
  extension/icons/icon48.png
  extension/icons/icon128.png
  templates/landing.html                    Landing page shown to users with no session
  .env                                      FERNET_KEY (gitignored)
  make_icons.py                             One-time script to generate placeholder icons (delete after use)

Modified files:
  fetch_usage.py:33,50,158                  Add cookies= and uuid= params; save to DB when uuid given
  app.py                                    Add UUID cookie middleware, /api/session, /api/session/status; read from DB
  templates/connect.html                    Replace "Connect SDGE" button with extension install instructions
  .gitignore                                Add .env and data/evsmart.db
  sdge_usage_test.py                        No changes needed — existing tests stay green throughout
```

---

## Task 1: Install Dependencies and Set Up `.env`

**Files:**
- Create: `.env`
- Modify: `.gitignore`

- [ ] **Step 1: Install new packages**

```bash
pip install cryptography python-dotenv
```

Expected output: `Successfully installed cryptography-... python-dotenv-...`

- [ ] **Step 2: Generate a Fernet key**

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output — it looks like `dGhpcyBpcyBhIHRlc3Qga2V5...` (43 base64 chars ending in `=`).

- [ ] **Step 3: Create `.env`**

```
FERNET_KEY=<paste key here>
```

- [ ] **Step 4: Add to `.gitignore`**

Append to the existing `.gitignore`:

```
.env
data/evsmart.db
```

- [ ] **Step 5: Verify existing tests still pass**

```bash
python -m unittest sdge_usage_test.py -v
```

Expected: all tests pass (no changes to existing code yet).

- [ ] **Step 6: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore .env and evsmart.db"
```

---

## Task 2: Create `db.py` — SQLite Session Layer

**Files:**
- Create: `db.py`
- Create: `test_db.py`

- [ ] **Step 1: Write the failing tests**

Create `test_db.py`:

```python
import importlib
import json
import os
import tempfile
import unittest
from cryptography.fernet import Fernet


class TestDb(unittest.TestCase):
    def setUp(self):
        # Generate a fresh key and temp DB for each test
        key = Fernet.generate_key().decode()
        os.environ['FERNET_KEY'] = key
        self._tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        os.environ['DB_PATH'] = self._tmp.name

        import db
        importlib.reload(db)       # pick up new env vars
        db._fernet = None          # reset cached Fernet instance
        db.init_db()
        self.db = db

    def test_store_and_load_session(self):
        cookies = [{'name': 'auth', 'value': 'abc', 'domain': '.sdge.com'}]
        self.db.store_session('uuid-1', cookies)
        self.assertEqual(self.db.load_session_cookies('uuid-1'), cookies)

    def test_load_nonexistent_returns_none(self):
        self.assertIsNone(self.db.load_session_cookies('nonexistent'))

    def test_mark_session_expired_nulls_cookies(self):
        self.db.store_session('uuid-1', [{'name': 'a', 'value': 'b'}])
        self.db.mark_session_expired('uuid-1')
        self.assertIsNone(self.db.load_session_cookies('uuid-1'))

    def test_save_and_load_data(self):
        self.db.store_session('uuid-1', [])
        data = {'super_off_peak_kwh': -100.0, 'on_peak_kwh': 50.0, 'fetched_at': '2026-04-12T06:00:00'}
        self.db.save_data('uuid-1', data)
        self.assertEqual(self.db.load_data('uuid-1'), data)

    def test_load_data_returns_none_before_first_fetch(self):
        self.db.store_session('uuid-1', [])
        self.assertIsNone(self.db.load_data('uuid-1'))

    def test_clear_session_removes_row(self):
        self.db.store_session('uuid-1', [])
        self.db.clear_session('uuid-1')
        self.assertIsNone(self.db.load_session_cookies('uuid-1'))
        self.assertIsNone(self.db.load_data('uuid-1'))

    def test_list_active_uuids_excludes_expired(self):
        self.db.store_session('uuid-1', [{'name': 'a'}])
        self.db.store_session('uuid-2', [{'name': 'b'}])
        self.db.mark_session_expired('uuid-1')
        active = self.db.list_active_uuids()
        self.assertNotIn('uuid-1', active)
        self.assertIn('uuid-2', active)

    def test_store_session_overwrites_on_conflict(self):
        self.db.store_session('uuid-1', [{'name': 'old'}])
        self.db.store_session('uuid-1', [{'name': 'new'}])
        result = self.db.load_session_cookies('uuid-1')
        self.assertEqual(result[0]['name'], 'new')


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m unittest test_db.py -v
```

Expected: `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 3: Create `db.py`**

```python
"""SQLite session storage with Fernet encryption for SDGE cookies.

Environment variables:
  FERNET_KEY  Base64-encoded 32-byte Fernet key (required)
  DB_PATH     Path to SQLite DB file (default: data/evsmart.db)
"""

import json
import os
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet

_fernet = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(os.environ['FERNET_KEY'].encode())
    return _fernet


def _db_path() -> str:
    return os.environ.get('DB_PATH', 'data/evsmart.db')


def get_db() -> sqlite3.Connection:
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                uuid                    TEXT PRIMARY KEY,
                sdge_cookies_encrypted  BLOB,
                last_fetched_at         TEXT,
                data_json               TEXT,
                created_at              TEXT DEFAULT (datetime('now')),
                updated_at              TEXT DEFAULT (datetime('now'))
            )
        ''')


def store_session(uuid: str, cookies: list) -> None:
    """Encrypt and store SDGE session cookies for the given anonymous UUID."""
    encrypted = _get_fernet().encrypt(json.dumps(cookies).encode())
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO sessions (uuid, sdge_cookies_encrypted, updated_at)
               VALUES (?, ?, datetime('now'))""",
            (uuid, encrypted),
        )


def load_session_cookies(uuid: str) -> list | None:
    """Return decrypted SDGE cookies for uuid, or None if missing/expired."""
    with get_db() as conn:
        row = conn.execute(
            'SELECT sdge_cookies_encrypted FROM sessions WHERE uuid = ?', (uuid,)
        ).fetchone()
    if row is None or row['sdge_cookies_encrypted'] is None:
        return None
    return json.loads(_get_fernet().decrypt(row['sdge_cookies_encrypted']))


def load_data(uuid: str) -> dict | None:
    """Return cached billing data dict for uuid, or None if not yet fetched."""
    with get_db() as conn:
        row = conn.execute(
            'SELECT data_json FROM sessions WHERE uuid = ?', (uuid,)
        ).fetchone()
    if row is None or row['data_json'] is None:
        return None
    return json.loads(row['data_json'])


def save_data(uuid: str, data: dict) -> None:
    """Update billing data and last_fetched_at for uuid."""
    with get_db() as conn:
        conn.execute(
            """UPDATE sessions
               SET data_json = ?, last_fetched_at = datetime('now'), updated_at = datetime('now')
               WHERE uuid = ?""",
            (json.dumps(data), uuid),
        )


def clear_session(uuid: str) -> None:
    """Delete all data for uuid (user disconnect)."""
    with get_db() as conn:
        conn.execute('DELETE FROM sessions WHERE uuid = ?', (uuid,))


def mark_session_expired(uuid: str) -> None:
    """Null out cookies so the extension shows a red badge; preserve data_json."""
    with get_db() as conn:
        conn.execute(
            "UPDATE sessions SET sdge_cookies_encrypted = NULL, updated_at = datetime('now') WHERE uuid = ?",
            (uuid,),
        )


def list_active_uuids() -> list[str]:
    """Return UUIDs with non-null cookies (eligible for cron fetch)."""
    with get_db() as conn:
        rows = conn.execute(
            'SELECT uuid FROM sessions WHERE sdge_cookies_encrypted IS NOT NULL'
        ).fetchall()
    return [row['uuid'] for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m unittest test_db.py -v
```

Expected: 8 tests, all PASS.

- [ ] **Step 5: Verify existing tests still pass**

```bash
python -m unittest sdge_usage_test.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add db.py test_db.py
git commit -m "feat: add SQLite session layer with Fernet encryption"
```

---

## Task 3: Update `fetch_usage.py` to Accept `cookies` and `uuid` Params

**Files:**
- Modify: `fetch_usage.py:33,50,158-170`

The two changes:
1. `fetch_current_billing_csv(debug, cookies)` — accepts cookies list directly; falls back to `load_session_cookies()` if not given.
2. `save_current_billing_data(uuid, cookies)` — if `uuid` given, saves to DB via `db.save_data()`; otherwise saves to `data/current.json` (backward compat for local CLI use).

- [ ] **Step 1: Write the failing tests**

Add to `test_db.py` (at the bottom, before `if __name__ == '__main__'`):

```python
class TestFetchUsageParams(unittest.TestCase):
    """Verify fetch_usage.py accepts cookies/uuid params without calling Playwright."""

    def test_save_current_billing_data_saves_to_db_when_uuid_given(self):
        """save_current_billing_data(uuid=..., cookies=...) must call db.save_data, not write a file."""
        import importlib
        import io
        import unittest.mock as mock

        import fetch_usage

        fake_result = {
            'meter_number': '123',
            'reading_start': '3/1/2026 00:00',
            'reading_end': '3/31/2026 23:45',
            'super_off_peak_kwh': -50.0,
            'off_peak_kwh': 20.0,
            'on_peak_kwh': 10.0,
            'total_kwh': -20.0,
        }

        with mock.patch('fetch_usage.fetch_current_billing_csv', return_value=b'fake,csv') as mock_fetch, \
             mock.patch('fetch_usage.iter_rows_csv_stream', return_value=[]), \
             mock.patch('fetch_usage.process', return_value=fake_result.copy()), \
             mock.patch('fetch_usage.db') as mock_db:

            result = fetch_usage.save_current_billing_data(uuid='uuid-99', cookies=[{'name': 'a'}])

        mock_fetch.assert_called_once_with(cookies=[{'name': 'a'}])
        mock_db.save_data.assert_called_once()
        call_args = mock_db.save_data.call_args
        self.assertEqual(call_args[0][0], 'uuid-99')
        self.assertIn('fetched_at', call_args[0][1])

    def test_save_current_billing_data_writes_file_when_no_uuid(self):
        """save_current_billing_data() without uuid must write data/current.json."""
        import io
        import unittest.mock as mock
        import fetch_usage

        fake_result = {
            'meter_number': '123',
            'reading_start': '3/1/2026 00:00',
            'reading_end': '3/31/2026 23:45',
            'super_off_peak_kwh': -50.0,
            'off_peak_kwh': 20.0,
            'on_peak_kwh': 10.0,
            'total_kwh': -20.0,
        }

        with mock.patch('fetch_usage.fetch_current_billing_csv', return_value=b'fake,csv'), \
             mock.patch('fetch_usage.iter_rows_csv_stream', return_value=[]), \
             mock.patch('fetch_usage.process', return_value=fake_result.copy()), \
             mock.patch('pathlib.Path.write_text') as mock_write:

            fetch_usage.save_current_billing_data()

        mock_write.assert_called_once()
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m unittest test_db.py TestFetchUsageParams -v
```

Expected: `TypeError` or `AssertionError` — `save_current_billing_data` doesn't accept `uuid`/`cookies` yet.

- [ ] **Step 3: Update `fetch_usage.py`**

Replace lines 25-26 (imports):
```python
from sdge_auth import load_session_cookies
from sdge_usage import iter_rows_csv_stream, process
```
with:
```python
from sdge_auth import load_session_cookies
from sdge_usage import iter_rows_csv_stream, process
import db
```

Replace the function signature at line 33:
```python
def fetch_current_billing_csv(debug: bool = False) -> bytes:
```
with:
```python
def fetch_current_billing_csv(debug: bool = False, cookies: list | None = None) -> bytes:
```

Replace line 50:
```python
        context.add_cookies(load_session_cookies())
```
with:
```python
        context.add_cookies(cookies if cookies is not None else load_session_cookies())
```

Replace lines 158-170 (`save_current_billing_data`):
```python
def save_current_billing_data() -> dict:
    """Download, parse, and cache the current billing period data.

    Returns:
        The result dict (same shape as sdge_usage.process() plus 'fetched_at').
    """
    csv_bytes = fetch_current_billing_csv()
    rows = iter_rows_csv_stream(io.BytesIO(csv_bytes))
    result = process(rows)
    result["fetched_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    DATA_DIR.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(result, default=str))
    return result
```
with:
```python
def save_current_billing_data(uuid: str | None = None, cookies: list | None = None) -> dict:
    """Download, parse, and cache the current billing period data.

    Args:
        uuid: Anonymous session UUID. If given, saves result to SQLite via db.save_data().
              If None, saves to data/current.json (local CLI backward-compat).
        cookies: SDGE session cookies list. If None, loads from .sdge_session.json.

    Returns:
        The result dict (same shape as sdge_usage.process() plus 'fetched_at').
    """
    csv_bytes = fetch_current_billing_csv(cookies=cookies)
    rows = iter_rows_csv_stream(io.BytesIO(csv_bytes))
    result = process(rows)
    result["fetched_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    if uuid is not None:
        db.save_data(uuid, result)
    else:
        DATA_DIR.mkdir(exist_ok=True)
        CACHE_FILE.write_text(json.dumps(result, default=str))
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m unittest test_db.py -v
```

Expected: all PASS.

- [ ] **Step 5: Verify existing tests still pass**

```bash
python -m unittest sdge_usage_test.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add fetch_usage.py test_db.py
git commit -m "feat: fetch_usage accepts cookies= and uuid= params for multi-user support"
```

---

## Task 4: Create `fetch_all.py` — Multi-User Cron Fetcher

**Files:**
- Create: `fetch_all.py`

- [ ] **Step 1: Write the failing tests**

Add to `test_db.py`:

```python
class TestFetchAll(unittest.TestCase):
    def setUp(self):
        key = Fernet.generate_key().decode()
        os.environ['FERNET_KEY'] = key
        import tempfile
        self._tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        os.environ['DB_PATH'] = self._tmp.name
        import db
        importlib.reload(db)
        db._fernet = None
        db.init_db()
        self.db = db

    def test_fetch_all_calls_save_for_each_active_uuid(self):
        import unittest.mock as mock
        self.db.store_session('uuid-a', [{'name': 'cookie_a'}])
        self.db.store_session('uuid-b', [{'name': 'cookie_b'}])

        import fetch_all
        with mock.patch('fetch_all.save_current_billing_data') as mock_save, \
             mock.patch('fetch_all.db', self.db):
            fetch_all.fetch_all_sessions()

        self.assertEqual(mock_save.call_count, 2)
        called_uuids = {call[1]['uuid'] for call in mock_save.call_args_list}
        self.assertIn('uuid-a', called_uuids)
        self.assertIn('uuid-b', called_uuids)

    def test_fetch_all_marks_expired_on_session_error(self):
        import unittest.mock as mock
        self.db.store_session('uuid-bad', [{'name': 'stale'}])

        import fetch_all
        with mock.patch('fetch_all.save_current_billing_data', side_effect=Exception('401 Unauthorized')), \
             mock.patch('fetch_all.db', self.db):
            fetch_all.fetch_all_sessions()

        self.assertIsNone(self.db.load_session_cookies('uuid-bad'))

    def test_fetch_all_skips_expired_sessions(self):
        import unittest.mock as mock
        self.db.store_session('uuid-active', [{'name': 'good'}])
        self.db.store_session('uuid-expired', [{'name': 'gone'}])
        self.db.mark_session_expired('uuid-expired')

        import fetch_all
        with mock.patch('fetch_all.save_current_billing_data') as mock_save, \
             mock.patch('fetch_all.db', self.db):
            fetch_all.fetch_all_sessions()

        self.assertEqual(mock_save.call_count, 1)
        self.assertEqual(mock_save.call_args[1]['uuid'], 'uuid-active')
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m unittest test_db.py TestFetchAll -v
```

Expected: `ModuleNotFoundError: No module named 'fetch_all'`

- [ ] **Step 3: Create `fetch_all.py`**

```python
"""Multi-user cron fetcher.

Iterates all active SDGE sessions in the database and runs a headless
Playwright fetch for each one. Marks sessions as expired on auth errors.

Usage:
    python fetch_all.py

Cron (6 AM daily):
    0 6 * * * cd /path/to/evsmart && python fetch_all.py >> logs/fetch.log 2>&1
"""

import logging
import sys

import db
from fetch_usage import save_current_billing_data

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# Error substrings that indicate an expired/invalid SDGE session
_SESSION_ERROR_SIGNALS = ('401', '403', 'unauthorized', 'session', 'login', 'expired')


def fetch_all_sessions() -> None:
    uuids = db.list_active_uuids()
    logger.info("Starting fetch for %d active session(s)", len(uuids))

    for uuid in uuids:
        short = uuid[:8]
        try:
            cookies = db.load_session_cookies(uuid)
            save_current_billing_data(uuid=uuid, cookies=cookies)
            logger.info("Fetched data for %s...", short)
        except Exception as exc:
            msg = str(exc).lower()
            if any(signal in msg for signal in _SESSION_ERROR_SIGNALS):
                logger.warning("Session expired for %s...: %s", short, exc)
                db.mark_session_expired(uuid)
            else:
                logger.error("Fetch failed for %s...: %s", short, exc)


if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    db.init_db()
    fetch_all_sessions()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m unittest test_db.py TestFetchAll -v
```

Expected: 3 tests, all PASS.

- [ ] **Step 5: Commit**

```bash
git add fetch_all.py test_db.py
git commit -m "feat: add multi-user cron fetcher fetch_all.py"
```

---

## Task 5: Update `app.py` — UUID Cookie + API Endpoints + Multi-User Routes

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Write the failing tests**

Create `test_app.py`:

```python
import importlib
import json
import os
import tempfile
import unittest
from cryptography.fernet import Fernet


def _make_app():
    """Return a configured Flask test client with a fresh temp DB."""
    key = Fernet.generate_key().decode()
    os.environ['FERNET_KEY'] = key
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    os.environ['DB_PATH'] = tmp.name
    import db
    importlib.reload(db)
    db._fernet = None
    db.init_db()

    import app as flask_app
    importlib.reload(flask_app)
    flask_app.app.config['TESTING'] = True
    flask_app.app.config['SECRET_KEY'] = 'test-secret'
    return flask_app.app.test_client(), db


class TestApiSession(unittest.TestCase):
    def setUp(self):
        self.client, self.db = _make_app()

    def test_post_api_session_stores_cookies(self):
        payload = {'uuid': 'test-uuid', 'cookies': [{'name': 'auth', 'value': 'x'}]}
        r = self.client.post('/api/session',
                             data=json.dumps(payload),
                             content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(self.db.load_session_cookies('test-uuid'))

    def test_post_api_session_missing_uuid_returns_400(self):
        r = self.client.post('/api/session',
                             data=json.dumps({'cookies': []}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_post_api_session_missing_cookies_returns_400(self):
        r = self.client.post('/api/session',
                             data=json.dumps({'uuid': 'u'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_get_session_status_connected(self):
        self.db.store_session('my-uuid', [{'name': 'a'}])
        r = self.client.get('/api/session/status?uuid=my-uuid')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(json.loads(r.data)['connected'])

    def test_get_session_status_not_connected(self):
        r = self.client.get('/api/session/status?uuid=unknown')
        self.assertFalse(json.loads(r.data)['connected'])

    def test_get_session_status_expired(self):
        self.db.store_session('exp-uuid', [{'name': 'a'}])
        self.db.mark_session_expired('exp-uuid')
        r = self.client.get('/api/session/status?uuid=exp-uuid')
        self.assertFalse(json.loads(r.data)['connected'])


class TestIndexRoute(unittest.TestCase):
    def setUp(self):
        self.client, self.db = _make_app()

    def _set_uuid_cookie(self, uuid):
        self.client.set_cookie('uuid', uuid)

    def test_index_without_uuid_sets_uuid_cookie(self):
        r = self.client.get('/')
        self.assertIn('uuid', r.headers.get('Set-Cookie', ''))

    def test_index_no_session_shows_landing(self):
        self._set_uuid_cookie('brand-new-uuid')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Install', r.data)

    def test_index_session_but_no_data_redirects_to_fetch(self):
        self.db.store_session('has-session', [{'name': 'a'}])
        self._set_uuid_cookie('has-session')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/fetch', r.headers['Location'])

    def test_index_with_data_shows_dashboard(self):
        data = {
            'meter_number': '123',
            'reading_start': '3/1/2026 00:00',
            'reading_end': '3/31/2026 23:45',
            'super_off_peak_kwh': -50.0,
            'off_peak_kwh': 20.0,
            'on_peak_kwh': 10.0,
            'total_kwh': -20.0,
            'fetched_at': '2026-04-12T06:00:00',
        }
        self.db.store_session('full-uuid', [{'name': 'a'}])
        self.db.save_data('full-uuid', data)
        self._set_uuid_cookie('full-uuid')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Super Off-Peak', r.data)


class TestDisconnect(unittest.TestCase):
    def setUp(self):
        self.client, self.db = _make_app()

    def test_disconnect_clears_session(self):
        self.db.store_session('del-uuid', [{'name': 'a'}])
        self.client.set_cookie('uuid', 'del-uuid')
        self.client.get('/disconnect-sdge')
        self.assertIsNone(self.db.load_session_cookies('del-uuid'))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m unittest test_app.py -v
```

Expected: failures because `app.py` doesn't have `/api/session`, UUID middleware, or DB-backed routes yet.

- [ ] **Step 3: Rewrite `app.py`**

```python
import datetime
import json
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from flask import Flask, flash, g, redirect, render_template, request, url_for

load_dotenv()

import db
from sdge_usage import get_charging_recommendation, iter_rows_csv_stream, iter_rows_xlsx_stream, process

app = Flask(__name__)
app.secret_key = "sdge-usage-secret"

ALLOWED_EXTENSIONS = {"csv", "xlsx"}


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _staleness(result: dict) -> tuple[bool, int]:
    """Return (is_stale, hours_since_fetch). Stale when older than 48 h."""
    fetched_at_str = result.get("fetched_at")
    if not fetched_at_str:
        return True, 999
    try:
        fetched_at = datetime.datetime.fromisoformat(fetched_at_str)
        hours = int((datetime.datetime.now() - fetched_at).total_seconds() / 3600)
        return hours > 48, hours
    except (ValueError, TypeError):
        return True, 999


def _tesla_session_exists() -> bool:
    try:
        from tesla_charge import tesla_session_exists  # noqa: PLC0415
        return tesla_session_exists()
    except ImportError:
        return False


# ── UUID cookie middleware ─────────────────────────────────────────────────────

@app.before_request
def ensure_uuid_cookie():
    g.uuid = request.cookies.get('uuid')
    g.new_uuid = None
    if not g.uuid:
        g.uuid = str(uuid4())
        g.new_uuid = g.uuid


@app.after_request
def set_uuid_cookie_if_new(response):
    if g.get('new_uuid'):
        response.set_cookie(
            'uuid', g.new_uuid,
            max_age=365 * 24 * 3600,
            httponly=True,
            samesite='Lax',
        )
    return response


# ── API endpoints (called by Chrome extension) ─────────────────────────────────

@app.route('/api/session', methods=['POST'])
def api_store_session():
    data = request.get_json(silent=True)
    if not data or 'uuid' not in data or 'cookies' not in data:
        return {'error': 'uuid and cookies required'}, 400
    db.store_session(data['uuid'], data['cookies'])
    return {'status': 'ok'}, 200


@app.route('/api/session/status', methods=['GET'])
def api_session_status():
    uuid = request.cookies.get('uuid') or request.args.get('uuid', '')
    cookies = db.load_session_cookies(uuid) if uuid else None
    return {'connected': cookies is not None}, 200


# ── Page routes ────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    uuid = g.uuid
    cookies = db.load_session_cookies(uuid)
    if cookies is None:
        return render_template('landing.html')
    cached = db.load_data(uuid)
    if cached is None:
        flash("Fetching your SDGE data for the first time…", "info")
        return redirect(url_for('fetch'))
    recommendation = get_charging_recommendation(cached)
    is_stale, hours_since_fetch = _staleness(cached)
    return render_template(
        'dashboard.html',
        result=cached,
        recommendation=recommendation,
        is_stale=is_stale,
        hours_since_fetch=hours_since_fetch,
        tesla_session_exists=_tesla_session_exists(),
    )


@app.route('/disconnect-sdge')
def disconnect_sdge():
    db.clear_session(g.uuid)
    return redirect(url_for('index'))


@app.route('/fetch', methods=['GET', 'POST'])
def fetch():
    uuid = g.uuid
    cookies = db.load_session_cookies(uuid)
    if cookies is None:
        flash("No SDGE session found. Please install the extension and log into sdge.com.", "danger")
        return redirect(url_for('index'))
    from fetch_usage import save_current_billing_data  # noqa: PLC0415
    try:
        save_current_billing_data(uuid=uuid, cookies=cookies)
        flash("Usage data refreshed successfully.", "success")
    except Exception as e:
        flash(f"Fetch failed: {e}", "danger")
    return redirect(url_for('index'))


@app.route('/schedule-tesla', methods=['POST'])
def schedule_tesla():
    cached = db.load_data(g.uuid)
    if not cached:
        flash("No usage data available. Please fetch data first.", "warning")
        return redirect(url_for('index'))
    from tesla_charge import apply_charge_schedule  # noqa: PLC0415
    rec = get_charging_recommendation(cached)
    outcome = apply_charge_schedule(rec['charge_start'], rec['charge_end'])
    if outcome['success']:
        flash(
            f"Tesla scheduled to charge "
            f"{rec['charge_start']:02d}:00\u2013{rec['charge_end']:02d}:00 "
            f"({outcome['vehicle']}).",
            "success",
        )
    else:
        flash(f"Tesla scheduling failed: {outcome['error']}", "danger")
    return redirect(url_for('index'))


@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or file.filename == '':
            flash("Please select a file.", "danger")
            return redirect(url_for('upload'))
        if not _allowed_file(file.filename):
            flash("Only .csv and .xlsx files are supported.", "danger")
            return redirect(url_for('upload'))
        ext = file.filename.rsplit('.', 1)[1].lower()
        try:
            rows = iter_rows_csv_stream(file.stream) if ext == 'csv' else iter_rows_xlsx_stream(file.stream)
            result = process(rows)
            result['filename'] = file.filename
            return render_template('result.html', result=result)
        except Exception as e:
            flash(f"Error processing file: {e}", "danger")
            return redirect(url_for('upload'))
    return render_template('index.html')


if __name__ == '__main__':
    db.init_db()
    app.run(debug=True)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m unittest test_app.py -v
```

Expected: all PASS.

- [ ] **Step 5: Verify all existing tests still pass**

```bash
python -m unittest sdge_usage_test.py test_db.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app.py test_app.py
git commit -m "feat: multi-user app.py with UUID cookie, /api/session, DB-backed routes"
```

---

## Task 6: Create `templates/landing.html` and Update `templates/connect.html`

**Files:**
- Create: `templates/landing.html`
- Modify: `templates/connect.html`

- [ ] **Step 1: Read the existing connect.html to match styles**

```bash
cat templates/connect.html
```

Note the Bootstrap classes and layout used, then apply the same style.

- [ ] **Step 2: Create `templates/landing.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>EVSmart — Solar EV Charging</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
  <style>
    body { background: #f8fafc; }
    .hero { padding: 80px 0 60px; }
    .step-num { width: 32px; height: 32px; border-radius: 50%; background: #0d6efd;
                color: #fff; display: inline-flex; align-items: center;
                justify-content: center; font-weight: bold; margin-right: 12px; flex-shrink: 0; }
    .step { display: flex; align-items: flex-start; margin-bottom: 20px; }
  </style>
</head>
<body>
  <div class="container hero">
    <div class="row justify-content-center">
      <div class="col-md-6 text-center">
        <h1 class="fw-bold mb-2">EVSmart</h1>
        <p class="lead text-muted mb-4">
          Automatically find the cheapest window to charge your EV<br>
          using your SDGE solar surplus.
        </p>

        {% with messages = get_flashed_messages(with_categories=true) %}
          {% for category, message in messages %}
            <div class="alert alert-{{ category }}">{{ message }}</div>
          {% endfor %}
        {% endwith %}

        <a href="https://chrome.google.com/webstore" target="_blank"
           class="btn btn-primary btn-lg mb-4">
          Install Chrome Extension
        </a>

        <div class="card text-start p-4">
          <h6 class="fw-semibold mb-3">How to get started</h6>
          <div class="step">
            <span class="step-num">1</span>
            <div>Click <strong>Install Chrome Extension</strong> above and add it to Chrome.</div>
          </div>
          <div class="step">
            <span class="step-num">2</span>
            <div>Visit <a href="https://myenergycenter.com/portal" target="_blank">sdge.com</a>
                 and log in to your account as normal.</div>
          </div>
          <div class="step">
            <span class="step-num">3</span>
            <div>The extension detects your login automatically.
                 Come back here — your dashboard will be ready.</div>
          </div>
        </div>

        <p class="text-muted mt-3" style="font-size:0.85rem;">
          Your SDGE credentials are never stored on this server.
          Session data is encrypted and tied only to your browser.
        </p>
      </div>
    </div>
  </div>
</body>
</html>
```

- [ ] **Step 3: Update `templates/connect.html`**

Replace the existing "Connect SDGE Account" button content with a redirect to the landing page instructions. Since `GET /` now renders `landing.html` directly when no session exists, `connect.html` is no longer used by the main routing. Keep the file but simplify it to a redirect:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta http-equiv="refresh" content="0;url=/">
  <title>Redirecting…</title>
</head>
<body>
  <p><a href="/">Click here if not redirected</a></p>
</body>
</html>
```

- [ ] **Step 4: Verify app starts and landing page renders**

```bash
FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") python app.py
```

Open `http://localhost:5000` — should show the landing page with 3 steps and "Install Chrome Extension" button.

Stop the server with Ctrl-C.

- [ ] **Step 5: Commit**

```bash
git add templates/landing.html templates/connect.html
git commit -m "feat: add landing page for new SaaS users"
```

---

## Task 7: Create the Chrome Extension

**Files:**
- Create: `extension/manifest.json`
- Create: `extension/background.js`
- Create: `extension/popup.html`
- Create: `extension/popup.js`
- Create: `make_icons.py` (one-time, delete after)
- Create: `extension/icons/icon16.png`, `icon48.png`, `icon128.png`

- [ ] **Step 1: Discover which SDGE cookies indicate a successful login**

Before writing the extension, you need to know which cookie name(s) SDGE sets after login so the extension can trigger the upload at the right time.

1. Open Chrome DevTools → Application → Cookies → `https://myenergycenter.com`
2. Log in to SDGE
3. Note all cookie names that appear after successful login (look for auth-related names like `.ASPXAUTH`, `ARRAffinity`, `SDGESession`, or similar)
4. Write down the names — you'll use them in `background.js` Step 3.

If you can't log in right now, use `''` as a trigger pattern (upload on any cookie change for sdge.com) — it's slightly over-eager but safe and correct.

- [ ] **Step 2: Generate placeholder icons**

Create `make_icons.py`:

```python
"""One-time script to generate green square placeholder icons for the extension.
Delete this file after running.
"""
import struct
import zlib
from pathlib import Path

def make_png(size):
    """Return minimal valid PNG bytes for a solid green square."""
    def chunk(name, data):
        c = struct.pack('>I', len(data)) + name + data
        return c + struct.pack('>I', zlib.crc32(c[4:]) & 0xffffffff)

    raw = b'\x00' + bytes([0x22, 0xc5, 0x5e] * size) * size  # green #22c55e
    compressed = zlib.compress(raw)
    ihdr = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', ihdr)
        + chunk(b'IDAT', compressed)
        + chunk(b'IEND', b'')
    )

out = Path('extension/icons')
out.mkdir(parents=True, exist_ok=True)
for size in [16, 48, 128]:
    (out / f'icon{size}.png').write_bytes(make_png(size))
    print(f'Created icon{size}.png')
```

Run it:
```bash
python make_icons.py
```

Expected output:
```
Created icon16.png
Created icon48.png
Created icon128.png
```

- [ ] **Step 3: Create `extension/manifest.json`**

```json
{
  "manifest_version": 3,
  "name": "EVSmart SDGE Connector",
  "version": "0.1.0-dev",
  "description": "Connects your SDGE account to EVSmart for automatic EV charging recommendations",
  "permissions": ["cookies", "storage"],
  "host_permissions": [
    "*://*.sdge.com/*",
    "*://*.myenergycenter.com/*",
    "http://localhost:5000/*"
  ],
  "background": {
    "service_worker": "background.js"
  },
  "action": {
    "default_popup": "popup.html",
    "default_icon": {
      "16": "icons/icon16.png",
      "48": "icons/icon48.png",
      "128": "icons/icon128.png"
    }
  },
  "icons": {
    "16": "icons/icon16.png",
    "48": "icons/icon48.png",
    "128": "icons/icon128.png"
  }
}
```

Note: `host_permissions` includes `myenergycenter.com` because that's SDGE's actual portal domain (confirmed in `sdge_auth.py:BASE_URL`).

- [ ] **Step 4: Create `extension/background.js`**

```js
// EVSmart SDGE Connector — background service worker
// Watches for SDGE login, captures cookies, uploads to EVSmart backend.

const API_BASE = chrome.runtime.getManifest().version.includes('dev')
  ? 'http://localhost:5000'
  : 'https://evsmart.com';

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
      chrome.action.setBadgeText({ text: '✓' });
      chrome.action.setBadgeBackgroundColor({ color: '#22c55e' });
      console.log('[EVSmart] Session uploaded at', syncTime);
    } else {
      await chrome.storage.local.set({ status: 'error' });
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
```

- [ ] **Step 5: Create `extension/popup.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      width: 260px;
      padding: 16px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 14px;
      color: #1e293b;
    }
    h1 { font-size: 16px; font-weight: 700; margin-bottom: 12px; }
    .status-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
    .dot {
      width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;
    }
    .dot.connected   { background: #22c55e; }
    .dot.disconnected{ background: #ef4444; }
    .dot.unknown     { background: #94a3b8; }
    .label { font-weight: 600; }
    .hint  { font-size: 12px; color: #64748b; margin-bottom: 12px; }
    a.dashboard-link {
      display: block; text-align: center; padding: 8px;
      background: #0d6efd; color: #fff; border-radius: 6px;
      text-decoration: none; font-size: 13px; font-weight: 500;
    }
    a.dashboard-link:hover { background: #0b5ed7; }
  </style>
</head>
<body>
  <h1>EVSmart</h1>
  <div class="status-row">
    <div class="dot" id="dot"></div>
    <span class="label" id="label">Checking…</span>
  </div>
  <div class="hint" id="hint"></div>
  <a class="dashboard-link" id="link" href="#" target="_blank">Open Dashboard →</a>
  <script src="popup.js"></script>
</body>
</html>
```

- [ ] **Step 6: Create `extension/popup.js`**

```js
const API_BASE = chrome.runtime.getManifest().version.includes('dev')
  ? 'http://localhost:5000'
  : 'https://evsmart.com';

async function render() {
  const { status, lastSync } = await chrome.storage.local.get(['status', 'lastSync']);

  const dot   = document.getElementById('dot');
  const label = document.getElementById('label');
  const hint  = document.getElementById('hint');
  const link  = document.getElementById('link');

  link.href = API_BASE;

  if (status === 'connected') {
    dot.className   = 'dot connected';
    label.textContent = 'Connected ✓';
    hint.textContent  = lastSync
      ? `Last synced: ${new Date(lastSync).toLocaleDateString()}`
      : 'Session active';
  } else if (status === 'expired') {
    dot.className   = 'dot disconnected';
    label.textContent = 'Session expired';
    hint.textContent  = 'Log into sdge.com to reconnect';
  } else if (status === 'error') {
    dot.className   = 'dot disconnected';
    label.textContent = 'Connection error';
    hint.textContent  = 'Could not reach EVSmart server';
  } else {
    dot.className   = 'dot unknown';
    label.textContent = 'Not connected';
    hint.textContent  = 'Log into sdge.com to connect';
  }
}

render();
```

- [ ] **Step 7: Load extension as unpacked and test manually**

1. Start Flask: `python app.py` (with `.env` loaded)
2. Open Chrome → `chrome://extensions` → enable **Developer mode**
3. Click **Load unpacked** → select the `extension/` folder
4. Confirm extension appears in toolbar with a grey badge
5. Open `https://myenergycenter.com/portal` and log into SDGE
6. Wait 2–3 seconds after login completes
7. Check extension badge — should turn green with ✓
8. Click the extension icon — popup should show "Connected ✓" with today's date
9. Open `http://localhost:5000` — should redirect to `/fetch` and then show dashboard

- [ ] **Step 8: Commit**

```bash
git add extension/ make_icons.py
git commit -m "feat: add Chrome extension for SDGE session bridging"
```

---

## Task 8: End-to-End Integration Test and Cleanup

**Files:**
- Modify: `app.py` (add `db.init_db()` call at startup)
- Delete: `make_icons.py`

- [ ] **Step 1: Ensure `db.init_db()` runs on app startup**

At the bottom of `app.py`, confirm the `if __name__ == '__main__':` block calls `init_db()`:

```python
if __name__ == '__main__':
    db.init_db()
    app.run(debug=True)
```

Also add a top-level call so `init_db()` runs when app is loaded by Gunicorn (not just `__main__`):

After `load_dotenv()` and before the Flask route definitions, add:

```python
db.init_db()
```

- [ ] **Step 2: Run all unit tests**

```bash
python -m unittest sdge_usage_test.py test_db.py test_app.py -v
```

Expected: all tests PASS.

- [ ] **Step 3: Full local integration test**

Follow these steps manually:

1. `python app.py` — starts at `http://localhost:5000`
2. Visit `http://localhost:5000` — landing page with "Install Chrome Extension"
3. Extension is loaded unpacked (from Task 7)
4. Visit `https://myenergycenter.com/portal` and log in to SDGE
5. Wait 2–3 seconds — extension badge turns green
6. Visit `http://localhost:5000` — auto-fetches data, then shows dashboard with:
   - Billing period header (meter number, date range)
   - Per-period kWh table (green = surplus, red = deficit)
   - Charging recommendation card
7. Click "Refresh from SDGE" — data refetches
8. Click "Disconnect" — returns to landing page; extension badge turns grey on next status check
9. Open a second Chrome profile → repeat steps 4–6 → confirm it shows its own dashboard (different UUID)

- [ ] **Step 4: Test `fetch_all.py` manually**

```bash
python fetch_all.py
```

Expected output:
```
2026-04-12 06:00:00 INFO Starting fetch for 1 active session(s)
2026-04-12 06:00:45 INFO Fetched data for abcd1234...
```

- [ ] **Step 5: Delete `make_icons.py`**

```bash
rm make_icons.py
```

- [ ] **Step 6: Final commit**

```bash
git add app.py
git rm make_icons.py
git commit -m "feat: EVSmart SaaS MVP complete — extension + multi-user Flask backend"
```

---

## Cron Setup (After Deployment)

Once deployed to DigitalOcean, add to crontab:

```bash
crontab -e
```

Add:
```
0 6 * * * cd /var/www/evsmart && python fetch_all.py >> logs/fetch.log 2>&1
```

---

## Self-Review Notes

- All 6 API functions in `db.py` are tested in `test_db.py`
- All new Flask routes tested in `test_app.py` with temp DB
- `fetch_usage.py` backward-compatible: `save_current_billing_data()` with no args still writes `data/current.json` (existing cron + CLI unaffected)
- Extension `host_permissions` includes both `sdge.com` and `myenergycenter.com` (actual portal domain from `sdge_auth.py`)
- `API_BASE` switches between localhost and production via manifest `version` string containing `'dev'`
- `db.init_db()` called both at `__main__` and module level so Gunicorn picks it up
- Tesla scheduling unchanged — still works for the personal-use case with `.tesla_session.json`
