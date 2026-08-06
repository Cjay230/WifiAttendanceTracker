"""Run the FreeRADIUS parser against a detail file and print SessionEvents."""

import sys

from presence_platform.sources.freeradius.source import FreeRADIUSSource


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: demo_freeradius.py <path-to-detail-file>")
        raise SystemExit(1)

    source = FreeRADIUSSource(sys.argv[1])
    count = 0
    for e in source.stream_sessions():
        print(
            f"{e.event_type.value:6} "
            f"user={e.user_id:8} "
            f"loc={e.location_id:12} "
            f"mac={e.device_mac:18} "
            f"ts={e.timestamp}"
        )
        count += 1
    print(f"\n{count} SessionEvent(s) parsed from {source.name}.")


if __name__ == "__main__":
    main()
