# Deployment model: citizen-to-citizen, through associations

Context: rising insecurity sentiment in Europe (Baltic subsea-cable sabotage, GPS jamming, national preparedness campaigns like Sweden's MSB booklet and Finland's 72-hour doctrine) creates real demand for citizen-built resilient comms — especially in the Nordics.

## Why "association", not "individual"

Wi-Fi, LoRa, and the services stack are individually deployable today. The **cellular layer legally is not**: it needs a spectrum authorization, which an individual can't practically hold. The deployment unit is therefore a local association — a proven European pattern (Freifunk Vereine, guifi.net commons, Danish antenna associations, Sarantaporo.gr):

- The association holds the license ([spectrum matrix](spectrum/README.md)), owns the anchor node, keeps subscriber keys.
- Members host relays, hold SIMs, staff drills ([playbook](../playbook/README.md)).
- The Nordics are the *easiest* start: Finland, Germany, UK, NL (and likely more <!-- VERIFY -->) have local-licensing regimes a small entity can navigate; and volunteer preparedness structures (Sweden's frivilliga försvarsorganisationer incl. FRO, Finnish preparedness associations, amateur-radio emergency groups) are natural hosts with existing legitimacy.
- **Peacetime mode is what keeps it alive**: community Wi-Fi + offline library + local chat between crises; a network first powered on during a disaster will fail.

## Vendor accelerators under RFC-0001 D10 (never dependencies)

- **Tesla Powerwall (donated):** near-ideal Class A power (integrated solar inverter, islanding; a 300–500 W anchor runs 1–2 days per unit on battery). Constraints: operate in "dumb mode" (no Tesla-cloud dependency, treat as AC source), and keep the open LiFePO₄ design as the repairable reference — a sealed proprietary unit can't be fixed in month 8 of a crisis. Details: [node-hw/power/](../node-hw/power/README.md).
- **Starlink:** the designed opportunistic backhaul (works at high latitudes; Mini fits Class C power budgets). It makes islands "inline": internet when available, federation transport, the path by which PEMEA/112 reaches real PSAPs. Constraints: one company's service (can be degraded, geofenced, billed — Ukraine showed both the value and the risk; Baltic RF interference is real); so multi-backhaul always (fixed line, PtP, second satellite provider — Eutelsat/OneWeb now, IRIS² later <!-- VERIFY availability -->), and the island is 100% functional with Starlink unplugged (the unplug test, stack/backhaul 1.4-b).

## The pitch, in one paragraph

ResCCOM turns diffuse civic anxiety into concrete, legal, useful infrastructure: a neighborhood association that owns its own cell, its own library, its own chat — running and drilled *before* anything breaks, powered by sun and batteries, satellite-linked when possible, and reachable by 112 when it matters. That framing (preparedness infrastructure, not disaster gadget) is also what EU civil-protection and MSB-style agencies fund.
