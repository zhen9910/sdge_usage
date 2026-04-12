"""Tesla charge scheduling via teslapy.

One-time setup: run save_tesla_session.py once in a terminal to complete the
OAuth flow and create .tesla_session.json. After that, apply_charge_schedule()
works headlessly from the dashboard.

Command name note: verify the exact teslapy command key before first use:
    python -c "import teslapy; print([k for k in teslapy.COMMANDS if 'CHARG' in k.upper()])"
The most common key is 'SET_SCHEDULED_CHARGING'; update _SCHEDULE_CMD if different.
"""

from pathlib import Path

TESLA_SESSION_FILE = Path(__file__).parent / ".tesla_session.json"
_SCHEDULE_CMD = "SET_SCHEDULED_CHARGING"


def tesla_session_exists() -> bool:
    return TESLA_SESSION_FILE.exists()


def _get_vehicle():
    """Return the first vehicle from the saved Tesla session.

    Raises:
        FileNotFoundError: No Tesla session file.
        ImportError: teslapy not installed.
    """
    import teslapy  # noqa: PLC0415

    cache = TESLA_SESSION_FILE.read_text()
    import json  # noqa: PLC0415
    data = json.loads(cache)
    email = data.get("email", "")
    tesla = teslapy.Tesla(email, cache_file=str(TESLA_SESSION_FILE))
    vehicles = tesla.vehicle_list()
    if not vehicles:
        raise RuntimeError("No vehicles found in Tesla account.")
    return vehicles[0]


def apply_charge_schedule(charge_start_hour: int, charge_end_hour: int) -> dict:
    """Schedule the Tesla to start charging at charge_start_hour (local time).

    Args:
        charge_start_hour: Hour to start charging (0–23).
        charge_end_hour:   Hour to stop charging (1–24). Currently informational
                           only — the API schedules a start time, not a range.

    Returns:
        {
            "success": bool,
            "vehicle": str | None,   # display name
            "scheduled_time": str | None,  # "HH:MM"
            "error": str | None,
        }
    """
    try:
        vehicle = _get_vehicle()
        vehicle.sync_wake_up()
        vehicle.command(
            _SCHEDULE_CMD,
            enable=True,
            time=charge_start_hour * 60,  # minutes from midnight
        )
        return {
            "success": True,
            "vehicle": vehicle.get("display_name"),
            "scheduled_time": f"{charge_start_hour:02d}:00",
            "error": None,
        }
    except FileNotFoundError as e:
        return {"success": False, "vehicle": None, "scheduled_time": None, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "vehicle": None, "scheduled_time": None, "error": str(e)}
