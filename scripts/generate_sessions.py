"""Synthetic FreeRADIUS accounting data generator.

WHY: scale-testing the presence engine needs volume, but more importantly it needs the
hard cases the engine was built to handle (missing STOPs, reconnects inside the grace
window, long sessions with interim updates) — not just clean start/stop pairs. Real
FreeRADIUS traffic mixes all of these; a generator that only emits clean pairs would
never actually exercise the engine.

WHAT: generates FreeRADIUS detail-file records — the same text format FreeRADIUSSource
parses — for a configurable population of users/devices across a time span, and writes
them to a detail file. Run scripts/scale_test.py against the output to push it through
the real FreeRADIUSSource -> PresenceEngine pipeline.

Usage:
    python scripts/generate_sessions.py --out data/generated.detail --users 200
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
from dataclasses import dataclass, field
from pathlib import Path

# Must match PresenceEngine's default reconnect_grace_ms (see pipeline/presence_engine.py).
# Generation deliberately targets just inside and just outside this window so a single
# run exercises both the "merges into one visit" and "genuinely a new visit" branches.
RECONNECT_GRACE_S = 120


@dataclass
class GeneratorConfig:
    """Knobs for the synthetic workday. All *_s fields are in seconds."""

    num_users: int = 50
    num_locations: int = 5
    start_ts: int = 0                    # epoch seconds; 0 means "today at 09:00 local"
    duration_s: int = 8 * 3600           # one workday
    avg_session_s: float = 45 * 60
    missing_stop_pct: float = 0.1        # dead-phone case: STOP never arrives
    reconnect_pct: float = 0.15          # next session starts inside the grace window
    multi_device_pct: float = 0.2        # user carries a second device (laptop + phone)
    interim_interval_s: float = 10 * 60  # heartbeat cadence on long sessions
    seed: int = 42

    def resolved_start_ts(self) -> int:
        """0 means "today at 09:00 local" — resolved lazily so import time stays cheap."""
        if self.start_ts:
            return self.start_ts
        return int(dt.datetime.now().replace(hour=9, minute=0, second=0, microsecond=0).timestamp())


def _random_mac(rng: random.Random) -> str:
    """A plausible-looking MAC. Deliberately never reused as an identity key downstream
    — matches the real-world constraint that MAC randomization makes it unreliable
    (see docs/ARCHITECTURE.md 4.3); user_id is always the stable key.
    """
    return ":".join(f"{rng.randint(0, 255):02X}" for _ in range(6))


def make_record(
    user: str,
    device_mac: str,
    location: str,
    status: str,
    ts: int,
    session_id: str,
    session_time_s: int | None = None,
) -> str:
    """Format one accounting event as a FreeRADIUS detail-file record: an unindented
    date header followed by indented ``Key = Value`` lines — exactly what
    FreeRADIUSSource._parse_records expects.

    Deterministic — no randomness — so callers (including tests) can build known
    scenarios directly without going through the stochastic workday generator below.
    """
    header = dt.datetime.fromtimestamp(ts).strftime("%a %b %e %H:%M:%S %Y")
    fields = {
        "User-Name": f'"{user}"',
        "Acct-Status-Type": status,
        "Acct-Session-Id": f'"{session_id}"',
        "Calling-Station-Id": f'"{device_mac}"',
        "Called-Station-Id": f'"{location}"',
        "NAS-IP-Address": "127.0.0.1",
        "Timestamp": str(ts),
    }
    if session_time_s is not None:
        fields["Acct-Session-Time"] = str(session_time_s)
    lines = [header] + [f"\t{key} = {value}" for key, value in fields.items()]
    return "\n".join(lines)


def write_detail_file(path: str | Path, records: list[str]) -> None:
    """Join formatted records with the blank-line separator FreeRADIUSSource splits
    records on, and write the detail file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(records) + "\n", encoding="utf-8")


@dataclass
class _DeviceStream:
    """One device's session timeline plus the counts needed for the CLI summary."""

    records: list[tuple[int, str]] = field(default_factory=list)  # (timestamp, record text)
    sessions: int = 0
    missing_stops: int = 0
    reconnects: int = 0


def _gen_device_sessions(
    rng: random.Random,
    user: str,
    device_mac: str,
    locations: list[str],
    config: GeneratorConfig,
) -> _DeviceStream:
    """Generate one device's full session timeline across the workday.

    WHY the loop shape: each iteration is one session (Start [.. Interim-Update ..]
    [Stop]) followed by a gap before the next. The gap is biased toward
    RECONNECT_GRACE_S sometimes (grace-window merge case) and toward a normal break
    otherwise, so a single run mixes both real-world patterns.
    """
    stream = _DeviceStream()
    start_ts = config.resolved_start_ts()
    end_ts = start_ts + config.duration_s
    t = start_ts + rng.uniform(0, config.avg_session_s)  # stagger initial connect times

    while t < end_ts:
        stream.sessions += 1
        location = rng.choice(locations)
        session_id = f"{user}-{device_mac[-5:]}-{stream.sessions}"
        session_start = int(t)

        session_len = max(60.0, rng.expovariate(1.0 / config.avg_session_s))
        stream.records.append(
            (session_start, make_record(user, device_mac, location, "Start", session_start, session_id))
        )

        # WHY: only sessions longer than one interim interval realistically send a
        # heartbeat — a short session never lives long enough to.
        n_updates = int(session_len // config.interim_interval_s)
        for i in range(1, n_updates + 1):
            update_ts = session_start + int(i * config.interim_interval_s)
            stream.records.append(
                (update_ts, make_record(user, device_mac, location, "Interim-Update", update_ts, session_id))
            )

        session_stop = session_start + int(session_len)
        if rng.random() < config.missing_stop_pct:
            # dead-phone case: no Stop record at all; the engine must time this out.
            stream.missing_stops += 1
        else:
            stream.records.append((
                session_stop,
                make_record(user, device_mac, location, "Stop", session_stop, session_id, session_time_s=int(session_len)),
            ))

        # Bias the gap before the next session toward the reconnect grace window
        # sometimes (same visit, engine should merge) and a normal break otherwise.
        if rng.random() < config.reconnect_pct:
            gap = rng.uniform(1, RECONNECT_GRACE_S - 10)
            stream.reconnects += 1
        else:
            gap = rng.uniform(RECONNECT_GRACE_S * 2, 3600)
        t = session_stop + gap

    return stream


def generate(config: GeneratorConfig) -> tuple[list[str], dict[str, int]]:
    """Generate a full synthetic workday across all users/devices.

    Returns (records, summary): records are formatted and sorted in chronological
    order (matching how a real detail file accumulates); summary has the counts used
    for the CLI printout.
    """
    rng = random.Random(config.seed)
    locations = [f"AP-Floor{i + 1}" for i in range(config.num_locations)]

    all_records: list[tuple[int, str]] = []
    summary = {
        "users": config.num_users,
        "devices": 0,
        "sessions": 0,
        "missing_stops": 0,
        "reconnects": 0,
        "multi_device_users": 0,
    }

    for u in range(config.num_users):
        user = f"user{u:04d}"
        num_devices = 2 if rng.random() < config.multi_device_pct else 1
        if num_devices > 1:
            summary["multi_device_users"] += 1
        for _ in range(num_devices):
            device_mac = _random_mac(rng)
            stream = _gen_device_sessions(rng, user, device_mac, locations, config)
            summary["devices"] += 1
            summary["sessions"] += stream.sessions
            summary["missing_stops"] += stream.missing_stops
            summary["reconnects"] += stream.reconnects
            all_records.extend(stream.records)

    all_records.sort(key=lambda pair: pair[0])
    return [record for _, record in all_records], summary


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate synthetic FreeRADIUS accounting data for scale-testing the presence engine."
    )
    p.add_argument("--out", default="data/generated.detail", help="output detail file path")
    p.add_argument("--users", type=int, default=50)
    p.add_argument("--locations", type=int, default=5)
    p.add_argument("--duration-hours", type=float, default=8.0)
    p.add_argument("--avg-session-min", type=float, default=45.0)
    p.add_argument("--missing-stop-pct", type=float, default=0.1)
    p.add_argument("--reconnect-pct", type=float, default=0.15)
    p.add_argument("--multi-device-pct", type=float, default=0.2)
    p.add_argument("--interim-interval-min", type=float, default=10.0)
    p.add_argument("--start-ts", type=int, default=0, help="epoch seconds; 0 = today at 09:00 local")
    p.add_argument("--seed", type=int, default=42)
    return p


def main() -> None:
    args = _build_arg_parser().parse_args()
    config = GeneratorConfig(
        num_users=args.users,
        num_locations=args.locations,
        start_ts=args.start_ts,
        duration_s=int(args.duration_hours * 3600),
        avg_session_s=args.avg_session_min * 60,
        missing_stop_pct=args.missing_stop_pct,
        reconnect_pct=args.reconnect_pct,
        multi_device_pct=args.multi_device_pct,
        interim_interval_s=args.interim_interval_min * 60,
        seed=args.seed,
    )
    records, summary = generate(config)
    write_detail_file(args.out, records)

    print(f"Wrote {len(records)} record(s) to {args.out}")
    print(
        f"  users={summary['users']} devices={summary['devices']} "
        f"multi_device_users={summary['multi_device_users']}"
    )
    print(
        f"  sessions={summary['sessions']} missing_stops={summary['missing_stops']} "
        f"reconnects={summary['reconnects']}"
    )


if __name__ == "__main__":
    main()
