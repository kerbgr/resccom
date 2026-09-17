# RFC-0001: Architecture & founding decisions

**Status:** Accepted · **Date:** 2026-09 · **Author:** project founder

## Context

Project NOMAD solves offline knowledge (Kiwix, Kolibri, maps, local LLM) but not connectivity. Commercial "network in a box" products (Athonet/HPE tactical backpack, VVDN, Firecell) prove private-cellular disaster kits work, but are closed and priced for defense. Open attempts nearest to this niche — CoLTE (rural billing focus), Rhizomatica RCCN (2G, unmaintained), Ukama (stalled), OpenCellular (dormant) — leave the space between "raw components" and "proprietary tactical kit" empty. See [docs/landscape.md](../docs/landscape.md).

Target scenarios, all three: sudden-onset disaster, protracted crisis, off-grid communities. Target geography for launch: Europe, with the Nordic/German local-licensing regimes as the legal beachhead.

## Decisions

### D1 — Private 4G/5G is the primary access layer
Open5GS core (5G SA **and** EPC dual-mode) + srsRAN on SDR front-ends. Rationale: any COTS smartphone with a provisioned SIM attaches natively — no app, no special hardware for users. LTE/EPC is the reliability floor (mature, broad handset support); 5G SA advances in parallel. Wi-Fi offload and LoRa/Meshtastic gateways are supported extension tiers, not the core.

### D2 — NOMAD is a component, not a fork
NOMAD deploys unmodified as the knowledge/services layer on Class A/B nodes. Same rule for all upstreams (upstream-first, unmodified version-pinned containers; our glue is thin and Apache-2.0).

### D3 — Voice/messaging: app-based first, IMS later
Matrix (E2EE messaging) + Jitsi/SIP at launch. Native-dialer VoLTE via open IMS is a timeboxed Phase 4 spike (WBS 4.4) producing RFC-0002, not a launch dependency.

### D4 — Federated identity from the schema up
Each island provisions its own SIMs (pySim) into its own Open5GS subscriber DB and holds its own keys. The subscriber schema and overlay (WireGuard between islands) are designed from day one so that island-A subscribers can roam onto island B (Phase 3, RFC-0003). No central ResCCOM identity service, ever.

### D5 — Offline-first backhaul
Every service functions with zero backhaul. Starlink (and any second satellite provider), inter-island PtP links, and DTN store-and-forward are opportunistic additions. Rule: unplugging every WAN cable must change *reach*, never *function*.

### D6 — Emergency-services interop via PEMEA
Class A/B nodes can host a PEMEA Application Provider so emergency apps on the island reach 112/PSAP infrastructure over any live backhaul, with location from the local network; degraded mode falls back to local incident coordination. This is the project's most differentiating capability — no open or community project does it.

### D7 — Association-owned deployment model
The deployment unit is a local legal association (community network, preparedness org), which holds the spectrum license and the subscriber keys. The project ships software, reference designs, and a playbook — never service. See [docs/deployment-model.md](../docs/deployment-model.md).

### D8 — Honest threat model
Non-goals: covertness, RF-metadata protection, anonymity. See [SECURITY.md](../SECURITY.md). Marketing or docs violating this are treated as bugs.

### D9 — Three node classes, one image
Class C backpack / Class B vehicle / Class A community anchor share one OS image and stack; profiles differ in radio, compute, energy, enabled services. See [node-hw/](../node-hw/README.md).

### D10 — Vendor accelerators, not dependencies
Tesla Powerwall (donated units) and Starlink are first-class *supported profiles* but the reference designs remain open/repairable (LiFePO₄ + open charge controllers; multi-provider WAN). A node must operate with every proprietary vendor service unavailable.

## Consequences

- Spectrum licensing is a permanent workstream (WBS 0.4), not a footnote; country matrix lives in [docs/spectrum/](../docs/spectrum/README.md).
- Dual-mode core means every stack task is tested against both EPC and 5GC paths.
- Solo-bootstrap reality: everything must be reproducible from docs alone — that is milestone M2's test and the standing bar for all `TASKS.md` acceptance criteria.

## Open questions (feed future RFCs)

1. Roaming mechanics: federated UDM lookup vs. home-routed via overlay (RFC-0003).
2. IMS: worth the operational weight? (RFC-0002 after WBS 4.4 spike.)
3. eSIM: at what scale does an SM-DP+ relationship become feasible for associations?
4. k3s vs. plain compose for Class C's constrained hardware.
