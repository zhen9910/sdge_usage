# EV Charging Dashboard — Design Spec

**Date:** 2026-04-09  
**Status:** Draft  
**Goal:** Know when to charge the EV by seeing real-time solar surplus per rate period for the current billing cycle.

---

## Problem

You have solar + EV on SDGE TOU-DR1. NEM-3 reduced export credit value significantly, so self-consumption matters: charging your EV when you have a solar surplus in that rate period is effectively free energy, whereas exporting it earns very little.

Currently you have to manually download a usage file from SDGE and upload it to the app every time you want to check. That friction means you check rarely, and the EV charges on a fixed schedule rather than responding to actual surplus.

---

## Goal

One dashboard, updated automatically every day, that answers: **"which rate period has surplus solar energy this billing cycle, and should I charge my EV tonight?"**

---

## User Story

> As a solar + EV owner on TOU-DR1, I open a local dashboard and immediately see whether I have surplus solar in Off-Peak or Super Off-Peak this billing cycle, so I know whether to schedule my EV charger for tonight.

---

## Design

### Dashboard (single screen)

```
Current billing period: Mar 14 – Apr 9   (last updated: Apr 9, 8:02 AM)

  Super Off-Peak   -142.3 kWh  ▼ surplus
  Off-Peak          -38.1 kWh  ▼ surplus
  On-Peak           +61.4 kWh  ▲ deficit

  → Charge your EV during Super Off-Peak or Off-Peak.
    You have 180.4 kWh of unabsorbed solar surplus.

  [Refresh now]
```

Rules for the recommendation:
- If a period has **negative net kWh** (surplus): safe to charge during that period
- If all periods are positive (deficit): recommend off-peak as cheapest option
- Show total surplus as a single number: sum of negative-period kWh (absolute value)

No charts, no history, no plan comparison. That can come later.

---

## Data Flow

```
[Cron / scheduler] daily at 6 AM
        │
        ▼
[fetch_usage.py] — Playwright → SDGE portal → download CSV for current billing period
        │
        ├─ success → save to data/current.csv → trigger process()
        │
        └─ failure (reCAPTCHA / session expired) → log error, notify via terminal/email
                                                    keep showing last successful data
        ▼
[sdge_usage.process()] — existing logic, unchanged
        │
        ▼
[data/current.json] — cached result: {super_off_peak_kwh, off_peak_kwh, on_peak_kwh, fetched_at, period_start, period_end}
        │
        ▼
[Flask app /] — reads current.json, renders dashboard
```

The Flask app becomes **read-only**: it just displays `current.json`. All data fetching happens in the background job.

---

## Automated Fetch Strategy

### The reCAPTCHA problem

`debug_login.py` shows SDGE uses reCAPTCHA v3 on login. Fully automated headless login is blocked. Three options:

**Option A: Session persistence (recommended for MVP)**  
Log in once manually in a headed browser. Export the browser cookies (Playwright's `storage_state`). The scheduler reuses the saved session for all subsequent requests — no login, no reCAPTCHA. When the session expires (typically 30 days), you log in manually again and re-export.

This is 80% automated with ~5 minutes of manual work per month.

**Option B: Green Button Connect OAuth (long-term)**  
SDGE supports the Green Button standard. Register as a third-party data recipient (SDGE/CPUC application process, timeline unknown). Users authorize via OAuth. No scraping, utility-sanctioned. Implement later if Option A becomes unreliable.

**Option C: Captcha solving service**  
Violates SDGE ToS. Not recommended.

### Option A implementation detail

```bash
# One-time manual step: login with headed browser, save session
python save_session.py   # opens browser, you log in, cookies saved to session.json

# Scheduler runs daily
python fetch_usage.py    # reuses session.json, downloads current period CSV
```

`fetch_usage.py` navigates directly to the usage download URL (bypassing login) using the saved session. If the session is expired, it logs an error and exits without overwriting `current.json` — the dashboard continues showing the last good data with a staleness warning.

---

## Components

### New: `save_session.py`
Manual one-time script. Launches a **headed** Chromium browser, navigates to SDGE login, waits for the user to complete login (including reCAPTCHA if prompted), then saves `storage_state` to `session.json`. Run this once and whenever the session expires.

### New: `fetch_usage.py`
Scheduled script. Loads `session.json`, navigates to the SDGE usage export page, downloads the CSV for the current billing period, runs `process()`, writes result to `data/current.json`. Handles errors by logging and exiting without overwriting the cache.

### Modified: `app.py`
Add a `/` GET route that reads `data/current.json` and renders the dashboard. Keep the existing upload route for manual use. Add a `/refresh` POST route that triggers `fetch_usage.py` as a subprocess (for the "Refresh now" button).

### New: `templates/dashboard.html`
Simple Bootstrap card showing the three periods with surplus/deficit indicators and the recommendation. Shows `fetched_at` timestamp and a warning if data is older than 2 days.

### Scheduler
Use `cron` (macOS/Linux) for simplicity — no new Python dependencies:

```cron
0 6 * * * cd /path/to/sdge_usage && python fetch_usage.py >> logs/fetch.log 2>&1
```

Alternative: `APScheduler` embedded in `app.py` if you want scheduling without touching cron.

---

## File Structure Changes

```
sdge_usage/
├── app.py                  (modified — add dashboard route)
├── sdge_usage.py           (unchanged)
├── fetch_usage.py          (new — automated download)
├── save_session.py         (new — one-time manual login)
├── session.json            (gitignored — saved browser session)
├── data/
│   └── current.json        (gitignored — cached result)
├── logs/
│   └── fetch.log           (gitignored)
└── templates/
    ├── index.html          (unchanged)
    ├── result.html         (unchanged)
    └── dashboard.html      (new)
```

---

## Error States

| Situation | Dashboard behavior |
|---|---|
| `current.json` doesn't exist yet | Show "No data yet — run fetch_usage.py to get started" |
| `fetched_at` > 2 days ago | Show data with yellow warning: "Last updated 3 days ago — session may have expired" |
| `fetch_usage.py` exits with error | Keep previous `current.json`, log error to `logs/fetch.log` |
| Session expired | Error logged, dashboard shows staleness warning, user runs `save_session.py` |

---

## Out of Scope (for now)

- Multi-user / accounts
- Historical trends / charts
- Plan comparison
- EV charger API integration (auto-scheduling)
- Push notifications / email alerts
- Green Button OAuth

---

## Open Questions

- [ ] Does SDGE's usage export page allow downloading the current (in-progress) billing period, or only completed periods? Need to verify the download flow in `fetch_usage.py`.
- [ ] What is the exact URL and form parameters for the SDGE CSV export? `debug_login.py` currently only tests login, not the download step.
- [ ] Should the dashboard show daily trend within the current period (e.g., "last 7 days vs. first 7 days") or just the cumulative total?
- [ ] Session expiry: does SDGE use 30-day sessions or shorter?
