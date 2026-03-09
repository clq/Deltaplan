#!/usr/bin/env python3
"""Deltaplan Shift Monitor — CLI entry point.

Usage:
  python main.py login          # Test login & print user info
  python main.py shifts         # Show your upcoming shifts
  python main.py vacant         # Show currently available vacant shifts
  python main.py shifttypes     # List all shift types (find abbreviations)
  python main.py dashboard      # Dump full dashboard data
  python main.py monitor        # Watch for new vacant shifts (runs continuously)
"""

import argparse
import json
import os
import subprocess
import sys
import time
import hashlib
from datetime import datetime, timedelta

from deltaplan import DeltaplanClient, load_config, DATA_DIR, ensure_data_dir


def cmd_login(client):
    """Test authentication and print user info."""
    user = client.login()
    print("✓ Login successful")
    print(f"  Name: {user.get('fullname', 'N/A')}")
    print(f"  Employee ID: {user.get('medarbejder_id', 'N/A')}")
    print(f"  Company ID: {user.get('virksomhed_id', 'N/A')}")


def cmd_shifts(client):
    """Show the user's own upcoming shifts."""
    client.login()
    today = datetime.now().strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")
    data = client.get_my_shifts(today, end)

    if not data.get("success") or not data.get("data"):
        print("No shifts found.")
        return

    shift_types = client.get_shift_types()
    for s in data["data"]:
        st = shift_types.get(str(s.get("vagttype_id", "")))
        st_name = f" [{st['vagttype_forkortelse']}]" if st else ""
        print(
            f"  {s['vagt_dato']}  {s['vagt_start'][:5]}-{s['vagt_slut'][:5]}"
            f"  status={s['status']}{st_name}"
        )


def cmd_vacant(client):
    """Show currently available vacant shifts, filtered by configured types."""
    client.login()
    target_types = client.config.get("shift_types", [])
    vacant = client.get_vacant_shifts_by_type(target_types)

    if not vacant:
        print(f"No vacant shifts right now (filter: {', '.join(target_types) or 'all'}).")
        return

    shift_types = client.get_shift_types()
    if isinstance(vacant, dict):
        for date in sorted(vacant.keys()):
            for s in vacant[date]:
                client.enrich_shift(s)
                print(
                    f"  {date}  {s.get('vagt_start','?')[:5]}-{s.get('vagt_slut','?')[:5]}"
                    f"  [{s.get('_shift_type_abbr', '?')}] {s.get('_shift_type_name', '')}"
                )
    elif isinstance(vacant, list):
        for s in vacant:
            client.enrich_shift(s)
            print(
                f"  {s.get('vagt_dato','?')}  {s.get('vagt_start','?')[:5]}-{s.get('vagt_slut','?')[:5]}"
                f"  [{s.get('_shift_type_abbr', '?')}] {s.get('_shift_type_name', '')}"
            )


def cmd_shifttypes(client):
    """List all shift types."""
    client.login()
    shift_types = client.get_shift_types()
    active = [st for st in shift_types.values() if st["status"] == "A"]
    active.sort(key=lambda x: x["vagttype_forkortelse"])
    for st in active:
        print(f"  [{st['vagttype_forkortelse']}] {st['vagttype_navn']}")


def cmd_dashboard(client):
    """Dump full dashboard data for debugging."""
    client.login()
    data = client.get_dashboard()
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def cmd_monitor(client):
    """Continuously poll for new vacant shifts and notify."""
    config = client.config
    interval = config.get("poll_interval_minutes", 30) * 60
    target_types = config.get("shift_types", [])

    ensure_data_dir()
    state_file = os.path.join(DATA_DIR, "last_vacant.json")

    print(f"Monitoring vacant shifts for types: {', '.join(target_types) or 'all'}")
    print(f"Poll interval: {interval // 60} minutes")
    print(f"Notify method: {config.get('notify_method', 'desktop')}")
    print()

    while True:
        try:
            client.login()
            vacant = client.get_vacant_shifts_by_type(target_types)

            # Normalize to a flat list for comparison
            if isinstance(vacant, dict):
                flat = []
                for shifts in vacant.values():
                    flat.extend(shifts)
            else:
                flat = vacant if isinstance(vacant, list) else []

            # Load previous state
            prev_ids = set()
            if os.path.exists(state_file):
                with open(state_file) as f:
                    prev = json.load(f)
                    prev_ids = set(prev.get("shift_ids", []))

            current_ids = {s.get("vagt_id", s.get("id", "")) for s in flat}
            new_ids = current_ids - prev_ids

            now = datetime.now().strftime("%H:%M:%S")
            if new_ids:
                new_shifts = [s for s in flat if s.get("vagt_id", s.get("id", "")) in new_ids]
                for s in new_shifts:
                    client.enrich_shift(s)

                lines = []
                for s in new_shifts:
                    lines.append(
                        f"{s.get('vagt_dato','?')} "
                        f"{s.get('vagt_start','?')[:5]}-{s.get('vagt_slut','?')[:5]} "
                        f"[{s.get('_shift_type_abbr', '?')}]"
                    )

                msg = f"{len(new_shifts)} new vacant shift(s):\n" + "\n".join(lines)
                print(f"🔔 [{now}] {msg}")
                notify(msg, config.get("notify_method", "desktop"))
            else:
                print(
                    f"[{now}] {len(flat)} vacant shift(s), no new ones"
                )

            # Save current state
            with open(state_file, "w") as f:
                json.dump(
                    {
                        "shift_ids": list(current_ids),
                        "shifts": flat,
                        "checked_at": datetime.now().isoformat(),
                    },
                    f,
                    ensure_ascii=False,
                    default=str,
                )

        except Exception as e:
            print(f"✗ [{datetime.now().strftime('%H:%M:%S')}] Error: {e}", file=sys.stderr)

        time.sleep(interval)


def notify(message, method="desktop"):
    """Send a notification."""
    if method == "desktop":
        subprocess.run(
            ["notify-send", "-u", "critical", "Deltaplan", message],
            check=False,
        )
    else:
        print(f"[NOTIFY] {message}")


def main():
    parser = argparse.ArgumentParser(description="Deltaplan Shift Monitor")
    parser.add_argument(
        "command",
        choices=["login", "shifts", "vacant", "shifttypes", "dashboard", "monitor"],
        help="Command to run",
    )
    args = parser.parse_args()

    config = load_config()
    client = DeltaplanClient(config)

    commands = {
        "login": cmd_login,
        "shifts": cmd_shifts,
        "vacant": cmd_vacant,
        "shifttypes": cmd_shifttypes,
        "dashboard": cmd_dashboard,
        "monitor": cmd_monitor,
    }
    commands[args.command](client)


if __name__ == "__main__":
    main()
