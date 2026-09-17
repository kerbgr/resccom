# sim-tools — TASKS (WBS 3.2, early slice pulled into Phase 1)

Goal: `resccom-sim`, a Python CLI an association volunteer can use to manage subscribers: create → store → program SIM → sync to the core. Wraps pySim and the Open5GS subscriber DB; no RF involved (programming uses a USB PC/SC reader — the only `[HW]` bit).

Security rules ([SECURITY.md](../SECURITY.md)): real K/OPc values and IMSIs never enter git; the tool's subscriber store is an encrypted-at-rest local file/DB owned by the association.

---

## 3.2-a — CLI skeleton & subscriber model

**Steps**
1. Python package `resccom_sim` (pinned deps, `pyproject.toml`), commands: `sub add|list|remove|export`, `db sync`, `sim program`, `sim verify`.
2. Subscriber model: IMSI (from the association's allocated range), K, OPc, name/label, node-class notes. Storage: local SQLite, encrypted at rest (e.g. SQLCipher or file-level age encryption — choose, justify in README).
3. `sub add --test` generates entries in the test PLMN `001/01` range with well-known test vectors for lab use.

**Acceptance**
- `pipx install .` then `resccom-sim sub add --test && resccom-sim sub list` works on a clean machine; store file is unreadable without the passphrase; unit tests cover the model.

## 3.2-b — Open5GS DB sync

**Steps**
1. `db sync` idempotently upserts subscribers into the Open5GS MongoDB (reuse/replace `stack/core`'s loader — one implementation, not two). <!-- VERIFY: current Open5GS subscriber document schema; pin to the core version used in stack/core -->

**Acceptance**
- Sync twice → no duplicates; removing a subscriber locally + sync removes core access (verified by a UERANSIM auth failure for that IMSI).

## 3.2-c `[HW]` — pySim programming

**Steps**
1. `sim program` drives pySim against a PC/SC reader + sysmoISIM-class card: writes IMSI/K/OPc/PLMN; `sim verify` reads back what's readable and cross-checks the store. <!-- VERIFY: current pySim invocation for sysmoISIM-SJA5 or successor cards -->

**Acceptance**
- A programmed card's readable fields match the store; the full path store→program→sync→attach passes with the ZMQ RAN rig (`stack/ran` 1.2-a) plus srsUE configured with the card's credentials, or with a real phone (`[HW]` 1.2-c).

## 3.2-d — Batch/field mode

**Steps**
1. `sub add --batch N` + `sim program --next`: program a stack of cards in sequence with printed labels (CSV export for label printers). Designed for a volunteer at a table during a drill, not an engineer.

**Acceptance**
- A dry-run batch of 10 test subscribers programs sequentially with clear per-card prompts; docs include the "drill day" runbook.

## 3.2-e — Rig-safe sync semantics and live-state verify gates (required follow-up, do before any new rig)

Found in review (2026-09-13) when several rigs were alive on one host: `stack/core/verify.sh`'s UERANSIM regression check failed although the UE had in fact registered, and Mongo held only one subscriber — the OAI rig's `…0002` had been deleted. Two root causes, both structural:

1. **Every rig uses its own throwaway single-IMSI store** (`rm -f` the store, `sub add` one IMSI, `db sync`), and `db sync` is a full reconcile — so each rig's sync deletes every other rig's subscriber. `island.sh`, `stack/core/verify.sh`, `stack/ran/verify-4g.sh`, `stack/ran/verify-5g-oai.sh` all do this against the *same* path (`stack/core/.dev-subscribers.db.enc`).
2. **`db sync` `replaceOne`s unchanged documents**, which breaks routing for a UE with an active PDU session (see `stack/ran/README.md` 5G-alt writeup), and the older verify scripts **gate pass/fail on `docker compose logs | grep` polls**, which are unreliable on this host (`verify-5g-oai.sh` already documents and avoids this).

**Steps**
1. `resccom-sim sub add --if-missing` (or equivalent): idempotent for an identical existing subscriber, error only on a *conflicting* one. Rigs stop `rm -f`-ing the shared dev store; each adds its own IMSI with `--if-missing`, then syncs — the store becomes the union of all rigs' test subscribers. Keep one dev store path and passphrase (already a SECURITY.md lab-register row).
2. `db sync` compares each existing Mongo document with the would-be document (ignoring generated `_id`/ObjectId fields) and **skips unchanged ones**; output reports `added/updated/unchanged/removed` counts.
3. Convert `stack/core/verify.sh` check 1 and `stack/ran/verify-4g.sh` check 1 to the live-state gate pattern in `stack/ran/verify-5g-oai.sh` (poll `ip -4 addr show <tun>` from a fresh `exec` each iteration; log grep is corroboration only, never the gate). `stack/services/verify.sh` check 1 uses the same log-grep gate (confirmed) — convert it too; check `stack/backhaul/*.sh` and convert any found.
4. Update `island.sh`, all four rigs, `sim-tools/README.md`, `stack/core/README.md` "Scripted path", and QUICKSTART if any prerequisite changes.

**Acceptance**
- With the UERANSIM rig attached and its session active: run `stack/ran/verify-5g-oai.sh` end-to-end → its own checks pass **and** its embedded core regression check passes (both UEs stay attached; `db.subscribers.countDocuments()` = 2 afterwards, neither IMSI deleted).
- `db sync` twice with an active session → second run reports all `unchanged`, UE still pings `10.46.0.1`.
- `grep -n "logs.*grep" stack/*/verify*.sh stack/ran/verify-*.sh` shows no remaining pass/fail gates on log greps (comments and corroboration lines are fine).
- `pytest` extended for `--if-missing` and unchanged-skip; STATUS 3.2 row updated in the same commit.
