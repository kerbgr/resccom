#!/usr/bin/env bash
# ResCCOM 1.3-f — one-command island: brings up (or down, or reports the
# status of) the real stack — stack/core, then stack/services (DNS +
# portal + NOMAD + Matrix + Jitsi) — in the right order, tearing down in
# reverse. On a fresh checkout, `up` also generates every secret and
# self-signed cert each component needs (from the *.example.env/.yaml
# templates already committed in this repo — see each component's own
# README for what's in them) so this genuinely is a single command
# on a fresh host, not "one command after some manual setup." It also
# bootstraps island-init/island.yaml (via `island-init new --lab`), the
# per-instance render outputs render_instance_outputs derives from it
# (portal settings, LIS geometry — 2.1-g, gitignored: see
# island_init/render.py's own comments on why these live under data/,
# not the tracked config/ paths they used to), and a fresh per-boot
# Island Console operator token — see bootstrap_island_init and
# bootstrap_console_token below, and island-init/TASKS.md 2.1-f/2.1-g for
# why: a fresh clone has none of these, and stack/services/compose.yaml's
# console and portal services bind-mount them directly.
#
# `island.sh apply` is separate from `up`: it's the host-side half of the
# Island Console's Apply flow (RFC-0006 D5) -- signing island.yaml and
# restarting affected services never happens inside the console
# container, only here, run by an operator on the node.
#
# Deliberately does NOT touch the UERANSIM UE/gNB simulator
# (stack/core/compose.sim.yaml) — that's test tooling for a human or
# stack/services/verify.sh to drive against a running island, standing
# in for a real phone; it isn't part of the island itself. [SIM] path
# only in the sense that everything this script brings up is the same
# whether the radio side is UERANSIM or a real srsRAN+SDR — see
# stack/README.md.
#
# `--island <dir>` (3.3-a, stack/federation/TASKS.md): operate against a
# second rendered tree instead of this script's own checkout -- "two
# islands on one host" means two full copies of stack/core (each rendered
# from a different island.yaml, so each has its own core_net/allocations,
# 3.3-a 1/3), brought up as two independent compose projects. Set
# COMPOSE_PROJECT_NAME (island A's default, unset, still yields today's
# literal container/network names) before calling so the two projects'
# containers and services_net don't collide -- SERVICES_NET_NAME follows
# it automatically below; AMF_NGAP_PORT (the host-published SCTP port,
# only relevant to real/attached radio hardware, never to the UERANSIM
# sim rig) is the operator's to set explicitly if both islands need a
# real gNB attached at once.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ISLAND_ROOT="$SCRIPT_DIR"

args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --island)
      [ -n "${2:-}" ] || { echo "FAIL: --island needs a directory argument" >&2; exit 1; }
      ISLAND_ROOT="$(cd "$2" && pwd)"
      shift 2
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done
set -- "${args[@]}"
cd "$ISLAND_ROOT"

if [ -n "${COMPOSE_PROJECT_NAME:-}" ]; then
  export SERVICES_NET_NAME="${SERVICES_NET_NAME:-${COMPOSE_PROJECT_NAME}_services_net}"
  # 3.3-b: same reasoning -- stack/federation/compose.yaml (a separate
  # compose project) needs core_net's real name too.
  export CORE_NET_NAME="${CORE_NET_NAME:-${COMPOSE_PROJECT_NAME}_core_net}"
fi

CORE_DIR=stack/core
SVC_DIR=stack/services
NOMAD_DIR=stack/services/nomad
JITSI_DIR=stack/services/jitsi

CORE="docker compose -f $CORE_DIR/compose.yaml"
SVC="docker compose -f $SVC_DIR/compose.yaml"
NOMAD="docker compose -f $NOMAD_DIR/compose.yaml"
JITSI="docker compose -f $JITSI_DIR/compose.yaml"

fail() { echo "FAIL: $1" >&2; exit 1; }
random_hex() { openssl rand -hex 16; }
random_b64() { openssl rand -base64 24 | tr -d '=+/'; }

# Waits for every container in a compose project to report healthy (or
# have no healthcheck at all, which docker compose ps also reports as an
# empty Health field — not a failure, just nothing to wait on).
wait_healthy() {
  local compose_cmd="$1" label="$2" attempts="${3:-40}" delay="${4:-3}"
  local i unhealthy
  for ((i = 0; i < attempts; i++)); do
    unhealthy=$($compose_cmd ps --format json | python3 -c "
import sys, json
lines = [json.loads(l) for l in sys.stdin if l.strip()]
print(' '.join(l['Name'] for l in lines if l.get('Health') not in ('healthy', '')))
")
    [ -z "$unhealthy" ] && return 0
    sleep "$delay"
  done
  fail "$label never became healthy: $unhealthy"
}

# --- first-run secret/cert generation -----------------------------------
# Each function is idempotent (returns immediately if its target already
# exists) and only fills in the *values* — structure and non-secret
# defaults come from the committed *.example.* file, so there's exactly
# one place (that file) that defines what belongs in each config.

bootstrap_services_env() {
  local f="$SVC_DIR/.env"
  [ -f "$f" ] && return 0
  echo "== first run: generating $f =="
  cp "$SVC_DIR/matrix.example.env" "$f"
  sed -i.bak "s|^MATRIX_DB_PASSWORD=.*|MATRIX_DB_PASSWORD=$(random_b64)|" "$f"
  rm -f "$f.bak"
}

bootstrap_matrix_secrets() {
  local data_dir="$SVC_DIR/data/matrix-synapse" f
  f="$data_dir/secrets.yaml"
  [ -f "$f" ] && return 0
  echo "== first run: generating Matrix secrets =="
  mkdir -p "$data_dir"
  # registration_shared_secret / macaroon_secret_key / form_secret just
  # need to be unpredictable strings Synapse compares byte-for-byte —
  # openssl rand is exactly as correct as upstream's own `generate` mode
  # for these three, and far more robust to call than shelling out to a
  # whole Synapse container. The signing key is different: it needs a
  # specific ed25519-plus-key-id format only upstream's own tooling
  # should produce, so that alone still goes through `generate` — but
  # only once, and only if it doesn't already exist.
  if [ ! -f "$data_dir/chat.island.signing.key" ]; then
    echo "== generating chat.island's signing key (upstream's own tooling) =="
    # A stale/empty homeserver.yaml here (e.g. from an interrupted earlier
    # run) makes `generate` try to "fill in missing parts" of it and fail
    # outright instead of doing a clean generate — remove it first.
    rm -f "$data_dir/homeserver.yaml"
    docker run --rm -v "$(cd "$data_dir" && pwd):/data" \
      -e SYNAPSE_SERVER_NAME=chat.island -e SYNAPSE_REPORT_STATS=no \
      ghcr.io/element-hq/synapse:v1.160.0 generate
    rm -f "$data_dir/homeserver.yaml"
  fi
  local db_password
  db_password=$(sed -n 's/^MATRIX_DB_PASSWORD=\(.*\)$/\1/p' "$SVC_DIR/.env")
  cp "$SVC_DIR/config/matrix-synapse/secrets.example.yaml" "$f"
  sed -i.bak \
    -e "s|^registration_shared_secret: \".*\"|registration_shared_secret: \"$(openssl rand -hex 32)\"|" \
    -e "s|^macaroon_secret_key: \".*\"|macaroon_secret_key: \"$(openssl rand -hex 32)\"|" \
    -e "s|^form_secret: \".*\"|form_secret: \"$(openssl rand -hex 32)\"|" \
    -e "s|^    password: \".*\"|    password: \"$db_password\"|" \
    "$f"
  rm -f "$f.bak"
}

bootstrap_nomad_env() {
  local f="$NOMAD_DIR/.env"
  [ -f "$f" ] && return 0
  echo "== first run: generating $f =="
  cp "$NOMAD_DIR/nomad.example.env" "$f"
  local mysql_password
  mysql_password=$(random_b64)
  sed -i.bak \
    -e "s|^NOMAD_DATA_DIR=.*|NOMAD_DATA_DIR=$(cd "$NOMAD_DIR" && pwd)/data|" \
    -e "s|^APP_KEY=.*|APP_KEY=$(random_hex)|" \
    -e "s|^MYSQL_ROOT_PASSWORD=.*|MYSQL_ROOT_PASSWORD=$(random_b64)|" \
    -e "s|^MYSQL_PASSWORD=.*|MYSQL_PASSWORD=$mysql_password|" \
    -e "s|^DB_PASSWORD=.*|DB_PASSWORD=$mysql_password|" \
    "$f"
  rm -f "$f.bak"
}

bootstrap_jitsi_env() {
  local f="$JITSI_DIR/.env"
  [ -f "$f" ] && return 0
  echo "== first run: generating $f =="
  cp "$JITSI_DIR/jitsi.example.env" "$f"
  sed -i.bak \
    -e "s|^TURN_CREDENTIALS=.*|TURN_CREDENTIALS=$(random_hex)|" \
    -e "s|^JICOFO_AUTH_PASSWORD=.*|JICOFO_AUTH_PASSWORD=$(random_hex)|" \
    -e "s|^JVB_AUTH_PASSWORD=.*|JVB_AUTH_PASSWORD=$(random_hex)|" \
    -e "s|^JIGASI_XMPP_PASSWORD=.*|JIGASI_XMPP_PASSWORD=$(random_hex)|" \
    -e "s|^JIGASI_TRANSCRIBER_PASSWORD=.*|JIGASI_TRANSCRIBER_PASSWORD=$(random_hex)|" \
    -e "s|^JIBRI_RECORDER_PASSWORD=.*|JIBRI_RECORDER_PASSWORD=$(random_hex)|" \
    -e "s|^JIBRI_XMPP_PASSWORD=.*|JIBRI_XMPP_PASSWORD=$(random_hex)|" \
    "$f"
  rm -f "$f.bak"
}

bootstrap_jitsi_cert() {
  local dir="$SVC_DIR/data/jitsi-gateway"
  [ -f "$dir/cert.crt" ] && [ -f "$dir/cert.key" ] && return 0
  echo "== first run: generating talk.island's self-signed cert =="
  # Self-signed, not real PKI (Phase 3) — the minimum needed for a
  # browser to treat talk.island as a secure context at all; see
  # stack/services/jitsi/README.md "Why jitsi-gateway terminates TLS".
  mkdir -p "$dir"
  openssl req -new -x509 -days 3650 -nodes \
    -out "$dir/cert.crt" -keyout "$dir/cert.key" \
    -subj "/CN=talk.island" -addext "subjectAltName=DNS:talk.island" 2>/dev/null
}

bootstrap_island_init() {
  command -v island-init >/dev/null 2>&1 \
    || fail "island-init not found on PATH -- pipx install ./island-init (see island-init/README.md)"

  local yaml="island-init/island.yaml" secrets_dir="secrets"

  # stack/services/compose.yaml's console service bind-mounts both these
  # paths. On a fresh clone neither exists (both are gitignored); Docker
  # itself would happily bind-mount a *directory* over a source path
  # that doesn't exist, so if a previous run got this far without this
  # guard (or `up` was interrupted mid-bootstrap), the fix is to remove
  # the directory Docker created, not to keep going.
  if [ -d "$yaml" ]; then
    fail "$yaml is a directory, not a file -- Docker creates this when a compose file bind-mounts a source path that doesn't exist yet. Remove it (rm -rf $yaml) and re-run ./island.sh up."
  fi
  if [ -e "$secrets_dir" ] && [ ! -d "$secrets_dir" ]; then
    fail "$secrets_dir exists but is not a directory -- remove it (rm -f $secrets_dir) and re-run ./island.sh up."
  fi
  mkdir -p "$secrets_dir"

  if [ ! -f "$yaml" ]; then
    echo "== first run: no $yaml -- running 'island-init new --lab' =="
    island-init new --lab --repo-root .
  fi

  # 3.3-b follow-up 5: found live -- 3.3-b made federation.peers a
  # required field, and an already-generated instance from before that
  # change failed `island-init check` while `up` kept right on running
  # against its now-stale render, with nothing telling the operator why.
  # A schema change that adds a required field ships an `island-init
  # migrate` step for exactly this; `up` now refuses to proceed on an
  # instance that doesn't pass, rather than rendering it anyway.
  island-init check "$yaml" --repo-root . \
    || fail "$yaml failed 'island-init check' -- if this instance predates a schema change, run: island-init migrate $yaml --repo-root ."
}

# 2.1-g: island-init render's per-deployment outputs (portal settings,
# LIS geometry) live under gitignored data/ paths now, not tracked ones
# -- stack/services/compose.yaml's portal service bind-mounts
# stack/services/data/portal/settings.json directly, so on a fresh clone
# (or after `secrets`/`island.yaml` were just generated above) that path
# doesn't exist yet either, and Docker would create a directory there
# the same way it used to for island.yaml itself (2.1-f). Rendering here,
# before $SVC ever comes up, both creates it and keeps it in sync with
# whatever island-init/island.yaml currently says -- a no-op diff against
# the tracked stack/ configs for an unedited lab instance (the golden
# rule), never a partial/missing file for compose to trip over.
render_instance_outputs() {
  island-init render --file island-init/island.yaml --repo-root .
}

# Per-boot operator token (2.1-f): required on every Island Console write
# endpoint (read-only map/status needs none) -- see server.py and
# SECURITY.md's lab-profile register row on console.island. Regenerated
# on every `up`, not idempotent like the bootstrap_* functions above:
# there's no secret-reuse reason to keep an old one across restarts, and
# a short-lived token is strictly safer.
bootstrap_console_token() {
  local dir="$SVC_DIR/data/console" f
  f="$dir/operator-token"
  mkdir -p "$dir"
  CONSOLE_OPERATOR_TOKEN=$(openssl rand -hex 24)
  printf '%s' "$CONSOLE_OPERATOR_TOKEN" > "$f"
  chmod 600 "$f"
}

ensure_kiwix_installed() {
  local status
  status=$(curl -s "http://localhost:8080/api/system/services" | python3 -c "
import sys, json
services = json.load(sys.stdin)
k = next((s for s in services if s['service_name'] == 'nomad_kiwix_server'), None)
print(k['status'] if k else 'not_installed')
")
  [ "$status" = "running" ] && return 0
  echo "== installing Kiwix (NOMAD's own bundled demo ZIM) =="
  curl -s -X POST "http://localhost:8080/api/system/services/install" \
    -H "Content-Type: application/json" \
    -d '{"service_name":"nomad_kiwix_server"}' >/dev/null
  local i
  for ((i = 0; i < 30; i++)); do
    status=$(curl -s "http://localhost:8080/api/system/services" | python3 -c "
import sys, json
services = json.load(sys.stdin)
k = next((s for s in services if s['service_name'] == 'nomad_kiwix_server'), None)
print(k['status'] if k else 'not_installed')
")
    [ "$status" = "running" ] && return 0
    sleep 3
  done
  fail "nomad_kiwix_server did not reach 'running' status"
}

# --- subcommands ---------------------------------------------------------

cmd_up() {
  echo "== stack/core =="
  $CORE up -d
  wait_healthy "$CORE" "stack/core"
  command -v resccom-sim >/dev/null 2>&1 \
    || fail "resccom-sim not found on PATH -- pipx install sim-tools/ (see sim-tools/README.md)"
  (
    cd "$CORE_DIR"
    export RESCCOM_SIM_STORE="$(pwd)/.dev-subscribers.db.enc"
    export RESCCOM_SIM_PASSPHRASE="dev-only-ephemeral"
    # --if-missing, not `rm -f` + add: this store is shared with
    # stack/ran's verify rigs (see sim-tools/TASKS.md 3.2-e) -- add only
    # this island's own IMSI and leave whatever else is already there.
    resccom-sim sub add --test --imsi 001010000000001 --if-missing
    resccom-sim db sync --core-dir .
  )

  # NOMAD (and installing Kiwix into it) comes before stack/services, not
  # after: stack/services/compose.yaml's nomad-gateway proxies straight
  # to Kiwix, and its healthcheck genuinely exercises that proxy path —
  # on a truly fresh host nomad-gateway can never report healthy until
  # Kiwix already exists. (This was masked in every earlier dev-session
  # test here by a Kiwix container left running from a previous run;
  # only surfaced when testing this script against a genuinely empty
  # state — see stack/services/nomad/README.md's own notes on Kiwix not
  # being compose-managed.) NOMAD needs neither core nor services_net
  # itself, so this ordering costs nothing.
  bootstrap_nomad_env
  echo "== stack/services/nomad =="
  $NOMAD up -d
  wait_healthy "$NOMAD" "stack/services/nomad"
  ensure_kiwix_installed

  bootstrap_services_env
  bootstrap_matrix_secrets
  # island-init/island.yaml + secrets/ before the console container's
  # bind-mounts can be resolved at all (island-init/TASKS.md 2.1-f); the
  # per-instance data/ outputs (portal settings, LIS geometry) before the
  # portal container's own bind-mount needs one to exist (2.1-g); the
  # operator token before the console can enforce write auth from its
  # first request.
  bootstrap_island_init
  render_instance_outputs
  bootstrap_console_token
  echo "== stack/services (DNS, portal, NOMAD gateway, Matrix, console) =="
  $SVC up -d
  wait_healthy "$SVC" "stack/services"

  bootstrap_jitsi_env
  bootstrap_jitsi_cert
  echo "== stack/services/jitsi =="
  $JITSI up -d
  wait_healthy "$JITSI" "stack/services/jitsi"

  cat <<EOF

Island is up. From a device on the UE subnet (a real phone with a
provisioned SIM, or the UERANSIM simulator — see stack/core/README.md):

    http://portal.island   live status + what this network is
    http://library.island  offline knowledge (NOMAD/Kiwix)
    https://chat.island    messaging (Element Web, E2EE by default)
    https://talk.island    voice/video calling
    http://console.island  operator console (map, sites/cells, drafts)

Console operator token (needed for every write in the console; shown
only this once -- also at $SVC_DIR/data/console/operator-token):

    $CONSOLE_OPERATOR_TOKEN

A change made in the console is only ever staged as a pending draft;
run '$0 apply' on this host to sign, render, and restart affected
services (RFC-0006 D5 -- signing never happens in the console
container).

stack/services/verify.sh drives the UERANSIM simulator through exactly
this scenario end-to-end (registration, browsing, an E2EE message, an
audio call, live status) if you want to confirm it yourself without a
real phone.
EOF
}

cmd_down() {
  echo "== stack/services/jitsi =="
  $JITSI down
  echo "== stack/services =="
  $SVC down
  echo "== stack/services/nomad =="
  $NOMAD down
  echo "== stack/core =="
  $CORE down
}

cmd_status() {
  local wan_state="down"
  curl -s -m 2 -o /dev/null https://1.1.1.1/ 2>/dev/null && wan_state="up"
  echo "Host WAN uplink: $wan_state"
  echo
  for pair in "stack/core:$CORE" "stack/services:$SVC" "stack/services/nomad:$NOMAD" "stack/services/jitsi:$JITSI"; do
    local label="${pair%%:*}" compose_cmd="${pair#*:}"
    echo "== $label =="
    $compose_cmd ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || echo "  (not running)"
    echo
  done
}

cmd_apply() {
  command -v island-init >/dev/null 2>&1 \
    || fail "island-init not found on PATH -- pipx install ./island-init (see island-init/README.md)"
  local draft="$SVC_DIR/data/console/draft.yaml"
  [ -f "$draft" ] \
    || fail "no pending draft at $draft -- stage one at http://console.island first (edit + Save Draft)"
  island-init apply --draft "$draft" --repo-root .
}

case "${1:-}" in
  up) cmd_up ;;
  down) cmd_down ;;
  status) cmd_status ;;
  apply) cmd_apply ;;
  *) echo "Usage: $0 [--island <dir>] {up|down|status|apply}" >&2; exit 1 ;;
esac
