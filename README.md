# Presence Platform

A vendor-agnostic platform that turns a company's existing **network authentication**
into reliable **presence and attendance** data.

Identity comes from the credentials people already use to log in to the corporate
network — not from MAC-address sniffing (defeated by randomization) and not from
raw WiFi signal (physically cannot identify a person). The network's authentication
system (FreeRADIUS / Cisco ISE / Aruba ClearPass) records *who* authenticated, *where*,
and *when*. That is the raw material for attendance.

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the full design.

## Status

**Phase 2 — Presence Engine (done).** SessionEvents flow through a state machine
(`ABSENT`/`PRESENT`/`IDLE`/`LEFT`) that handles missing STOPs via timeout, interim
heartbeats, and reconnect grace. Built on Phase 0 (FreeRADIUS producing real RADIUS
accounting records) and Phase 1 (`FreeRADIUSSource` parsing those records into
SessionEvents).

## Structure

```
src/presence_platform/
  core/         # the central abstraction: IdentitySource + SessionEvent
  sources/      # one adapter per backend
    freeradius/ # Phase 1 adapter
  pipeline/     # ingestion, dedup, ordering
  storage/      # persistence
  api/          # query layer
docs/           # architecture + decisions
tests/
scripts/        # dev/setup helpers
```

## Build order

FreeRADIUS-first, but designed vendor-agnostic. See the Phasing section of the
architecture doc. Current phase: **2**.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```
