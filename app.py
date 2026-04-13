import datetime
import json
import os
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from flask import Flask, flash, g, redirect, render_template, request, url_for

load_dotenv()

import db
from sdge_usage import get_charging_recommendation, iter_rows_csv_stream, iter_rows_xlsx_stream, process

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'sdge-usage-secret-dev-only')

ALLOWED_EXTENSIONS = {"csv", "xlsx"}

db.init_db()


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
            secure=not app.debug,
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
        flash("Fetching your SDGE data for the first time\u2026", "info")
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
        return redirect(url_for('index'))
    except Exception as e:
        # Render landing directly — redirecting to / would loop because
        # / redirects back here when there's no cached data yet.
        flash(f"Fetch failed: {e}", "danger")
        return render_template('landing.html')


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
    app.run(debug=True)
