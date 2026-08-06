"""Full pipeline demo: FreeRADIUS log -> SessionEvents -> attendance.

Usage (inside WSL, from repo root):
    sudo PYTHONPATH=src python3 scripts/demo_presence.py \
        /var/log/freeradius/radacct/127.0.0.1/detail-20260806
"""

import sys

from presence_platform.pipeline.presence_engine import build_presence
from presence_platform.sources.freeradius.source import FreeRADIUSSource


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: demo_presence.py <path-to-detail-file>")
        raise SystemExit(1)

    # 1. read raw login records -> normalized events
    events = list(FreeRADIUSSource(sys.argv[1]).stream_sessions())
    # events must be in time order for the engine
    events.sort(key=lambda e: e.timestamp)

    # 2. run them through the presence engine -> attendance
    engine = build_presence(events)

    print("=== Currently present ===")
    for r in engine.current_presence():
        mins = r.duration_ms / 60000
        print(f"  {r.user_id:8} @ {r.location_id:12} {r.state.value:8} for {mins:.0f} min")

    print("\n=== Completed visits ===")
    for r in engine.completed_visits():
        mins = r.duration_ms / 60000
        print(f"  {r.user_id:8} @ {r.location_id:12} {r.state.value:8} {mins:.0f} min")

    total = len(engine.all_records())
    print(f"\n{total} visit(s) total from {len(events)} event(s).")


if __name__ == "__main__":
    main()
