# Architecture

> Status: **Draft v0.1** — this document describes the target system. It is intentionally
> ahead of the code. Build order (see [Phasing](#phasing)) is deliberately narrower than
> the design.

---

## 1. What this system is

A vendor-agnostic software platform that connects to a company's existing
**network authentication infrastructure** and turns real login/session events into
**reliable presence and attendance** data, surfaced to a management dashboard.

**One sentence:** *Who is in the building, on which floor, since when — derived from the
authentication the network already performs.*

### What it is NOT
- Not a "student taps a button to mark themselves present" app (manual, trivial).
- Not WiFi CSI body-sensing (detects bodies, cannot identify people — physically impossible to get identity from raw signal).
- Not MAC-address sniffing (defeated by MAC randomization on modern phones).

### The core idea
Identity does not come from the radio signal. It comes from the **credentials a person
already presents to log in** to the corporate network. The network's authentication
system (RADIUS / Cisco ISE / Aruba ClearPass) records *who* authenticated, *on which
access point*, *when*. That record is the raw material for attendance.

---

## 2. The central abstraction: Identity Source

The whole product hinges on one boundary. Every supported backend
(FreeRADIUS, Cisco ISE, Cisco Spaces, Aruba ClearPass, ...) is just an implementation
of a single interface:

```
IdentitySource
    └── stream_sessions() -> yields SessionEvent
```

A `SessionEvent` is the **common event model** — the normalized record every source maps into:

| Field         | Meaning                                          |
|---------------|--------------------------------------------------|
| `user_id`     | The authenticated identity (the person)          |
| `device_mac`  | The device used (may be randomized)              |
| `location_id` | Where they connected (AP / controller / zone)    |
| `event_type`  | START / UPDATE / STOP                             |
| `timestamp`   | When it happened (epoch ms)                       |
| `source`      | Which backend produced it (freeradius, ise, ...) |
| `raw`         | The original untouched record (for audit/debug)  |

Everything downstream (attendance logic, storage, dashboard) works only on
`SessionEvent`. It never knows or cares which vendor produced it. **This is what makes
the platform vendor-agnostic — and it is the part that does not exist as open source.**

---

## 3. The pipeline (8 layers)

```
┌────────────────────────────────────────────────────────────────┐
│  1. IDENTITY SOURCE   FreeRADIUS │ Cisco ISE │ Aruba │ Spaces   │
│     (adapters)        each emits raw auth/accounting records    │
└───────────────┬────────────────────────────────────────────────┘
                │  maps raw record → SessionEvent (common model)
┌───────────────▼────────────────────────────────────────────────┐
│  2. INGESTION         consume stream, dedupe, order, buffer      │
└───────────────┬────────────────────────────────────────────────┘
                │
┌───────────────▼────────────────────────────────────────────────┐
│  3. IDENTITY RESOLUTION   collapse many devices/sessions → one   │
│                           human; handle MAC randomization        │
└───────────────┬────────────────────────────────────────────────┘
                │
┌───────────────▼────────────────────────────────────────────────┐
│  4. PRESENCE ENGINE   SessionEvents → attendance state.          │
│                       "what counts as present?" lives here.      │
│                       (THE hard algorithmic core)                │
└───────────────┬────────────────────────────────────────────────┘
                │
┌───────────────▼────────────────────────────────────────────────┐
│  5. STORAGE           events + resolved attendance records.      │
│                       encrypted, access-controlled, retention.   │
└───────────────┬────────────────────────────────────────────────┘
                │
┌───────────────▼────────────────────────────────────────────────┐
│  6. API LAYER         query attendance, presence, history.       │
└───────────────┬────────────────────────────────────────────────┘
                │
┌───────────────▼────────────────────────────────────────────────┐
│  7. DASHBOARD         what management/HR actually sees.          │
└───────────────┬────────────────────────────────────────────────┘
                │
┌───────────────▼────────────────────────────────────────────────┐
│  8. MULTI-TENANCY     each customer's data isolated (product).   │
└────────────────────────────────────────────────────────────────┘
```

---

## 4. The hard problems (named, not hand-waved)

These are the parts that make this a real project. Each is an **open design question**,
documented here so decisions are explicit and defensible.

### 4.1 Presence ≠ Attendance  (Layer 4)
A session-started event is not attendance. Open questions:
- What counts as "present"? Seen once? Continuously connected? For ≥ N minutes?
- A phone sleeps and drops the session, then reconnects — one presence or two?
- Someone walks between floors, reconnecting to different APs — one visit or many?
- Define the state machine: ABSENT → PRESENT → IDLE → LEFT, and the timers that drive it.

### 4.2 Multi-device / multi-session identity  (Layer 3)
- One person = laptop + phone + tablet = 3 concurrent sessions. Collapse to one human.
- Across reconnects the MAC may change (randomization). The **username** is the stable key.
- Guest identity vs corporate identity: guest networks often carry weak/no real identity.

### 4.3 MAC randomization  (Layers 1 & 3)
- Modern iOS/Android rotate MAC per network by design to prevent tracking.
- **Consequence:** MAC is NOT a reliable identity key. The authenticated username is.
- This is exactly why the system is built on the auth layer, not on MAC sniffing.

### 4.4 The "phone ≠ person" limit  (Layer 4 + product honesty)
- Presence proves the *device* is on the network, not that the *human* is at their desk.
- This is a boundary to disclose, not hide. Product must state what "present" means.
- Possible mitigations (future): require periodic re-auth, combine with a second signal.

### 4.5 Reliability at scale  (Layers 2 & 5)
- Thousands of employees → constant session churn. Ordering, dedup, back-pressure.

### 4.6 Privacy, security, law  (Layer 5, cross-cutting)
- Storing every employee's location all day = regulated, sensitive data.
- Encryption at rest + in transit, access control, audit logs, retention policy, consent.
- Get this wrong and the product is a liability, not a product.

---

## 5. Data model (initial)

Core entities (to be refined):

- **users** — the people (id, name, corporate username, ...)
- **devices** — known devices mapped to users (mac/deviceId → user_id)
- **session_events** — raw normalized SessionEvents (append-only, audit trail)
- **presence_records** — computed attendance (user, location, check_in, check_out, state)
- **locations** — hierarchy (building → floor → zone → AP)
- **tenants** — customer isolation (multi-tenancy)

`session_events` is append-only and immutable — it is the source of truth.
`presence_records` is *derived* by the Presence Engine and can be recomputed.

---

## 6. Phasing (build order)

The document above is the full vendor-agnostic target. The **build** is deliberately
narrower and concrete first, so we never design against imaginary APIs.

- **Phase 0 — Foundation.** Stand up FreeRADIUS locally. Authenticate a device through it.
  Produce real RADIUS **accounting** records. Deliverable: one real session logged.
- **Phase 1 — First adapter.** `FreeRADIUSSource` implements `IdentitySource`, maps raw
  accounting records → `SessionEvent`. Deliverable: real records become normalized events.
- **Phase 2 — Presence Engine (the hard core).** SessionEvents → attendance state machine.
  Solve 4.1. Deliverable: "who is present right now" from real data.
- **Phase 3 — Identity resolution.** Solve 4.2 / 4.3. Collapse devices → humans.
- **Phase 4 — Storage + API + dashboard.** Persist, query, display.
- **Phase 5 — Second adapter (Cisco ISE / Spaces).** Prove the abstraction by adding a
  second source with zero changes downstream. This is the moment "vendor-agnostic" is real.
- **Phase 6 — Security, multi-tenancy, deployability.** Make it a product.

**Current phase: 0.**

---

## 7. Open decisions log

Track every non-obvious architectural decision here as it's made, so the reasoning
survives (and is defensible in a review / interview).

| Date       | Decision                                   | Why |
|------------|--------------------------------------------|-----|
| 2026-08-05 | Identity comes from auth layer, not MAC.   | MAC randomization makes MAC unreliable; username is stable. |
| 2026-08-05 | Build FreeRADIUS-first, design vendor-agnostic. | Can't design a correct abstraction against imaginary APIs; need one real source first. |
| 2026-08-05 | `session_events` append-only, presence derived. | Auditability; ability to recompute attendance when logic changes. |
