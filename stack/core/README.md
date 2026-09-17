# stack/core — Open5GS dual-mode 4G/5G core (1.1-a through 1.1-e)

Brings up a full Open5GS 5G Standalone core under Docker Compose: NRF, AMF,
SMF, UPF, AUSF, UDM, UDR, PCF, NSSF, BSF + MongoDB (1.1-a); a test
subscriber, manually or scripted (1.1-b); a UERANSIM gNB+UE rig that
verifies the 5G path end to end — the M1-core gate (1.1-c); and a 4G EPC
alongside it — MME, HSS, SGW-C, SGW-U, reusing the same SMF/UPF as
PGW-C/PGW-U (1.1-d). No radio hardware involved anywhere here — this is
the `[SIM]` path per [CLAUDE.md](../../CLAUDE.md).

## Prerequisites

- Docker Engine with Compose v2 (`docker compose`, not `docker-compose`).
- A Linux host (Debian 12+/Ubuntu LTS is the deployment target) is where
  this is meant to run. It was developed and verified on **macOS via Docker
  Desktop**, forcing `linux/amd64` — see "Known limitations" below.
- Outbound internet access to pull the pinned images the first time.
- `resccom-sim` on PATH (`pipx install ../../sim-tools`) for subscriber
  management (1.1-b / 3.2-b) — see "Scripted path" below and
  [sim-tools/README.md](../../sim-tools/README.md). Not needed for
  bring-up itself, only for loading/removing subscribers.

## Bring-up

```bash
cd stack/core
docker compose up -d
docker compose ps          # 14 of 16 containers report healthy (sgwc/sgwu
                            # have no TCP/HTTP port to healthcheck — see
                            # "4G EPC" below for how to check those instead)
docker compose logs amf | grep -i ngap
```

Expected AMF log line (confirms NGAP is listening):

```
[amf] INFO: ngap_server() [10.10.0.5]:38412 (../src/amf/ngap-sctp.c:61)
```

All containers reach `healthy` well inside 60 s on a clean host. Teardown:

```bash
docker compose down -v   # -v also drops the mongo-data volume (see 1.1-e)
```

## Subscriber management (1.1-b)

Adding a subscriber means writing one document to Mongo's `open5gs`
database, `subscribers` collection — that's all `open5gs-dbctl` and the
WebUI do under the hood. Both paths below use the same test IMSI/K/OPc:

- IMSI `001010000000001` (test PLMN `001/01` + MSIN `0000000001`, per
  [CLAUDE.md](../../CLAUDE.md))
- Key `465B5CE8B199B49FAA5F0A2EE238A6BC`, OPc
  `E8ED289DEBA952E4283B54E88E6183CA`, AMF `8000` — these are
  [UERANSIM's own published test vectors](https://github.com/aligungr/UERANSIM/blob/master/config/open5gs-ue.yaml),
  not a real subscriber's keys, safe to keep in version control.

Either path needs the `mongo` service running (`docker compose up -d
mongo`, or the whole stack).

### Manual path

Upstream's `open5gs-dbctl` (`open5gs/open5gs`, `misc/db/open5gs-dbctl`) is
a thin wrapper around exactly this `mongosh` command — fetching it
pinned to the same tag as our image and running it directly is the
manual path, no separate WebUI container needed for a single test
subscriber:

```bash
curl -O https://raw.githubusercontent.com/open5gs/open5gs/v2.8.0/misc/db/open5gs-dbctl
chmod +x open5gs-dbctl
DB_URI="mongodb://localhost:27017/open5gs" ./open5gs-dbctl add \
  001010000000001 465B5CE8B199B49FAA5F0A2EE238A6BC E8ED289DEBA952E4283B54E88E6183CA
```

That needs `mongosh` on the host and Mongo's port reachable at
`localhost:27017`, which this compose file does not publish by default.
The equivalent that needs neither — run the same insert through the
`mongo` container itself:

```bash
docker compose exec mongo mongosh --quiet mongodb://localhost/open5gs --eval '
db.subscribers.replaceOne(
  { imsi: "001010000000001" },
  { imsi: "001010000000001", schema_version: NumberInt(1),
    msisdn: [], imeisv: [], mme_host: [], mm_realm: [], purge_flag: [],
    slice: [{ sst: NumberInt(1), default_indicator: true, session: [{
      name: "internet", type: NumberInt(3),
      qos: { index: NumberInt(9), arp: { priority_level: NumberInt(8),
        pre_emption_capability: NumberInt(1), pre_emption_vulnerability: NumberInt(2) } },
      ambr: { downlink: { value: NumberInt(1000000000), unit: NumberInt(0) },
               uplink:   { value: NumberInt(1000000000), unit: NumberInt(0) } },
      pcc_rule: [], _id: new ObjectId() }], _id: new ObjectId() }],
    security: { k: "465B5CE8B199B49FAA5F0A2EE238A6BC", op: null,
                opc: "E8ED289DEBA952E4283B54E88E6183CA", amf: "8000" },
    ambr: { downlink: { value: NumberInt(1000000000), unit: NumberInt(0) },
             uplink:   { value: NumberInt(1000000000), unit: NumberInt(0) } },
    access_restriction_data: 32, network_access_mode: 0, subscriber_status: 0,
    operator_determined_barring: 0, subscribed_rau_tau_timer: 12, __v: 0 },
  { upsert: true }
);'
```

### Scripted path

The scripted path is now [`resccom-sim`](../../sim-tools/README.md) (WBS
3.2-b), the same CLI an association volunteer uses for real subscriber
management — there is only one implementation of "how a subscriber
document looks in Mongo and how to write it there", not a separate
one-off script for dev/test. The one-time `stack/core/load-subscribers.py`
this replaced was upsert-only and had no way to revoke a subscriber; it
has been removed (see `stack/core/TASKS.md` 1.1-b for its original spec,
still accurate history, and `sim-tools/TASKS.md` 3.2-b for what replaced
it).

```console
$ pipx install ../../sim-tools   # once; see sim-tools/README.md
$ docker compose up -d mongo     # or the whole stack

$ export RESCCOM_SIM_STORE=$(pwd)/.dev-subscribers.db.enc
$ export RESCCOM_SIM_PASSPHRASE=dev-only-ephemeral   # local dev store, gitignored, recreated at will
$ resccom-sim sub add --test --imsi 001010000000001 --if-missing
added 001010000000001
$ resccom-sim db sync --core-dir .
added=1 updated=0 unchanged=0 removed=0 (./mongo)
```

`db sync` is a full reconcile, not an upsert-only push: it upserts every
subscriber currently in the local `resccom-sim` store, keyed on `imsi`
(same `mongosh --eval` document shape as before, run through `docker
compose exec`), and then **deletes any Mongo subscriber document whose
IMSI is not in the local store**. That's what lets removing a subscriber
locally actually revoke its core access — see "Verified live" below.
Because it's a reconcile, running `db sync` twice with the same local
store leaves exactly one document, same as before:

```console
$ resccom-sim db sync --core-dir . && resccom-sim db sync --core-dir .
added=1 updated=0 unchanged=0 removed=0 (./mongo)
added=0 updated=0 unchanged=1 removed=0 (./mongo)
$ docker compose exec mongo mongosh --quiet mongodb://localhost/open5gs \
  --eval "db.subscribers.countDocuments()"
1
```

**`sub add --if-missing`, not `rm -f` the store first:** this dev store
(`.dev-subscribers.db.enc`, gitignored) is shared with `stack/ran`'s
verify rigs and `island.sh` — each adds only its own IMSI with
`--if-missing`, so the store stays the union of every rig's subscribers
rather than one rig wiping out another's when it syncs. See
[sim-tools/TASKS.md](../../sim-tools/TASKS.md) 3.2-e and
[stack/ran/README.md](../ran/README.md)'s 5G-alt writeup for the
multi-rig session this was found broken against.

Manage subscribers with `resccom-sim sub add|list|remove` (see
[sim-tools/README.md](../../sim-tools/README.md)) — never edit Mongo by
hand once you're using this path, since the next `db sync` will delete
anything it doesn't recognize from the local store. Real subscriber data
lives only in the local, encrypted-at-rest `resccom-sim` store; it is
never a checked-in file, so there is nothing to `.gitignore` by name the
way `subscribers.json` used to need — the root `.gitignore`'s `*.db.enc`
pattern covers the store file itself regardless of where it's created.

**Verified live** (this machine, 2026-09-13): with the M1 rig already
attached (`stack/core/verify.sh`, UE at `10.45.0.7`), removing the
subscriber locally and re-syncing, then forcing the UE to re-register,
produced an authentication failure instead of a successful attach; adding
it back and re-syncing restored a normal attach. Exact commands and log
lines are in
[sim-tools/README.md](../../sim-tools/README.md#verification-run-32-b-acceptance).

## UERANSIM verification rig (1.1-c) — the M1-core gate

```bash
./verify.sh
```

Brings up the core, loads the test subscriber, brings up a simulated
gNB + one UE (UERANSIM) against it, and checks: registration succeeds,
the UE gets an IP in `10.45.0.0/16`, local breakout works, and none of it
needed a WAN path. Exits non-zero on any failure. Verified passing (twice
in a row, including a re-run without teardown) on this machine.

Expected UE log line (confirms registration — this is upstream's current
wording, not the literal "Registration is successful" from older
versions):

```text
[nas] [info] Initial Registration is successful
```

To run gNB/UE against an already-running core instead of the full script:
`docker compose -f compose.yaml -f compose.sim.yaml up -d gnb ue`.

**Local breakout to the services subnet.** `stack/services` 1.3-a wired
this for real: `compose.yaml` defines `services_net` (`10.46.0.0/24`) and
attaches UPF to it at `10.46.0.2`, NAT'ing UE-sourced traffic there (see
the `ENABLE_NAT` comment on the `upf` service) — so it's UPF's actual
router path now, not a stand-in. `verify.sh` gives the UE a route to
`10.46.0.0/24` over its PDU session (nr-ue's PDU session only
auto-installs the route to its own assigned subnet) and pings UPF's real
address. This still isn't a substitute for `stack/services`' own
acceptance criteria (reaching an actual service behind that address) —
see [../services/README.md](../services/README.md).

**Offline-first, verified by construction, not by disconnecting a
cable.** `compose.yaml`'s `core_net` is `internal: true` — Docker itself
refuses any route out of it, so there is no WAN path for the "unplug the
default route" check to remove in the first place. `verify.sh` confirms
this directly (a core container's `curl` to a public IP fails to even
connect) rather than simulating an unplug that wouldn't have proven
anything stronger.

## 4G EPC dual-mode (1.1-d)

Adds MME, HSS, SGW-C, SGW-U alongside the 5G core. No changes were needed
to SMF or UPF — upstream's own sample configs already have them double as
PGW-C/PGW-U (SMF's `gtpc` server and UPF's `gtpu` server are shared,
protocol-generic interfaces regardless of whether the control plane
reaching them is AMF/5G or MME/SGW-C/4G), and HSS reads subscriber data
from the *same* `mongo` `subscribers` collection UDR uses — the document
`resccom-sim db sync` (3.2-b) already writes has the legacy fields
(`msisdn`, `mme_host`, `mm_realm`, `subscribed_rau_tau_timer`, ...) HSS
needs, so there's no separate 4G subscriber-provisioning step.

**Verified live:** all four new containers come up clean (zero restarts)
and the control-plane plumbing associates correctly:

- MME↔HSS Diameter (S6a): both sides log `CONNECTED TO
  'hss.localdomain'` / `'mme.localdomain'` (SCTP).
- SGW-C↔SGW-U PFCP (Sxa): both sides log `PFCP associated`.
- The 1.1-c UERANSIM 5G path still passes unchanged with the EPC
  services present (no regression).

**Verified: an actual 4G UE attaching** — via `stack/ran`'s srsRAN 4G ZMQ
rig ([../ran/](../ran/README.md), `../ran/verify-4g.sh`), which closed
this task's last open line item: srsue attaches (`Network attach
successful. IP: 10.45.0.x`), pings UPF's `services_net` address
(`10.46.0.2`) through eNB→SGW-U→UPF(ogstun, NAT'd out to services_net),
and the 1.1-c 5G path is re-run afterwards to prove no regression.

Getting there surfaced one real EPC gap: **4G needs PCRF.** The first
attach attempt reached the MME and authenticated fine, then failed at
session creation — SMF (playing PGW-C) logs `No Gx Diameter Peer` and
refuses the CreateSession, which surfaces at the UE as Attach Reject
cause 11. 5G sessions take policy from PCF over SBI, but the 4G path
requires the Diameter twin. Fix: `open5gs-pcrfd` (10.10.0.34, same mongo)
plus the Gx freeDiameter pair (`config/freeDiameter/{smf,pcrf}.conf`) and
a `freeDiameter:` line in `smf.yaml`. Verified: SMF and PCRF both log
`CONNECTED TO '...localdomain'`, and the attach then succeeds.

Bring up just the EPC pieces to inspect them directly:

```bash
docker compose up -d hss sgwu sgwc mme
docker compose logs mme hss | grep -i "connected to"
docker compose logs sgwc sgwu | grep -i "pfcp associated"
```

## Teardown & state hygiene (1.1-e)

```bash
docker compose down -v   # drops containers, the network, AND mongo-data
docker compose up -d
export RESCCOM_SIM_STORE=$(pwd)/.dev-subscribers.db.enc
export RESCCOM_SIM_PASSPHRASE=dev-only-ephemeral
resccom-sim sub add --test --imsi 001010000000001
resccom-sim db sync --core-dir .
```

`-v` removes the named volume `mongo-data`, so this always starts from a
genuinely empty MongoDB — there's no `mongo-data/` directory in the repo
to forget to delete: Mongo's data lives entirely in a Docker-managed
named volume, never inside this working tree, so there's nothing here
*to* commit by accident. The `mongo-data/` entry in the root
[.gitignore](../../.gitignore) is a second layer of protection in case
someone ever switches this to a bind mount.

Verified live: a full `down -v` → `up -d` → loader cycle leaves all 16
containers running with **zero restarts** (`docker inspect ... --format
'{{.RestartCount}}'`), `db.subscribers.countDocuments()` at exactly `0`
right after the fresh `up -d` and exactly `1` after the loader runs, and
MME↔HSS / SGW-C↔SGW-U re-associate on the new volume exactly as they did
before the teardown (same log lines as in "4G EPC dual-mode" above).

## Layout

- `compose.yaml` — one container per Open5GS daemon, on a fixed-address
  internal network `core_net` (`10.10.0.0/24`) so each NF's config can
  hardcode its peers' SBI/PFCP addresses, the same way upstream ships its
  own sample configs (loopback addresses in a single-host build). Also
  defines `services_net` (`10.46.0.0/24`, named `resccom_services_net` so
  `stack/services/compose.yaml` can attach to it as `external`) and joins
  UPF to it at `10.46.0.2` — see 1.3-a above.
- `config/*.yaml` — per-NF configs derived from upstream's
  `configs/open5gs/*.yaml.in` samples, adapted to: test PLMN `001/01`, TAC
  `1`, UE subnet `10.45.0.0/16`, DNS `10.46.0.53` (see
  [CLAUDE.md](../../CLAUDE.md) conventions), and direct NRF-based service
  discovery (no SCP — out of scope for this task's NF list).
- **SBI addressing (3.3-c v2d)**: NRF, AUSF, UDM, SMF and NSSF are each addressed by a
  3GPP FQDN (`<nf>.5gc.mnc<mnc>.mcc<mcc>.3gppnetwork.org`, matching upstream's own
  home-PLMN roaming example, `configs/examples/5gc-no-scp-sepp2-001-01.yaml.in`) as
  their *primary* `sbi.server` listener, on the default port 80 — not the plain
  `core_net` IP:7777 every other NF still uses. This is what makes each of these
  NFs' own NRF-registered profile carry an FQDN, which is what a foreign PLMN's AMF
  actually checks (`ogs_sbi_fqdn_in_vplmn`, `lib/sbi/context.c`) before it will route
  a request via SEPP instead of dialing straight across islands — this project's
  overlay forward-filter only ever carries SEPP's own N32 ports, so without an FQDN
  in the profile the home-routed roaming path (RFC-0003 D1) can never work at all,
  whatever else is correct. AMF, PCF, BSF, UDR and SEPP keep their plain `core_net`
  IP:7777 listener, matching upstream exactly — they are never themselves the
  *target* of this kind of cross-PLMN lookup. Every core NF's own `client.nrf.uri`
  is the NRF's FQDN, resolved (this lab runs no DNS on `core_net`) via an
  `extra_hosts` entry Compose renders on every SBI-participating container, mapping
  every NF's FQDN to its own fixed `core_net` address — the lab-profile equivalent
  of the DNS server a real deployment would run for this instead. `stack/federation/TASKS.md`
  3.3-c v2b–v2d has the full history of why this addressing scheme is what it is.
- `config/freeDiameter/{mme,hss}.conf` — the S6a Diameter peer configs for
  1.1-d, derived from upstream's `configs/freeDiameter/*.conf.in` samples
  with only the `ListenOn`/`ConnectTo` addresses and install paths
  resubbed for this network.
- `compose.sim.yaml` — UERANSIM gNB + UE overlay for 1.1-c, layered on
  top with `-f compose.yaml -f compose.sim.yaml`.
- `verify.sh` — brings up core + sim and runs the 1.1-c acceptance checks.

## Versions

| Component | Image | Tag | Notes |
|---|---|---|---|
| Open5GS | `gradiant/open5gs` | `2.8.0` | Community-maintained image (Apache-2.0, [Gradiant/5g-images](https://github.com/Gradiant/5g-images)); no image is published directly by the open5gs project itself. Matches upstream [open5gs v2.8.0](https://github.com/open5gs/open5gs/releases). `linux/amd64` only. |
| MongoDB | `mongo` | `8.0.30` | Official image, 8.0 LTS-style release line (not the 8.3 rapid-release line). |
| UERANSIM | `gradiant/ueransim` | `3.3.0` | Same Gradiant image family as open5gs. Matches upstream [UERANSIM v3.3.0](https://github.com/aligungr/UERANSIM/releases). `linux/amd64` only. Sim-only (1.1-c); not part of the base `compose.yaml`. |

<!-- VERIFY: re-check these tags periodically; open5gs.org and the gradiant/open5gs Docker Hub page are the sources of truth. -->

## Known limitations / design notes

- **Platform pin.** `gradiant/open5gs` publishes `linux/amd64` only (no
  arm64 manifest as of this writing). `compose.yaml` pins
  `platform: linux/amd64` on every open5gs service so it also runs (via
  emulation) on arm64 dev machines; on amd64 Debian/Ubuntu deployment
  hosts this is a no-op. <!-- VERIFY: re-check for an arm64 build before
  targeting arm64 node hardware (node-hw/). -->
- **UPF runs `privileged: true`.** The image's `entrypoint.sh` creates the
  `ogstun` TUN device and unconditionally runs
  `sysctl -w net.ipv6.conf.all.disable_ipv6=0` under `set -e`. That sysctl
  write needs real root past Docker's default read-only `/proc/sys`
  mount — `cap_add: NET_ADMIN` alone was not sufficient (verified: it
  restart-loops with `sysctl: permission denied`). Privileged is the
  pattern other open5gs docker-compose recipes use for this same image.
  `ENABLE_NAT` is `true` (1.3-a): the image's own entrypoint turns this
  into one iptables rule, `-t nat -A POSTROUTING -s 10.45.0.0/16 !
  -o ogstun -j MASQUERADE`, matching only UE-subnet traffic leaving by a
  non-`ogstun` interface — i.e. breakout to `services_net`
  (`10.46.0.0/24`, also added in 1.3-a, UPF at `10.46.0.2`). A services
  container never needs to know the UE subnet exists: it just sees UPF's
  `services_net` address and replies to that, and UPF's conntrack un-NATs
  the reply back into `ogstun` to the right UE. UPF's own `core_net`
  (SBI/PFCP) traffic is untouched — wrong source prefix to match.
- **SMF runs without freeDiameter/CTF.** The image's bundled
  `freeDiameter/smf.conf` assumes hostnames this compose network doesn't
  provide and fails to parse, aborting `smfd`. We don't need a legacy
  Gx/online-charging interface for M1 (PCF talks to SMF over SBI), so
  `smf.yaml` sets `ctf.enabled: no` instead of pointing at that file.
- **NRF/AUSF/UDM/UDR/NSSF/BSF have no metrics endpoint.** Only AMF, SMF,
  UPF and PCF actually bind the `metrics:` port in this open5gs version
  (verified: the others never log `metrics_server()` and refuse the
  connection). Their healthchecks are a bare TCP connect to the SBI port
  instead — deliberately not a real HTTP request, since open5gs's SBI
  server speaks HTTP/2 without TLS (h2c) and logs an `ERROR: cannot parse
  HTTP message` for anything else, which would spam the logs every
  healthcheck interval.
- **AMF NGAP host port (`38412/sctp`).** Published for real gNB/hardware
  attach. SCTP port publishing through Docker's userland proxy is a
  known soft spot on some hosts/platforms (notably Docker Desktop's
  non-Linux networking backends) — the 1.1-c UERANSIM rig joins
  `core_net` directly as a container instead of going through this host
  port, which is both more reliable and closer to how a real gNB
  container on the same box would attach.
- **`core_net` is `internal: true`.** No NF ever needs the internet
  (SBI/PFCP/NGAP are all internal-only), so this is a permanent property
  of the network, not a test-time toggle — see 1.1-c's offline-first
  check above. If a future task genuinely needs outbound access from a
  core container (e.g. NTP), that's a deliberate, separate decision, not
  an accidental regression of this setting.
- **UERANSIM's `ue` service overrides the image's own entrypoint.**
  Through the stock `command: ue` entrypoint, `nr-ue` reliably aborts
  right after its first PDU session establishes
  (`terminate called after throwing 'LibError': select failed:
  Interrupted system call`) — reproduced 5/5 times. Replacing the shell
  with `nr-ue` via `exec` (instead of the entrypoint's
  `nr-ue & wait "$child"`) made it disappear across many runs. This
  still uses the unmodified upstream binary and config template, just a
  different process lifecycle — `compose.sim.yaml`'s `ue.entrypoint`
  reproduces the entrypoint's own config-templating steps, then execs.
  The `gnb` service didn't show this issue and keeps the stock
  `command: gnb`. <!-- VERIFY: re-check against a newer gradiant/ueransim
  tag or a native (non-emulated) amd64 host — this may be specific to
  running under Docker Desktop's amd64 emulation on Apple Silicon. -->
- **No SCP/SEPP.** This task's NF list (NRF, AMF, SMF, UPF, AUSF, UDM,
  UDR, PCF, NSSF, BSF) doesn't include a Service Communication Proxy, so
  every NF talks to the NRF directly (`sbi.client.nrf`) rather than
  through indirect/delegated discovery.
- **No real credentials anywhere here.** UDM's `hnet` keys are upstream's
  published sample ECIES test keys baked into the image at
  `/opt/open5gs/etc/open5gs/hnet/` (not overridden); UDR/PCF's `db_uri`
  points at the compose `mongo` service with no auth. Real subscriber
  data (1.1-b) goes in `subscribers.example.json` / `*.example.*`, never
  here.

## Verification performed

Ran `docker compose up -d` end-to-end on this machine (macOS + Docker
Desktop, `linux/amd64` emulation) and confirmed:

- All 11 containers reach `healthy` within ~20 s (well under the 60 s
  acceptance bar), with zero restarts.
- `docker compose logs amf | grep -i ngap` shows AMF's NGAP server bound
  on `10.10.0.5:38412`.
- UPF creates `ogstun` and reaches `PFCP associated` with SMF.
- NRF logs show NF registrations and discovery subscriptions from every
  other NF.
- No config contains real credentials; nothing secret-shaped needed a
  `*.example.*` name for this task (subscriber data is 1.1-b).

Then ran `./verify.sh` (1.1-c) end-to-end, twice in a row including a
re-run without teardown, and confirmed:

- UE registration: log line `[nas] [info] Initial Registration is
  successful`.
- UE got an IP in `10.45.0.0/16` (`10.45.0.2` on the run quoted in the
  1.1-c section above).
- Local breakout ping to UPF's real `services_net` address `10.46.0.2`
  (1.3-a; the UE still needs an explicit route added, per 1.1-c) succeeded,
  0% packet loss.
- A core container's `curl` to a public IP failed to connect at all,
  confirming `core_net`'s `internal: true` actually blocks WAN egress.

Then, after adding the 4G EPC (1.1-d) and a `depends_on: mongo:
condition: service_healthy` fix for HSS (it raced Mongo's startup twice
before that fix — 0 restarts after), confirmed:

- `docker inspect` shows 0 restarts for `mme`, `hss`, `sgwc`, `sgwu`.
- `mme`/`hss` logs both show `CONNECTED TO 'hss.localdomain'` /
  `'mme.localdomain'` (S6a Diameter peer association).
- `sgwc`/`sgwu` logs both show `PFCP associated` (Sxa).
- Re-ran `./verify.sh` with the EPC services present: still `ALL CHECKS
  PASSED`, no regression to the 5G path.

Then ran a full `docker compose down -v` → `up -d` → loader cycle (1.1-e,
with the `load-subscribers.py` shown at the time — since superseded by
`resccom-sim db sync`, 3.2-b, same upsert behavior for this cycle) and
confirmed:

- All 15 containers came back with `docker inspect ... RestartCount` at
  `0` for every one of them.
- `db.subscribers.countDocuments()` was `0` immediately after the fresh
  `up -d` (proving `-v` actually dropped the data) and `1` after the
  loader ran once.
- MME↔HSS and SGW-C↔SGW-U re-associated on the fresh volume with the
  same log lines as before the teardown.

Not verified here (genuinely out of scope, needs real hardware, a
different environment, or a component that doesn't exist yet): the SCTP
host-port path with a real external gNB (only container-to-container
NGAP over `core_net` was exercised); bring-up on real Debian/Ubuntu
hardware (only tested via Docker Desktop's Linux VM under amd64
emulation on Apple Silicon); and 1.1-d's actual 4G UE-attach acceptance
line, which needs an LTE UE/eNB simulator that doesn't exist in this
repo yet (see "4G EPC dual-mode" above).
