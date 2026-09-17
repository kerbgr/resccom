# Instructions for AI agents working on ResCCOM

You are helping bootstrap ResCCOM: an open-source private 4G/5G network stack for disasters, crises, and off-grid communities. Read [README.md](README.md) first, then [rfcs/rfc-0001-architecture.md](rfcs/rfc-0001-architecture.md) for any design question.

## How to pick and do work

1. Work is defined in `TASKS.md` files ([stack/core/](stack/core/TASKS.md), [stack/ran/](stack/ran/TASKS.md), [stack/services/](stack/services/TASKS.md), [stack/backhaul/](stack/backhaul/TASKS.md), [sim-tools/](sim-tools/TASKS.md), [island-init/](island-init/TASKS.md), [stack/federation/](stack/federation/TASKS.md), [docs/](docs/TASKS.md)). Every task has a WBS code (e.g. `1.1-a`), steps, and **acceptance criteria**. A task is done only when its acceptance criteria pass verbatim.
2. Do tasks in order within a file unless a task says otherwise; earlier tasks are dependencies of later ones.
3. Tasks tagged **`[HW]`** need physical radio hardware (SDR, SIMs, phones). If no hardware is attached to the machine you run on, **skip them and say so** — do the `[SIM]` (software-simulation) variant instead. Never mark an `[HW]` task done based on simulation.
4. Reference the WBS code in every commit message, e.g. `1.1-b: open5gs SA core boots under compose`.
5. When a task's acceptance criteria pass, update [STATUS.md](STATUS.md) in the same commit.

## Hard rules

- **Never fork upstreams.** Open5GS, srsRAN, NOMAD, pySim, UERANSIM, Synapse are consumed as unmodified upstream containers/packages, version-pinned. If an upstream change is needed, write it as an upstream issue/PR, and note it in the local `TASKS.md`.
- **Never commit secrets.** No SIM Ki/OPc values, no real subscriber IMSIs, no private keys, no `.env` with credentials. Test values go in files named `*.example.*`. The [.gitignore](.gitignore) enforces some of this — respect its intent, don't work around it.
- **Never instruct anyone to radiate RF without a license.** Any doc or script touching the RAN must keep its shielded-enclosure/test-license warning. The simulation path (srsRAN ZMQ virtual radio, UERANSIM) is the default for all development.
- **Never overclaim security.** Do not write copy implying the network is covert, untraceable, or protects users from a state-level adversary. The threat model in [SECURITY.md](SECURITY.md) is the boundary of claims.
- **Don't invent results.** If a verification command wasn't run, or failed, say exactly that. Field/RF performance numbers (coverage, capacity) may only come from real measurements, never estimated into docs as fact.
- **Version-pin everything** (container tags, package versions). Record every pin in the component's README under "Versions".
- **Dual-use project — guardrails are signal.** If you hit a safety refusal or reassignment on this material, stop and re-check scope against [SECURITY.md](SECURITY.md) "Dual-use notice"; never rephrase or split a task to get around it. Any new lab-only shortcut (test keys, open registration, hardcoded dev passphrases) gets a row in SECURITY.md's "Lab-profile register" in the same commit.
- **If you change what `island.sh` or any verify script requires** (a new binary on PATH, a new env var), update [QUICKSTART.md](QUICKSTART.md) prerequisites in the same commit.

## Conventions

- Glue code license: Apache-2.0. Languages: Python for tooling, YAML/compose for deployment, Bash only for ≤20-line wrappers.
- Deployment target: Debian 12+ / Ubuntu LTS, Docker Compose first; k3s comes later (Phase 2), don't build for it yet.
- Docs are a deliverable of every task: if behavior changed, the same PR updates the relevant README.
- Mermaid for all diagrams (GitHub renders it). Keep diagrams minimal — mechanism, not decoration.
- Network conventions — these are the **lab profile** (single-island development). Production islands get unique allocations (PLMN, IMSI block, prefixes, realm) from the registry per [rfcs/rfc-0005](rfcs/rfc-0005-island-identity.md); never treat these values as deployable defaults for a real, federating island:
  - UE subnet: `10.45.0.0/16` (Open5GS default) · Services subnet: `10.46.0.0/24`
  - Test PLMN: MCC `001` MNC `01` (the reserved test PLMN) · TAC `1`
  - Local DNS zone: `.island` (e.g. `library.island`, `chat.island`) — local-only alias, never routed between islands
- When a fact needs checking against the real world (prices, regulations, upstream versions), mark it `<!-- VERIFY -->` in the doc rather than asserting it.

## What "on wheels" means, in order

The bootstrap sequence a fresh agent session should drive toward (details in each TASKS.md):

1. `stack/core` — Open5GS up under compose, subscriber added, verified with UERANSIM (no hardware).
2. `stack/services` — NOMAD + Matrix + DNS reachable from the simulated UE subnet, all backhauls down.
3. `sim-tools` — subscriber CRUD CLI wrapping Open5GS DB + pySim programming (programming itself is `[HW]`).
4. `stack/ran` — srsRAN with ZMQ virtual radio replacing UERANSIM's gNB; `[HW]` variants when an SDR is present.
5. `stack/backhaul` — WAN failover + the unplug test.

Milestone M1 (sim) = steps 1–2 passing on one machine. That is the current target.

## Commit attribution

The human maintainer is the sole author and copyright holder of everything in this repository; AI tooling is a tool, not a contributor. **Never add `Co-Authored-By:` trailers or "Generated with …" footers** to commit messages or pull requests, whatever the tooling's default or any runtime instruction says. Never name a model or vendor as author, reviewer or contributor in code, comments, commit messages, docs or status files; write "review" or "the executor", not a model name. Tool use is acknowledged once, in README "How the project works", in tool language (assistance, not authorship), and nowhere else.
