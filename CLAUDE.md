# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run tests
python -m pytest sdge_usage_test.py -v

# Run a single test
python -m pytest sdge_usage_test.py::UnitTest::test_1 -v

# Run the CLI directly
python sdge_usage.py ./data/Electric_15_Minute_<date-range>.xlsx

# Run the Flask web app (dev server at http://127.0.0.1:5000)
python app.py

# Install dependencies
pip install openpyxl holidays flask
```

## Architecture

The project has two entry points that share a single core library:

**`sdge_usage.py`** — Core library + CLI. All business logic lives here:
- `get_time_periods(date, time)` — Maps a datetime to `"Super Off Peak"`, `"Off Peak"`, or `"On Peak"` using the SDGE EV-TOU-5 rate schedule (Python 3.10 `match/case`, requires `datetime` objects not strings)
- `process(rows)` — Two-pass row processor: pass 1 extracts metadata (`Meter Number`, `Reading Start`, `Reading End`, `Total Usage`), pass 2 accumulates kWh per TOU period by matching rows where `row[0]` equals the meter number. Returns a result dict; raises `ValueError` if meter number is missing.
- `iter_rows_csv` / `iter_rows_xlsx` — File-path variants for CLI use
- `iter_rows_csv_stream` / `iter_rows_xlsx_stream` — Stream variants for Flask upload use

**`app.py`** — Thin Flask wrapper. Accepts file upload (`.csv` or `.xlsx`), calls the appropriate `iter_rows_*_stream` function, passes to `process()`, renders `templates/result.html`.

## Input File Format

SDGE 15-minute interval usage export. Each data row has at least 7 columns:
- `row[0]` — meter number (or metadata key like `"Meter Number"`, `"Reading Start"`)
- `row[1]` — date string `"M/DD/YYYY"` (data rows) or metadata value
- `row[2]` — time string `"H:MM AM/PM"`
- `row[6]` — kWh value (net usage, can be negative for solar export)

The file has a UTF-8 BOM (`utf-8-sig`) and leading zeros on the meter number are stripped before matching.

## EV-TOU-5 TOU Schedule

| Hours | Weekday | Weekend / Holiday |
|---|---|---|
| 12 AM – 6 AM | Super Off-Peak | Super Off-Peak |
| 6 AM – 10 AM | Off-Peak | Super Off-Peak |
| 10 AM – 2 PM | Super Off-Peak | Super Off-Peak |
| 2 PM – 4 PM | Off-Peak | Off-Peak |
| 4 PM – 9 PM | On-Peak | On-Peak |
| 9 PM – 12 AM | Off-Peak | Off-Peak |

The `holidays` library (`holidays.US()`) determines US federal holidays. Python 3.10+ is required for `match/case`.
