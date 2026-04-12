"""One-time Tesla OAuth setup script.

Run this once in a terminal to complete the OAuth browser flow and save
.tesla_session.json. After that, tesla_charge.apply_charge_schedule() works
headlessly from the dashboard.

Usage:
    python save_tesla_session.py
"""

import json
from pathlib import Path

TESLA_SESSION_FILE = Path(__file__).parent / ".tesla_session.json"


def main() -> None:
    try:
        import teslapy  # noqa: PLC0415
    except ImportError:
        print("Error: teslapy is not installed. Run:  pip install teslapy")
        return

    email = input("Tesla account email: ").strip()
    tesla = teslapy.Tesla(email, cache_file=str(TESLA_SESSION_FILE))

    if not tesla.authorized:
        print("Opening browser for Tesla OAuth…")
        tesla.fetch_token()

    vehicles = tesla.vehicle_list()
    print(f"\nConnected! Found {len(vehicles)} vehicle(s):")
    for v in vehicles:
        print(f"  - {v.get('display_name', 'Unknown')} ({v.get('vin', '')})")

    # Persist the email so tesla_charge.py can reconstruct the session.
    cache_data = json.loads(TESLA_SESSION_FILE.read_text()) if TESLA_SESSION_FILE.exists() else {}
    if isinstance(cache_data, dict):
        cache_data["email"] = email
    else:
        # teslapy writes a list of token dicts; wrap to preserve tokens + email
        cache_data = {"email": email, "tokens": cache_data}
    TESLA_SESSION_FILE.write_text(json.dumps(cache_data))

    print(f"\nSession saved to {TESLA_SESSION_FILE}")
    print("You can now use 'Schedule Tesla Now' from the dashboard.")


if __name__ == "__main__":
    main()
