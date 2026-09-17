#!/usr/bin/env bash
# ResCCOM 3.3-b follow-up 1 — reproducible two-island harness.
#
# Replaces the hand-run procedure 3.3-b's own acceptance needed
# (hand-generate B's keys, edit both islands' federation.peers[], render
# both trees, bring up four compose projects in the right order) with
# one command. This is what STATUS.md cites for 3.3-b/c, and what 3.3-c/
# d and 4.1's own acceptance is built on.
#
# Usage: ./two-island.sh [--b-dir <path>] [--ue oai|ueransim] [--log-level <level>] {up|down|verify|roam|roam-legacy|drill}
#   up      generate/peer both islands' identities (transient copies
#           only -- island.example.yaml/island.example.b.yaml are never
#           touched), render, bring up both islands' stack/core, attach
#           island A's own UERANSIM UE (once amf is in its final peered
#           shape -- see the attach step's own comment on why that
#           order; NOTE this recreates A's gnb/ue containers even if A
#           was already running -- a known, documented side effect of
#           peering, not a bug: amf itself gets recreated once, and the
#           UE rig has to reattach to it), bring up both islands'
#           stack/federation, wait healthy throughout.
#   down    tear down island B entirely and island A's stack/federation;
#           tear down island A's stack/core too, *but only if this
#           harness is the one that started it* (tracked in a state
#           file -- an island A this harness found already running is
#           never `down -v`'d, so its mongo volume and whatever
#           subscribers it already had survive). Either way, re-renders
#           island A's tracked stack/ configs from its own *unpeered*
#           island-init/island.yaml and asserts the tree is clean
#           afterward -- failing loudly if it isn't, never leaving a
#           peered amf/wg-up.sh behind for the next `git status` or
#           `pytest` to trip over (found in review, 2026-09-15: 3.3-b
#           follow-up item 7).
#   verify  up, then each island's own stack/federation/verify.sh in
#           both directions, then confirms island A's UE is still
#           attached (the 3.2-e multi-rig scenario: federating must not
#           disrupt an already-attached local subscriber), then down
#           (always, even on failure -- leaves no state behind, so a
#           re-run starts clean).
#   roam [--ue oai|ueransim]  3.3-c v2's acceptance vehicle (RFC-0003 D1
#           amendment, distinct PLMN per island + SEPP/N32): up, establish
#           overlay routes both directions (SEPP N32-c/N32-f, not direct
#           NRF/UDM -- see verify.sh's own header), provision a
#           roaming-test subscriber in island A's IMSI block on A only,
#           export that subscriber's POLICY ONLY (no security anywhere --
#           `resccom-sim roaming export`) and import it into island B as a
#           marked inbound-roamer record (`roaming import`, TASKS.md
#           3.3-c v2h: B's own PCF needs this for Local Breakout PDU
#           session establishment, `lib/dbi/session.c`), bring up island
#           B's own gNB broadcasting *B's* PLMN (999/70) with a roaming UE
#           configured with *A's* home PLMN (001/01) attached to it, then
#           checks every acceptance bullet (B's AMF/SEPP log shows the
#           home-routed path to A's SEPP, A's AUSF/UDM/SEPP logs show the
#           authentication, B's Mongo holds exactly the one marked
#           policy-only record with no security field, session served by
#           B's SMF/UPF) and prints PASS/FAIL against each -- a settled
#           negative finding is printed plainly, not hidden, if upstream
#           doesn't work as its own examples imply (CLAUDE.md "don't
#           invent results"). Always
#           tears down (same as verify), including the roaming-test
#           subscriber this leaves on A (3.3-c v2 review nit).
#           --ue ueransim (default): UERANSIM's own PLMN-selection
#           (src/ue/rrc/idle.cpp lookForSuitableCell) only ever attempts
#           registration on a cell matching its own configured PLMN --
#           TASKS.md 3.3-c v2's own negative finding, reproduced by this
#           mode every run, not a defect in SEPP/N32 itself.
#           --ue oai (TASKS.md 3.3-c v2b): OpenAirInterface's nrUE over
#           rfsimulator does attempt registration on a visited PLMN (no
#           such check in its own RRC source) -- settles 3.3-c v2b's own
#           VERIFY marker every run: whether a real Registration Request
#           with a roaming SUCI gets home-routed via SEPP, or rejected.
#   roam-legacy  3.3-c v1's now-closed mechanism (same-PLMN SUPI-range NF
#           discovery), kept exactly as it was for reproducibility -- see
#           TASKS.md 3.3-c's negative finding. Superseded by `roam`; not
#           the acceptance vehicle for anything current.
#   drill --ue oai  4.1's partition drill (RFC-0003 D3, corrected by this
#           task). Same up + roaming attach as `roam --ue oai` (the M3
#           state: roamer authenticated at A over SEPP, served by Local
#           Breakout on B), then, with BOTH islands held up throughout:
#           (b) drop the overlay (B's wg-overlay is disconnected from the
#           simulated WAN bridge -- the very link verify.sh tests) and
#           measure whether the ESTABLISHED session keeps passing user
#           plane; (c) with the overlay still down, force a fresh
#           registration (nrUE detach/re-attach) and record B's AMF's
#           own failure line -- the measured partition limit, not a
#           designed one: B holds NO key for the roamer (policy-only
#           record, 3.3-c v2h), and Open5GS's AMF only skips
#           re-contacting home while the UE's security context is valid
#           (src/amf/gmm-sm.c:1752, SECURITY_CONTEXT_IS_VALID) -- a
#           fresh registration has none; (d) guest-provision a LOCAL B
#           subscriber (full credentials in B's own store, an IMSI in
#           B's own block -- deliberately NOT the roamer's home IMSI, and
#           deliberately not an inbound-roamer record, which needs the
#           home island) for the same phone-analog and show it registers
#           and breaks out locally with home still unreachable; (e)
#           restore the overlay, re-attach the original roamer, record
#           recovery time as measured, and print A's SEPP log for the
#           whole drill (RFC-0003 D5: the home island's own record of
#           the roaming events). Every step prints its evidence and its
#           observed-vs-expected verdict; a step that behaves differently
#           than expected is printed as such, never hidden (CLAUDE.md
#           "don't invent results"). Tears down only at the very end
#           (same cmd_down as every other command: island A's
#           pre-existing core is never `down -v`'d). Requires --ue oai:
#           UERANSIM never attempts registration on a visited PLMN
#           (TASKS.md 3.3-c v2), so there is nothing for it to drill.
#
# --log-level <level> (3.3-c v2g): applied as node.log_level to BOTH
# islands' *transient peered* island.yaml copies only (two_island_setup.py
# build_peered_copy) -- never island.example.yaml/island.example.b.yaml or
# either island's own tracked island-init/island.yaml. Default: leave
# island.yaml's own log_level as rendered (usually "info" -- Open5GS's
# AUSF/UDM print no per-UE lines at that level, TASKS.md 3.3-c v2e). Needed
# because the fast PDU-session-establishment reject v2f found on B's own
# local SMF has no stated cause captured at info level.
#
# --b-dir defaults to a gitignored directory next to this script; island
# A is always this checkout (three levels up from here).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

A_DIR="$(cd ../.. && pwd)"
B_DIR="$A_DIR/stack/federation/.two-island-b"
# Records whether island A's stack/core already existed before this
# harness touched it -- every `up` (re)writes it at its very start,
# `down` reads it to decide whether A's core is this harness's to
# destroy. A file, not a shell variable: `up` and `down` are routinely
# invoked as separate process instances (an operator driving the two
# islands by hand), not only together via `verify`.
A_PREEXISTING_STATE_FILE="$A_DIR/stack/federation/.two-island-a-preexisting"

# Re-detected from live docker state on EVERY `up`, overwriting whatever
# a previous run left in the state file -- never trusted from disk. The
# old write-once rule ("a repeat `up` leaves an existing answer alone")
# is what let a roam run that died before cmd_down's `rm -f` leave a
# stale a_core_preexisting=0 behind for the next run to trust: its
# cmd_down then `down -v`'d island A's real dev core (3.3-b follow-up,
# hit live 2026-09-17: 16 core containers and the mongo volume gone, one
# orphan sepp left). Rule now: A's core is this harness's to destroy
# only if THIS run creates it from nothing -- no container *and* no
# volume of A's compose project (an `island.sh down` keeps mongo's
# volume, so "no containers" alone is not "nothing"). Anything else,
# including docker not answering, counts as pre-existing: leak, never
# destroy. Cost accepted: a retried `up` after this run's own failed one
# now leaves A's core up instead of destroying it.
record_a_core_preexisting() {
  local containers volumes
  containers=$(docker compose -f "$A_DIR/stack/core/compose.yaml" ps -a -q 2>/dev/null) || containers="?"
  volumes=$(docker volume ls -q --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME:-core}" 2>/dev/null) || volumes="?"
  if [ -z "$containers" ] && [ -z "$volumes" ]; then
    echo "a_core_preexisting=0" > "$A_PREEXISTING_STATE_FILE"
  else
    echo "a_core_preexisting=1" > "$A_PREEXISTING_STATE_FILE"
    echo "== island A's core (or its data) predates this run -- down will leave it up, its data untouched =="
  fi
}

# roam --ue oai|ueransim (default ueransim): which [SIM] UE attaches the
# roaming subscriber via island B's gNB. TASKS.md 3.3-c v2b's own
# rationale for oai: upstream OpenAirInterface's nrUE, unlike UERANSIM,
# performs no PLMN-suitability check before attempting registration
# (openair2/RRC/NR_UE/rrc_UE.c sets selected_plmn_identity = 1
# unconditionally) -- confirmed live, it's the one that actually reaches
# a roaming NAS Registration Request. Default stays ueransim: it's the
# already-established negative finding (3.3-c v2), reproduced every run
# without needing an extra flag.
ROAM_UE=ueransim

# --log-level (3.3-c v2g): empty means "leave island.yaml's own
# log_level as rendered" (the default, golden-rule-preserving path --
# see the header comment above). Only Open5GS's own accepted values
# (open5gs.conf(5) `level:`) are allowed here; anything else is a typo
# this harness should catch, not silently render and let Open5GS itself
# reject at container startup.
LOG_LEVEL=""

args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --b-dir)
      [ -n "${2:-}" ] || { echo "FAIL: --b-dir needs a directory argument" >&2; exit 1; }
      B_DIR="$2"
      shift 2
      ;;
    --ue)
      [ -n "${2:-}" ] || { echo "FAIL: --ue needs 'oai' or 'ueransim'" >&2; exit 1; }
      case "$2" in
        oai|ueransim) ROAM_UE="$2" ;;
        *) echo "FAIL: --ue must be 'oai' or 'ueransim', got '$2'" >&2; exit 1 ;;
      esac
      shift 2
      ;;
    --log-level)
      [ -n "${2:-}" ] || { echo "FAIL: --log-level needs a level argument" >&2; exit 1; }
      case "$2" in
        fatal|error|warn|info|debug|trace|trace2) LOG_LEVEL="$2" ;;
        *) echo "FAIL: --log-level must be one of fatal|error|warn|info|debug|trace|trace2, got '$2'" >&2; exit 1 ;;
      esac
      shift 2
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done
set -- "${args[@]}"

fail() { echo "FAIL: $1" >&2; exit 1; }

command -v island-init >/dev/null 2>&1 \
  || fail "island-init not found on PATH -- pipx install ./island-init (see island-init/README.md)"
command -v resccom-sim >/dev/null 2>&1 \
  || fail "resccom-sim not found on PATH -- pipx install ./sim-tools (see sim-tools/README.md)"
# Runs two_island_setup.py with the *pipx-installed* island-init's own
# interpreter, not whatever `python3` resolves to on PATH -- guarantees
# `import island_init` finds the real package and its dependencies
# without needing a separate dev venv, the same reasoning
# island-init/README.md gives for island.sh only ever shelling out to the
# installed CLI. pipx writes its console-script wrapper in one of two
# forms, and both occur across this project's own hosts (0.3-d, found
# by CI's first Linux run): a plain `#!<venv>/bin/python -E` shebang
# when the venv path has no spaces (Ubuntu runner, /opt/pipx/venvs;
# the `-E` is pipx's own interpreter flag, not part of the path), or a
# polyglot sh/python file whose literal first line is `#!/bin/sh` and
# whose line 2 is `'''exec' '<venv>/bin/python' "$0" "$@"` when the path
# can't be a shebang (macOS, ~/Library/Application Support/pipx has a
# space). Take the shebang when it names a python; fall back to line 2.
ISLAND_INIT_WRAPPER=$(command -v island-init)
PYBIN=$(head -1 "$ISLAND_INIT_WRAPPER")
if [[ "$PYBIN" == '#!'*python* ]]; then
  PYBIN="${PYBIN#\#!}"
  # A shebang path can't contain spaces (that is why pipx switches to the
  # polyglot form at all), so the first word is the whole path and what
  # follows is interpreter flags.
  PYBIN="${PYBIN%% *}"
else
  PYBIN=$(sed -n "2p" "$ISLAND_INIT_WRAPPER" | sed -E "s/^'''exec' '([^']+)'.*/\1/")
fi
[ -x "$PYBIN" ] || fail "could not find island-init's own Python interpreter (parsed '$PYBIN' from $ISLAND_INIT_WRAPPER)"

# island B's compose invocations, every time: distinct project/network
# names and ports so both islands coexist on one host (3.3-a's own
# procedure -- see island-init/README.md "Node-internal addressing").
B_WAN_IP=10.200.0.3
B_ENV=(COMPOSE_PROJECT_NAME=island-b SERVICES_NET_NAME=island-b_services_net CORE_NET_NAME=island-b_core_net AMF_NGAP_PORT=38413 WG_LISTEN_PORT=51821 WG_WAN_IP=$B_WAN_IP)

# 3.3-c v2f: a dedicated bridge standing in for a real WAN link between
# the two islands' wg-overlay containers (compose.wan.yaml), replacing
# the earlier host.docker.internal hairpin -- see that file's own header
# and two_island_setup.py's for why (Docker Desktop's NAT hairpin
# poisoned WireGuard's own endpoint-roaming on both peers at once,
# black-holing the overlay before SEPP's N32 could complete; 3.3-c v2e
# review). Owned by this script, not by either island's compose project
# (external: true in compose.wan.yaml, same as core_net/services_net
# being external to stack/federation/compose.yaml) -- created once in
# cmd_up, removed once in cmd_down. WG_WAN_IP is exported for island A's
# own (unwrapped) compose invocations below; B_ENV above carries B's own
# value the same way it already carries B's other overrides.
WAN_NET_NAME=two-island-wan
export WAN_NET_NAME
export WG_WAN_IP=10.200.0.2

wait_healthy() {
  local compose_cmd="$1" label="$2"
  local i unhealthy
  for ((i = 0; i < 40; i++)); do
    unhealthy=$($compose_cmd ps --format json | python3 -c "
import sys, json
lines = [json.loads(l) for l in sys.stdin if l.strip()]
print(' '.join(l['Name'] for l in lines if l.get('Health') not in ('healthy', '')))
")
    [ -z "$unhealthy" ] && return 0
    sleep 3
  done
  fail "$label never became healthy: $unhealthy"
}

# Live state, exec'd fresh every call -- never a `docker compose logs`
# grep (see stack/core/verify.sh's own header on why, and the poll-loop
# fix in stack/core/verify.sh: a failing command substitution inside
# `set -e` aborts silently, so every caller here uses `|| true`).
a_ue_ip() {
  docker compose -f "$A_DIR/stack/core/compose.yaml" -f "$A_DIR/stack/core/compose.sim.yaml" \
    exec -T ue ip -4 -o addr show uesimtun0 2>/dev/null | awk '{print $4}' | cut -d/ -f1 || true
}

cmd_up() {
  # First thing, before anything here touches island A -- see
  # record_a_core_preexisting's header for why this is unconditional.
  record_a_core_preexisting

  if [ ! -d "$B_DIR/.git" ]; then
    echo "== cloning island B checkout into $B_DIR =="
    git clone --local "$A_DIR" "$B_DIR"
  fi

  echo "== generating identities + cross-peering (transient copies only) =="
  # TWO_ISLAND_LOG_LEVEL (3.3-c v2g): read by two_island_setup.py, applied
  # to node.log_level on BOTH islands' transient peered copies only, empty
  # is a no-op -- see --log-level's own header comment above.
  TWO_ISLAND_LOG_LEVEL="$LOG_LEVEL" "$PYBIN" two_island_setup.py "$A_DIR" "$B_DIR"

  echo "== bringing up island A core =="
  docker compose -f "$A_DIR/stack/core/compose.yaml" up -d
  # 3.3-c v2c found nrf needed an explicit --force-recreate here: its
  # compose service definition never changed on peering, only nrf.yaml's
  # *content* did (the peer-conditional port-80 listener, 3.3-c v2b (1)),
  # and compose only recreates a service whose definition changed.
  # 3.3-c v2d removes that peer-conditional listener entirely -- nrf's
  # FQDN is now its one, unconditional listener (nrf.yaml.j2), so its
  # content no longer depends on peering status at all, and there is
  # nothing left to reload here.
  wait_healthy "docker compose -f $A_DIR/stack/core/compose.yaml" "island A core"

  echo "== bringing up island B core =="
  (cd "$B_DIR/stack/core" && env "${B_ENV[@]}" docker compose -f compose.yaml up -d)
  wait_healthy "env ${B_ENV[*]} docker compose -f $B_DIR/stack/core/compose.yaml" "island B core"

  # Island A's UERANSIM UE, attached *after* peering, not before: peering
  # changes amf's own compose definition (cap_add + services_net, only
  # rendered once a peer exists), so `docker compose up -d` above just
  # recreated amf if it was already running unpeered -- a hard restart
  # that would drop any UE already attached to it. Attaching here, once
  # island A's amf is in its final peered shape, is what makes "stays
  # attached during the two-island run" (the 3.2-e multi-rig scenario:
  # federating shouldn't disrupt an already-attached local subscriber)
  # an honest claim for everything that happens after this point --
  # cmd_verify checks it again at the end to prove it held.
  echo "== attaching island A's UERANSIM UE (IMSI 001010000000001) =="
  command -v resccom-sim >/dev/null 2>&1 || fail "resccom-sim not found on PATH -- pipx install ./sim-tools"
  (
    cd "$A_DIR/stack/core"
    export RESCCOM_SIM_STORE="$(pwd)/.dev-subscribers.db.enc"
    export RESCCOM_SIM_PASSPHRASE="dev-only-ephemeral"
    resccom-sim sub add --test --imsi 001010000000001 --if-missing
    resccom-sim db sync --core-dir .
  )
  docker compose -f "$A_DIR/stack/core/compose.yaml" -f "$A_DIR/stack/core/compose.sim.yaml" up -d gnb ue
  ue_ip=""
  for _ in $(seq 1 15); do
    ue_ip=$(a_ue_ip)
    [ -n "$ue_ip" ] && break
    sleep 2
  done
  [ -n "$ue_ip" ] || fail "island A's UE did not attach (no uesimtun0) -- check: docker compose -f $A_DIR/stack/core/compose.yaml -f $A_DIR/stack/core/compose.sim.yaml logs ue"
  echo "OK: island A's UE attached, uesimtun0 = $ue_ip"

  # 3.3-c v2f: the shared-WAN bridge both wg-overlay containers land on
  # below, created once here (idempotent -- a second `up` in the same
  # session, or a stale one from a prior run this session's `down` never
  # reached, both just reuse it; it's always the same fixed subnet).
  echo "== creating simulated WAN network ($WAN_NET_NAME, 10.200.0.0/24) =="
  docker network create --subnet 10.200.0.0/24 "$WAN_NET_NAME" >/dev/null 2>&1 || true

  # Both sides' wg-overlay, before either side's verify.sh: each verify.sh
  # brings up (and tests reachability through) its *own* wg-overlay, but
  # a handshake needs the *peer's* endpoint already listening too --
  # found live, running verify.sh for A first with B's wg-overlay not up
  # yet left A's side sending into nothing, hanging on the SBI TCP probe.
  # -f compose.wan.yaml on both sides attaches wg-overlay to wan_net at
  # its static address (WG_WAN_IP -- exported above for A, carried in
  # B_ENV for B) instead of the old host.docker.internal hairpin path.
  echo "== bringing up island A federation =="
  docker compose -f "$A_DIR/stack/federation/compose.yaml" -f "$A_DIR/stack/federation/compose.wan.yaml" up -d
  echo "== bringing up island B federation =="
  (cd "$B_DIR/stack/federation" && env "${B_ENV[@]}" docker compose -f compose.yaml -f compose.wan.yaml up -d)

  echo "OK: both islands' stack/core + stack/federation are up and healthy"
}

cmd_down() {
  # cmd_roam's one-off `docker compose run --name ...` containers aren't
  # reliably matched by `down`'s own container lookup (found live: it
  # names containers by expected compose-generated names, and `run
  # --name` overrides that) -- removed by literal name first so neither
  # ever survives a run as an orphan. The --ue oai pair (plain `docker
  # run`, not compose-managed at all -- no project label for `down` to
  # match in the first place) removed here too, and *before* `down`
  # below: left attached, they'd make island-b_core_net's removal fail
  # ("network has active endpoints").
  docker rm -f island-b-roam-ue island-b-roam-gnb island-b-oai-nrue island-b-oai-gnb island-b-oai-guest >/dev/null 2>&1 || true

  # cmd_roam's own subscriber, removed from A's *local store file* (not
  # just left to whatever happens to A's core below) -- found live: A's
  # core surviving (harness didn't create it) or being torn down and
  # recreated both leave the *store file* untouched either way, and the
  # next `up`'s own UE-attach step re-syncs every subscriber the store
  # file has into mongo, silently resurrecting this one on the next run
  # even after a `down -v`. `db sync` (not just `sub remove`) is what
  # actually removes it from a *currently reachable* mongo too, best
  # effort -- harmless if A's core happens to be down right now.
  if [ -f "$A_DIR/stack/core/.dev-subscribers.db.enc" ]; then
    (
      cd "$A_DIR/stack/core"
      export RESCCOM_SIM_STORE="$(pwd)/.dev-subscribers.db.enc"
      export RESCCOM_SIM_PASSPHRASE="dev-only-ephemeral"
      resccom-sim sub remove "$ROAM_IMSI" 2>/dev/null || true
      resccom-sim db sync --core-dir . 2>/dev/null || true
    ) || true
  fi

  # 3.3-c v2h: cmd_roam's inbound-roamer record on B, removed by name
  # before B's core comes down -- best effort and largely redundant (B's
  # whole Mongo volume is destroyed by the `down -v` right below anyway),
  # but hygiene for the case a future run points --b-dir at a B this
  # harness doesn't fully own. Never touches an unmarked document (see
  # roaming.py's own `run_remove`).
  (cd "$B_DIR/stack/core" 2>/dev/null && env "${B_ENV[@]}" resccom-sim roaming remove "$ROAM_IMSI" 2>/dev/null) || true

  # Island B is always this harness's own checkout -- always a full,
  # destroying teardown.
  (cd "$B_DIR/stack/federation" 2>/dev/null && env "${B_ENV[@]}" docker compose -f compose.yaml down -v --remove-orphans) || true
  (cd "$B_DIR/stack/core" 2>/dev/null && env "${B_ENV[@]}" docker compose -f compose.yaml -f compose.sim.yaml down -v --remove-orphans) || true

  # Island A's federation is always this harness's addition too --
  # nothing else in the project brings stack/federation up.
  docker compose -f "$A_DIR/stack/federation/compose.yaml" down -v 2>/dev/null || true

  # 3.3-c v2f: wan_net is external to both federation compose projects
  # (same as core_net/services_net are to stack/federation/compose.yaml),
  # so neither `down` above ever removes it -- both wg-overlay containers
  # are gone by this point, so this is safe every time.
  docker network rm "$WAN_NET_NAME" >/dev/null 2>&1 || true

  # Island A's *core* only comes down -- and only with -v, destroying its
  # mongo volume -- if this harness is the one that created it (3.3-b
  # follow-up 7: a naive `down -v` here previously destroyed whatever
  # subscribers an already-running island A had, harness-added or not).
  # Destroy needs the state file's explicit =0 from the last `up`; a
  # missing file (an `up` that died before writing it, or a bare `down`
  # with no `up` at all) is ambiguity, and ambiguity leaves A's core up.
  if [ -f "$A_PREEXISTING_STATE_FILE" ] && grep -q "^a_core_preexisting=0$" "$A_PREEXISTING_STATE_FILE"; then
    docker compose -f "$A_DIR/stack/core/compose.yaml" -f "$A_DIR/stack/core/compose.sim.yaml" down -v 2>/dev/null || true
  else
    echo "== island A's core predates this harness run (or its origin is unknown) -- leaving it up, its data untouched =="
  fi
  rm -f "$A_PREEXISTING_STATE_FILE"

  # Removed before the clean-tree assertion below, not after: a dirty A
  # tree (this harness's own uncommitted WIP, most commonly) must not
  # leave a *stale* B checkout behind for the next run to silently reuse
  # -- found live, `fail`'s exit meant a previous run's B_DIR (cloned
  # from whatever A last committed) survived across several later runs
  # that each believed they were testing current code and weren't. A
  # fresh clone next `up` is always correct; skipping it never is.
  rm -rf "$B_DIR"

  # Always: undo whatever peered render `up` left in island A's own
  # tracked tree. two_island_setup.py never edits island A's real
  # island-init/island.yaml (only a transient data/two-island-peered.yaml
  # copy), so re-rendering straight from it restores stack/core/
  # compose.yaml, stack/federation/compose.yaml and data/wg-up.sh to
  # their unpeered shape -- the same golden-rule render every other
  # island-init workflow relies on, just pointed at A's real identity
  # instead of --lab. Fails loudly instead of leaving a dirty tree behind
  # for the next `git status` or `pytest` to trip over.
  local a_yaml="$A_DIR/island-init/island.yaml"
  if [ -f "$a_yaml" ]; then
    echo "== restoring island A's tracked configs to their unpeered state =="
    island-init render --file "$a_yaml" --repo-root "$A_DIR" >/dev/null
    # Only rendered outputs are asserted clean; the harness script itself
    # lives under stack/ but is hand-written, and an uncommitted edit to it
    # (e.g. while fixing a gate) is not a restore failure.
    dirty=$(cd "$A_DIR" && git status --porcelain -- stack/ ':(exclude)stack/federation/two-island.sh')
    [ -z "$dirty" ] || fail "island A's tree is not clean after re-rendering from $a_yaml:
$dirty"
    echo "OK: island A's tree is clean"
  fi

  echo "OK: both islands torn down, $B_DIR removed"
}

cmd_verify() {
  trap cmd_down EXIT
  cmd_up

  echo "== island A -> B =="
  (cd "$A_DIR/stack/federation" && ./verify.sh)

  echo "== island B -> A =="
  (cd "$B_DIR/stack/federation" && env "${B_ENV[@]}" ./verify.sh)

  # 3.2-e's multi-rig scenario, applied to federation: cross-peering and
  # verifying B must not have disrupted A's already-attached local UE.
  # Re-checked here, not assumed from cmd_up's own attach check, so this
  # is live state gated on what's true *now* -- after both directions'
  # SBI traffic actually crossed the overlay.
  echo "== confirming island A's UE is still attached (3.2-e multi-rig scenario) =="
  ue_ip=$(a_ue_ip)
  [ -n "$ue_ip" ] || fail "island A's UE lost its PDU session during the two-island run (uesimtun0 gone)"
  echo "OK: island A's UE is still attached, uesimtun0 = $ue_ip"

  echo
  echo "ALL CHECKS PASSED (both directions, island A's local UE undisturbed)"
}

# The roaming-test subscriber: distinct from island A's own local UE
# (001010000000001) and resccom-sim's second fixture subscriber
# (...002), inside A's imsi_block (00101, island.example.yaml) so
# TASKS.md 3.3-c step 2's "in island A's IMSI block" is literal.
ROAM_IMSI="001010000099999"

cmd_roam_legacy() {
  trap cmd_down EXIT
  cmd_up

  # Reuses verify.sh's own routing step both directions -- it's what
  # actually adds amf's route to the peer's node_internal_base over
  # wg-overlay (see that script's header); running the whole script, not
  # just its routing loop, also re-confirms the overlay itself is healthy
  # before this test builds anything on top of it.
  echo "== establishing overlay routes both directions =="
  (cd "$A_DIR/stack/federation" && ./verify.sh)
  (cd "$B_DIR/stack/federation" && env "${B_ENV[@]}" ./verify.sh)

  echo "== provisioning roaming-test subscriber on A only (IMSI $ROAM_IMSI) =="
  (
    cd "$A_DIR/stack/core"
    export RESCCOM_SIM_STORE="$(pwd)/.dev-subscribers.db.enc"
    export RESCCOM_SIM_PASSPHRASE="dev-only-ephemeral"
    resccom-sim sub add --test --imsi "$ROAM_IMSI" --if-missing
    resccom-sim db sync --core-dir .
  )

  roam_started=$(date -u +%Y-%m-%dT%H:%M:%S)
  echo "== registering A's AUSF/UDM into B's NRF (TASKS.md 3.3-c step 1) =="
  roam_reg_out=$(env "${B_ENV[@]}" "$PYBIN" roam_test.py "$A_DIR" "$B_DIR" "$B_DIR/stack/core/compose.yaml")
  echo "$roam_reg_out"
  a_ausf_ip=$(echo "$roam_reg_out" | grep '^a_ausf_ip=' | cut -d= -f2)
  a_udm_ip=$(echo "$roam_reg_out" | grep '^a_udm_ip=' | cut -d= -f2)
  [ -n "$a_ausf_ip" ] && [ -n "$a_udm_ip" ] || fail "roam_test.py did not report a_ausf_ip/a_udm_ip"

  echo "== bringing up island B's own gNB =="
  (cd "$B_DIR/stack/core" && env "${B_ENV[@]}" docker compose -f compose.yaml -f compose.sim.yaml up -d gnb)

  # A one-off container (docker compose run), not a second `ue` service
  # definition: the roaming subscriber needs a different MSISDN (hence
  # IMSI) than compose.sim.yaml's own hardcoded default UE, and `run -e`
  # overrides that env var for just this container without templating a
  # second compose file for one test. `down -v` at teardown removes it
  # along with everything else in island B's project (matched by
  # project label, not by which compose files defined it).
  msisdn="${ROAM_IMSI#00101}"
  echo "== attaching the roaming UE via island B's gNB (MSISDN $msisdn) =="
  (cd "$B_DIR/stack/core" && env "${B_ENV[@]}" docker compose -f compose.yaml -f compose.sim.yaml \
    run -d --name island-b-roam-ue -e MSISDN="$msisdn" ue)

  roam_ue_ip=""
  for _ in $(seq 1 15); do
    roam_ue_ip=$(docker exec island-b-roam-ue ip -4 -o addr show uesimtun0 2>/dev/null | awk '{print $4}' | cut -d/ -f1 || true)
    [ -n "$roam_ue_ip" ] && break
    sleep 2
  done

  echo
  echo "== evidence =="
  b_amf_new_log=$(env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" logs amf --since "$roam_started" 2>&1 || true)
  # NF_DEREGISTERED for A's injected profile: NRF's own heartbeat-timeout
  # dropping a one-shot PUT that nothing kept alive (found live -- the
  # profile's declared heartBeatTimer, 10s, elapsed with no PATCH before
  # the attach attempt). A real "static profile" would need something
  # re-PUTing/PATCHing it before every timeout, not a single registration
  # call. gmm-sm.c's "Cannot find SUCI"/nas-path.c's "Registration
  # reject" are B's own AUSF answering for a subscriber it has never
  # heard of -- printed here rather than one narrow grep, since which
  # lines matter is exactly the finding, not assumed in advance.
  echo "-- B's AMF log since registration (full, for the negative-finding record) --"
  echo "${b_amf_new_log:-<no new AMF log lines>}"
  ausf_evidence=$(echo "$b_amf_new_log" | grep -E "nausf-handler|nudm-handler" || true)

  b_mongo_hit=$(env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" exec -T mongo \
    mongosh --quiet open5gs --eval "db.subscribers.countDocuments({imsi:'$ROAM_IMSI'})" 2>&1 || true)

  a_ausf_evidence=$(docker compose -f "$A_DIR/stack/core/compose.yaml" logs ausf --since "$roam_started" 2>&1 | grep -i "$ROAM_IMSI" || true)
  a_udm_evidence=$(docker compose -f "$A_DIR/stack/core/compose.yaml" logs udm --since "$roam_started" 2>&1 | grep -i "$ROAM_IMSI" || true)

  echo
  echo "== acceptance =="
  if [ -n "$roam_ue_ip" ]; then
    echo "UE registered on B: YES (uesimtun0 = $roam_ue_ip)"
  else
    echo "UE registered on B: NO -- check: docker logs island-b-roam-ue"
  fi
  if echo "$ausf_evidence" | grep -q "$a_ausf_ip"; then
    echo "B's AMF used A's AUSF/UDM over the overlay: YES"
  else
    echo "B's AMF used A's AUSF/UDM over the overlay: NO"
  fi
  if [ -n "$a_ausf_evidence" ] || [ -n "$a_udm_evidence" ]; then
    echo "A's AUSF/UDM logged the authentication: YES"
  else
    echo "A's AUSF/UDM logged the authentication: NO"
  fi
  echo "B's Mongo subscriber count for $ROAM_IMSI: ${b_mongo_hit:-<query failed>} (want 0)"
  echo
  echo "See TASKS.md 3.3-c for the full negative-finding writeup if any of the above did not hold."
}

# Shared by cmd_roam and cmd_drill (4.1): overlay routes both directions,
# the roaming-test subscriber on A, its policy-only record on B.
roam_prepare() {
  # verify.sh now routes/tests SEPP N32-c/N32-f (3.3-c v2), not direct
  # NRF/UDM -- see that script's own header. Running it both directions
  # also confirms the overlay + forward-filter are healthy before this
  # test builds a real attach attempt on top of them.
  echo "== establishing overlay routes both directions (SEPP N32) =="
  (cd "$A_DIR/stack/federation" && ./verify.sh)
  (cd "$B_DIR/stack/federation" && env "${B_ENV[@]}" ./verify.sh)

  echo "== provisioning roaming-test subscriber on A only (IMSI $ROAM_IMSI) =="
  (
    cd "$A_DIR/stack/core"
    export RESCCOM_SIM_STORE="$(pwd)/.dev-subscribers.db.enc"
    export RESCCOM_SIM_PASSPHRASE="dev-only-ephemeral"
    resccom-sim sub add --test --imsi "$ROAM_IMSI" --if-missing
    resccom-sim db sync --core-dir .
  )

  # 3.3-c v2g review, done 3.3-c v2h: island B's PCF answers SM Policy
  # Association from its OWN local Mongo (`lib/dbi/session.c`
  # ogs_dbi_session_data()), never via SBI/SEPP -- so a roaming subscriber
  # provisioned on A only (above) has nothing there for B's PCF to find,
  # and Local Breakout PDU session establishment rejects with a real 404.
  # The fix is policy-only data, exported from A's store (no security
  # anywhere -- refused on import, not just omitted) and imported into B's
  # Mongo marked resccom_inbound_roamer:true, BEFORE the UE attaches --
  # sim-tools/README.md "Inbound roaming" has the full mechanism and the
  # upstream shared-DB caveat this works around. The export file is an
  # unsigned hand-over between the two checkouts this harness manages --
  # SECURITY.md's lab-profile register names this shortcut.
  echo "== exporting A's roaming subscriber policy (no security) + importing into B =="
  roam_export_file="$A_DIR/stack/federation/data/roam-export.json"
  (
    cd "$A_DIR/stack/core"
    export RESCCOM_SIM_STORE="$(pwd)/.dev-subscribers.db.enc"
    export RESCCOM_SIM_PASSPHRASE="dev-only-ephemeral"
    resccom-sim roaming export --imsi "$ROAM_IMSI" --out "$roam_export_file"
  )
  (cd "$B_DIR/stack/core" && env "${B_ENV[@]}" resccom-sim roaming import "$roam_export_file" --core-dir . --home-plmn 001/01)
}

# --ue oai (TASKS.md 3.3-c v2b): OpenAirInterface's gNB+nrUE over
# rfsimulator, against island B's own core -- unlike
# stack/ran/compose.5g-oai.yaml (hardcoded to island A's own
# core_core_net/10.10.0.x, single-island only), this needs its own
# addressing on B's core_net, so `docker run` with explicit
# --network/--ip rather than that compose file (whose external
# network name is a literal string, not env-var-overridable the way
# every other B-side compose invocation in this script is).
# Sets b_core_net_subnet, b_gnb_ip, b_ue_ip, ran_dir for the nrUE steps.
oai_gnb_up() {
  b_core_net_subnet=$(awk '/^  core_net:/{f=1} f && /subnet:/{print $3; exit}' "$B_DIR/stack/core/compose.yaml")
  read -r b_gnb_ip b_ue_ip <<EOF
$(python3 -c "
import ipaddress
net = ipaddress.ip_network('$b_core_net_subnet')
print(net.network_address + 80, net.network_address + 81)
")
EOF
  ran_dir="$B_DIR/stack/ran"
  # Same four upstream-vs-this-project substitutions
  # stack/ran/config/gnb.sa.rfsim.yaml's own header documents (plmn,
  # amf_ip_address, NETWORK_INTERFACES), generated here rather than
  # committed since they're per-run (B's actual core_net subnet, not
  # assumed) -- same "derived output, not a template target" reasoning
  # as two_island_setup.py's own transient peered island.yaml.
  sed -e "s/mcc: 1/mcc: 999/" -e "s/mnc: 1\$/mnc: 70/" \
      -e "s/10\.10\.0\.5/$(python3 -c "import ipaddress; print(ipaddress.ip_network('$b_core_net_subnet').network_address + 5)")/" \
      -e "s/10\.10\.0\.80/$b_gnb_ip/g" \
      "$ran_dir/config/gnb.sa.rfsim.yaml" > "$ran_dir/config/gnb.sa.rfsim.b.yaml"

  echo "== bringing up island B's own OAI gNB (PLMN 999/70, $b_gnb_ip) =="
  docker run -d --name island-b-oai-gnb --network island-b_core_net --ip "$b_gnb_ip" \
    --cap-add SYS_NICE \
    -e USE_ADDITIONAL_OPTIONS="--rfsim --log_config.global_log_options level,nocolor,time" \
    -v "$ran_dir/config/gnb.sa.rfsim.b.yaml:/opt/oai-gnb/etc/gnb.yaml:ro" \
    oaisoftwarealliance/oai-gnb:2026.w37 >/dev/null
  local ok=0
  # 3.3-c v2c: found live -- 15x2s=30s (this loop's original budget)
  # isn't always enough; a real run through this script (everything
  # else B/A are simultaneously settling: overlay, SEPP routing, A's
  # own just-recreated nrf) took 60s to complete NG Setup, against an
  # isolated manual run's <2s. 60x2s=120s gives real margin over that
  # observed worst case without a real bound on the happy path (the
  # loop exits the moment the log line appears).
  # Gate on live state, not on a log grep: `docker logs | grep` polled
  # from a script misses lines on this host (known quirk -- the review
  # of 3.3-c v2c hit exactly that here: the dumped log below contained
  # "Received NGAP_REGISTER_GNB_CNF" while this loop reported failure).
  # NG Setup done == an ESTABLISHED SCTP association (state 3) from the
  # gNB to the AMF's NGAP port 38412, read from the gNB's own kernel view.
  for _ in $(seq 1 60); do
    if docker exec island-b-oai-gnb cat /proc/net/sctp/assocs 2>/dev/null \
         | awk 'NR>1 && $5==3 && $13==38412 {found=1} END {exit !found}'; then
      ok=1; break
    fi
    sleep 2
  done
  if [ "$ok" -eq 1 ] && docker logs island-b-oai-gnb 2>&1 | grep -q "Received NGAP_REGISTER_GNB_CNF"; then
    echo "   (corroborated by gNB log: Received NGAP_REGISTER_GNB_CNF)"
  fi
  if [ "$ok" -ne 1 ]; then
    echo "-- island-b-oai-gnb's own log (teardown removes the container next) --"
    docker logs island-b-oai-gnb 2>&1
    fail "island B's OAI gNB never completed NG Setup -- see its log above"
  fi
  echo "OK: island B's OAI gNB completed NG Setup"
}

# oai_nrue_config <imsi> <out-file>: stack/ran/config/nrue.uicc.yaml with
# this run's IMSI and B's gNB address swapped in (K/OPc stay the committed
# well-known test vector every rig in this repo uses -- SECURITY.md
# lab-profile register, row 1).
oai_nrue_config() {
  sed -e "s/imsi: \"001010000000002\"/imsi: \"$1\"/" \
      -e "s/10\.10\.0\.80/$b_gnb_ip/" \
      "$ran_dir/config/nrue.uicc.yaml" > "$2"
}

# oai_nrue_up <container> <config-file> <poll-iterations>: starts one
# OAI nrUE against island B's OAI gNB (oai_gnb_up first) and waits up to
# <iterations> x 2s for it to hold a PDU session. Sets roam_ue_ip (empty
# if it never registered -- the caller decides whether that's a failure
# or, in cmd_drill's partition step, the expected result).
oai_nrue_up() {
  local container="$1" cfg="$2" iterations="$3"
  docker run -d --name "$container" --network island-b_core_net --ip "$b_ue_ip" \
    --cap-add NET_ADMIN --cap-add NET_RAW --device /dev/net/tun \
    -e USE_ADDITIONAL_OPTIONS="--rfsim -r 106 --numerology 1 -C 3319680000 --log_config.global_log_options level,nocolor,time" \
    -v "$cfg:/opt/oai-nr-ue/etc/nr-ue.yaml:ro" \
    oaisoftwarealliance/oai-nr-ue:2026.w37 >/dev/null

  roam_ue_ip=""
  # Live-state gate (same reasoning as the gNB gate above): a registered
  # nrUE with a PDU session has an address on oaitun_ue1.
  for _ in $(seq 1 "$iterations"); do
    roam_ue_ip=$(docker exec "$container" ip -4 -o addr show oaitun_ue1 2>/dev/null | awk '{print $4}' | cut -d/ -f1 || true)
    [ -n "$roam_ue_ip" ] && break
    sleep 2
  done
  if [ -n "$roam_ue_ip" ] && docker logs "$container" 2>&1 | grep -q "FGS_REGISTRATION_ACCEPT"; then
    echo "   (corroborated by nrUE log: FGS_REGISTRATION_ACCEPT)"
  fi
}

# breakout_ping <container> <count> <label>: RFC-0003 D1's user-plane
# check -- a ping from the UE to B's own services subnet (B's UPF's
# address there). Sets b_services_subnet, b_upf_ip, ping_out, and
# ping_ok=yes|no (yes only on a literal " 0% packet loss").
breakout_ping() {
  local container="$1" count="$2" label="$3"
  b_services_subnet=$(awk '/^  services_net:/{f=1} f && /subnet:/{print $3; exit}' "$B_DIR/stack/core/compose.yaml")
  b_upf_ip=$(python3 -c "import ipaddress; print(ipaddress.ip_network('$b_services_subnet').network_address + 2)")
  # 3.3-c v2d: OAI's own nrUE (unlike UERANSIM) never adds a route
  # beyond its own PDU session subnet -- stack/ran/verify-5g-oai.sh
  # already carries the identical `ip route add` step for its own
  # (single-island) breakout ping; found live, missing it here reads
  # as "Network is unreachable", not a real connectivity failure.
  # `|| true`: a second ping from the same UE (cmd_drill pings the same
  # session before and during the partition) finds the route already
  # there, and `ip route add` then fails -- which, as the last command of
  # an && list, is exactly the case `set -e` does NOT ignore (found live,
  # 4.1's first drill run died right here at the start of step (b)).
  if [ "$ROAM_UE" = oai ]; then
    docker exec "$container" ip route add "$b_services_subnet" dev oaitun_ue1 2>/dev/null || true
  fi
  echo "== $label: breakout ping to B's own services subnet ($b_upf_ip) =="
  ping_out=$(docker exec "$container" ping -c "$count" -W 2 "$b_upf_ip" 2>&1 || true)
  echo "$ping_out"
  # Leading space matters: "100% packet loss" also contains "0% packet loss".
  if echo "$ping_out" | grep -q " 0% packet loss"; then
    ping_ok=yes
  else
    ping_ok=no
  fi
}

cmd_roam() {
  trap cmd_down EXIT
  cmd_up
  roam_prepare

  roam_started=$(date -u +%Y-%m-%dT%H:%M:%S)
  msisdn="${ROAM_IMSI#00101}"
  roam_ue_container="island-b-roam-ue"

  if [ "$ROAM_UE" = ueransim ]; then
    # Island B's own gNB has to broadcast *B's* PLMN (999/70), not the
    # compose.sim.yaml default (001/01, correct for a same-PLMN local UE
    # but wrong the moment islands have distinct PLMNs) -- overridden here
    # via `run -e` rather than templating compose.sim.yaml itself, since
    # this is this test's own concern, not every island's.
    echo "== bringing up island B's own gNB (PLMN 999/70, UERANSIM) =="
    (cd "$B_DIR/stack/core" && env "${B_ENV[@]}" docker compose -f compose.yaml -f compose.sim.yaml \
      run -d --name island-b-roam-gnb -e MCC=999 -e MNC=70 gnb)

    # The roaming UE itself keeps *A's* home PLMN (001/01, ue.yaml's
    # mcc/mnc, documented as HPLMN) while MSISDN gives it A's IMSI block.
    # --no-deps is required, not optional: found live, without it `run ue`
    # sees the "gnb" *service* has no container satisfying its own
    # bookkeeping (island-b-roam-gnb's custom name doesn't count) and
    # silently creates a second, *default* gNB (MCC/MNC 001/01,
    # compose.sim.yaml's own hardcoded values) to satisfy `depends_on` --
    # the roaming UE then found two cells and attached to the wrong one.
    # GNB_HOSTNAME must be the container's own literal name, not "gnb":
    # found live, a compose *service* DNS alias is only registered for
    # containers compose itself named -- `run --name` opts a container out
    # of it, so the default GNB_HOSTNAME=gnb resolves to nothing ("Bad
    # Inet address: null") once no default-named gnb container exists.
    echo "== attaching the roaming UE (home PLMN 001/01, MSISDN $msisdn) via island B's gNB =="
    (cd "$B_DIR/stack/core" && env "${B_ENV[@]}" docker compose -f compose.yaml -f compose.sim.yaml \
      run -d --no-deps --name island-b-roam-ue -e MSISDN="$msisdn" -e GNB_HOSTNAME=island-b-roam-gnb ue)

    roam_ue_ip=""
    for _ in $(seq 1 15); do
      roam_ue_ip=$(docker exec island-b-roam-ue ip -4 -o addr show uesimtun0 2>/dev/null | awk '{print $4}' | cut -d/ -f1 || true)
      [ -n "$roam_ue_ip" ] && break
      sleep 2
    done
  else
    roam_ue_container="island-b-oai-nrue"
    oai_gnb_up
    oai_nrue_config "$ROAM_IMSI" "$ran_dir/config/nrue.uicc.b.yaml"
    echo "== attaching the roaming nrUE (home PLMN 001/01, IMSI $ROAM_IMSI) via island B's OAI gNB =="
    oai_nrue_up "$roam_ue_container" "$ran_dir/config/nrue.uicc.b.yaml" 30
  fi

  echo
  echo "== evidence =="
  roam_ue_log=$(docker logs "$roam_ue_container" 2>&1 || true)
  echo "-- the roaming UE's own log (RRC/NAS state -- shows exactly how far it got) --"
  echo "${roam_ue_log:-<no log>}"
  b_amf_log=$(env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" logs amf --since "$roam_started" 2>&1 || true)
  b_sepp_log=$(env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" logs sepp --since "$roam_started" 2>&1 || true)
  echo "-- B's AMF log since the roaming attach attempt --"
  echo "${b_amf_log:-<no new AMF log lines>}"
  echo "-- B's SEPP log since the roaming attach attempt --"
  echo "${b_sepp_log:-<no new SEPP log lines>}"

  a_sepp_log=$(docker compose -f "$A_DIR/stack/core/compose.yaml" logs sepp --since "$roam_started" 2>&1 || true)
  echo "-- A's SEPP log since the roaming attach attempt (RFC-0003 D5: A's home log of the roaming event) --"
  echo "${a_sepp_log:-<no new SEPP log lines>}"

  # 3.3-c v2f follow-up: dump B's own V-SMF log unconditionally. LBO roaming
  # anchors the PDU session at B's local SMF, so when session establishment
  # fails (v2f found a fast application-level reject one hop past a correct
  # LBO selection) this is where the cause is stated -- previously only
  # grepped, never printed, and the container is gone by teardown.
  b_smf_full_log=$(env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" logs smf --since "$roam_started" 2>&1 || true)
  echo "-- B's SMF log since the roaming attach attempt (LBO anchor -- PDU session establishment) --"
  echo "${b_smf_full_log:-<no new SMF log lines>}"

  # 3.3-c v2e: the previous check ("A's AUSF/UDM logged an authentication
  # request") was log-level dependent -- at info level (the lab default)
  # Open5GS's AUSF/UDM print no per-UE lines at all, so it read NO even
  # when authentication demonstrably went home (v2d review, corrected
  # 2026-09-16). Evidence that survives at info level instead: A's SEPP
  # itself logs "Setup NF EndPoint(fqdn) [ausf.5gc.mnc<home>...]" and
  # "[udm.5gc.mnc<home>...]" when it forwards the roaming subscriber's
  # AUSF/UDM requests to A's real NFs (3.3-c v2d's own signature check).
  a_sepp_ausf_fwd=$(echo "$a_sepp_log" | grep -i "Setup NF EndPoint(fqdn) \[ausf\.5gc\.mnc" || true)
  a_sepp_udm_fwd=$(echo "$a_sepp_log" | grep -i "Setup NF EndPoint(fqdn) \[udm\.5gc\.mnc" || true)

  # Corroborating negative check: if authentication genuinely stayed home
  # (K never left A), B's own AUSF/UDM must show nothing for this
  # subscriber's SUCI. Scoped to the roaming IMSI's own MSIN (its last 10
  # digits, the SUCI's own final segment) -- not just the mcc/mnc/routing-
  # indicator prefix, which island A's own already-attached local UE
  # (001010000000001, same home PLMN) also matches (3.3-c v2c false-
  # positive fix, same reasoning applied here to B's side).
  a_msin="${ROAM_IMSI:5}"
  b_ausf_log=$(env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" logs ausf --since "$roam_started" 2>&1 | grep -i "$a_msin" || true)
  b_udm_log=$(env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" logs udm --since "$roam_started" 2>&1 | grep -i "$a_msin" || true)

  # Local-Breakout evidence (3.3-c v2e, RFC-0003 D1): B's own SMF must
  # anchor the session -- "UE SUPI[imsi-<roam>] ... IPv4[<addr>]", the
  # same line shape v2d found A's SMF logging for the Home-Routed case --
  # with the address inside B's own UE pool, and no "HR Roaming in V-SMF"
  # (src/smf/gsm-sm.c:345, HOME_ROUTED_ROAMING_IN_VSMF(sess)) for this IMSI.
  b_smf_log=$(env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" logs smf --since "$roam_started" 2>&1 || true)
  b_smf_supi_line=$(echo "$b_smf_log" | grep -i "UE SUPI\[imsi-$ROAM_IMSI\]" || true)
  b_smf_ip=$(echo "$b_smf_supi_line" | sed -n 's/.*IPv4\[\([0-9.]*\)\].*/\1/p' | head -1)
  b_smf_hr=$(echo "$b_smf_log" | grep -i "HR Roaming in V-SMF" | grep -i "imsi-$ROAM_IMSI" || true)
  b_ue_subnet=$(awk '/subnet:/{print $3; exit}' "$B_DIR/stack/core/config/upf.yaml")
  b_smf_ip_in_pool=no
  if [ -n "$b_smf_ip" ] && [ -n "$b_ue_subnet" ]; then
    b_smf_ip_in_pool=$(python3 -c "
import ipaddress
print('yes' if ipaddress.ip_address('$b_smf_ip') in ipaddress.ip_network('$b_ue_subnet') else 'no')
")
  fi

  # A's own SMF/UPF must log nothing for the roaming IMSI: if the session
  # were still Home-Routed (v2d's finding), A's SMF/UPF would be the ones
  # anchoring it, exactly as the pre-v2e evidence showed.
  a_smf_log=$(docker compose -f "$A_DIR/stack/core/compose.yaml" logs smf --since "$roam_started" 2>&1 | grep -i "imsi-$ROAM_IMSI\|$a_msin" || true)
  a_upf_log=$(docker compose -f "$A_DIR/stack/core/compose.yaml" logs upf --since "$roam_started" 2>&1 | grep -i "imsi-$ROAM_IMSI\|$a_msin" || true)

  # 3.3-c v2h: superseded the old "want 0" check -- B's Mongo is now
  # SUPPOSED to hold the roaming subscriber, as the marked, policy-only
  # inbound-roamer record `roaming import` wrote above. Query the full
  # document set (not just a count) so "exactly one, marked, no security"
  # is checked explicitly rather than assumed from a count alone.
  b_mongo_docs=$(env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" exec -T mongo \
    mongosh --quiet open5gs --eval "JSON.stringify(db.subscribers.find({imsi:'$ROAM_IMSI'}).toArray())" 2>&1 || true)
  b_mongo_check=$(python3 -c "
import json, sys
try:
    docs = json.loads(sys.stdin.read())
    if not isinstance(docs, list):
        raise ValueError('not a list')
except Exception:
    print('count=? marked=no no_security=no')
else:
    count = len(docs)
    marked = count == 1 and docs[0].get('resccom_inbound_roamer') is True
    no_security = count == 1 and 'security' not in docs[0]
    print(f'count={count} marked={\"yes\" if marked else \"no\"} no_security={\"yes\" if no_security else \"no\"}')
" <<< "$b_mongo_docs")

  echo
  echo "== acceptance =="
  if [ -n "$roam_ue_ip" ]; then
    ue_ip_in_pool=no
    if [ -n "$b_ue_subnet" ]; then
      ue_ip_in_pool=$(python3 -c "
import ipaddress
print('yes' if ipaddress.ip_address('$roam_ue_ip') in ipaddress.ip_network('$b_ue_subnet') else 'no')
")
    fi
    if [ "$ue_ip_in_pool" = yes ]; then
      echo "UE registered on B: YES ($roam_ue_ip, in B's UE pool $b_ue_subnet -- RFC-0003 D1 Local Breakout)"
    else
      echo "UE registered on B: YES ($roam_ue_ip) but NOT in B's UE pool ($b_ue_subnet) -- session may still be Home-Routed, see B's SMF evidence below"
    fi
  elif [ "$ROAM_UE" = ueransim ]; then
    echo "UE registered on B: NO -- see the roaming UE's own log above."
    echo "  If it shows a cell found as category[ACCEPTABLE] (not SUITABLE) followed by"
    echo "  MM-DEREGISTERED/LIMITED-SERVICE, that is TASKS.md 3.3-c v2's negative finding:"
    echo "  UERANSIM v3.3.0's own PLMN selection (src/ue/rrc/idle.cpp"
    echo "  lookForSuitableCell) only treats a cell as SUITABLE when its broadcast PLMN"
    echo "  equals the UE's configured mcc/mnc -- any other PLMN, including the one"
    echo "  actually connected to, is downgraded to ACCEPTABLE/limited-service and never"
    echo "  attempts registration. Not a bug in this render pipeline or in SEPP/N32 --"
    echo "  see the SEPP evidence above, which is unaffected by this."
    echo "  Re-run with --ue oai for the UE that does attempt registration on a"
    echo "  visited PLMN (TASKS.md 3.3-c v2b)."
  else
    echo "UE registered on B: NO -- see the roaming UE's own log above."
    echo "  If it shows 'Registration Reject cause: Payload_was_not_forwarded', that is"
    echo "  TASKS.md 3.3-c v2b's negative finding: unlike UERANSIM, OAI's nrUE *does*"
    echo "  attempt registration on a visited PLMN (its own RRC source has no PLMN-"
    echo "  suitability check), and B's AMF does correctly trigger home-routed discovery"
    echo "  (target_plmn_list/requester_plmn_list) for the roaming SUCI -- but Open5GS's"
    echo "  own inter-PLMN NRF discovery (TS29.510 5.3.2.2.3, no hnrf-uri) returns an"
    echo "  empty result even once its FQDN/port gaps are worked around (3.3-c v2b (1)),"
    echo "  so AMF has no AUSF candidate to use. See B's AMF/NRF evidence above."
  fi
  if [ -n "$a_sepp_log" ]; then
    echo "A's SEPP saw N32 activity from B (home-routed path reached A): YES"
  else
    echo "A's SEPP saw N32 activity from B (home-routed path reached A): NO"
  fi
  if [ -n "$a_sepp_ausf_fwd" ] && [ -n "$a_sepp_udm_fwd" ]; then
    echo "A's SEPP forwarded the AUSF and UDM requests (authentication served at home): YES"
  else
    echo "A's SEPP forwarded the AUSF and UDM requests (authentication served at home): NO"
  fi
  if [ -z "$b_ausf_log" ] && [ -z "$b_udm_log" ]; then
    echo "B's AUSF/UDM logged nothing for the roaming MSIN (K never left A): YES"
  else
    echo "B's AUSF/UDM logged nothing for the roaming MSIN (K never left A): NO"
  fi
  if [ "$b_smf_ip_in_pool" = yes ] && [ -z "$b_smf_hr" ]; then
    echo "B's SMF anchored the session locally, address $b_smf_ip in B's UE pool, no 'HR Roaming in V-SMF': YES"
  else
    echo "B's SMF anchored the session locally (Local Breakout): NO$([ -n "$b_smf_hr" ] && echo " -- 'HR Roaming in V-SMF' found")"
  fi
  if [ -z "$a_smf_log" ] && [ -z "$a_upf_log" ]; then
    echo "A's SMF/UPF logged nothing for the roaming IMSI: YES"
  else
    echo "A's SMF/UPF logged nothing for the roaming IMSI: NO"
  fi
  if [ "$b_mongo_check" = "count=1 marked=yes no_security=yes" ]; then
    echo "B's Mongo holds exactly one marked, policy-only record for $ROAM_IMSI (no security field): YES ($b_mongo_check)"
  else
    echo "B's Mongo holds exactly one marked, policy-only record for $ROAM_IMSI (no security field): NO ($b_mongo_check)"
  fi

  if [ -n "$roam_ue_ip" ]; then
    breakout_ping "$roam_ue_container" 3 "RFC-0003 D1 (sessions/services stay local)"
    if [ "$ping_ok" = yes ]; then
      echo "OK: breakout served by B's own SMF/UPF ($b_upf_ip), 0% packet loss"
    else
      echo "breakout ping to B's own services subnet ($b_upf_ip): FAILED (not 0% packet loss)"
    fi
  fi

  echo "See TASKS.md 3.3-c v2h for the acceptance writeup (pass, or a negative finding) if any of the above did not hold."
}

# 4.1 -- the partition drill. See the header's `drill` entry for the
# sequence and why each step is shaped the way it is.
#
# The guest identity for step (d): inside B's own imsi_block (99970,
# island.example.b.yaml) and deliberately NOT the roamer's home IMSI --
# a guest is a new, local subscriber B issues itself (full credentials in
# B's own store), not a copy of someone else's identity. K/OPc are the
# same well-known 3GPP test vector every rig in this repo already uses
# (stack/ran/config/nrue.uicc.yaml, sim-tools `--test`; SECURITY.md
# lab-profile register, row 1) -- the guest nrUE config is derived from
# that same committed file, so the two must agree.
GUEST_IMSI="999700000000001"
TEST_K="465B5CE8B199B49FAA5F0A2EE238A6BC"
TEST_OPC="E8ED289DEBA952E4283B54E88E6183CA"

b_wg_container() {
  (cd "$B_DIR/stack/federation" && env "${B_ENV[@]}" docker compose -f compose.yaml -f compose.wan.yaml ps -q wg-overlay)
}

# Live overlay state, from the same probe verify.sh uses: a bounded TCP
# connect from B's sepp to A's SEPP, over the tunnel. Probes BOTH N32
# ports, not just N32-c: 4.1's first drill run found the N32-c port (7778)
# unreachable while the *N32-f* port (7779, the one home-routed
# authentication actually forwards over) was still carrying a real 201
# response home -- a `docker network disconnect` of B's wg-overlay left
# an asymmetric, half-open partition, so a 7778-only probe read "down"
# while auth still reached home. The drill now stops the wg-overlay
# container outright (cmd_drill step (b)), which cannot carry either
# port, and this probe gates on both. overlay_reachable=yes only if BOTH
# answer; overlay_reachable=no only if NEITHER does; a split reads
# "partial" and is treated as still-up (fail-safe: never call a partition
# real unless it demonstrably is). Also reports B's wg0 last-handshake age.
overlay_probe() {
  local a_sepp="$1" hs now c f wgc
  if env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" exec -T sepp \
       timeout 4 bash -c "echo -n > /dev/tcp/$a_sepp/7778" 2>/dev/null; then c=yes; else c=no; fi
  if env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" exec -T sepp \
       timeout 4 bash -c "echo -n > /dev/tcp/$a_sepp/7779" 2>/dev/null; then f=yes; else f=no; fi
  if [ "$c" = yes ] && [ "$f" = yes ]; then
    overlay_reachable=yes
  elif [ "$c" = no ] && [ "$f" = no ]; then
    overlay_reachable=no
  else
    overlay_reachable=partial
  fi
  wgc=$(b_wg_container)
  hs=""
  [ -n "$wgc" ] && hs=$(docker exec "$wgc" wg show wg0 latest-handshakes 2>/dev/null | awk '{print $2}' | head -1 || true)
  now=$(date +%s)
  if [ -n "${hs:-}" ] && [ "$hs" -gt 0 ] 2>/dev/null; then
    echo "   B sepp -> A SEPP over the overlay: N32-c($a_sepp:7778)=$c N32-f($a_sepp:7779)=$f -> $overlay_reachable; B's wg0 last handshake $((now - hs))s ago"
  else
    echo "   B sepp -> A SEPP over the overlay: N32-c($a_sepp:7778)=$c N32-f($a_sepp:7779)=$f -> $overlay_reachable; B's wg-overlay not running or no handshake"
  fi
}

cmd_drill() {
  [ "$ROAM_UE" = oai ] || fail "drill needs --ue oai: UERANSIM never attempts registration on a visited PLMN (TASKS.md 3.3-c v2), so there is no roamer to drill"
  trap cmd_down EXIT
  cmd_up
  roam_prepare

  local a_core_subnet a_sepp_ip b_ue_subnet step_started
  local verdicts=()
  a_core_subnet=$(awk '/^  core_net:/{f=1} f && /subnet:/{print $3; exit}' "$A_DIR/stack/core/compose.yaml")
  a_sepp_ip=$(python3 -c "import ipaddress; print(ipaddress.ip_network('$a_core_subnet').network_address + 16)")
  b_ue_subnet=$(awk '/subnet:/{print $3; exit}' "$B_DIR/stack/core/config/upf.yaml")
  drill_started=$(date -u +%Y-%m-%dT%H:%M:%S)

  oai_gnb_up
  oai_nrue_config "$ROAM_IMSI" "$ran_dir/config/nrue.uicc.b.yaml"

  echo
  echo "#### drill step (a): roamer attached, served by Local Breakout on B (the M3 state) ####"
  step_started=$(date -u +%Y-%m-%dT%H:%M:%S)
  echo "== attaching the roaming nrUE (home PLMN 001/01, IMSI $ROAM_IMSI) via island B's OAI gNB =="
  oai_nrue_up island-b-oai-nrue "$ran_dir/config/nrue.uicc.b.yaml" 30
  if [ -z "$roam_ue_ip" ]; then
    docker logs island-b-oai-nrue 2>&1 | tail -40
    fail "step (a): the roamer never registered -- the M3 state this drill starts from is not there (run roam --ue oai to diagnose)"
  fi
  local a_ip="$roam_ue_ip" a_sepp_fwd ping_a
  a_sepp_fwd=$(docker compose -f "$A_DIR/stack/core/compose.yaml" logs sepp --since "$step_started" 2>&1 | grep -i "Setup NF EndPoint(fqdn) \[\(ausf\|udm\)\.5gc\.mnc" || true)
  echo "-- A's SEPP forwarding lines since the attach (authentication served at home) --"
  echo "${a_sepp_fwd:-<none>}"
  breakout_ping island-b-oai-nrue 5 "step (a), overlay up"
  ping_a="$ping_ok"
  overlay_probe "$a_sepp_ip"
  if [ "$ping_a" = yes ] && [ -n "$a_sepp_fwd" ]; then
    verdicts+=("(a) roamer registered ($a_ip, in B's pool $b_ue_subnet), auth forwarded home by A's SEPP, breakout 0% loss: AS EXPECTED")
  else
    verdicts+=("(a) roamer registered ($a_ip) but breakout_ok=$ping_a, A-SEPP-forwarded=$([ -n "$a_sepp_fwd" ] && echo yes || echo no): DIFFERENT FROM EXPECTED")
  fi

  echo
  echo "#### drill step (b): drop the overlay -- does the ESTABLISHED session keep passing user plane? ####"
  local session_up_at partition_at ping_b
  session_up_at=$(date +%s)
  # Stop the wg-overlay container, don't just disconnect it from wan_net:
  # 4.1's first run found `docker network disconnect` left an asymmetric
  # partition (N32-c dead, N32-f still forwarding a real 201 home), so the
  # "fresh registration fails" step didn't actually test a partition. A
  # stopped container runs no WireGuard at all and cannot carry either
  # port -- the same link verify.sh brings up and tests. The ESTABLISHED
  # PDU session does not traverse wg-overlay (it is anchored at B's own
  # UPF), so stopping it must not disturb the session -- which is exactly
  # what this step measures.
  echo "== stopping B's wg-overlay (severs the inter-island link; the local session must not care) =="
  (cd "$B_DIR/stack/federation" && env "${B_ENV[@]}" docker compose -f compose.yaml -f compose.wan.yaml stop wg-overlay)
  partition_at=$(date +%s)
  sleep 3
  overlay_probe "$a_sepp_ip"
  [ "$overlay_reachable" = no ] || fail "step (b): B can still reach A's SEPP (N32 probe = $overlay_reachable) after stopping wg-overlay -- the partition never happened, nothing below would mean anything"
  breakout_ping island-b-oai-nrue 5 "step (b), overlay DOWN"
  ping_b="$ping_ok"
  if [ "$ping_b" = yes ]; then
    verdicts+=("(b) established session kept passing user plane with the overlay down, breakout 0% loss: AS EXPECTED (B's own UPF anchors it)")
  else
    verdicts+=("(b) established session did NOT keep passing user plane with the overlay down (breakout_ok=$ping_b): DIFFERENT FROM EXPECTED")
  fi

  echo
  echo "#### drill step (c): overlay still down -- force a fresh registration of the roamer ####"
  step_started=$(date -u +%Y-%m-%dT%H:%M:%S)
  echo "== detaching the roamer (removing its nrUE) and re-attaching it with the overlay down =="
  docker rm -f island-b-oai-nrue >/dev/null
  oai_nrue_up island-b-oai-nrue "$ran_dir/config/nrue.uicc.b.yaml" 25
  local c_ip="$roam_ue_ip" b_amf_c b_amf_c_lines nrue_c b_amf_c_fail b_amf_c_reject
  b_amf_c=$(env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" logs amf --since "$step_started" 2>&1 || true)
  # The lines that name the outcome of a home-routed auth that can't reach
  # home: AMF tries nausf-auth, the SBI request to B's own SEPP can't be
  # answered (SEPP has no live N32 to A), the 10s SBI timer fires, AMF
  # rejects. Any of these is the signature.
  b_amf_c_lines=$(echo "$b_amf_c" | grep -iE "Registration request|Try to discover \[nausf-auth\]|Cannot receive SBI message|Registration reject|nas_5gs_send_registration_reject|Couldn't connect|Connection refused|timed out" || true)
  b_amf_c_fail=$(echo "$b_amf_c" | grep -iE "Cannot receive SBI message|Couldn't connect|Connection refused|timed out" || true)
  b_amf_c_reject=$(echo "$b_amf_c" | grep -iE "Registration reject|nas_5gs_send_registration_reject" || true)
  nrue_c=$(docker logs island-b-oai-nrue 2>&1 | grep -iE "Registration (Reject|Accept)|FGS_REGISTRATION|Payload_was_not_forwarded" || true)
  echo "-- B's AMF log since the re-attach (the lines that name the outcome) --"
  echo "${b_amf_c_lines:-<no matching AMF lines -- full AMF log since the re-attach follows>}"
  [ -n "$b_amf_c_lines" ] || echo "$b_amf_c"
  echo "-- B's SEPP log since the re-attach (its attempt to forward the auth to A, now unreachable) --"
  env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" logs sepp --since "$step_started" 2>&1 | grep -iE "Cannot|error|refused|timed out|nausf|Setup NF EndPoint\(fqdn\) \[ausf" || echo "   <no forward-attempt or error lines in B's SEPP log>"
  echo "-- the roamer nrUE's own NAS outcome --"
  echo "${nrue_c:-<no registration outcome line in the nrUE log>}"
  if [ -z "$c_ip" ] && { [ -n "$b_amf_c_reject" ] || [ -n "$b_amf_c_fail" ]; }; then
    verdicts+=("(c) fresh registration with home unreachable: FAILED at B's AMF (auth to home timed out / rejected), no PDU session: AS EXPECTED (B holds no key for the roamer -- the measured partition limit)")
  elif [ -z "$c_ip" ]; then
    verdicts+=("(c) fresh registration with home unreachable: no PDU session, but B's AMF log named no auth-timeout or reject: DIFFERENT FROM EXPECTED (see the log above)")
  else
    verdicts+=("(c) fresh registration with home unreachable SUCCEEDED ($c_ip): DIFFERENT FROM EXPECTED -- the partition may not be real; see B's AMF/SEPP log above")
  fi

  echo
  echo "#### drill step (d): guest provisioning on B (RFC-0003 D3 fallback), home still unreachable ####"
  step_started=$(date -u +%Y-%m-%dT%H:%M:%S)
  overlay_probe "$a_sepp_ip"
  echo "== provisioning a LOCAL B subscriber (IMSI $GUEST_IMSI, B's own block, full credentials in B's own store) =="
  (
    cd "$B_DIR/stack/core"
    export RESCCOM_SIM_STORE="$(pwd)/.dev-subscribers.db.enc"
    export RESCCOM_SIM_PASSPHRASE="dev-only-ephemeral"
    resccom-sim sub add --imsi "$GUEST_IMSI" --key "$TEST_K" --opc "$TEST_OPC" --label "4.1 drill guest" --if-missing
    env "${B_ENV[@]}" resccom-sim db sync --core-dir .
  )
  local b_mongo_now
  # Never prints a key: only which documents exist, whether each is a
  # marked inbound-roamer record, and whether it carries a security block.
  b_mongo_now=$(env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" exec -T mongo \
    mongosh --quiet open5gs --eval "JSON.stringify(db.subscribers.find({}, {imsi:1, resccom_inbound_roamer:1, security:1, _id:0}).toArray().map(d => ({imsi: d.imsi, inbound_roamer: d.resccom_inbound_roamer === true, has_security: 'security' in d})))" 2>&1 || true)
  echo "-- B's Mongo subscribers now (want: guest local WITH security, roamer marked WITHOUT) --"
  echo "$b_mongo_now"
  echo "== swapping the phone-analog to the guest identity (removing the roamer nrUE, attaching a guest nrUE) =="
  docker rm -f island-b-oai-nrue >/dev/null
  oai_nrue_config "$GUEST_IMSI" "$ran_dir/config/nrue.uicc.guest.yaml"
  oai_nrue_up island-b-oai-guest "$ran_dir/config/nrue.uicc.guest.yaml" 30
  local d_ip="$roam_ue_ip" ping_d=no b_smf_guest guest_msin b_ausf_guest
  b_smf_guest=$(env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" logs smf --since "$step_started" 2>&1 | grep -i "UE SUPI\[imsi-$GUEST_IMSI\]" || true)
  # The guest is B's OWN subscriber (home PLMN 999/70): B's own AUSF/UDM
  # authenticate it locally, with no SEPP hop at all. That local
  # authentication is the positive signal the guest path is genuinely
  # local -- unambiguous, unlike grepping A's SEPP (which logs its own
  # startup/periodic NF-setup noise regardless, 4.1 run 1). And the
  # overlay is asserted down (step b), so nothing could reach A anyway.
  guest_msin="${GUEST_IMSI:5}"
  b_ausf_guest=$(env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" logs ausf udm --since "$step_started" 2>&1 | grep -i "$guest_msin" | grep -iE "auth|SUPI|SUCI|imsi" | head -5 || true)
  echo "-- B's SMF line for the guest (anchored locally) --"
  echo "${b_smf_guest:-<none>}"
  echo "-- B's own AUSF/UDM lines for the guest MSIN (authenticated locally, no SEPP hop) --"
  echo "${b_ausf_guest:-<none at this log level; the SMF anchor line above is the local-service signal>}"
  if [ -n "$d_ip" ]; then
    breakout_ping island-b-oai-guest 5 "step (d), guest, overlay DOWN"
    ping_d="$ping_ok"
  else
    docker logs island-b-oai-guest 2>&1 | tail -30
  fi
  if [ -n "$d_ip" ] && [ "$ping_d" = yes ] && [ -n "$b_smf_guest" ]; then
    verdicts+=("(d) guest $GUEST_IMSI registered on B with home unreachable ($d_ip), anchored by B's own SMF, breakout 0% loss: AS EXPECTED (the local-guest fallback, no home island needed)")
  else
    verdicts+=("(d) guest registered=$([ -n "$d_ip" ] && echo "yes ($d_ip)" || echo no), B-SMF-anchored=$([ -n "$b_smf_guest" ] && echo yes || echo no), breakout_ok=$ping_d: DIFFERENT FROM EXPECTED")
  fi

  echo
  echo "#### drill step (e): restore the overlay -- the original roamer registers again ####"
  step_started=$(date -u +%Y-%m-%dT%H:%M:%S)
  docker rm -f island-b-oai-guest >/dev/null
  echo "== starting B's wg-overlay again (restores the inter-island link) =="
  local restore_at overlay_recovery_s="" i c7778 f7779
  restore_at=$(date +%s)
  (cd "$B_DIR/stack/federation" && env "${B_ENV[@]}" docker compose -f compose.yaml -f compose.wan.yaml start wg-overlay)
  # Recovery is timed on BOTH N32 ports coming back (not 7778 alone --
  # step (b)'s finding), since home-routed auth needs N32-f (7779).
  for i in $(seq 1 90); do
    c7778=no; f7779=no
    env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" exec -T sepp timeout 2 bash -c "echo -n > /dev/tcp/$a_sepp_ip/7778" 2>/dev/null && c7778=yes
    env "${B_ENV[@]}" docker compose -f "$B_DIR/stack/core/compose.yaml" exec -T sepp timeout 2 bash -c "echo -n > /dev/tcp/$a_sepp_ip/7779" 2>/dev/null && f7779=yes
    if [ "$c7778" = yes ] && [ "$f7779" = yes ]; then
      overlay_recovery_s=$(( $(date +%s) - restore_at ))
      break
    fi
    sleep 1
  done
  overlay_probe "$a_sepp_ip"
  if [ -n "$overlay_recovery_s" ]; then
    echo "   A's SEPP (both N32 ports) reachable from B again: ${overlay_recovery_s}s after wg-overlay restarted"
  else
    echo "   A's SEPP NOT reachable from B again within 90s of wg-overlay restart"
  fi
  echo "== re-attaching the original roamer (IMSI $ROAM_IMSI) =="
  oai_nrue_up island-b-oai-nrue "$ran_dir/config/nrue.uicc.b.yaml" 45
  local e_ip="$roam_ue_ip" reg_recovery_s="" a_sepp_e ping_e=no
  [ -n "$e_ip" ] && reg_recovery_s=$(( $(date +%s) - restore_at ))
  a_sepp_e=$(docker compose -f "$A_DIR/stack/core/compose.yaml" logs sepp --since "$step_started" 2>&1 | grep -i "Setup NF EndPoint(fqdn) \[\(ausf\|udm\)\.5gc\.mnc" || true)
  echo "-- A's SEPP forwarding lines since the restore --"
  echo "${a_sepp_e:-<none>}"
  if [ -n "$e_ip" ]; then
    breakout_ping island-b-oai-nrue 5 "step (e), roamer back, overlay up"
    ping_e="$ping_ok"
  else
    docker logs island-b-oai-nrue 2>&1 | grep -iE "Registration|FGS_" | tail -10
  fi
  if [ -n "$e_ip" ] && [ -n "$a_sepp_e" ] && [ "$ping_e" = yes ]; then
    verdicts+=("(e) roamer registered again ($e_ip) via A's SEPP, breakout 0% loss; A reachable ${overlay_recovery_s}s and roamer registered ${reg_recovery_s}s after the reconnect: AS EXPECTED")
  else
    verdicts+=("(e) roamer registered=$([ -n "$e_ip" ] && echo yes || echo no), A-SEPP-forwarded=$([ -n "$a_sepp_e" ] && echo yes || echo no), breakout_ok=$ping_e, A reachable after ${overlay_recovery_s:-?}s: DIFFERENT FROM EXPECTED")
  fi

  echo
  echo "== RFC-0003 D5: A's SEPP log for the whole drill (the home island's own record of the roaming events) =="
  docker compose -f "$A_DIR/stack/core/compose.yaml" logs sepp --since "$drill_started" 2>&1 || true
  echo
  echo "== island A's own UE, untouched throughout (3.2-e multi-rig scenario) =="
  ue_ip=$(a_ue_ip)
  echo "   island A's UE uesimtun0 = ${ue_ip:-<gone>}"

  echo
  echo "== drill summary (as measured, $(date -u +%Y-%m-%dT%H:%M:%SZ)) =="
  local v n_ok=0
  for v in "${verdicts[@]}"; do
    echo "  $v"
    case "$v" in *"AS EXPECTED"*) n_ok=$((n_ok + 1)) ;; esac
  done
  echo "  session had been up $((partition_at - session_up_at))s when the overlay dropped; overlay down for $((restore_at - partition_at))s"
  echo
  echo "DRILL COMPLETE: $n_ok/5 steps as expected -- TASKS.md 4.1 records what each result means"
}

case "${1:-}" in
  up) cmd_up ;;
  down) cmd_down ;;
  verify) cmd_verify ;;
  roam) cmd_roam ;;
  roam-legacy) cmd_roam_legacy ;;
  drill) cmd_drill ;;
  *) echo "Usage: $0 [--b-dir <path>] [--ue oai|ueransim] [--log-level <level>] {up|down|verify|roam|roam-legacy|drill}" >&2; exit 1 ;;
esac
