# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

SDGE Usage is a local web dashboard for solar + EV owners on SDGE's TOU-DR1 rate plan. It automatically fetches the current billing period's electricity usage from SDGE, identifies which rate period has solar surplus (negative net kWh), and recommends — or directly schedules — when to charge an EV. Negative kWh values represent net solar export (you produced more than you consumed in that period).

## Commands

**Run the web app:**
```bash
python app.py
# Serves at http://localhost:5000
```

**Run tests:**
```bash
python -m unittest sdge_usage_test.py
```

**Run a single test:**
```bash
python -m unittest sdge_usage_test.TestGetTimePeriods.test_off_peak
```

**Fetch current billing data and update cache (also used by cron):**
```bash
python fetch_usage.py
# Debug mode (headed browser + Playwright Inspector pauses):
python fetch_usage.py --debug
```

**One-time Tesla setup:**
```bash
python save_tesla_session.py
```

**CLI usage (manual file analysis):**
```bash
python sdge_usage.py ./path/to/Electric_15_Minute_*.xlsx
```

## Architecture

### Core Logic (`sdge_usage.py`)

`get_time_periods(date, time)` classifies each 15-min interval into a TOU-DR1 period:
- **0–6 AM**: Super Off-Peak (always)
- **6–10 AM**: Super Off-Peak on weekends/holidays; Off-Peak otherwise
- **10 AM–2 PM**: Super Off-Peak on weekends/holidays and in March/April; Off-Peak otherwise
- **2–4 PM**: Off-Peak (always)
- **4–9 PM**: On-Peak (always)
- **9 PM–midnight**: Off-Peak (always)

`process(rows)` aggregates kWh by period and returns `{meter_number, reading_start, reading_end, super_off_peak_kwh, off_peak_kwh, on_peak_kwh, total_kwh, warning}`.

`get_charging_recommendation(result)` takes the output of `process()` and returns the best TOU-DR1 window for EV charging based on which period has solar surplus (negative kWh). Returns `{recommended_period, charge_start, charge_end, surplus_kwh, reason}`.

### SDGE Auth (`sdge_auth.py`)

Single source of truth for SDGE session management. Owns `.sdge_session.json`. No other file reads or writes the session file directly.

- `start_sdge_login()` — opens a headed Playwright browser for the user to log in manually (handles reCAPTCHA); blocks up to 120 s; saves cookies on success
- `load_session_cookies()` — returns saved cookies; raises `FileNotFoundError` if no session
- `session_exists()` / `clear_session()` — session state helpers

Sessions last ~30 days. When expired, re-run the connect flow from the web app (`/connect`).

### SDGE Fetch (`fetch_usage.py`)

`fetch_current_billing_csv(debug=False)` — loads saved session cookies, navigates to `Usage/Index` headlessly, reads the last x-axis date label from the Month bar chart to derive the current billing period start, opens the Green Button Download dialog, sets From/To dates, downloads the CSV, returns raw bytes.

`save_current_billing_data()` — calls `fetch_current_billing_csv()`, runs `process()`, adds `fetched_at` timestamp, writes to `data/current.json`. This is what the `/fetch` route and the cron job call.

Pass `--debug` to launch with a headed browser and Playwright Inspector pauses for selector inspection after a portal update.

### Tesla Integration (`tesla_charge.py`)

Uses `teslapy` (unofficial Tesla Owner API). Command key is `SET_SCHEDULED_CHARGING` — verify with:
```bash
python -c "import teslapy; print([k for k in teslapy.COMMANDS if 'CHARG' in k.upper()])"
```

- `apply_charge_schedule(charge_start_hour, charge_end_hour)` — wakes the vehicle and sets scheduled charging. Returns `{success, vehicle, scheduled_time, error}`. `charge_end_hour` is informational only; the API schedules a start time, not a range.
- `tesla_session_exists()` — checks for `.tesla_session.json`

One-time setup: `python save_tesla_session.py` (teslapy OAuth browser flow; saves email + token to `.tesla_session.json`).

### Web App (`app.py`)

Multi-route Flask app. Smart routing at `GET /` based on session and cache state.

| Route | Method | Purpose |
|---|---|---|
| `GET /` | GET | No cache + no session → `/connect`; no cache + session → `/fetch`; cache exists → `dashboard.html` |
| `GET /connect` | GET | First-run SDGE setup page |
| `POST /connect-sdge` | POST | Triggers `start_sdge_login()` (opens browser); success → `/fetch`; timeout → flash + `/connect` |
| `GET /disconnect-sdge` | GET | Clears session + cache, redirects to `/connect` |
| `GET /fetch` or `POST /fetch` | GET/POST | Calls `save_current_billing_data()`, updates cache, redirects to `/` |
| `POST /schedule-tesla` | POST | Loads cache, calls `apply_charge_schedule()`, flashes result, redirects to `/` |
| `GET /upload` or `POST /upload` | GET/POST | Manual file upload fallback |

Key helpers: `_load_cache()` reads `data/current.json` or returns `None`; `_staleness(result)` returns `(is_stale: bool, hours: int)` — stale when older than 48 h.

Lazy imports inside `/fetch` and `/schedule-tesla` handlers avoid Playwright/teslapy startup cost on every request.

### Templates

- `templates/connect.html` — first-run page; "Connect SDGE Account" button posts to `/connect-sdge`
- `templates/dashboard.html` — main view: billing period header, per-period kWh table (green if negative/surplus, red if positive/deficit), charging recommendation card, action buttons
- `templates/index.html` — manual upload form (used only by `/upload`)
- `templates/result.html` — upload result view

### Data Flow

```
cron (6 AM daily) or POST /fetch
        │
        ▼
fetch_usage.save_current_billing_data()
        │
        ├── fetch_current_billing_csv()  ← Playwright headless + SDGE portal
        ├── process()                    ← sdge_usage.py
        └── writes data/current.json
                │
                ▼
        GET /  reads data/current.json
        get_charging_recommendation()
        renders dashboard.html
                │
                ▼ (user clicks "Schedule Tesla Now")
        POST /schedule-tesla
        tesla_charge.apply_charge_schedule()
```

## Dependencies

No `requirements.txt`. Required packages:
- `openpyxl` — read XLSX exports
- `holidays` — US holiday detection
- `flask` — web interface
- `playwright` — SDGE login (headed, one-time) and data fetch (headless, recurring)
- `teslapy` — Tesla Owner API

## Key Files (gitignored, never commit)

- `.sdge_session.json` — SDGE browser session cookies (~30 day lifetime)
- `.tesla_session.json` — Tesla OAuth token + email
- `data/current.json` — cached billing period result with `fetched_at` timestamp
- `logs/fetch.log` — cron job output

## Key Details

- SDGE login is reCAPTCHA-protected. Playwright is used in headed mode so the user logs in manually; subsequent fetches reuse the saved session headlessly.
- Total validation uses `math.isclose(..., rel_tol=1e-6)` to confirm categorized kWh sums match the reported total.
- The dashboard shows a staleness warning if `data/current.json` is older than 48 hours.
- `fetch_usage.py --debug` launches a headed browser with `page.pause()` at key steps — use this when SDGE updates their portal and selectors break.
- Recommended cron for automatic daily refresh: `0 6 * * * cd /path/to/sdge_usage && python fetch_usage.py >> logs/fetch.log 2>&1`
