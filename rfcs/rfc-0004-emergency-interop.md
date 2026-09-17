# RFC-0004: Emergency access — an island-native service with optional upstream routes

**Status:** Draft v2 (2026-09-14; v1 made PEMEA the mechanism, v2 makes it one route) · **Refines:** RFC-0001 D6 · **Implements as:** WBS 4.3

## Context

v1 of this RFC framed emergency access around "a PEMEA app attached to a PEMEA AP." Two things were wrong with that. First, RFC-0001 D2 promises no app-store dependency, and a PEMEA app is a store-installed native app. Second, and more fundamentally, **PEMEA's value is routing** — home-node registration, PSP peering, getting a session to the right PSAP across networks and borders. Off-grid, with no PSAP reachable, that machinery has nothing to do, precisely when the island matters most. Designing the whole emergency path around it meant the feature with the least off-grid value shaped everything.

There is also no need for PEMEA's *roaming app* concept: every island serves the same emergency portal, so a visitor uses the island they are standing on. (Subscriber roaming — RFC-0003 — is what lets a visitor's phone attach at all; that is a separate question and stands.)

## Decisions

### D1 — The emergency service is island-native and works with zero backhaul

Every Class A/B island runs an **Island Emergency Service (IES)**:

- **Public emergency portal** at `sos.island`, linked from the captive portal: from any phone browser, a WebRTC voice/video call, real-time text, and the browser's geolocation carried as PIDF-LO. No app, no store.
- **Local incident desk**: an operator console where trained association members answer, triage, and log — the island is its own PSAP of last resort.
- **Incident records and queue**: every session is recorded (signed, encrypted at rest) with location, time, and a callback reference, whether or not anything upstream is reachable.
- **Location** from the tiered island LIS (D3 of v1, unchanged: device GNSS → cell/sector geometry from the survey → opt-in civic mapping).

The IES speaks standards internally — SIP/WebRTC, PIDF-LO, NG112-style session handling — so that upstream routes are adapters, not rewrites. The seed is the maintainer's PEMEA/NG112 interworking node (`PEMEA_Core`): its public emergency portal is a citizen-browser caller, its operator portal is a PSAP console, and its ESInet role can terminate calls locally — exactly the IES shape. It is consumed upstream-first as a component once it carries an open-source license (none is declared today).

### D2 — Upstream routes are pluggable and opportunistic

When any backhaul exists, the IES forwards live sessions and queued records through whichever routes the association has configured, in priority order:

| Route | When it applies | What it needs in peacetime |
|---|---|---|
| **NG112 / ESInet SIP** to a PSAP | Countries with NG112-capable PSAPs reachable from the association | PSAP peering/credentials; LoST/ECRF entry |
| **PEMEA PSP peering** | Countries where 112 is reachable through the PEMEA network; also lets *national PEMEA apps* already on phones work through the island | AP/PSP onboarding with the national PSP |
| **Voice gateway** (IMS/PSTN) | If RFC-0002 decides IMS | Interconnect agreement |
| **None** | Isolated islands, or associations that never onboard anywhere | — |

No route is required for the IES to function; a route only adds reach. Which routes exist, and their state, are `island.yaml` policy (RFC-0006 D4) and shown live on the portal.

### D3 — The connectivity ladder, unchanged in spirit, now route-agnostic

- **Mode 0 (upstream reachable):** sessions go out over the best available route; the incident desk sees them too.
- **Mode 1 (intermittent):** the local desk handles the session now **and** the record is queued for forwarding.
- **Mode 2 (isolated):** the local desk is the responder; records forward on reconnect via DTN (WBS 4.2).

**The caller is always told the truth:** the portal shows the mode *before* the call is placed — "112 reachable", or "not reachable — you are calling local responders on this network; your report will be forwarded when a link exists" (RFC-0001 D8). If a route's protocol lacks a way to signal degraded mode to a native app (PEMEA), that is raised upstream as a spec contribution; the island-served portal needs no extension to be honest.

### D4 — Location (unchanged from v1)

Tiered island LIS: device GNSS carried by the portal/app; HELD-style cell/sector lookup from surveyed geometry (RFC-0006 produces it); opt-in civic mapping on village anchors, disclosed only inside an active emergency session. Full 3GPP positioning is out of scope for v1.

### D5 — Native 112 dialing: state the limitation, loudly (unchanged)

Until IMS exists (RFC-0002), the phone's green dial button does not reach 112 over the island; handsets will try any reachable macro network. Every user-facing surface — portal, SIM handout script, drill materials — says: *emergencies go through `sos.island` on this network.* Emergency-call support remains a major argument **for** IMS in RFC-0002.

## Consequences

- WBS 4.3 decomposes as: IES core (portal + desk + records) → LIS tier 2 → route adapters (NG112 SIP first where a test PSAP is available, PEMEA second) → DTN forwarding (with 4.2).
- The playbook gains the IES operator role and drill scenarios for Modes 1–2; onboarding with a national PSP (PEMEA or NG112) becomes an *optional* peacetime step, not a founding requirement.
- Backhaul QoS (1.4-c) top class = IES upstream traffic.
- The README's objective 5 is worded to match: emergency access is island-native, browser-based, with 112 reach as an opportunistic add.

## Open questions

1. Which national PSAPs will peer with a community-association node at all (NG112 or PEMEA) — still the largest external unknown; drives the WP 5.1 partner conversation.
2. Retention and consent for queued emergency records that may wait days.
3. Whether the IES should be the same operator surface as the console (RFC-0006 open question 4) or deliberately separate so a coordinator never needs configuration rights.
4. Test path: a PSAP-side sandbox for at least one route before claiming interop.
