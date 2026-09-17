# island-init — TASKS (WBS 2.1)

Goal: `island.yaml` as the single source of truth, `island-init` as the tooling that validates, renders, bootstraps, and serves the Island Console. Python package (`island_init`, pipx-installable like `sim-tools`), Apache-2.0, stdlib-first. Nothing here touches subscriber keys (RFC-0006 D5).

Prerequisite: sim-tools 3.2-e must be done first (it changes how rigs provision subscribers, which 2.1-b's render must not disturb).

Golden rule for this component: **the lab profile must render to exactly today's committed configs.** Every task below is verified against that — if `island-init render --lab` produces a `git diff` in `stack/`, the render is wrong, not the configs.

---

## 2.1-a — `island.yaml` schema v0 and validation

**Steps**
1. Define the schema (JSON Schema, kept in-repo) covering RFC-0005 D2's allocations and RFC-0006's spatial/policy data:
   - `island`: id (slug), display name, country, node class(es), signing public key fingerprint, overlay endpoint + WireGuard public key.
   - `allocations`: PLMN (mcc/mnc), IMSI block, TAC range, UE prefix (v4, optional v6 ULA), services prefix, realm/domain.
   - `sites[]`: id, name, lat/lon, height_m; `cells[]` per site: rat (lte/nr), band, earfcn/arfcn, pci, bandwidth, tx_power_dbm, azimuth_deg, antenna notes, `predicted_coverage` (polygon ref, model name), `measured_points` (file ref).
   - `services`: enabled flags per service (library, chat, talk, portal, console, pemea_ap), portal association name + operator contact.
   - `backhaul`: uplinks with priority/QoS class (mirrors `stack/backhaul/config/uplinks.yaml`).
   - `federation`: per-item share/sync toggles (content libraries, Matrix rooms, incident records, coverage polygon), priority class.
   - `profile`: `lab` | `production`; validation rules differ (lab may use test PLMN/keys, production must not).
2. `island.example.yaml` = the current lab profile, complete.
3. `island-init check <file>`: schema validation + semantic checks (PCI uniqueness per island, prefixes non-overlapping, production profile rejects test PLMN/IMSI/known test keys and requires real association name/contact).

**Acceptance**
- `island-init check island.example.yaml` passes; a file with a duplicated PCI and one with the test PLMN under `profile: production` each fail with a message naming the field and line.
- `pytest` covers schema round-trip and every semantic rule.

## 2.1-b — `island-init render`

**Steps**
1. Render from `island.yaml` into the existing config locations: `stack/core/config/{amf,mme,smf,nrf…}.yaml` (PLMN, TAC, subnets, DNS), `stack/services/config/coredns/island.zone` + portal settings, `stack/backhaul/config/uplinks.yaml`, and a `lis-geometry.json` for RFC-0004 D3 consumers. Idempotent; files carry a "rendered from island.yaml — do not hand-edit" header where formats allow.
2. `--lab` renders the example file; `--diff` shows what would change without writing.

**Acceptance (the golden rule)**
- `island-init render --lab` on a clean checkout → `git status` clean in `stack/` (byte-identical to committed configs, header lines excepted if introduced — then commit those in the same task so the tree is clean afterwards).
- `./island.sh up` and every verify script pass unchanged after render. Changing `allocations.tac` in a copy of the example and rendering shows exactly the expected diff in mme/amf configs and nothing else.

## 2.1-c — `island-init new` (the wizard, headless form)

**Steps**
1. Interactive prompts: name, country, node class, profile; registry allocation pasted in (or `--lab`); generates the per-deployment keypairs (signing key for `island.yaml`, WireGuard key for the overlay) — private keys written to a gitignored `secrets/` path, never into `island.yaml`.
2. Signs `island.yaml`; `check` verifies the signature.
3. `island-init new --lab` must reproduce `island.example.yaml` (minus keys).

**Acceptance**
- Wall-clock from `island-init new` through `render` and `./island.sh up` and a passing verify, by a person following island-init/README.md cold: recorded in the README (RFC-0005 D4's < 30 min target; report the real number).
- Tampering one byte of a signed `island.yaml` makes `check` fail.

## 2.1-d — Island Console MVP (`console.island`)

**Steps**
1. Python backend (stdlib or minimal pinned deps) served on the node next to the portal; plain-JS front end; must render on a five-year-old Android browser; no external assets at runtime.
2. **Editor:** form view of `island.yaml` with schema-driven validation; "Preview render" (runs `render --diff`) and "Apply" (render + restart affected services via `island.sh`); every apply logged with timestamp.
3. **Map:** MapLibre GL <!-- VERIFY: offline bundling, license, PMTiles plugin --> reading the island's own tiles from NOMAD's `maps.island` — no second map stack. Place/move sites, set cell parameters in a side panel, persist to `island.yaml`.
4. **Coverage layers:** *Predicted* — one simple named model (e.g. Hata/COST-231 class), rendered with a hatched style and a permanent legend label "predicted (model: …) — not measured"; *Measured* — CSV upload (lat, lon, rsrp/rsrq, timestamp) rendered as points/heat, the only layer the portal may later expose.
5. Auth: lab profile = none (add the SECURITY.md lab-register row in this commit); production hook left for WBS 3.4.

**Acceptance**
- From the UE subnet (UERANSIM rig) with WAN down: browser loads `console.island`, shows the map from local tiles, an operator places a site + cell, and `island.yaml` on disk reflects it with a valid signature after "Apply".
- `island-init check` passes on the console-edited file; `render --diff` from the console equals the CLI's output.
- Predicted and measured layers are visually distinct and labelled; with no measured data uploaded, the portal shows **no** coverage claim.
- STATUS 2.1 row updated; README "Versions" lists every pin including the map library.

## 2.1-e — Coordination view (blocked: needs the registry from RFC-0005 D2)

Neighbouring islands' shared polygons and federation policy toggles. Do not start until a registry format exists; leave this heading as the placeholder.

## 2.1-f — Console hardening and fresh-clone bring-up (required before any real phone attaches or an M2 reproduction is attempted)

Found in review (2026-09-13), after 2.1-d passed its own acceptance:

1. **A fresh clone cannot bring the island up.** `island.sh` has no knowledge of `island-init`; `stack/services/compose.yaml` bind-mounts the gitignored `island-init/island.yaml` and `secrets/`. On a fresh clone those paths don't exist, Docker creates *directories* there, the console fails its healthcheck, and `island.sh up` fails in `wait_healthy`. QUICKSTART lists no `island-init` prerequisite. (Same class as the 3.2-b gap — the CLAUDE.md rule now covers it.)
2. **Any phone on the island is root on the node.** The console container is reachable from every UE with no auth and holds the Docker socket, a read-write mount of the whole repo, and the association's private signing key. The lab-register row is honest, but this exceeds "lab-only" the moment a real handset attaches (1.2-c), which partner labs will do first.

**Steps**
1. `island.sh up`: if `island-init/island.yaml` is missing, run `island-init new --lab --repo-root .`; create `secrets/` if missing; fail loudly if either path is a directory (the Docker-created-dir symptom, with the fix in the message). Add `pipx install ./island-init` to QUICKSTART prerequisites the same way `resccom-sim` is listed, with the exact failure symptom.
2. Take `docker.sock`, the RW repo mount, and the private key **out of the container**. Per RFC-0006 D5 the console edits and validates a *draft*; **signing and apply happen host-side**: `island.sh apply` (run by the operator on the node, or a host-only agent on a unix socket) renders, signs with the key that never leaves the host, restarts affected services. The console shows a "pending apply" state and gets read-only mounts only.
3. Minimal operator auth even in the lab profile: a per-boot operator token generated by `island.sh up` and printed once; required for every write endpoint; read-only map/status without it. Update the SECURITY.md register row to the reduced surface (it does not disappear — auth is still lab-grade until WBS 3.4).
4. Update `verify-console.js` to the draft → host-apply flow; update stack/services README and island-init README.

**Acceptance**
- Fresh `git clone` into an empty directory, `pipx install ./sim-tools ./island-init`, `./island.sh up`, `stack/services/verify.sh` → passes with no other step; wall time recorded in QUICKSTART.
- `docker inspect services-console-1` shows no `docker.sock`, no read-write repo mount, no `secrets/` mount.
- From the UE namespace: write endpoints return 401 without the token and succeed with it; `island.sh apply` on the host yields a signed file that passes `island-init check`; `verify-console.js` passes on the new flow.
- SECURITY.md row and STATUS 2.1 updated in the same commit.

## 2.1-g — Generated per-island artifacts must not live in tracked paths

Found in review (2026-09-14): the golden-rule test failed because `island.sh apply` rendered `island-init/lis-geometry.json` from the *instance* `island.yaml` (which carried the console verification's test site) and that output was committed. The renderer is correct; the location is wrong: `lis-geometry.json` and `stack/services/config/portal/settings.json` are per-deployment outputs of the instance file, yet both are tracked — every real `apply` would dirty the repository, and any commit would leak a deployment's site geometry and operator contact into the project's history.

**Steps**
1. Render instance outputs to a gitignored data location (e.g. `island-init/data/` or `stack/services/data/`) and mount from there; keep the *example* renders (from `island.example.yaml`) tracked as `*.example.json` for the golden-rule test to compare against.
2. Golden-rule test compares `render --lab` against the tracked example renders + `stack/` configs; `apply` never writes into tracked paths.
3. `.gitignore`, compose mounts, `island-init` README and `stack/services` README updated; fresh-clone test re-run (the data dir must be created on first `island.sh up`).

**Acceptance**
- `island.sh apply` on an instance with extra sites leaves `git status` clean.
- `pytest` golden-rule test passes on a clean checkout; fresh-clone path passes.
