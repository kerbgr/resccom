# Landscape: neighboring projects and the gap (scanned 2026-09)

Summary: every layer of ResCCOM exists somewhere; nobody has assembled them, and the two most distinctive capabilities (inter-island roaming, 112/PEMEA interop on community networks) exist nowhere in open source.

## Building blocks (healthy — consume as upstream)

| Project | Role for us | Status at scan |
|---|---|---|
| [Open5GS](https://open5gs.org) | The core (RFC-0001 D1) | Active |
| [srsRAN](https://www.srsran.com) | RAN, SDR + ZMQ virtual radio | Active |
| [OpenAirInterface](https://openairinterface.org) | RAN alternative if srsRAN blocks | Active |
| [pySim](https://osmocom.org/projects/pysim) | SIM programming (sim-tools) | Active |
| [Project NOMAD](https://github.com/crosstalk-solutions/project-nomad) | Services/knowledge layer | Active |
| [Kiwix](https://kiwix.org) / Kolibri | Content (via NOMAD) | Active, mature |
| Matrix (Synapse/Dendrite) | Messaging + federation | Active |

## Nearest neighbors (validate the niche; mostly stalled)

- **[CoLTE](https://github.com/uw-ictd/colte)** (UW) — closest ancestor: Open5GS EPC + billing GUI for community LTE (Indonesia, Oaxaca deployments). Rural-ISP economics focus, LTE-era, quiet lately. Study; possibly collaborate.
- **[Rhizomatica](https://www.rhizomatica.org/about/)** — invented community cellular (Mexico, TIC A.C.); [RCCN stack unmaintained](https://github.com/Rhizomatica/rccn) (2G), org pivoted to HF (HERMES). Governance lessons.
- **[Magma](https://github.com/magma/magma)** — LF open core; momentum faded ([charmed-magma archived 2023](https://github.com/canonical/charmed-magma)). Cautionary tale for big-consortium cores; Open5GS bet reaffirmed.
- **[Ukama](https://www.ukama.com)** — open private-cellular hardware by the OpenCellular founder; crowdfunding stalled. **[OpenCellular](https://github.com/Telecominfraproject/OpenCellular)** — dormant. The open-hardware promise remains unmet (our node-hw lane).

## Commercial "network in a box" (proves demand; closed)

Athonet/HPE tactical backpack, VVDN, Firecell, Tidalwave — exactly our Class B/C concept, sold into defense/PPDR (multi-billion market). None open, none community-priced, none content-integrated. Use as demand evidence in launch material.

## Mesh / off-grid messaging (booming; complementary tier, don't compete)

[Meshtastic](https://meshtastic.org) (thriving; carried real traffic in the 2025 Iberian grid failure), [Reticulum](https://reticulum.network) (cryptographically serious), MeshCore; Serval dormant. Integration path: Meshtastic gateway on every node as the license-free long-range text tier.

## Community Wi-Fi networks (governance models, allies, pilot partners)

guifi.net, Freifunk, Althea, LibreMesh/LibreRouter, Sarantaporo.gr — the association playbook borrows their legal/governance patterns (playbook §1); their communities are WP 5.1 pilot candidates.

## Institutional disaster telecom (potential adopters, not competitors)

ETC (WFP-led cluster), Télécoms Sans Frontières, Vodafone Foundation Instant Network — deploy proprietary kit today; an open, cheaper, content-integrated alternative is a story to bring to them at v1.0.

## The white space ResCCOM claims

1. Maintained open-source disaster-oriented private 4G/5G kit (between raw components and proprietary tactical backpacks).
2. Cellular access + offline services (NOMAD) as one deployable unit.
3. Inter-island subscriber roaming for association-owned networks — exists nowhere open.
4. 112/PSAP (PEMEA) interop from community networks — exists nowhere, open or commercial-community.
5. Open tiered hardware reference designs with honest power engineering — OpenCellular's abandoned promise.
