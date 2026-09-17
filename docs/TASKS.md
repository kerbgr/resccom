# docs — TASKS (WBS 0.3 follow-ups: index, status, onboarding)

Cross-cutting documentation tasks. Governing principle — **progressive disclosure, single source of truth**: each fact lives in exactly one file, everything else links to it. Statuses live only in `STATUS.md`, work instructions only in `TASKS.md` files, architecture only in RFCs, agent rules only in `CLAUDE.md`. A docs PR that restates content from another file instead of linking to it is wrong.

---

## 0.3-b — Status board + index pass (do now)

**Goal:** anyone — human or coding agent — lands in the repo and knows in under a minute what works, what's open, and where their entry point is. Token-frugal: the always-loaded files stay small.

**Steps**
1. Create root `STATUS.md`: one table — WBS code | work package | state (`done-verified` / `partial` / `open`) | evidence (verify script or commit hash) | date. **States come from git history and the verify scripts, never from optimism**; anything not proven by a passing script or a commit is `open` or `partial`. No narrative — statuses only.
2. Root `README.md`: point its status line at `STATUS.md`; add a short "Where to start" block with three audience rows (hands-on reproducer → `stack/core/README.md`; contributor → `CONTRIBUTING.md`; coding agent → `CLAUDE.md`). Net growth of README: **≤ 20 lines** — trim if needed, the repo-map table is already the index.
3. `CLAUDE.md`: add one rule to "How to pick and do work": *when a task's acceptance criteria pass, update `STATUS.md` in the same commit.* `CLAUDE.md` total stays **≤ 85 lines** (it is loaded into every agent session — it has a token budget; move anything overflowing into a linked file).
4. Create root `AGENTS.md` containing only a pointer: this project's agent briefing is `CLAUDE.md` (for non-Claude coding agents that look for the AGENTS.md convention).
5. Sweep all READMEs for status claims that duplicate `STATUS.md`'s job ("Done, verified", "Not started" tables) and replace with a link — component READMEs keep *how it works*, not *whether it's done*. (`stack/ran/README.md`'s status table is the known offender.)

**Acceptance**
- `STATUS.md` rows for every WBS code in `ROADMAP.md`'s table, states consistent with `git log` and the existing verify scripts (spot-check: 1.1-a..e `done-verified`, 1.2-a `partial` — 4G half only, everything in Phase ≥ 1.3 `open`).
- The link-check loop from `.github/workflows/docs-check.yml` passes locally.
- `wc -l CLAUDE.md` ≤ 85; README net diff ≤ +20 lines; no file restates another file's content where a link would do.

## 0.3-c — Hands-on QUICKSTART (do ONLY after stack/services 1.3-f passes / milestone M1-sim)

**Goal:** the doc a partner-lab student or community volunteer follows on day one, cold.

**Steps**
1. Root `QUICKSTART.md`: single path — prerequisites (incl. the macOS amd64-emulation note and Rosetta setting), clone, bring up the island, run the verify scripts, expected output, where to report failures (the repro-report issue form). Written for someone who knows Docker and nothing about 3GPP.
2. It must be **executed, not imagined**: run the documented path start-to-finish on a clean checkout and record the wall-clock time in the doc.
3. Add the `[HW]` lane pointer for lab partners (what hardware unlocks `stack/ran` 1.2-b/c/d, with the legal warning) — link, don't restate.

**Acceptance**
- A run of the documented commands on a clean clone passes with no undocumented step; timing recorded from that run.
- `README.md` links QUICKSTART in the "Where to start" block (one line changed).

## 0.3-d — CI: the repo proves itself on every push (do now, after milestone M3)

**Goal:** a partner lab, a contributor, or the next coding agent sees on GitHub that the checkout works on a plain Linux x86 host — not only on the maintainer's macOS machine under amd64 emulation. Everything up to M3 (2026-09-17) was verified on one Apple-silicon laptop; a GitHub Actions `ubuntu-latest` runner is the first unemulated x86 run of this stack, and the first place Sonnet-scale changes get caught without a human re-running scripts.

**Steps**
1. `.github/workflows/ci.yml`, three jobs, all on `ubuntu-latest`, images pinned as in the repo (never `latest`):
   - **`checks`** (fast, required): `pipx install ./sim-tools ./island-init`; `uvx --with-editable ./sim-tools pytest -q sim-tools` and the same for `island-init`; the golden rule (`island-init render --lab --repo-root .` then `git status --porcelain -- stack/` must be empty); `bash -n` on every `*.sh`; `docker compose -f … config -q` for every compose file (including `compose.sim.yaml`, `compose.5g-oai.yaml`, `compose.wan.yaml` with the env they need); `shellcheck` on `island.sh` and every verify script if it is on the runner (warnings allowed, errors not).
   - **`core-sim`** (required, ~10 min budget): `stack/core/verify.sh` end to end — Open5GS core + UERANSIM attach + local breakout, the M1 core path. Needs `/dev/net/tun` and `NET_ADMIN` inside containers (compose already declares them); confirm the runner permits both and record the fact in the workflow's header comment. Cache image pulls (`docker/setup-buildx-action` or a plain layer cache) so the job does not re-download ~2 GB every run. On failure upload `docker compose logs` as an artifact.
   - **`federation-sim`** (`workflow_dispatch` and nightly only, **not** required): `stack/federation/two-island.sh verify` then `roam --ue oai`. Two cores plus OAI on a 7 GB runner may not fit — try it, record the measured memory and wall-clock in the workflow header, and if it cannot run reliably say so there and leave the job manual. Never make a flaky job required.
2. README: a CI badge next to the status line; QUICKSTART: one sentence that the same commands run in CI on Linux, linking the workflow (labs will diff their failure against a known-green run).
3. `STATUS.md` 0.3 row: what CI now covers and what it deliberately does not (RF, two-island by default). `docs/partner-labs.md` rung 0: "CI green on Linux" as the reproduction baseline.
4. No secrets in CI: the lab profile uses the published test vector only; `secrets/` is generated on the runner by `island-init new --lab` exactly as `island.sh up` does on a fresh clone. If a step needs a passphrase, it is the documented dev-only value, never a repository secret.

**Acceptance**
- `checks` and `core-sim` green on `main` on GitHub (link the run in STATUS); a deliberately broken golden-rule commit on a branch turns `checks` red (prove the guard bites, then drop the branch).
- `core-sim` prints `ALL CHECKS PASSED` from `stack/core/verify.sh` on the runner; its measured wall-clock recorded in the workflow header.
- `federation-sim` either green on a manual dispatch with its measurements recorded, or documented as not fitting the free runner, with the numbers.
- Every image tag in the workflow matches the repo's pins; no `latest`, no unpinned actions (pin `uses:` to a version tag).
