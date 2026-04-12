# EV Charging Dashboard — Implementation Plan

## Context

The repo is a Flask app on the `feature-ev-dashboard` branch with a single upload-and-display flow (`app.py` → `process()` → `result.html`). The goal is to add:

1. **Automated SDGE data fetch** via Playwright (session persistence strategy from the design spec)
2. **In-app SDGE connect** — a `/connect-sdge` route that opens a headed browser so the user never needs a terminal
3. **Charging recommendation** — which rate period has solar surplus this billing cycle
4. **Tesla one-click scheduling** — push the recommended window to the car from the dashboard

**Important correction to the draft plan:** There is no `feature-auto-fetch` branch and no pre-existing `fetch_usage.py`, `save_session.py`, or `debug_login.py`. Every file listed as "New" in the critical files table must be created from scratch. Nothing is being merged and nothing is being deleted.

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Browser: GET /                                               │
│                                                             │
│  no session → /connect → [Connect SDGE] button              │
│  session, no cache → POST /fetch (auto-redirect)            │
│  cache present → render dashboard.html                      │
└───────────────────────┬─────────────────────────────────────┘
                        │
        POST /connect-sdge          POST /fetch
                │                        │
        sdge_auth.py                fetch_usage.py
        start_sdge_login()          save_current_billing_data()
        (headed browser,                 │
         blocks request thread)    sdge_auth.load_session_cookies()
                │                        │ Playwright headless
                └──→ .sdge_session.json  │ download CSV
                                         │
                                  sdge_usage.iter_rows_csv_stream()
                                  sdge_usage.process()
                                         │
                                  data/current.json
                                  (adds fetched_at)
                                         │
        POST /schedule-tesla ──→ tesla_charge.apply_charge_schedule()
                                  teslapy → car scheduled
```

---

## Critical Files

| File | Action |
|---|---|
| `app.py` | Full rewrite |
| `sdge_usage.py` | Append `get_charging_recommendation()` |
| `sdge_usage_test.py` | Append `TestChargingRecommendation` class |
| `templates/index.html` | Update form `action="/upload"` |
| `.gitignore` | Append `.sdge_session.json`, `.tesla_session.json`, `logs/` |
| `sdge_auth.py` | **New** |
| `fetch_usage.py` | **New** |
| `tesla_charge.py` | **New** |
| `save_tesla_session.py` | **New** |
| `templates/connect.html` | **New** |
| `templates/dashboard.html` | **New** |

---

## Build Order

The plan is split into two sequential phases. Each phase ships something usable on its own.

**Phase 1 — In-App SDGE Connect** (Steps 1–3)
Get the session connect/disconnect flow working end-to-end in the browser, with a basic dashboard that displays cached data if it exists. After this phase, the user can click "Connect SDGE Account", complete browser login, and reach a functional dashboard — no terminal required for SDGE auth.

**Phase 2 — Automated Data Fetch** (Steps 3–5)
Add `fetch_usage.py` (Playwright headless download + caching), the charging recommendation, and the full dashboard template. After this phase, the dashboard is fully functional: cron can keep data fresh, `/fetch` works from the browser, and the recommendation is visible.

**Phase 3 — Tesla Scheduling** (Steps 6–7)
Add Tesla session setup and one-click charge scheduling from the dashboard. Kept last because it requires external hardware (a Tesla vehicle) and a separate one-time terminal setup step (`save_tesla_session.py`).

---

## Step 1 — `sdge_auth.py` (New)

Single source of truth for `.sdge_session.json`. No other file touches the session file directly.

```python
SESSION_FILE = Path(__file__).parent / ".sdge_session.json"
BASE_URL = "https://myenergycenter.com/portal"

def start_sdge_login() -> None:
    """Open headed browser; block until redirected to Usage/Index or 120s timeout."""
    # sync_playwright → chromium.launch(headless=False) → wait_for_url
    # saves context.cookies() to SESSION_FILE on success
    # raises TimeoutError if not completed within 120s

def load_session_cookies() -> list:
    """Return cookies or raise FileNotFoundError."""

def session_exists() -> bool: ...
def clear_session() -> None: ...
```

**Threading note:** `start_sdge_login()` is called from a Flask route and will block that worker thread for up to 120 seconds while the user logs in. This is acceptable for a single-user local tool running with `debug=True` (single-threaded dev server). Document this constraint.

---

## Step 2 — Phase 1 App + Templates (connect flow)

### `templates/connect.html` (New)
Bootstrap 5 card (matches existing style from `index.html`/`result.html`):
- Heading: "Connect your SDGE account"
- Explanation: session saved locally, password never stored
- "Connect SDGE Account" button → `POST /connect-sdge`
- Secondary link: "Upload a file manually →" → `/upload`
- Flash messages block (same pattern as `index.html` lines 18–25)

### Phase 1 `app.py` changes
Add these routes to the existing `app.py` (don't rewrite yet — keep the current upload logic intact):

| Route | Method | Logic |
|---|---|---|
| `/` | GET | Cache exists → render `dashboard.html` (stub: pass result + `is_stale`); no cache + session → flash "Fetching data…", redirect `/fetch`; no session → redirect `/connect` |
| `/connect` | GET | Render `connect.html` |
| `/connect-sdge` | POST | `start_sdge_login()` → success: redirect `/fetch`; `TimeoutError`: flash error, redirect `/connect` |
| `/disconnect-sdge` | GET | `clear_session()`, delete `data/current.json`, redirect `/connect` |
| `/upload` | GET/POST | Move existing `/` upload logic here; update `index.html` form `action="/upload"` |

At this point `/fetch` can be a stub that just redirects to `/` with a flash "No fetch yet — run manually". The dashboard stub can show raw JSON data in a `<pre>` block until Step 5 builds the real template.

**Verify Phase 1:**
```bash
python -m unittest sdge_usage_test.py -v   # must still pass
python app.py &
# GET / → redirect to /connect (no session)
# POST /connect-sdge → headed browser opens → login → redirects
# GET /upload → shows file upload form
# GET /disconnect-sdge → clears session, back to /connect
```

---

## Step 3 — `fetch_usage.py` (New)

Playwright headless download of the current billing period CSV, plus caching.

### Portal layout (confirmed from screenshots)

- **URL:** `https://myenergycenter.com/portal/Usage/Index`
- **Month view** (default): bar chart titled "By Bill Period End Date". X-axis labels are the end date of each past billing period (e.g. "Mar 12", "Feb 10"). The last label = most-recent billing period's end date → start of *current* period = end date + 1 day.
- **Green Button Download** dialog (modal overlay): shows Address/Account/Meter info, a **From** date field, a **To** date field (both showing "Month DD, YYYY" format), format radio buttons (.csv selected by default), and a **Download** button.

### Playwright flow inside `fetch_current_billing_csv()`

```python
# 1. Launch headless Chromium, load saved session cookies
async with async_playwright() as p:
    browser = await p.chromium.launch(headless=True)
    context = await browser.new_context()
    await context.add_cookies(load_session_cookies())
    page = await context.new_page()

    # 2. Navigate to Usage/Index; wait for chart to render
    await page.goto("https://myenergycenter.com/portal/Usage/Index")
    await page.wait_for_load_state("networkidle")

    # 3. Ensure Month view is active (it is the default, but click to be safe)
    await page.click("text=Month")          # the Month tab/button
    await page.wait_for_load_state("networkidle")

    # 4. Extract the last x-axis date label to derive billing period start
    last_label = await page.evaluate("""() => {
        // X-axis labels are SVG <text> or similar; filter by "Mon DD" pattern
        const pattern = /^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\\s+\\d{1,2}$/;
        const nodes = Array.from(document.querySelectorAll('text, [class*="x-axis"], [class*="tick"]'));
        const labels = nodes.map(n => n.textContent.trim()).filter(t => pattern.test(t));
        return labels[labels.length - 1];  // e.g. "Mar 12"
    }""")
    # Year heuristic: if the parsed month is after the current month, it must be last year
    parsed = datetime.strptime(last_label, "%b %d").replace(year=date.today().year)
    if parsed.month > date.today().month:
        parsed = parsed.replace(year=date.today().year - 1)
    billing_start = parsed + timedelta(days=1)   # e.g. Mar 13
    today = date.today()

    # 5. Open Green Button Download dialog
    await page.click("text=Green Button Download")
    await page.wait_for_selector("text=Select Format")  # wait for modal body

    # 6. Set From date (clear field, type date in "Month DD, YYYY" format)
    from_field = page.locator("input").filter(has_text="").nth(0)
    await from_field.triple_click()
    await from_field.fill(billing_start.strftime("%B %d, %Y"))

    # 7. Set To date
    to_field = page.locator("input").filter(has_text="").nth(1)
    await to_field.triple_click()
    await to_field.fill(today.strftime("%B %d, %Y"))

    # 8. Confirm .csv radio is selected (it is the default)
    csv_radio = page.locator("input[type='radio']").first
    if not await csv_radio.is_checked():
        await csv_radio.click()

    # 9. Click Download; capture the file download event
    async with page.expect_download() as dl_info:
        await page.click("button:has-text('Download')")
    download = await dl_info.value
    csv_bytes = Path(await download.path()).read_bytes()

    await browser.close()
    return csv_bytes
```

**Selector resilience note:** The x-axis label selector and date-field locator may need adjustment once run against the live page. Write a `--debug` CLI flag that launches with `headless=False` and pauses with `page.pause()` before each step, so the user can inspect selectors in the Playwright Inspector without modifying production code.

### `save_current_billing_data()`

```python
def save_current_billing_data() -> dict:
    """Download + process + cache. Returns result dict."""
    csv_bytes = asyncio.run(fetch_current_billing_csv())
    rows = iter_rows_csv_stream(io.BytesIO(csv_bytes))   # import from sdge_usage
    result = process(rows)                                # import from sdge_usage
    result["fetched_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    DATA_DIR.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(result, default=str))
    return result
```

**`--save` / `--debug` CLI flags:**
```python
if __name__ == "__main__":
    import sys
    if "--debug" in sys.argv:
        # re-run with headless=False + page.pause() for selector inspection
        ...
    save_current_billing_data()
    print("Saved to", CACHE_FILE)
```

Cron (document in README, not automated):
```
0 6 * * * cd /path/to/repo && python fetch_usage.py --save >> logs/fetch.log 2>&1
```

---

## Step 4 — `get_charging_recommendation()` in `sdge_usage.py`

Append after `process()`, before `if __name__ == '__main__':`. No existing functions modified.

```python
def get_charging_recommendation(result: dict) -> dict:
    sop = result.get("super_off_peak_kwh", 0.0)
    op  = result.get("off_peak_kwh", 0.0)

    if sop < 0:
        return {"recommended_period": "Super Off-Peak", "charge_start": 0, "charge_end": 6,
                "surplus_kwh": round(abs(sop), 4),
                "reason": f"Super Off-Peak has {abs(sop):.1f} kWh solar surplus. "
                          "Charging midnight–6 AM maximises self-consumption."}
    elif op < 0:
        return {"recommended_period": "Off-Peak", "charge_start": 21, "charge_end": 24,
                "surplus_kwh": round(abs(op), 4),
                "reason": f"Off-Peak has {abs(op):.1f} kWh solar surplus. "
                          "Charging 9 PM–midnight uses that surplus cheaply."}
    else:
        return {"recommended_period": "Super Off-Peak", "charge_start": 0, "charge_end": 6,
                "surplus_kwh": 0.0,
                "reason": "No solar surplus yet this period. "
                          "Super Off-Peak (midnight–6 AM) is still the cheapest window."}
```

**Tests** — add `TestChargingRecommendation` to `sdge_usage_test.py`:
1. `super_off_peak_kwh=-142.3` → `recommended_period="Super Off-Peak"`, `charge_start=0`
2. `super_off_peak_kwh=10.0, off_peak_kwh=-38.1` → `recommended_period="Off-Peak"`, `charge_start=21`
3. All positive → `recommended_period="Super Off-Peak"`, `surplus_kwh=0.0`

---

## Step 5 — Full Dashboard Template + Full `app.py` Rewrite

### `templates/dashboard.html` (New)
Context vars: `result`, `recommendation`, `is_stale`, `hours_since_fetch`, `tesla_session_exists`.

Layout (Bootstrap 5 cards):
1. Staleness `alert-warning` if `is_stale`
2. Header card: billing period, last updated
3. Usage breakdown: three rows with badge colors from `result.html` (`bg-info`/`bg-secondary`/`bg-danger`); green if `< 0`, red if `> 0`
4. Recommendation `alert-success`: period, surplus kWh, reason
5. Action buttons: "Schedule Tesla Now" (`POST /schedule-tesla`, only if `tesla_session_exists`), "Refresh from SDGE" (`POST /fetch`), "Disconnect SDGE" (`GET /disconnect-sdge`)
6. "Upload file manually" small link at bottom

### Full `app.py` Rewrite

Add `/fetch` route and helpers; replace Phase 1 stub:

| Route | Method | Logic |
|---|---|---|
| `/fetch` | POST | `save_current_billing_data()`, flash result, redirect `/` |
| `/schedule-tesla` | POST | Load cache → `apply_charge_schedule(rec["charge_start"], rec["charge_end"])`, flash result, redirect `/` |

```python
def _load_cache() -> dict | None:
    """Read data/current.json; return None if missing or corrupt (json.JSONDecodeError)."""

def _staleness(result: dict) -> tuple[bool, int]:
    """Parse result['fetched_at'], return (is_stale, hours). is_stale when > 48h."""
```

Lazy imports inside route handlers:
```python
# inside /fetch handler:
from fetch_usage import save_current_billing_data
# inside /schedule-tesla handler:
from tesla_charge import apply_charge_schedule, tesla_session_exists
```

---

## Step 6 — Tesla Integration

### `save_tesla_session.py` (New)
One-time terminal setup script. Uses `teslapy.Tesla(email, cache_file=str(TESLA_SESSION_FILE))` — teslapy opens a browser OAuth flow automatically. Prints vehicle list on success. Writes email into cache for later retrieval.

### `tesla_charge.py` (New)

```python
TESLA_SESSION_FILE = Path(__file__).parent / ".tesla_session.json"

def tesla_session_exists() -> bool: ...

def apply_charge_schedule(charge_start_hour: int, charge_end_hour: int) -> dict:
    """Returns {"success": bool, "vehicle": str|None, "scheduled_time": str|None, "error": str|None}"""
    # _get_tesla() → vehicle_list()[0] → sync_wake_up()
    # vehicle.command("CHARGING_SCHEDULE", enable=True, time=charge_start_hour * 60)
    # Catches FileNotFoundError, PermissionError, and generic Exception
```

**Before implementing**, verify the exact teslapy command name:
```bash
python -c "import teslapy; print([k for k in teslapy.COMMANDS if 'CHARG' in k])"
```
The command key used in `vehicle.command(...)` must match exactly.

`sync_wake_up()` blocks ~30 seconds. Acceptable for a local tool.

---

## Step 7 — `.gitignore`

Append three lines:
```
.sdge_session.json
.tesla_session.json
logs/
```

(`data/` is already gitignored.)

---

## Verification

```bash
# 1. Unit tests (run before and after to confirm no regression)
cd repo && python -m unittest sdge_usage_test.py -v

# 2. First-run connect flow
rm -f .sdge_session.json data/current.json
python app.py &
# GET / → must redirect to /connect → shows connect.html
# POST /connect-sdge → headed browser opens → log in → closes → redirects to /fetch → /
# dashboard.html should show usage data with recommendation

# 3. Disconnect
# GET /disconnect-sdge → .sdge_session.json deleted → redirects to /connect

# 4. Cache integrity
python -c "import json; d=json.load(open('data/current.json')); assert 'fetched_at' in d; print('OK')"

# 5. Staleness warning
python -c "
import json, datetime, pathlib
p = pathlib.Path('data/current.json')
d = json.loads(p.read_text())
d['fetched_at'] = (datetime.datetime.now() - datetime.timedelta(days=3)).isoformat()
p.write_text(json.dumps(d))
"
# GET / → yellow staleness warning visible

# 6. Tesla session setup (requires teslapy installed + Tesla account)
python save_tesla_session.py
python -c "from tesla_charge import apply_charge_schedule; print(apply_charge_schedule(0, 6))"
# → {"success": true, "vehicle": "...", "scheduled_time": "00:00", "error": null}

# 7. Upload fallback
# GET /upload → shows file upload form; submit a .csv → shows result.html
```
