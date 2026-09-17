# sim-tools — subscriber & SIM provisioning

`resccom-sim`: the CLI an association volunteer uses to manage subscribers — create, store (encrypted at rest), program onto SIM cards (via [pySim](https://osmocom.org/projects/pysim)), and sync to the island's Open5GS core. Designed for a person at a folding table during a drill, not a telecom engineer.

Work is defined in [TASKS.md](TASKS.md) (WBS 3.2; tasks 3.2-a/b are pure software — good first contributions). Security rules for anything touching keys: [SECURITY.md](../SECURITY.md). Current state: [STATUS.md](../STATUS.md).

## Status of this CLI

WBS 3.2-a and 3.2-b are implemented: `sub add|list|remove` work end to end
against the local encrypted store (3.2-a), and `db sync` reconciles that
store into the island's Open5GS core over `docker compose exec mongo`
(3.2-b) — see "Syncing to the core" below. `sub export` and `sim
program|verify` exist as commands but each exits with an error naming the
WBS task (3.2-c/d) that will implement them — they are not stubs left
silently broken, they are deliberately unimplemented until that work
lands.

`db sync` is also now the *only* implementation of "how a subscriber
document looks in Open5GS's Mongo and how to write it there" in this
repo: it replaces `stack/core/load-subscribers.py`, which did the same
thing but upsert-only, with no way to revoke a subscriber. See
[stack/core/README.md](../stack/core/README.md)'s "Scripted path"
section, which now uses this CLI too.

## Install

```bash
pipx install .        # from sim-tools/
```

`pipx` builds an isolated virtualenv for the CLI and puts `resccom-sim` on
your PATH. Requires Python 3.11+ (see "Versions" below).

For development (editable install + tests):

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

## Usage

Every command reads/writes one local encrypted store. The default location
is the OS-standard app-config directory (`click.get_app_dir("resccom-sim")`
— e.g. `~/Library/Application Support/resccom-sim/subscribers.db.enc` on
macOS, `~/.config/resccom-sim/subscribers.db.enc` on Linux); override with
`--store PATH` or `$RESCCOM_SIM_STORE`. The store passphrase is read from
`$RESCCOM_SIM_PASSPHRASE` if set, otherwise prompted for interactively
(with confirmation the first time a store is created).

Add a lab subscriber using the well-known 3GPP/GSMA test vector (test PLMN
`001/01` — see [rfc-0001](../rfcs/rfc-0001-architecture.md)) and list it
back — real commands, real output from a clean store:

```console
$ export RESCCOM_SIM_STORE=/tmp/demo/subscribers.db.enc
$ resccom-sim sub add --test
New store passphrase:
Repeat for confirmation:
added 001010000000001

$ resccom-sim sub list
Store passphrase:
001010000000001  -

$ resccom-sim sub list --show-secrets
Store passphrase:
001010000000001  -                     key=465B5CE8B199B49FAA5F0A2EE238A6BC opc=E8ED289DEBA952E4283B54E88E6183CA

$ resccom-sim sub remove 001010000000001
Store passphrase:
removed 001010000000001
```

A second `sub add --test` picks the next free IMSI in the test range
(`001010000000002`, ...) rather than colliding. `sub add` without `--test`
takes `--imsi`, `--key` and `--opc` explicitly for a real association
subscriber — those values must never be committed to git (see "Storage &
encryption" below and [SECURITY.md](../SECURITY.md)).

Multiple independent rigs (e.g. `stack/core`'s and `stack/ran`'s verify
scripts) often share one dev store. Plain `sub add` errors on any existing
IMSI, which is right for a human but wrong for a script that just wants
"my subscriber is there" — `--if-missing` makes that idempotent: it
succeeds silently if an identical subscriber already exists, and only
errors if the existing one has different key/opc/amf/label/notes (a real
conflict, not a rerun):

```console
$ resccom-sim sub add --test --imsi 001010000000002 --if-missing
added 001010000000002
$ resccom-sim sub add --test --imsi 001010000000002 --if-missing
already present: 001010000000002
```

This is what lets several rigs share one store without `rm -f`-ing it
first (see WBS 3.2-e and "Syncing to the core" below): each rig adds only
its own IMSI, so the store stays the union of everyone's test
subscribers instead of whoever ran last winning.

### Roaming policy: Local Breakout vs Home-Routed

Every subscriber carries `lbo_roaming_allowed` (WBS 3.3-c v2e), written into
every `slice[].session[]` entry of its Mongo document under exactly that
name — the same field and semantics as upstream's own roaming tutorial
(`docs/_docs/tutorial/05-roaming.md` section 2 of the pinned Open5GS
release): unset/`false` anchors a roaming PDU session at the subscriber's
*home* island (Home-Routed); `true` anchors it at the *visited* island
(Local Breakout). This project's default is `true` — RFC-0003 D1 wants
Local Breakout, so a roaming subscriber's traffic is served by whichever
island it's actually visiting, not tunneled back home over the overlay
(which the federation forward-filter deliberately only carries SEPP/N32
across anyway — see [RFC-0003](../rfcs/rfc-0003-roaming.md) D1).

`sub add --home-routed` opts a subscriber out at creation; `sub edit
<imsi> --home-routed` flips an existing one to Home-Routed, and `sub edit
<imsi>` with no flag flips it back to Local Breakout. `sub show` and `sub
list` both display the current mode (`LBO`/`Local Breakout` or
`HR`/`Home-Routed`):

```console
$ resccom-sim sub add --test --imsi 001010000000003 --home-routed
added 001010000000003
$ resccom-sim sub show 001010000000003
imsi: 001010000000003
label: -
notes: -
amf: 8000
roaming: Home-Routed (lbo_roaming_allowed=false)
created_at: ...
$ resccom-sim sub edit 001010000000003
001010000000003: lbo_roaming_allowed=true
```

A subscriber added before this field existed loads with
`lbo_roaming_allowed=True` (the store migrates its schema in place on next
open) — the project default applies retroactively rather than silently
defaulting such subscribers to Home-Routed.

Commands not yet implemented fail clearly instead of silently no-op'ing:

```console
$ resccom-sim sub export
Error: sub export is not implemented yet (WBS 3.2-d) -- this is a CLI skeleton for 3.2-a.
```

## Syncing to the core

`db sync` makes the island's Open5GS `subscribers` collection match the
local store exactly: it upserts every local subscriber, keyed on IMSI,
then **deletes any Mongo subscriber document not in the local store**.
The local store is authoritative — this is what makes `sub remove` +
`db sync` actually revoke a subscriber's core access, not just leave a
stale, still-valid document behind. Run it from anywhere with
`--core-dir` pointing at a running `stack/core` compose project (needs
`docker compose` and a healthy `mongo` service there):

```console
$ resccom-sim db sync --core-dir ../stack/core
added=1 updated=0 unchanged=0 removed=0 (../stack/core/mongo)
```

Because it's a full reconcile rather than an upsert-only push, running it
twice with an unchanged local store leaves Mongo unchanged (no
duplicates) — see "Verification run (3.2-b acceptance)" below for a live
run against the UERANSIM rig, including the revoke-on-removal case.

**WBS 3.2-e:** a subscriber whose document already matches exactly
(ignoring generated `_id`/ObjectId fields) is left alone, not
`replaceOne`'d — the second `db sync` above reports `unchanged=1`, not
`updated=1`. This isn't just cosmetic: Open5GS's UDR treats any write to a
subscriber document as a subscription-data change, and for a UE with an
active PDU session that can tear down routing the AMF/SMF/UPF won't
recover from on its own, even when the write's *content* didn't change
(see `resccom_sim/sync.py`'s module docstring, and
[stack/ran/README.md](../stack/ran/README.md)'s 5G-alt writeup for the
live PFCP-session breakage this was first found as). That's what makes it
safe for several rigs to `db sync` the same shared store repeatedly
without disturbing each other's live sessions — see "Rig-safe sync
(3.2-e)" below.

**This changes what "the source of truth" means for `stack/core`'s
subscribers.** Once you're managing them through `resccom-sim`, don't
also edit Mongo by hand (the "Manual path" in
[stack/core/README.md](../stack/core/README.md)) — the next `db sync`
will delete anything it doesn't recognize from the local store.

## Inbound roaming: policy-only records (WBS 3.3-c v2h)

Local Breakout roaming (RFC-0003 D1: a roaming subscriber's session is
served by whichever island they're *visiting*, not tunneled home) needs
the visited island's Open5GS PCF to answer an SM Policy Association
request for that subscriber. TASKS.md 3.3-c v2g traced why that fails by
default straight to source: `pcf_get_session_data()` →
`ogs_dbi_session_data()` (upstream Open5GS `lib/dbi/session.c`) queries
the PCF's *own* island's local MongoDB by SUPI and reads only that
subscriber's `slice[].session[]` policy (QoS, AMBR, `lbo_roaming_allowed`)
— it never reads `security` (K/OPc/AMF), and there is no SBI/N32 hop in
this lookup for SEPP to carry at all. A roaming subscriber's document
exists only at their home island (K never leaves home), so a visited
PCF that's never been told anything about them can't find them and
rejects the session with a real `404 {"title":"[...] Cannot find SUPI in
DB"}`.

**The fix is data, not a workaround**: the home island exports each
roaming-enabled subscriber's *policy only* — no key, no opc, no security
block anywhere, not filtered out but never present in the type at all
(`roaming.PolicyRecord` has no field that could hold one) — and the
visited island imports it as a document marked
`resccom_inbound_roamer: true` / `home_plmn: {mcc, mnc}`, so `db sync`
(above) can tell it apart from that island's own subscribers and never
touch it. This is what a visited PCF holds under a real 3GPP roaming
agreement — the visited operator's own policy applied to the roamer's
session — not [D3](../rfcs/rfc-0003-roaming.md) guest provisioning (a
full credentialed local subscriber).

```console
# On island A (home), after provisioning the roaming subscriber:
$ resccom-sim roaming export --out roamers.json
exported 1 policy-only record(s) to roamers.json

# Handed over to island B's operator (unsigned -- see "Lab-only" below).
# On island B (visited):
$ resccom-sim roaming import roamers.json --core-dir ../stack/core --home-plmn 001/01
imported 1 inbound-roamer record(s) (home_plmn=001/01)

$ resccom-sim roaming list --core-dir ../stack/core
001010000099999  home_plmn=001/01

$ resccom-sim roaming remove 001010000099999 --core-dir ../stack/core
removed 001010000099999
```

`roaming import` refuses any record carrying a credential-like field
(`security`/`k`/`opc`/`op`/`amf`, case-insensitive, anywhere at the
record's top level) — a hard rule enforced in code before Mongo is ever
touched, not a convention the export side is trusted to follow. It also
refuses to overwrite an existing *unmarked* document at the visited
island: an inbound-roamer import can never silently clobber that
island's own real subscriber. `roaming export` defaults to every
subscriber with `lbo_roaming_allowed=true` (a Home-Routed subscriber
never needs a visited PCF's policy); `--imsi` (repeatable) narrows it,
erroring on an IMSI the store doesn't have or that's Home-Routed.

**`db sync` leaves inbound-roamer records alone.** Its reconcile-delete
excludes anything marked `resccom_inbound_roamer: true` regardless of
whether the IMSI is in the local store (it never will be — that store
belongs to the *other* island), and its upsert loop skips a marked
document outright rather than comparing or replacing it. A local `db
sync` at the visited island can run freely without ever touching what
`roaming import` put there.

**Upstream shared-DB caveat.** Open5GS's own roaming examples
(`configs/examples/5gc-no-scp-sepp{1,2,3}-*.yaml.in`) never hit the gap
this section closes, because every PCF in those examples points
`db_uri` at the *same* MongoDB (`mongodb://localhost/open5gs`) — a
"visited" PCF finds every SUPI because there is only one database in
the example. Two real islands, each running their own Mongo (this
project's actual model), need this policy to actually travel between
them; that's what `roaming export`/`roaming import` do.

**Lab-only, not a deployment-ready exchange mechanism.** The export
file here is an unsigned, unencrypted JSON hand-over — `two-island.sh`'s
own harness just copies it between the two checkouts it manages (see
[stack/federation/TASKS.md](../stack/federation/TASKS.md) 3.3-c v2h and
[SECURITY.md](../SECURITY.md)'s lab-profile register). A real
association-to-association exchange needs signing and transport over
the overlay, which belongs with WBS 3.4 (PKI) — not implemented here.

## Storage & encryption

The subscriber model (IMSI, K, OPc, AMF, label, node-class notes,
created-at) is stored as one SQLite table. Per [TASKS.md](TASKS.md) 3.2-a
it must be encrypted at rest; the choice was between:

- **SQLCipher** (`pysqlcipher3` or similar) — a drop-in encrypted SQLite,
  but it wraps a compiled native extension. There's no universal pip wheel
  for it across macOS/Linux/arch combinations, so `pipx install .` on a
  volunteer's unprepared machine (the actual target user — see TASKS.md's
  "designed for a person at a folding table, not an engineer") could fail
  on a missing compiler/toolchain.
- **File-level encryption around a plain SQLite file** (chosen) — every
  operation decrypts the on-disk file into a `0600` temp file, runs normal
  `sqlite3` against it, and re-encrypts the result back to disk. Key
  derivation is `scrypt` (`n=2**14, r=8, p=1`) from the passphrase plus a
  random per-file salt; encryption is AES-256-GCM (authenticated, so a
  wrong passphrase or corrupted file is detected and rejected rather than
  silently returning garbage). This uses only the pure-Python
  `cryptography` wheel already pinned below — no native build step, so the
  install stays a plain `pipx install .` on any platform pip has a wheel
  for. See [`resccom_sim/crypto.py`](resccom_sim/crypto.py) and
  [`resccom_sim/store.py`](resccom_sim/store.py).

The on-disk file is opaque ciphertext (`RESCSIM1` magic + salt + nonce +
ciphertext) — `file` reports it as generic `data`, and neither the schema
nor any K/OPc value appears in the bytes. Verified as part of 3.2-a's
acceptance run (see below).

## Verification run (3.2-a acceptance)

Commands and their actual output, run 2026-09-12 on macOS (Homebrew
Python 3.14.7 via `pipx`; dev/test venv on Python 3.12.7 — both satisfy
`requires-python = ">=3.11"`):

```console
$ cd sim-tools && pipx install .
creating virtual environment...
installing resccom-sim from spec '.../sim-tools'...
  installed package resccom-sim 0.1.0, installed using Python 3.14.7
  These apps are now available
    - resccom-sim
done! ✨ 🌟 ✨

$ export RESCCOM_SIM_STORE=/tmp/acceptance-test/subscribers.db.enc
$ export RESCCOM_SIM_PASSPHRASE=correct-horse-battery-staple
$ resccom-sim sub add --test
added 001010000000001
$ resccom-sim sub list
001010000000001  -

$ file "$RESCCOM_SIM_STORE"
subscribers.db.enc: data                     # not "SQLite 3.x database"

$ RESCCOM_SIM_PASSPHRASE=totally-wrong-passphrase resccom-sim sub list
Error: wrong passphrase or corrupted store    # exit code 1

$ .venv/bin/python -m pytest -q
...................                                                      [100%]
19 passed in 2.85s
```

`pipx install .` succeeded on a fresh isolated venv, the store file was
confirmed unreadable (rejected, not silently wrong) without the correct
passphrase, and all 19 unit tests passed. STATUS.md's 3.2 row cites this
run.

## Verification run (3.2-b acceptance)

Run 2026-09-13 on macOS + Docker Desktop against the already-attached
`stack/core` UERANSIM rig (`stack/core/verify.sh`'s M1 gate), `resccom-sim`
0.1.0 reinstalled via `pipx` with `db sync` added:

```console
$ cd stack/core
$ export RESCCOM_SIM_STORE=$(pwd)/.dev-subscribers.db.enc
$ export RESCCOM_SIM_PASSPHRASE=dev-only-ephemeral
$ resccom-sim sub add --test --imsi 001010000000001
added 001010000000001
$ resccom-sim db sync --core-dir .
synced 1 subscriber(s) to ./mongo

$ resccom-sim db sync --core-dir . && resccom-sim db sync --core-dir .
synced 1 subscriber(s) to ./mongo
synced 1 subscriber(s) to ./mongo
$ docker compose exec -T mongo mongosh --quiet mongodb://localhost/open5gs \
    --eval "db.subscribers.countDocuments()"
1
```

Forced a fresh attach (`docker compose -f compose.yaml -f compose.sim.yaml
up -d --force-recreate ue`) against the synced subscriber — succeeded:

```text
[nas] [info] Initial Registration is successful
```

(UE got `10.45.0.8`.)

Then removed the subscriber locally and re-synced:

```console
$ resccom-sim sub remove 001010000000001
removed 001010000000001
$ resccom-sim db sync --core-dir .
synced 0 subscriber(s) to ./mongo
$ docker compose exec -T mongo mongosh --quiet mongodb://localhost/open5gs \
    --eval "db.subscribers.countDocuments()"
0
```

Forced another fresh attach attempt — this time it failed, both client-
and core-side:

```text
ue-1  | [nas] [error] Initial Registration failed [FIVEG_SERVICES_NOT_ALLOWED]
amf-1 | WARNING: [suci-0-001-01-0000-0-0-0000000001] Cannot find SUCI [404]
amf-1 | WARNING: [suci-0-001-01-0000-0-0-0000000001] Registration reject [7]
```

Re-added the subscriber, re-synced, and forced one more attach to confirm
the rig was left working (it was — `10.45.0.9`, `Initial Registration is
successful` again) before moving on. `stack/core/verify.sh` was then run
end to end with its new `resccom-sim`-based loading step and passed (`ALL
CHECKS PASSED`), and the full `sim-tools` unit test suite passed (25 tests
— 6 new ones for `sync.py` and `db sync`):

```console
$ ./verify.sh
...
ALL CHECKS PASSED

$ .venv/bin/python -m pytest -q
.........................                                                [100%]
25 passed in 2.64s
```

## Verification run (3.2-e acceptance)

Run 2026-09-13 on macOS + Docker Desktop, with the UERANSIM rig
(`stack/core/verify.sh`'s M1 gate) already attached and left running
throughout. Found the bug this task fixes on the very first attempt:
`stack/ran/verify-5g-oai.sh` reported `updated=1` for the UERANSIM
subscriber during its check-4 delegation, and the UPF genuinely could not
route to the UERANSIM UE afterwards (`docker compose exec upf ping
<ue-ip>` — 100% loss) — the *original* 3.2-e bug (each rig's `db sync`
reconciling every other rig's subscriber away), reproduced live before
any fix landed:

```console
$ docker compose exec -T mongo mongosh --quiet mongodb://localhost/open5gs \
    --eval "db.subscribers.find({}, {imsi:1, _id:0}).toArray()"
[ { imsi: '001010000000001' } ]      # the OAI rig's 002 already deleted,
                                      # even though its UE's tunnel (oaitun_ue1,
                                      # 10.45.0.20) was still up
```

`sub add --if-missing` (never `rm -f`) plus `db sync`'s unchanged-skip
fixed that structural problem, but running the full scenario again
surfaced a *second*, previously-unknown one: even with both fixes in
place, one `db sync` still reported `updated=1` for the (untouched,
already-registered) UERANSIM subscriber, and the same UPF-can't-route
symptom recurred. Cause: Open5GS had written `imeisv` and
`security.sqn` into that subscriber's live document since it last
registered — real, expected runtime state, not drift — and comparing the
full document (as WBS 3.2-e's acceptance text describes: "ignoring
generated `_id`/ObjectId fields") saw that as a genuine change. Excluding
those specific core-managed fields from the comparison (see
`resccom_sim/sync.py`'s module docstring) fixed it for good. Full run
after both fixes:

```console
$ ./verify-5g-oai.sh
...
== check 4: primary (UERANSIM) 5G path regression (delegates to stack/core verify.sh) ==
...
== check 5: multi-rig acceptance -- both IMSIs survived, Mongo holds both ==
OK: Mongo holds both IMSIs, and the OAI UE's PDU session (10.45.0.23) survived
    the UERANSIM regression check

ALL CHECKS PASSED -- OAI rfsimulator attach + breakout, the primary
UERANSIM 5G path still passes, and both rigs' subscribers/sessions
survived running back to back (WBS 3.2-e)

$ docker compose exec -T mongo mongosh --quiet mongodb://localhost/open5gs \
    --eval "db.subscribers.countDocuments()"
2
```

`db sync` run twice in a row against the live, two-subscriber, two-active-session
state:

```console
$ resccom-sim db sync --core-dir . && resccom-sim db sync --core-dir .
added=0 updated=0 unchanged=2 removed=0 (./mongo)
added=0 updated=0 unchanged=2 removed=0 (./mongo)
$ docker compose -f compose.yaml -f compose.sim.yaml exec -T ue ping -c2 -W2 -I uesimtun0 10.46.0.1
2 packets transmitted, 2 received, 0% packet loss
```

`grep -n "logs.*grep" stack/*/verify*.sh stack/ran/verify-*.sh` afterward
shows only best-effort corroboration lines in the four converted scripts
(`stack/core/verify.sh`, `stack/ran/verify-4g.sh`,
`stack/ran/verify-5g-oai.sh`, `stack/services/verify.sh`) — each now
gates on a live tunnel-interface poll, with the log line kept only as an
`echo` alongside an already-decided pass. `stack/ran/verify-5g.sh` still
gates two checks on log content and is documented there as a deliberate
exception: that rig has no UE/tunnel interface at all to poll, and an
NG-Setup accept/reject is an NGAP application-layer outcome with no
kernel-visible analogue (see that script's own added comment); it has
also never reached that code path in practice, crash-looping first on
the unrelated upstream YAML bug it already documents. `stack/backhaul/*.sh`
had no log-grep pass/fail gates to convert.

`.venv/bin/python -m pytest -q`: 34 passed (9 new: `add_if_missing`
insert/no-op/conflict in `test_store.py`; unchanged-skip and
core-managed-field-ignoring in `test_sync.py`; `--if-missing` no-op/conflict
and the new `db sync` output format in `test_cli.py`).

## Versions

Exact pins from [pyproject.toml](pyproject.toml):

| Component | Pin |
| --- | --- |
| Python (interpreter) | `>=3.11` (tested: 3.12.7, 3.14.7) |
| Build backend: `hatchling` | `==1.27.0` |
| `click` | `==8.1.8` |
| `cryptography` | `==50.0.1` |
| `pytest` (dev only) | `==8.4.2` |

`db sync` (3.2-b) adds no new pip dependency — it shells out to `docker
compose exec ... mongosh` exactly like `stack/core/load-subscribers.py`
did, so it inherits that project's own pins
([stack/core/README.md](../stack/core/README.md) "Versions": Open5GS
`2.8.0`, MongoDB `8.0.30`) rather than duplicating them here.

<!-- VERIFY: pySim invocation/version, once 3.2-c lands -->
