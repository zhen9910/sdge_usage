"""Single source of truth for the SDGE session cookie file.

No other module reads or writes .sdge_session.json directly.

Threading note: start_sdge_login() blocks the calling thread for up to 120 s
while the user logs in interactively. This is acceptable for a single-user
local tool running with debug=True (Flask's single-threaded dev server).
"""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError  # noqa: F401

SESSION_FILE = Path(__file__).parent / ".sdge_session.json"
BASE_URL = "https://myenergycenter.com/portal"
_LOGIN_TIMEOUT_MS = 120_000  # 2 minutes


def start_sdge_login() -> None:
    """Open a headed browser so the user can log in to SDGE.

    Blocks until the browser lands on Usage/Index (successful login) or
    120 seconds elapse.

    Raises:
        PlaywrightTimeoutError: login not completed within 120 s.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(BASE_URL)
        page.wait_for_url(f"{BASE_URL}/Usage/Index", timeout=_LOGIN_TIMEOUT_MS)
        SESSION_FILE.write_text(json.dumps(context.cookies()))
        browser.close()


def load_session_cookies() -> list:
    """Return saved cookies from the session file.

    Raises:
        FileNotFoundError: no session file — user must log in first.
    """
    if not SESSION_FILE.exists():
        raise FileNotFoundError(
            "No SDGE session found. Please connect your account first."
        )
    return json.loads(SESSION_FILE.read_text())


def session_exists() -> bool:
    return SESSION_FILE.exists()


def clear_session() -> None:
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
