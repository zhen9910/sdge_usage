# SDGE Usage — EV Charging Dashboard

A local web dashboard for solar + EV owners on SDGE's **TOU-DR1** rate plan.
Automatically fetches the current billing period's electricity usage, identifies
which rate period has solar surplus, and recommends — or directly schedules —
when to charge your EV.

> **Negative kWh = net solar export** (you produced more than you consumed).

---

## Features

- **One-click SDGE connect** — opens a browser for manual login (handles reCAPTCHA); session is saved locally, no password stored
- **Automatic data fetch** — downloads the current billing period CSV from SDGE headlessly using the saved session; runs daily via cron
- **Charging recommendation** — identifies which TOU-DR1 period (Super Off-Peak or Off-Peak) has solar surplus and recommends the optimal EV charging window
- **Tesla one-click scheduling** — pushes the recommended charge window directly to your Tesla via the Owner API
- **Staleness warning** — alerts when cached data is older than 48 hours

---

## Requirements

- Python 3.10+
- SDGE account (TOU-DR1 rate plan)
- Tesla account (optional, for one-click scheduling)

Install dependencies:
```bash
pip install flask openpyxl holidays playwright teslapy
playwright install chromium
```

---

## Quick Start

```bash
# 1. Start the app
python app.py

# 2. Open http://localhost:5000
#    → Click "Connect SDGE Account" and log in
#    → Dashboard loads automatically with your current billing period data
```

**Optional — Tesla scheduling:**
```bash
python save_tesla_session.py   # one-time OAuth setup
# Then click "Schedule Tesla Now" from the dashboard
```

**Daily auto-refresh (cron):**
```
0 6 * * * cd /path/to/sdge_usage && python fetch_usage.py >> logs/fetch.log 2>&1
```

---

## CLI Usage (manual file analysis)

```bash
python sdge_usage.py ./Electric_15_Minute_*.csv
```

---

## Release Notes

### v0.5.0 (2026-04-12)
- **EV Charging Dashboard** — full web UI replacing the single upload-and-display flow
- **In-app SDGE connect** — one-click browser login flow; no terminal commands needed
- **Automated SDGE fetch** — Playwright headless scraper downloads current billing period CSV via Green Button Download
- **Charging recommendation** — surplus-aware logic recommends Super Off-Peak (midnight–6 AM) or Off-Peak (9 PM–midnight) based on real billing data
- **Tesla integration** — `save_tesla_session.py` + `tesla_charge.py`; one-click charge scheduling from dashboard
- **Staleness warning** — yellow banner when `data/current.json` is older than 48 hours
- **Loading states** — spinner feedback during SDGE login (~60s) and data fetch (~30s)

### v0.1.0 (2023-04-07)
- Initial CLI tool — parse SDGE 15-minute interval XLSX/CSV exports
- Categorise usage into TOU-DR1 periods: Super Off-Peak, Off-Peak, On-Peak
- Print net kWh per period to stdout
