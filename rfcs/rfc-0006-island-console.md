# RFC-0006: Island Console — map-based configuration and coordination

**Status:** Draft · **Date:** 2026-09 · **Refines:** RFC-0005 D4 (turnkey startup), RFC-0004 D3 (LIS geometry), RFC-0003/WBS 4.2 (federation, data sharing) · **Implements as:** WBS 2.1

## Context

Project NOMAD ships a configuration UI (its Command Center); ResCCOM today ships only CLIs (`island.sh`, `resccom-sim`) and RFC-0005 D4 defined the turnkey startup wizard, `island-init`, as another CLI. That is the wrong shape for the people RFC-0001 D7 says will run this: association volunteers and local operators. Two of the hardest operator tasks are inherently **spatial** — planning where cells go and what they cover, and coordinating with neighbouring islands — and a third, choosing what data islands share, is inherently a **policy** decision that should not require editing YAML.

## Decisions

### D1 — The Island Console is the primary operator interface; the CLI remains for automation

A web application served by the node (`console.island`, next to the portal), offline-first, no external assets. It is an **editor over `island.yaml`** (RFC-0005 D1) — never a second configuration store. Every change the console makes is a change to that one signed file, followed by `island-init render`; the CLIs read the same file. Headless and scripted use keeps the CLI; humans get the console. First-run of the console *is* the RFC-0005 wizard.

### D2 — Map-based coverage designer, with predicted and measured kept visibly distinct

Built on the island's **own offline map tiles** — the ProtoMaps data NOMAD already serves at `maps.island` (upstream-first: reuse, don't bundle a second map stack). The operator places sites, sets per-cell antenna height/azimuth/power/band, and the console renders coverage in two layers that are never allowed to look alike:

| Layer | Source | Treatment |
|---|---|---|
| **Predicted** | A simple, documented propagation model (e.g. Hata/COST-231 class; terrain-aware only if an offline DEM is present) | Always labelled as a model estimate, with the model named; never shown on user-facing pages as coverage fact |
| **Measured** | Field points: drive/walk tests, phone signal reports uploaded by operators | The only layer the portal may present to the public as "where this network works" |

This is CLAUDE.md's "don't invent results" rule made visual: prediction is a planning aid, measurement is the claim.

### D3 — The console produces the survey data the rest of the design already demands

Site coordinates, cell geometry, PCI/EARFCN plan (RFC-0005 D3), and coverage polygons written into `island.yaml` are exactly what the island LIS tier 2 needs (RFC-0004 D3) and what the playbook's install survey step was going to collect by hand. The console makes that survey the natural by-product of planning the network, not a separate chore that gets skipped.

### D4 — Coordination and data-sharing view

Neighbouring islands (from the registry, RFC-0005 D2) appear on the same map with their **voluntarily shared** coverage polygons, so adjacent-island RF coordination (RFC-0005 D3) is a conversation over a shared picture. Federation settings become explicit, reviewable policy toggles instead of config: which content libraries replicate (WBS 4.2), which Matrix rooms federate, whether incident records forward (RFC-0004 D2), and with what priority on constrained links (WBS 1.4-c classes). Overlay link state is shown live.

### D5 — Safety and scope boundaries

- Operator authentication is association-held; every change is logged with who/when (lab profile: a SECURITY.md register row until per-deployment PKI, WBS 3.4).
- The console **never handles subscriber keys in the browser** — SIM provisioning stays in `resccom-sim` (programming needs the physical reader anyway).
- What is shared between islands is opt-in per item; site coordinates can be sensitive in some crises (RFC-0005 open question 4) and default to *not shared*.
- No feature that exists to hide the network (RFC-0001 D8). Coverage visualisation is for planning and honesty, not concealment.

### D6 — Implementation constraints

Python backend (CLAUDE.md tooling language), lightweight browser front end, must render on a five-year-old Android browser like the portal. Map rendering via an offline-capable library reading local PMTiles/ProtoMaps data <!-- VERIFY: MapLibre GL + PMTiles offline bundling and licensing, no CDN at runtime -->. Ships in the node OS image (WBS 2.1) on Class A/B; Class C runs a trimmed read-only status/map view.

## Consequences

- RFC-0005 D4 is amended: `island-init` is the backend/renderer; the console is its face. The "verified island in under 30 minutes" target now applies to the console's first-run flow.
- WBS 2.1 grows the console as a deliverable; the playbook's survey step becomes a console workflow.
- A new tool boundary: `resccom-sim` (keys, SIMs) vs. console (everything else). Keep it.

## Open questions

1. Propagation model and offline terrain data source; how to keep predicted coverage honest at village scale without pretending to be a planning suite.
2. Measured-data ingestion: which phone-side export formats to accept, and whether a PEMEA-style app could contribute signal reports opportunistically (privacy first).
3. Sharing model for coverage polygons between islands: registry-published vs. peer-to-peer over the overlay.
4. Whether the console should also host the local incident desk from RFC-0004 D2, or that stays a separate operator surface.
