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


def _get_db() -> sqlite3.Connection:
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with _get_db() as conn:
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
    with _get_db() as conn:
        conn.execute(
            """INSERT INTO sessions (uuid, sdge_cookies_encrypted, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(uuid) DO UPDATE SET
                 sdge_cookies_encrypted = excluded.sdge_cookies_encrypted,
                 updated_at = excluded.updated_at""",
            (uuid, encrypted),
        )


def load_session_cookies(uuid: str) -> list | None:
    """Return decrypted SDGE cookies for uuid, or None if missing/expired."""
    with _get_db() as conn:
        row = conn.execute(
            'SELECT sdge_cookies_encrypted FROM sessions WHERE uuid = ?', (uuid,)
        ).fetchone()
    if row is None or row['sdge_cookies_encrypted'] is None:
        return None
    return json.loads(_get_fernet().decrypt(row['sdge_cookies_encrypted']))


def load_data(uuid: str) -> dict | None:
    """Return cached billing data dict for uuid, or None if not yet fetched."""
    with _get_db() as conn:
        row = conn.execute(
            'SELECT data_json FROM sessions WHERE uuid = ?', (uuid,)
        ).fetchone()
    if row is None or row['data_json'] is None:
        return None
    return json.loads(row['data_json'])


def save_data(uuid: str, data: dict) -> None:
    """Update billing data and last_fetched_at for uuid."""
    with _get_db() as conn:
        conn.execute(
            """UPDATE sessions
               SET data_json = ?, last_fetched_at = datetime('now'), updated_at = datetime('now')
               WHERE uuid = ?""",
            (json.dumps(data), uuid),
        )
        changed = conn.execute('SELECT changes()').fetchone()[0]
    if changed == 0:
        import logging
        logging.getLogger(__name__).warning('save_data: no row found for uuid %s', uuid[:8])


def clear_session(uuid: str) -> None:
    """Delete all data for uuid (user disconnect)."""
    with _get_db() as conn:
        conn.execute('DELETE FROM sessions WHERE uuid = ?', (uuid,))


def mark_session_expired(uuid: str) -> None:
    """Null out cookies so the extension shows a red badge; preserve data_json."""
    with _get_db() as conn:
        conn.execute(
            "UPDATE sessions SET sdge_cookies_encrypted = NULL, updated_at = datetime('now') WHERE uuid = ?",
            (uuid,),
        )


def list_active_uuids() -> list[str]:
    """Return UUIDs with non-null cookies (eligible for cron fetch)."""
    with _get_db() as conn:
        rows = conn.execute(
            'SELECT uuid FROM sessions WHERE sdge_cookies_encrypted IS NOT NULL'
        ).fetchall()
    return [row['uuid'] for row in rows]
