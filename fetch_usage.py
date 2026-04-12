"""Download the current billing period CSV from SDGE and cache the result.

Playwright headless flow:
  1. Load saved session cookies and navigate to Usage/Index.
  2. Read the last x-axis date label (bill-period end dates) from the Month
     bar chart to derive the start of the current billing period.
  3. Open the Green Button Download dialog, set From/To dates, download CSV.
  4. Parse the CSV with sdge_usage.process() and write data/current.json.

Selector note: the x-axis label selector and date-field locators are based on
the page structure observed in screenshots. If they stop matching after a portal
update, run with --debug to open the Playwright Inspector and verify live.
"""

import datetime
import io
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

from sdge_auth import load_session_cookies
from sdge_usage import iter_rows_csv_stream, process

DATA_DIR = Path(__file__).parent / "data"
CACHE_FILE = DATA_DIR / "current.json"
BASE_URL = "https://myenergycenter.com/portal"


def fetch_current_billing_csv(debug: bool = False) -> bytes:
    """Download the current billing period CSV from SDGE.

    Args:
        debug: Launch a headed browser and pause at key steps so selectors
               can be inspected in the Playwright Inspector.

    Returns:
        Raw CSV bytes.

    Raises:
        FileNotFoundError: No saved SDGE session.
        RuntimeError: Could not find billing-period date labels in the chart.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not debug)
        context = browser.new_context()
        context.add_cookies(load_session_cookies())
        page = context.new_page()

        # ── 1. Load Usage/Index ──────────────────────────────────────────────
        page.goto(f"{BASE_URL}/Usage/Index")
        page.wait_for_load_state("networkidle")

        if debug:
            print("[debug] Loaded Usage/Index. Inspect the page, then resume.")
            page.pause()

        # ── 2. Ensure Month view is active ───────────────────────────────────
        page.click("text=Month")
        page.wait_for_load_state("networkidle")

        # ── 3. Extract the last x-axis date label ────────────────────────────
        # The Month chart shows bill-period END dates on the x-axis
        # (e.g. "Apr 10", "May 12", …, "Mar 12"). The last label is the most
        # recent billing period end date; adding 1 day gives the current
        # billing period start.
        last_label: str | None = page.evaluate(
            """() => {
                const pattern =
                    /^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\\s+\\d{1,2}$/;
                const nodes = Array.from(
                    document.querySelectorAll(
                        'text, [class*="x-axis"], [class*="tick"], [class*="label"]'
                    )
                );
                const labels = nodes
                    .map(n => n.textContent.trim())
                    .filter(t => pattern.test(t));
                return labels.length ? labels[labels.length - 1] : null;
            }"""
        )

        if not last_label:
            raise RuntimeError(
                "Could not find billing-period date labels in the chart. "
                "Run with --debug to inspect the page selectors."
            )

        # Parse "Mar 12" → date.  Year heuristic: if the month is later in the
        # year than today, it must be last year (e.g. reading "Dec 10" in Jan).
        today = date.today()
        parsed = datetime.datetime.strptime(last_label, "%b %d").replace(year=today.year)
        if parsed.month > today.month:
            parsed = parsed.replace(year=today.year - 1)
        billing_start: date = parsed.date() + timedelta(days=1)

        if debug:
            print(f"[debug] Last bill-period end: {parsed.date()}  →  billing start: {billing_start}")
            page.pause()

        # ── 4. Open Green Button Download dialog ─────────────────────────────
        page.click("text=Green Button Download")
        page.wait_for_selector("text=Select Format")

        if debug:
            print("[debug] Green Button Download dialog open.")
            page.pause()

        # ── 5. Set From date via calendar picker ─────────────────────────────
        # The date fields use a calendar popup widget — they are not fillable
        # text inputs. Click the From field to open the calendar, navigate back
        # to the billing start month, then click the correct day cell.

        # Open the From calendar. The date fields use the CSS class "calText"
        # (Material Design textfield with calendar icon). First = From, second = To.
        page.locator(".calText").first.click()

        # Navigate back from the currently shown month to billing_start's month.
        # Calendar header selector covers Bootstrap datepicker (.datepicker-switch)
        # and jQuery UI (.ui-datepicker-title).
        for _ in range(24):  # safety cap: never go back more than 2 years
            header = page.locator(
                ".datepicker-switch, .ui-datepicker-title, [class*='month-year']"
            ).first.inner_text()
            # header is "April 2026" or "April\n2026"
            shown = datetime.datetime.strptime(header.strip().split()[0] + " " + header.strip().split()[-1], "%B %Y").date().replace(day=1)
            target_month = billing_start.replace(day=1)
            if shown <= target_month:
                break
            page.locator(".prev").or_(page.get_by_text("«", exact=True)).first.click()

        # Click the exact day cell (use text-is to avoid partial matches like
        # clicking "13" when "30" is also present on the same calendar)
        page.locator("td").filter(has_text=re.compile(rf"^{billing_start.day}$")).first.click()

        if debug:
            print(f"[debug] From date set to {billing_start}. Check the dialog, then resume.")
            page.pause()

        # ── 7. Confirm .csv radio is selected (it is the default) ────────────
        csv_radio = page.locator("input[type='radio']").first
        if not csv_radio.is_checked():
            csv_radio.click()

        # ── 8. Click Download and capture the file ───────────────────────────
        with page.expect_download() as dl_info:
            page.click("button:has-text('Download')")
        download = dl_info.value
        csv_bytes = Path(download.path()).read_bytes()

        browser.close()
        return csv_bytes


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


if __name__ == "__main__":
    if "--debug" in sys.argv:
        print("Debug mode: launching headed browser with Playwright Inspector pauses.")
        fetch_current_billing_csv(debug=True)
        print("Debug run complete (data not saved).")
    else:
        result = save_current_billing_data()
        print(f"Saved to {CACHE_FILE}")
        print(f"Period: {result.get('reading_start')} to {result.get('reading_end')}")
