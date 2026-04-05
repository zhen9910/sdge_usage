import csv
import openpyxl
import holidays
import datetime
import sys
import math

us_holidays = holidays.US()

def get_time_periods(date, time):

    hour = time.hour
    weekday = date.weekday() < 5
    weekend = not weekday
    holiday = date in us_holidays
    march_or_april = date.month == 3 or date.month == 4

    match hour:
        case hour if hour >= 0 and hour < 6:
            time_period = "Super Off Peak"
        case hour if hour >= 6 and hour < 10:
            time_period = "Super Off Peak" if (weekend or holiday) else "Off Peak"
        case hour if hour >= 10 and hour < 14:
            time_period = "Super Off Peak" if (weekend or holiday or march_or_april) else "Off Peak"
        case hour if hour >= 16 and hour < 21:
            time_period = "On Peak"
        case _:
            time_period = "Off Peak"

    return time_period


def parse_date(value):
    if isinstance(value, str):
        return datetime.datetime.strptime(value.strip(), "%m/%d/%Y")
    return value


def parse_time(value):
    if isinstance(value, str):
        return datetime.datetime.strptime(value.strip(), "%I:%M %p").time()
    return value


def iter_rows_xlsx(filename):
    wb = openpyxl.load_workbook(filename)
    sheet = wb.active
    for row in sheet.iter_rows(values_only=True):
        yield [cell for cell in row]


def iter_rows_csv(filename):
    with open(filename, newline='', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        for row in reader:
            while len(row) < 7:
                row.append(None)
            yield row


def iter_rows_csv_stream(stream):
    text = stream.read().decode('utf-8-sig')
    reader = csv.reader(text.splitlines())
    for row in reader:
        while len(row) < 7:
            row.append(None)
        yield row


def iter_rows_xlsx_stream(stream):
    wb = openpyxl.load_workbook(stream)
    sheet = wb.active
    for row in sheet.iter_rows(values_only=True):
        yield [cell for cell in row]


def process(rows):
    """Process rows and return a result dict, or raise ValueError on bad input."""
    meter_number = None
    total_usage = 0
    reading_start = ""
    reading_end = ""
    super_off_peak_kwh = 0
    off_peak_kwh = 0
    on_peak_kwh = 0

    all_rows = list(rows)

    # Pass 1: metadata
    for row in all_rows:
        key = str(row[0]).strip() if row[0] is not None else ""
        match key:
            case "Meter Number":
                val = str(row[1]).strip() if row[1] is not None else ""
                if val != "Date":
                    meter_number = val.lstrip("0") or val
            case "Reading Start":
                reading_start = row[1]
            case "Reading End":
                reading_end = row[1]
            case "Total Usage":
                total_usage = float(row[1])

    if meter_number is None:
        raise ValueError("Could not find Meter Number in file")

    # Pass 2: usage data
    for row in all_rows:
        val = str(row[0]).strip().lstrip("0") if row[0] is not None else ""
        if val == meter_number:
            date = parse_date(row[1])
            time = parse_time(row[2])
            kwh = float(row[6])
            time_period = get_time_periods(date, time)
            match time_period:
                case "Super Off Peak":
                    super_off_peak_kwh += kwh
                case "Off Peak":
                    off_peak_kwh += kwh
                case "On Peak":
                    on_peak_kwh += kwh

    total_kwh = super_off_peak_kwh + off_peak_kwh + on_peak_kwh
    warning = None
    if not math.isclose(total_kwh, total_usage, rel_tol=1e-6):
        warning = f"Categorized total {total_kwh:.4f} kWh does not match reported total {total_usage:.4f} kWh"

    return {
        "meter_number": meter_number,
        "reading_start": reading_start,
        "reading_end": reading_end,
        "super_off_peak_kwh": round(super_off_peak_kwh, 4),
        "off_peak_kwh": round(off_peak_kwh, 4),
        "on_peak_kwh": round(on_peak_kwh, 4),
        "total_kwh": round(total_kwh, 4),
        "warning": warning,
    }


if __name__ == '__main__':

    if len(sys.argv) != 2:
        print("Usage: python sdge_usage.py filename")
        sys.exit(1)

    filename = sys.argv[1]
    print(f"\n\nReading file: {filename}\n\n")

    if filename.lower().endswith(".csv"):
        rows = iter_rows_csv(filename)
    elif filename.lower().endswith(".xlsx"):
        rows = iter_rows_xlsx(filename)
    else:
        print("Error: unsupported file type. Use .xlsx or .csv")
        sys.exit(1)

    result = process(rows)
    print(f"Meter Number: {result['meter_number']}")
    print(f"\n\nElectricity usage from {result['reading_start']} to {result['reading_end']}\n\n")
    print(f"Super Off Peak net usage (kwh): {result['super_off_peak_kwh']}")
    print(f"Off Peak net usage (kwh):       {result['off_peak_kwh']}")
    print(f"On Peak net usage (kwh):        {result['on_peak_kwh']}\n")
    print(f"Total net usage (kwh):          {result['total_kwh']}")
    if result['warning']:
        print(f"\nWarning: {result['warning']}")
