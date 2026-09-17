# Contributing to ResCCOM

Thanks for showing up. This project is bootstrapping — the highest-value contributions right now are reproducing the PoC from the docs and reporting where the docs failed you.

## Where to start (no radio hardware needed)

- **Run the sim path:** [stack/core/TASKS.md](stack/core/TASKS.md) then [stack/services/TASKS.md](stack/services/TASKS.md) — Open5GS + UERANSIM + services, entirely in software. File an issue for every step that didn't work as written.
- **Tooling:** [sim-tools/](sim-tools/TASKS.md) is plain Python against a MongoDB — no RF anywhere.
- **Docs & playbook:** the [community playbook](playbook/README.md) and [spectrum matrix](docs/spectrum/README.md) need contributors who know their own country's rules and volunteer structures.
- **Hardware:** if you *do* have an SDR (USRP B210, LimeSDR) — the `[HW]` tasks in [stack/ran/TASKS.md](stack/ran/TASKS.md) need independent reproduction, always under a test license or shielded enclosure.

## Ground rules

- **Upstream-first (WBS 0.2).** Open5GS, srsRAN, NOMAD, pySim, Matrix are consumed as **unmodified, version-pinned upstream containers**. Bug in an upstream? Report/fix it upstream and link the issue here. We do not carry patches and we do not fork. This also keeps the licensing story clean: AGPL-3.0 upstreams stay intact and separate; everything original in this repo is Apache-2.0.
- **Legal RF only.** PRs containing instructions to transmit without authorization will be closed. Keep the warnings in RAN docs intact.
- **No security overclaiming** in any user-facing copy — [SECURITY.md](SECURITY.md) defines what we may claim.
- **Docs are part of the change.** If your PR alters behavior, it updates the relevant README in the same PR.
- **Commits** reference a WBS code (see [ROADMAP.md](ROADMAP.md)): `1.3-b: matrix reachable from UE subnet`.

## Process

1. Small fixes: just open a PR.
2. Anything architectural: open an issue first, or an RFC ([rfcs/README.md](rfcs/README.md)) if it changes a design principle.
3. AI-assisted contributions are welcome and expected — [CLAUDE.md](CLAUDE.md) is the agent briefing. You are responsible for what you submit: run the acceptance criteria yourself.

## Conduct

[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) (Contributor Covenant 2.1). This project will be used by people in bad situations; we hold a correspondingly low tolerance for bad behavior in it.
