# Starlink profile (1.4-d) `[HW]`

**Status: open.** TASKS.md 1.4-d's own acceptance criterion is "measured
(not estimated) power figures and failover timings from a real
terminal, or the task stays open" — no Starlink terminal is attached to
any machine this has been developed on, so per
[CLAUDE.md](../../CLAUDE.md) ("never mark an `[HW]` task done based on
simulation") this stays a paper design. Nothing below is a substitute
for that measurement; it's the profile to measure *against* once a
terminal is available. See [../../STATUS.md](../../STATUS.md).

## CPE bypass mode

<!-- VERIFY: current Starlink hardware options, bypass-mode mechanics,
roam plan terms — Starlink's own hardware/firmware/plan lineup changes
without this repo's involvement. -->

A stock Starlink router does its own DHCP/NAT and presents a private
address to anything downstream — a second layer of NAT this island
doesn't want stacked in front of `wan-edge`'s own uplink handling.
"Bypass mode" (Starlink's own documented term, at least as of this
writing) has the dish hand a routable address directly to whatever's
plugged into it, which is what lets it slot into the *exact same* model
`wand.py` already uses for every other uplink (`config/uplinks.yaml`):

```yaml
  - name: starlink
    self_ip: <DHCP-assigned, from the dish in bypass mode>
    gateway: <the dish's own gateway address in bypass mode>
    bandwidth_kbit: <per the active plan tier — VERIFY>
```

No code change needed in `wand.py` itself for this — `find_iface`,
`setup_policy_routing`, the link+path health check, and `setup_qos` are
all already generic over "some interface with some self_ip/gateway"
(see [README.md](README.md#the-failover-model)). The only real-hardware
work is wiring the physical dish into whatever NIC becomes this
uplink's interface and confirming DHCP actually hands back a routable
(non-CGNAT) address in bypass mode — which is exactly the kind of thing
that needs a real terminal to confirm, not something safe to assume from
a spec sheet.

## Power draw

Node-hw's own power budgets ([../../node-hw/power/README.md](../../node-hw/power/README.md))
are explicit that every number "must eventually come from measurement"
and its "Measured budgets" table is deliberately empty until hardware
exists — Starlink's own draw is no exception, and doesn't get a number
here either.

What's already decided, from the BOMs:

- **Class B** ([../../node-hw/class-b-vehicle/BOM.md](../../node-hw/class-b-vehicle/BOM.md),
  item 6): Starlink Mini + mount, against a ~150 W total budget — plenty
  of headroom on paper.
- **Class C** ([../../node-hw/class-c-backpack/BOM.md](../../node-hw/class-c-backpack/BOM.md)):
  does **not** list Starlink at all, against a ≤30 W total budget.
  Starlink Mini's own published draw <!-- VERIFY current spec --> is a
  meaningful fraction of that entire budget on its own, before compute
  or radio — TASKS.md's own step 1 asks this profile to cover "Starlink
  Mini on Class C power budget" specifically, and the honest answer
  until measured is: **marginal at best, likely infeasible as a
  continuously-on backhaul at Class C**, only plausible as an
  intermittent/opportunistic add-on (dish powered only when backhaul is
  actually wanted, not held up continuously) — a real terminal and a
  real power meter are what turn "likely infeasible" into a fact one way
  or the other.

## Behavior under obstruction/outage

<!-- VERIFY: current constellation/obstruction behavior — LEO handoffs,
typical outage duration and frequency, change over time as Starlink's
own constellation and firmware evolve. -->

Two separable claims:

1. **The failover mechanism itself is already verified**, independent of
   which real-world uplink sits behind it: `wand.py`'s health check
   (link + path, every ~3s) and policy-routing failover measured 2-3s in
   1.4-a's own `verify.sh`, and the same mechanism correctly reacted to
   a real, host-level WAN drop in 1.4-b's `unplug-test.sh` — see
   [README.md](README.md#verification-performed). A Starlink uplink
   going unhealthy (obstruction, an outage, a firmware update reboot)
   would be handled by the exact same code path already exercised
   there, not new logic.
2. **What that mechanism actually experiences against a real Starlink
   terminal — how often, how long, whether a brief LEO handoff even
   registers as "unhealthy" before self-healing — is not known and
   isn't claimed here.** That's squarely what "failover timings from a
   real terminal" in the acceptance criterion means, and squarely what's
   missing.

## The dependency, recorded honestly

Per CLAUDE.md ("never overclaim security") and TASKS.md 1.4-d step 2:

- Starlink is a **third-party commercial service**, not something this
  project operates or controls. It can be geofenced to specific
  countries/regions, its pricing/plan terms can change, and its
  availability during a real crisis is not guaranteed — regulatory
  action, an outage on Starlink's own side, or a plan/roaming
  restriction can all remove it without this island's operators having
  any recourse. RFC-0001 D5 exists precisely so that losing it changes
  *reach*, never *function*.
- **Second-provider options** (Eutelsat OneWeb resellers, at least as of
  this writing <!-- VERIFY current availability, pricing, and regional
  coverage -->) exist and should be evaluated per-deployment rather than
  assumed interchangeable with Starlink — different terminal hardware,
  different bypass-mode mechanics (or none), different plan terms. A
  second uplink entry in `uplinks.yaml`, at a lower failover priority or
  higher, is the same config-only change either way (see "CPE bypass
  mode" above) — nothing about `wand.py` itself is Starlink-specific.

## Closing this task

Requires physical access to a real Starlink terminal (any current
model) in bypass mode, wired into a `wan-edge`-equivalent node, with a
power meter on its supply, per CLAUDE.md's `[HW]` handling — tracked as
open here until that happens, not simulated toward "done."
