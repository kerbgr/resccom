# Quickstart (M1-sim)

The path a partner-lab student or community volunteer follows on day one,
cold. Everything below is **software-only** — no radio hardware, no
spectrum license, nothing that radiates; see [the HW lane](#hw-lane-for-lab-partners)
at the end for what changes once real radio hardware is available.

## Prerequisites

- A Debian 12+/Ubuntu LTS host, or macOS/Linux with **Docker Desktop**,
  with **Docker Engine + Compose v2** (`docker compose`, not the old
  `docker-compose`) and this repo cloned. You need to know Docker; you
  don't need to know anything about 3GPP.
- **`resccom-sim` on your PATH** — the subscriber-provisioning CLI, which
  `island.sh up` calls to load the test subscriber the network needs.
  Install it once with [pipx](https://pipx.pypa.io) (Python 3.11+):

  ```bash
  pipx install ./sim-tools
  ```

  See [sim-tools/README.md](sim-tools/README.md) for details. Without it,
  `island.sh up` stops early with `resccom-sim not found on PATH`.
- **`island-init` on your PATH** — the `island.yaml` validate/render/apply
  CLI, which `island.sh up` calls on a fresh clone to bootstrap
  `island-init/island.yaml` and `secrets/` (neither is committed — both
  are gitignored, generated fresh per node) before the Island Console
  container can even start, and which `island.sh apply` calls to sign
  and apply a change staged in the console. Install it the same way:

  ```bash
  pipx install ./island-init
  ```

  See [island-init/README.md](island-init/README.md) for details.
  Without it, `island.sh up` stops early with `island-init not found on
  PATH`; skipping this step on a truly fresh clone is also what used to
  make the console container fail its healthcheck deep inside
  `island.sh`'s own `wait_healthy` with no obvious cause (Docker silently
  creating a directory at the bind-mounted `island.yaml` path that
  doesn't exist yet) — `island.sh up` now checks for and reports that
  exact symptom by name instead. `island.sh up` also now runs
  `island-init check` on `island-init/island.yaml` before bringing
  anything up (3.3-b follow-up 5) — if you already bootstrapped an island
  before a schema change (3.3-a's `node`, 3.3-b's `federation.peers`) and
  see it refuse to proceed, the failure message names the fix:
  `island-init migrate island-init/island.yaml`.
- **~20 GB free disk** for container images (the full stack — Open5GS,
  UERANSIM, Matrix/Synapse, Element, Jitsi Meet, Project NOMAD, CoreDNS —
  pulls to roughly 13 GB of images the first time).
- **Outbound internet access for the first run only**, to pull the pinned
  images. After that, `island.sh up` genuinely works with the network
  disconnected — that's the whole point of this stack.
- **Apple Silicon (M-series Mac) users:** `gradiant/open5gs` and several
  other images are `linux/amd64`-only (no arm64 build exists yet — see
  each component's README under "Versions" for which). Every compose file
  in this repo pins `platform: linux/amd64` on the images that need it, so
  Docker Desktop runs them under emulation automatically — no manual
  `--platform` flags needed. Do turn on **Docker Desktop → Settings →
  General → "Use Rosetta for x86_64/amd64 emulation on Apple Silicon"**;
  it's markedly faster than the default QEMU emulation for this stack.
  Expect the timing below to run slower than on native amd64 hardware.

## Bring up the island

```bash
git clone https://github.com/kerbgr/resccom.git
cd resccom
./island.sh up
```

On a first run, `island.sh` also generates every secret and self-signed
TLS certificate each component needs (from the `*.example.env`/`.yaml`
templates already committed in this repo — nothing is invented that isn't
already in the repo), so this really is the one command, not "one command
after some manual setup." It brings up, in order: the Open5GS core
([stack/core](stack/core/README.md)), then local DNS + a landing page +
[Project NOMAD](https://github.com/crosstalk-solutions/project-nomad)'s
offline knowledge library + [Matrix](https://matrix.org)/Element
messaging + Jitsi Meet voice/video
([stack/services](stack/services/README.md)).

Expected output ends with:

```
Island is up. From a device on the UE subnet (a real phone with a
provisioned SIM, or the UERANSIM simulator — see stack/core/README.md):

    http://portal.island   live status + what this network is
    http://library.island  offline knowledge (NOMAD/Kiwix)
    https://chat.island    messaging (Element Web, E2EE by default)
    https://talk.island    voice/video calling
```

`./island.sh down` tears everything back down; `./island.sh status`
reports what's currently running.

## Verify it

You don't need a real phone to confirm the island actually works:
[stack/services/verify.sh](stack/services/README.md) drives the UERANSIM
simulator through this milestone's full scenario end-to-end — registers
onto the network, browses `library.island`, and sends a real E2EE Matrix
message — plus, going beyond the milestone's own bar, a real audio call
and a live status check:

```bash
stack/services/verify.sh
```

Expected output ends with:

```
ALL CHECKS PASSED
```

The same commands — the pytest suites, the golden rule, and
`stack/core/verify.sh` end to end — run in CI on a plain Linux x86
runner on every push ([.github/workflows/ci.yml](.github/workflows/ci.yml)),
so a failure here can be diffed against a known-green run rather than
against the maintainer's laptop.

If a check fails, the script's own output names which one and why —
that's the exact text to paste into a
[reproduction report](https://github.com/kerbgr/resccom/issues/new?template=repro-report.yml)
(the most valuable issue type in this repo: what you were reproducing,
your environment, and what happened).

## Measured timing

Run 2026-09-13 (island-init/TASKS.md 2.1-f), one command at a time, from
a **literal** `git clone` into an empty directory on a clean host state
(every ResCCOM-related container, network, and volume removed first) —
macOS, Apple Silicon, Docker Desktop, images already present in the
local Docker cache from prior pulls on this machine (so this excludes
first-time image pull, which depends entirely on your connection to the
registries — budget extra time for that on a first-ever run):

| Step | Wall time |
|---|---|
| `pipx install ./sim-tools` | <1s (already installed on this run) |
| `pipx install ./island-init` | ~1s |
| `./island.sh up` | 1m 58s |
| `stack/services/verify.sh` | 43s |
| **Total, clone → fully verified** | **~2m 41s** (plus first-time image pull) |

No step beyond the ones listed above and in "Bring up the island" was
needed — this run is what caught and fixed a real bug (an unbound-variable
crash in `island.sh`'s console-token bootstrap, see git history) that a
non-literal "should work" pass would have missed.

## HW lane for lab partners

Everything above is the `[SIM]` path. Lab partners with an SDR (e.g. a
USRP B210) unlock the real-radio variants of `stack/ran` —
[1.2-b (SIM programming)](stack/ran/TASKS.md), 1.2-c (first phone attach),
and 1.2-d (low-cost radio variant). Those tasks carry a hard legal
requirement — **never radiate on cellular spectrum without a test/local
license or a shielded enclosure** — spelled out in
[stack/ran/TASKS.md](stack/ran/TASKS.md); read it before touching any
`[HW]` task. Don't restate that warning here — it lives in exactly one
place.
