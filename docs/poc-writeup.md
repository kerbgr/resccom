# M1-sim: a private cellular network, proven in software, before a single antenna

**WBS 1.5.** This is the public post announcing ResCCOM's first milestone —
**M1-sim**, as [ROADMAP.md](../ROADMAP.md) defines it: *"a simulated UE
attaches to Open5GS and uses NOMAD + Matrix with all backhauls down."*
Everything below is software only, reproducible on a laptop, no radio
hardware or spectrum license involved. Every claim here cites the verify
script that produced it — no estimates, per
[CLAUDE.md](../CLAUDE.md)'s "don't invent results" rule and
[SECURITY.md](../SECURITY.md)'s no-overclaiming rule, which applies to this
document hardest of all.

## What ResCCOM is

ResCCOM answers *"how do a thousand people reach a server, and each
other, when the towers are down?"* The bet: **the phone people already
carry is the terminal.** A ResCCOM node runs Open5GS (5G SA + 4G EPC,
dual-mode) and srsRAN for the radio side, so an ordinary smartphone with a
provisioned SIM attaches the way it would to any commercial network — no
app, no special hardware. Behind that core sit local services — an
offline knowledge library (currently Project NOMAD), E2EE messaging
(Matrix), voice/video (Jitsi), a local DNS + status portal — that keep
working with **zero internet**, plus opportunistic backhaul (Starlink,
point-to-point radio to other islands) that only ever *adds* reach and is
never required. Full rationale:
[rfcs/rfc-0001-architecture.md](../rfcs/rfc-0001-architecture.md).

This is infrastructure for disasters, protracted crises, and off-grid
communities, deployed and owned by local associations — not a product this
project operates for anyone. It is not covert, not undetectable, and not a
defense against a state-level adversary; see
[SECURITY.md](../SECURITY.md) for exactly what threat model it does target.

## What provably works today

### The island itself: one command, then verified end-to-end

```bash
git clone https://github.com/kerbgr/resccom.git
cd resccom
./island.sh up
stack/services/verify.sh
```

`island.sh up` brings up, in order, the Open5GS core and every service
(local DNS, NOMAD/Kiwix, Matrix/Element, Jitsi, the status portal) —
generating every secret and self-signed cert on first run from the
templates already committed in the repo. `stack/services/verify.sh` then
drives the UERANSIM simulator through the full milestone scenario: UE
registration, `.island` DNS resolution, real Kiwix content from
`library.island`, a real E2EE Matrix message (decrypted client-side,
confirmed as ciphertext server-side), a real Jitsi audio call with live
bidirectional RTP, and the portal's live status page.

Measured, not estimated ([QUICKSTART.md](../QUICKSTART.md), run
2026-09-12, clean clone, images already cached, macOS/Apple Silicon under
Docker Desktop emulation):

| Step | Wall time |
|---|---|
| `./island.sh up` | 1m 57s |
| `stack/services/verify.sh` | 42s |
| **Clone → fully verified** | **~2m 40s** |

Evidence: [QUICKSTART.md](../QUICKSTART.md) (0.3-c).

### Backhaul: three tests that break the network for real and confirm it keeps working

RFC-0001's design rule D5 — *"unplugging every WAN changes reach, never
function"* — isn't a slogan here; three scripts in
[stack/backhaul/](../stack/backhaul/) put it to a real, measured test.

**1. Failover between simulated uplinks** ([`verify.sh`](../stack/backhaul/verify.sh),
1.4-a). Three uplinks (fixed line > satellite > PtP,
priority order), each a genuinely independent path to the real internet.
Killing the active one, then the next, then the last:

| Event | Failover time |
|---|---|
| Kill `fixed` (active) | failed over to `satellite` in **3s** |
| Kill `satellite` (new active) | failed over to `ptp` in **3s** |
| Kill `ptp` (last one) | active uplink → `None` in **2s** |
| Reconnect all three | failed back to `fixed` in **2s** |

With every uplink dead, `stack/services/verify.sh` was re-run in full and
**all checks still passed** — the island doesn't notice backhaul is gone,
by design.

**2. The literal unplug test** ([`unplug-test.sh`](../stack/backhaul/unplug-test.sh),
1.4-b). This one doesn't simulate anything: it inserts a
real, host-level firewall rule (`DOCKER-USER` iptables chain) that drops
every standing island component's route to the real internet, at the
routing level — the first *literal* "unplug the cable" test in this repo.
The drop list is guard-verified complete on every run (a parser
cross-checks it against every fixed-address, WAN-capable container all
five compose files declare — a guard that has already caught real gaps
twice — see stack/backhaul/README.md). With real WAN genuinely dropped
for all of them — Jitsi's media components included, mid-audio-call:

- `stack/core/verify.sh` passed in full, unaffected.
- `stack/services/verify.sh` passed in full — including the real E2EE
  Matrix message and the real Jitsi audio call — with one check now
  reading **"WAN reported as 'down', matching reality"** instead of
  assuming WAN is up, the first time this project produced that line for
  real rather than asserting it.
- WAN reachability was confirmed genuinely gone within **2s** of dropping
  the rule, and genuinely restored within **2s** of removing it.

**3. QoS under a constrained link** ([`qos-test.sh`](../stack/backhaul/qos-test.sh),
1.4-c). With the uplink capped at 2 Mbit (the lab-profile
default) and a real 6 MB bulk transfer saturating it:

| Scenario | Baseline avg | Under bulk load, avg (max) |
|---|---|---|
| Unclassified (no QoS) | 0.5ms | **23.6ms** (65.5ms) |
| Classified (real QoS active) | 0.5ms | **0.4ms** (0.7ms) |

With no traffic classification, Matrix-tier round trips degraded ~47x
under load. With `wand.py`'s real HTB+SFQ classification restored via an
actual failover cycle (not hand-added), they were statistically
indistinguishable from an unloaded baseline — measured, not asserted,
per TASKS.md 1.4-c's own acceptance text.

Full transcripts for all three: each script's own output on a clean run,
plus the "Verification performed" section in
[stack/backhaul/README.md](../stack/backhaul/README.md).

### Federation: two islands, real inter-PLMN roaming (sim path, milestone M3)

[`stack/federation/two-island.sh`](../stack/federation/two-island.sh) runs
two full ResCCOM islands — distinct PLMNs (001/01 and 999/70), each its
own Open5GS core, cross-peered over a real WireGuard overlay with
Open5GS's own SEPP/N32 security-association mechanism — on one host, and
proves a subscriber from one island (the "home" island) can roam onto the
other (the "visited" island) and be served *by the visited island*, not
tunneled home, exactly as RFC-0003 D1 specifies. `two-island.sh roam
--ue oai`, run twice on 2026-09-17, both runs identical:

- The roaming UE gets a real `Registration Accept` on the visited
  island's cell, authenticated at home (K never left the home island —
  confirmed by the home island's SEPP log showing the forwarded
  authentication, and the visited island's own AUSF/UDM logging nothing
  for the roaming subscriber at all).
- The visited island's own SMF/UPF anchor the PDU session and hand out
  the address (Local Breakout, not Home-Routed) — the roaming subscriber
  gets an IP in the *visited* island's own UE pool.
- A real ping from the roaming UE to the visited island's services
  subnet completes with **0% packet loss**, served by the visited
  island's own UPF.
- What makes this possible: Open5GS's visited-side policy function (PCF)
  needs a policy record for the roaming subscriber in its own local
  database to authorize the session at all — it has no way to fetch this
  cross-island on its own. The home island exports that subscriber's
  *policy only* (no key, no OPc, no credential of any kind — enforced in
  code, not just by convention) and the visited island imports it as a
  marked record before the UE attaches
  ([sim-tools README, "Inbound roaming"](../sim-tools/README.md#inbound-roaming-policy-only-records-wbs-33-c-v2h)).
- Both runs tore down cleanly: the home island's own tree, core, and
  already-attached local subscriber were all confirmed undisturbed.

This is the sim path (`[SIM]`, CLAUDE.md): OpenAirInterface's nrUE, not a
real phone, and both islands run as containers on one Docker host, not
on separate real hosts. `[HW]` roaming (a real phone doing standard PLMN
selection, two islands on separate real hosts with a real WAN link
between them) is untried. 4G inter-realm roaming (WBS 3.3-d) is
untested. Full evidence, both runs' exact log lines, and the road to
this result (five prior tasks, each closing one real blocker in turn):
[stack/federation/TASKS.md](../stack/federation/TASKS.md) 3.3-c v2 through v2h.

### Partition drill: a roamer, the link cut, and the honest limit (sim path, WBS 4.1)

[`stack/federation/two-island.sh drill --ue oai`](../stack/federation/two-island.sh) takes the M3 state above — a subscriber of one island roaming onto the other, served by the visited island — and cuts the inter-island link under it, to measure what actually survives a partition. It holds both islands up through the whole sequence and tears down only at the end, leaving the home island's own core untouched. Measured on 2026-09-17:

- **(a) Roamer attached (baseline).** Registers on the visited island, address from the visited island's own pool, breakout ping 0% loss, authentication forwarded home over SEPP.
- **(b) Link cut, established session survives.** With the visited island's `wg-overlay` stopped (both SEPP N32 ports confirmed unreachable), the roamer's existing PDU session keeps passing user-plane traffic: the breakout ping to the visited services subnet stayed at 5/5 packets, 0% loss. The session is anchored on the visited island's own UPF, so nothing about it needs the home island.
- **(c) Fresh registration fails, honestly.** With the link still down, the roamer's phone re-registers from scratch: the visited AMF logged `Cannot receive SBI message` (504) for the roamer and no PDU session came up. The visited island holds no key for the roamer (only a policy record), so a fresh authentication must reach the home island, and it cannot. This is the measured limit of roaming during a partition.
- **(d) Guest provisioning works.** With the link still down, the visited association issues a local guest identity (a normal local subscriber in its own block, `resccom-sim sub add`) for the same handset: registered with an address from the visited UE pool, breakout 0% loss, anchored by the visited island's own core. This is the fallback for anyone who cannot be authenticated.
- **(e) Link restored, roamer recovers.** on restarting the visited island's `wg-overlay`, both SEPP N32 ports answered again 1 second later and the original roamer re-registered through its home island 7 seconds after the restart, breakout back to 0% loss.

The first cut of this drill used `docker network disconnect` to drop the link and read it down from a single N32-c probe; that left an asymmetric partition in which the N32-f port still forwarded a real authentication home, so step (c) did not test what it claimed. The drill now stops the `wg-overlay` container outright and gates on both N32 ports being unreachable before proceeding. Recorded here as measured, per [CLAUDE.md](../CLAUDE.md).

This is the sim path: OpenAirInterface's nrUE, two islands as containers on one host, a simulated inter-island link. Matrix federation across a partition (RFC-0003 D4) is out of scope and not enabled in the shipped configuration — a separate task, [stack/federation/TASKS.md](../stack/federation/TASKS.md) 4.1-b. Operator-facing walkthrough: [playbook/drills.md](../playbook/drills.md).

## What is honestly not done

- **Real RF (WBS 1.2-b/c/d, `[HW]`).** Everything above runs over
  UERANSIM's simulated radio or srsRAN's ZMQ virtual radio — no antenna
  has transmitted anything. The 4G ZMQ virtual-radio path (srsRAN eNB+UE
  over ZMQ against the same Open5GS EPC) is up and passes
  [`stack/ran/verify-4g.sh`](../stack/ran/verify-4g.sh); the 5G software
  path passes via OpenAirInterface's gNB + nrUE over its RF simulator
  ([`stack/ran/verify-5g-oai.sh`](../stack/ran/verify-5g-oai.sh)) after
  the srsRAN ZMQ attempt ended in a documented upstream-bug negative
  finding. SIM programming, first real-phone attach over
  an SDR, and the low-cost-radio variant all need physical hardware (a
  USRP B210 or similar, programmable SIMs, a PC/SC reader) plus a test
  license or shielded enclosure — see
  [stack/ran/TASKS.md](../stack/ran/TASKS.md)'s legal warning. This isn't
  simulated toward "done": per [CLAUDE.md](../CLAUDE.md), `[HW]` tasks stay
  open until real hardware evidence exists.
- **Starlink backhaul (WBS 1.4-d, `[HW]`).** The failover mechanism itself
  is already proven above, against three uplink types; what a real
  Starlink terminal actually experiences (obstruction behavior, real
  power draw against a Class C ≤30W budget) is not known and isn't
  claimed. The paper design is ready to measure against:
  [stack/backhaul/starlink-profile.md](../stack/backhaul/starlink-profile.md).
- **Everything else past Phase 1** — node hardware builds, the full
  security/identity baseline (WBS 3.4, PKI), 4G inter-realm roaming
  (3.3-d), Matrix federation across the overlay and its partition
  tolerance (4.1-b, deliberately not enabled yet), PEMEA/112 interop — is
  `open` in [STATUS.md](../STATUS.md); none of it is claimed here. (5G
  inter-PLMN roaming, milestone M3, and the roaming partition drill, WBS
  4.1, are the federation results now proven — see above.)

## Where to help — no radio hardware needed

- **Reproduce the PoC on your own machine** and file a
  [reproduction report](https://github.com/kerbgr/resccom/issues/new?template=repro-report.yml)
  for every step that didn't match this doc — the highest-value
  contribution right now (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
- **WBS 1.2-a (5G ZMQ gNB)** — the 4G half above is the template; the 5G
  half is open.
- **WBS 3.2 (`sim-tools`)** — a plain Python CLI over pySim + the Open5GS
  subscriber DB, no RF anywhere: [sim-tools/TASKS.md](../sim-tools/TASKS.md).
- **Docs that need someone who isn't the author** — the
  [spectrum matrix](spectrum/README.md) and the
  [community playbook](../playbook/README.md) need contributors who know
  their own country's rules and volunteer structures.
- **If you have an SDR** (USRP B210, LimeSDR) — WBS 1.2-b/c/d in
  [stack/ran/TASKS.md](../stack/ran/TASKS.md) need independent
  reproduction, always under a test license or shielded enclosure.

Every task above carries a WBS code and acceptance criteria you can check
yourself — see [ROADMAP.md](../ROADMAP.md) for the full map and
[CONTRIBUTING.md](../CONTRIBUTING.md) for the ground rules (upstream-first,
no forks, no security overclaiming).
