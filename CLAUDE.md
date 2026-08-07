# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A vendor-agnostic platform that turns a company's existing **network authentication**
(FreeRADIUS / Cisco ISE / Aruba ClearPass) into reliable **presence and attendance** data.
Identity always comes from the credentials a person uses to log in to the network — never
from MAC address (defeated by randomization) and never from raw WiFi signal (physically
cannot identify a person; see `docs/documentations/wifi-sensing-findings.md` for the
research behind that decision).

Full design: `docs/ARCHITECTURE.md`. It documents the target vendor-agnostic system (8
layers, phases 0-6); the codebase implements a deliberately narrower slice, tracked below.

**Current phase: 2 (done).**
- Phase 0 — FreeRADIUS running locally, producing real RADIUS accounting records.
- Phase 1 — `FreeRADIUSSource` parses accounting detail files into `SessionEvent`s.
- Phase 2 — Presence engine: `SessionEvent`s → attendance state machine (`ABSENT` →
  `PRESENT` → `IDLE` → `LEFT`), handling missing STOPs via timeout, interim heartbeats,
  and reconnect grace.
- Not yet built: identity resolution across devices (Phase 3), storage/API/dashboard
  (Phase 4), a second adapter (Phase 5), multi-tenancy/security (Phase 6).

## Commands

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

# tests (pytest is not currently a declared dependency — pip install pytest first)
pytest
pytest tests/test_presence_engine.py
pytest tests/test_presence_engine.py::test_missing_stop_times_out_to_left

# run the FreeRADIUS parser standalone against a detail file
python scripts/demo_freeradius.py <path-to-detail-file>

# run the full pipeline: FreeRADIUS detail file -> SessionEvents -> presence
# (typically run inside WSL against a real FreeRADIUS accounting file, hence sudo)
sudo PYTHONPATH=src python3 scripts/demo_presence.py \
    /var/log/freeradius/radacct/127.0.0.1/detail-<date>
```

There is no lint/format tooling configured in `pyproject.toml` yet.

## Architecture

Everything is built around one boundary: `IdentitySource.stream_sessions()` yields
`SessionEvent` objects (`src/presence_platform/core/models.py`). Every backend adapter
implements this interface; every downstream layer (presence engine, storage, API) works
*only* on `SessionEvent` and never knows which vendor produced it. This is the
vendor-agnostic abstraction the whole platform hinges on — when adding or changing a
source, only the adapter's raw-record → `SessionEvent` mapping should change, nothing
downstream.

`SessionEvent` fields: `user_id` (the stable identity key — the authenticated username,
never the MAC), `device_mac`, `location_id`, `event_type` (`START`/`UPDATE`/`STOP`),
`timestamp` (epoch ms), `source`, `raw` (untouched original record, for audit). It is
frozen/immutable — `SessionEvent`s are facts that happened, an append-only trail.

**`sources/freeradius/source.py`** — `FreeRADIUSSource`, the only adapter so far. Parses
FreeRADIUS detail-file records (blank-line-delimited blocks of `Key = Value` lines) and
maps `Acct-Status-Type` (`Start`/`Interim-Update`/`Stop`) to `EventType`. Records missing
a recognized status or a `User-Name` are silently skipped.

**`pipeline/presence_engine.py`** — `PresenceEngine`, the algorithmic core (Phase 2). A
state machine keyed by `(user_id, location_id)`, fed one `SessionEvent` at a time via
`process()`. Key design points, since they're easy to get wrong when modifying:
- Three timeouts drive transitions: `idle_timeout_ms` (quiet → `IDLE`), `left_timeout_ms`
  (quiet → `LEFT`, the safety net for a STOP that never arrives — e.g. a dead phone),
  `reconnect_grace_ms` (declared but the actual grace behavior is just: a new START while
  a visit is still active in `_active` extends the same visit rather than starting a new
  one — visits only leave `_active` on an explicit STOP or a `left_timeout_ms` expiry).
- On each `process(event)`, the incoming event's own visit is updated *first*, and only
  *other* visits are checked for staleness against that event's timestamp
  (`_expire_stale(..., skip=key)`). This ordering matters: a legitimately late STOP on a
  long session must not time out its own visit before it gets to close it.
- `build_presence(events)` is the convenience entry point used by `demo_presence.py`: runs
  a whole (already time-sorted) stream through a fresh engine and calls `finalize()` at the
  end so trailing-open visits get one last timeout pass.
- Same user at two different `location_id`s = two independent visits; collapsing that into
  one human movement is explicitly deferred to Phase 3 (identity resolution), not handled
  here.

`src/presence_platform/{storage,api}/` exist as empty package stubs for Phases 4+; there
is no implementation there yet.
