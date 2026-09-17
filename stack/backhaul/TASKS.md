# stack/backhaul — TASKS (WBS 1.4)

Goal: opportunistic WAN that *adds reach without ever being required*. Supported uplinks: Starlink (or any satellite CPE presenting Ethernet/DHCP), fixed line, inter-island PtP. Design rule (RFC-0001 D5): unplugging every WAN changes reach, never function.

Depends on: core 1.1-c and services 1.3-a (DNS behavior under WAN loss).

---

## 1.4-a — WAN abstraction & failover

**Steps**
1. Define the node's WAN model: any number of uplink interfaces, priority-ordered (e.g. fixed > satellite > PtP), health-checked (ping + DNS probe per uplink).
2. Implement with boring Linux tooling (systemd-networkd + routing tables, or mwan3-style scripts — choose, justify in README).
3. State exposed at a local endpoint for the portal's status display (services 1.3-e).

**Acceptance**
- With two simulated uplinks (netns/veth is fine), killing the active one fails over within 30 s; killing both leaves all island services fully working (re-run services acceptance checks).

## 1.4-b — The unplug test (standing CI-of-the-island)

**Steps**
1. `unplug-test.sh`: drops all WAN routes, runs the full M1-sim acceptance set (core + services), restores, verifies recovery + failback.

**Acceptance**
- Passes on a node with WAN; documented as the test every deployment runs at handover and every drill starts with.

## 1.4-c — QoS: emergency traffic wins

**Steps**
1. Classify and prioritize on constrained uplinks: (1) PEMEA/112 flows [Phase 4], (2) Matrix + operational coordination, (3) everything else. tc/cake-based; document the shaping choices.

**Acceptance**
- With the uplink artificially constrained (e.g. 2 Mbit), a bulk download does not starve Matrix message delivery (measure and record latency).

## 1.4-d — Starlink profile `[HW]`

**Steps**
1. Document the Starlink-specific profile: CPE in bypass mode, power draw measured per node class, behavior under obstruction/outage; Starlink Mini on Class C power budget. <!-- VERIFY: current Starlink hardware options, bypass-mode mechanics, roam plan terms -->
2. Record the dependency honestly in the doc: third-party service, can be geofenced/billed/degraded; second-provider options noted (Eutelsat/OneWeb resellers). <!-- VERIFY current availability -->

**Acceptance**
- Measured (not estimated) power figures and failover timings from a real terminal, or the task stays open.
