import datetime
import json
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for

from sdge_auth import clear_session, session_exists, start_sdge_login
from sdge_usage import (
    get_charging_recommendation,
    iter_rows_csv_stream,
    iter_rows_xlsx_stream,
    process,
)

app = Flask(__name__)
app.secret_key = "sdge-usage-secret"

ALLOWED_EXTENSIONS = {"csv", "xlsx"}
CACHE_FILE = Path(__file__).parent / "data" / "current.json"


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _load_cache() -> dict | None:
    """Read data/current.json; return None if missing or corrupt."""
    try:
        return json.loads(CACHE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


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
    """Return True if a Tesla session file is present, without hard-importing tesla_charge."""
    try:
        from tesla_charge import tesla_session_exists  # noqa: PLC0415
        return tesla_session_exists()
    except ImportError:
        return False


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    result = _load_cache()
    if result:
        recommendation = get_charging_recommendation(result)
        is_stale, hours_since_fetch = _staleness(result)
        return render_template(
            "dashboard.html",
            result=result,
            recommendation=recommendation,
            is_stale=is_stale,
            hours_since_fetch=hours_since_fetch,
            tesla_session_exists=_tesla_session_exists(),
        )
    if session_exists():
        flash("Fetching data from SDGE\u2026", "info")
        return redirect(url_for("fetching"))
    return redirect(url_for("connect"))


@app.route("/connect")
def connect():
    return render_template("connect.html")


@app.route("/connecting")
def connecting():
    return render_template("connecting.html")


@app.route("/fetching")
def fetching():
    return render_template("fetching.html")


@app.route("/connect-sdge", methods=["POST"])
def connect_sdge():
    try:
        start_sdge_login()
    except Exception as e:
        flash(f"Login failed or timed out: {e}", "danger")
        return redirect(url_for("connect"))
    return redirect(url_for("fetching"))


@app.route("/disconnect-sdge")
def disconnect_sdge():
    clear_session()
    CACHE_FILE.unlink(missing_ok=True)
    return redirect(url_for("connect"))


@app.route("/fetch", methods=["GET", "POST"])
def fetch():
    from fetch_usage import save_current_billing_data  # noqa: PLC0415
    try:
        save_current_billing_data()
        flash("Usage data refreshed successfully.", "success")
    except FileNotFoundError:
        flash("No SDGE session found. Please reconnect your account.", "danger")
        return redirect(url_for("connect"))
    except Exception as e:
        flash(f"Fetch failed: {e}", "danger")
        return redirect(url_for("connect"))
    return redirect(url_for("index"))


@app.route("/schedule-tesla", methods=["POST"])
def schedule_tesla():
    result = _load_cache()
    if not result:
        flash("No usage data available. Please fetch data first.", "warning")
        return redirect(url_for("index"))
    from tesla_charge import apply_charge_schedule  # noqa: PLC0415
    rec = get_charging_recommendation(result)
    outcome = apply_charge_schedule(rec["charge_start"], rec["charge_end"])
    if outcome["success"]:
        flash(
            f"Tesla scheduled to charge "
            f"{rec['charge_start']:02d}:00\u2013{rec['charge_end']:02d}:00 "
            f"({outcome['vehicle']}).",
            "success",
        )
    else:
        flash(f"Tesla scheduling failed: {outcome['error']}", "danger")
    return redirect(url_for("index"))


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or file.filename == "":
            flash("Please select a file.", "danger")
            return redirect(url_for("upload"))

        if not _allowed_file(file.filename):
            flash("Only .csv and .xlsx files are supported.", "danger")
            return redirect(url_for("upload"))

        ext = file.filename.rsplit(".", 1)[1].lower()
        try:
            if ext == "csv":
                rows = iter_rows_csv_stream(file.stream)
            else:
                rows = iter_rows_xlsx_stream(file.stream)
            result = process(rows)
            result["filename"] = file.filename
            return render_template("result.html", result=result)
        except Exception as e:
            flash(f"Error processing file: {e}", "danger")
            return redirect(url_for("upload"))

    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)
