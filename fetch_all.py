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
