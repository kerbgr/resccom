# RFC-0005: Island identity, allocations, and turnkey non-interference

**Status:** Draft · **Date:** 2026-09 · **Refines:** RFC-0001 D4/D5/D9 · **Implements as:** WBS 2.1 (island-init), feeds 3.3 (roaming)

## Context

Every convention in CLAUDE.md today — test PLMN `001/01`, IMSI block `00101…`, UE subnet `10.45.0.0/16`, DNS zone `.island`, Diameter realm `localdomain`, Matrix server `chat.island` — is **identical for every deployment**. Perfect for one lab island; fatal for the actual vision: many independently-owned islands forming a federated overlay (a dn42/Tor-style network of autonomous nodes). Two islands that both hand out `10.45.0.2` to a subscriber called `001010000000001` on a realm called `localdomain` cannot roam, route, or even talk about each other unambiguously. Federation without an identity and numbering plan is a collision generator.

The second requirement raised with this: **turnkey startup.** An association volunteer must be able to bring up a correctly-allocated, non-colliding island without understanding PLMNs or IP planning.

## Decisions

### D1 — One file is the island: `island.yaml`

Every island is fully described by a single signed config file: island name, country, node class(es), all allocations (below), and the association's public keys. **Every** generated config (Open5GS, srsRAN, DNS, Matrix, WireGuard, LIS geometry) derives from it — no hand-edited per-service files. Regeneration is idempotent: `island-init render` after any change. This file *is* the turnkey mechanism, and it ships in the node OS image work (WBS 2.1).

### D2 — A public allocation registry, dn42-style

A git repository (`registry/`) holds one small file per island, allocated first-come by pull request — the same lightweight commons model dn42 uses for ASNs/prefixes and amateur mesh networks use for addressing. Registered per island:

| Allocation | Plan | Collision it prevents |
|---|---|---|
| Island ID | short slug + per-deployment PKI root fingerprint (RFC-0001 D4) | naming, trust, overlay membership |
| PLMN | **MCC 999 + a registry-allocated MNC per island** (ITU designates MCC 999 for private networks; no license or assignment needed for the MCC itself — amended 2026-09-15 from "shared project MNC" because inter-island roaming must be standard inter-PLMN roaming via SEPP/N32, see RFC-0003 D1 amendment; upstream Open5GS's own roaming examples use `999-70`) <!-- VERIFY: national stance on MCC 999 use per launch country; MNC-space policy once islands number in the hundreds --> | broadcast identity and roaming; lab-only `001/01` never leaves the lab |
| IMSI block | `999` + MNC + island number (3–4 digits) + subscriber space | roaming subscriber identity (3.3 depends on this) |
| UE prefix | island-unique IPv4 prefix carved from a project supernet (e.g. CGNAT `100.64.0.0/10` space) + an IPv6 ULA /48 | home-routed roaming traffic, inter-island routing |
| Overlay address + WG pubkey | island-unique overlay endpoint identity | the federation mesh itself |
| Realm / server names | `<island-id>.islands.arpa`-style realm for Diameter/Matrix/DNS <!-- VERIFY: pick a domain the project actually controls vs. .arpa-style internal --> | Diameter peering, Matrix federation |
| TAC range | per-island block | mobility management across neighboring islands |

`.island` stays as a **local-only convenience alias** (like `.local`): valid on-island, never routed between islands; inter-island names always use the unique island domain.

Offline-first constraint: allocation happens **once, at association founding** (peacetime, like PSP onboarding in RFC-0004) — after that the island never needs the registry to operate. Pre-allocated blocks for rapid-deploy kits (Class B/C) are reserved by responder orgs in advance.

### D3 — RF non-interference is survey + convention, not coordination infrastructure

Neighboring islands on the same band are a physical-layer question: the install survey (already mandated by RFC-0004 D3 for LIS geometry) records EARFCN/NR-ARFCN, PCI, and power per cell into `island.yaml`; `island-init` assigns PCIs from island-number-seeded offsets so accidental PCI collision between registry neighbors is unlikely by construction. Actual RF coordination between physically adjacent islands is a human step in the playbook (they are, after all, neighbors) — no global radio controller. Licensing stays per-association per country (WBS 0.4); the registry records what each island holds, it does not grant spectrum.

### D4 — `island-init`: the turnkey startup wizard

Part of the node OS image (WBS 2.1). *Amended by RFC-0006: the operator-facing form of this wizard is the web Island Console; `island-init` is its backend and renderer, and remains usable headless.* Flow: ask island name + country + class → fetch or accept the registry allocation file → generate keys → write `island.yaml` → render all service configs → run the island's own acceptance checks (the verify scripts) → print the drill card. Target: **a volunteer reaches a verified, non-colliding island in under 30 minutes without editing any config file.** The current lab conventions become simply the output of `island-init --lab` (test PLMN, `10.45.0.0/16`, `.island`-only), so nothing about today's stack/core changes yet.

## Consequences

- CLAUDE.md's network conventions get annotated as **lab profile** values; production values come from `island.yaml`.
- WBS 2.1 grows the `island-init` deliverable; WBS 3.3's roaming design (RFC-0003) can now assume collision-free IMSIs, prefixes, and realms as a precondition.
- A `registry/` repo becomes part of the org scaffolding (WBS 0.3 follow-up).
- The federation overlay gets its membership model "for free": being in the registry with a valid key *is* being join-able (trust ceremonies per RFC-0003 still gate actual peering).

## Open questions

1. MCC 999 acceptance: technically designated for private networks, but per-country regulator stances vary — needs the WBS 0.4 matrix treatment. Fallback: per-country shared PLMNs where a regulator offers them.
2. Registry governance: who merges allocation PRs once the project isn't one person (ties to eventual governance doc).
3. IPv6-first vs dual-stack for the inter-island plan (ULA /48 per island is clean; 4G UE support is the constraint).
4. How much of `island.yaml` is public in the registry vs. private to the association (site coordinates are sensitive in some crisis contexts).
