#!/usr/bin/env bash
# ResCCOM 1.2-a (4G half) — srsRAN ZMQ eNB+UE verification against the EPC.
# Also the closing check for stack/core 1.1-d: a simulated 4G UE attaches
# and pings the services subnet, then the 5G path is re-run to prove no
# regression. [SIM] path only — nothing here radiates RF.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

CORE_DIR=../core
RAN="docker compose -f compose.4g.yaml"

fail() { echo "FAIL: $1" >&2; exit 1; }

echo "== bringing up the core (delegates to stack/core) =="
(cd "$CORE_DIR" && docker compose up -d)

echo "== waiting for the core to report healthy =="
ok=0
for _ in $(seq 1 30); do
  unhealthy=$(cd "$CORE_DIR" && docker compose ps --format json | python3 -c "
import sys, json
lines = [json.loads(l) for l in sys.stdin if l.strip()]
print(' '.join(l['Name'] for l in lines if l.get('Health') not in ('healthy', '')))
")
  if [ -z "$unhealthy" ]; then ok=1; break; fi
  sleep 2
done
[ "$ok" -eq 1 ] || fail "core services never became healthy: $unhealthy"

echo "== loading the test subscriber (IMSI 001010000000001) via resccom-sim =="
command -v resccom-sim >/dev/null 2>&1 \
  || fail "resccom-sim not found on PATH -- pipx install ../../sim-tools (see sim-tools/README.md)"
(
  cd "$CORE_DIR"
  export RESCCOM_SIM_STORE="$(pwd)/.dev-subscribers.db.enc"
  export RESCCOM_SIM_PASSPHRASE="dev-only-ephemeral"
  # --if-missing, not `rm -f` + add -- this store is shared across every
  # rig (see sim-tools/TASKS.md 3.2-e); each rig adds only its own IMSI so
  # the store stays the union of all rigs' test subscribers, and `db sync`
  # skips any document that's already correct instead of replaceOne-ing it.
  resccom-sim sub add --test --imsi 001010000000001 --if-missing
  resccom-sim db sync --core-dir .
)

echo "== bringing up srsRAN 4G eNB + UE (ZMQ virtual radio) =="
docker network inspect core_core_net >/dev/null 2>&1 \
  || fail "core_core_net network not found — is stack/core up under its own compose project?"
# Always recreate the pair together: the eNB's ZMQ device runs with
# upstream's fail_on_disconnect=true, so a UE that restarted on its own
# leaves the eNB's sample stream dead — a fresh pair makes this script
# deterministic, and starts the log poll below from a clean log.
$RAN down 2>/dev/null || true
$RAN up -d

echo "== check 1: 4G UE attach + PDU session =="
# Polls the container's live interface state (exec'd fresh each
# iteration), not `docker compose logs` -- see stack/ran/verify-5g-oai.sh's
# header for why a script-driven log poll has been unreliable on this
# host. The software PHY also runs amd64-emulated on Apple-silicon hosts,
# so cell search + attach can take a while — poll generously. The log line
# is kept below as best-effort corroboration only, never the pass/fail gate.
attached=0
UE_IP=""
for _ in $(seq 1 60); do
  UE_IP=$($RAN exec -T ue4g ip -4 -o addr show tun_srsue 2>/dev/null | awk '{print $4}' | cut -d/ -f1 || true)
  if [ -n "$UE_IP" ]; then attached=1; break; fi
  sleep 2
done
[ "$attached" -eq 1 ] \
  || fail "4G UE did not bring up tun_srsue (no attach) -- check: docker compose -f compose.4g.yaml logs ue4g"
echo "OK: 4G UE brought up tun_srsue"
if $RAN logs ue4g 2>&1 | grep -q "Network attach successful"; then
  echo "   (corroborated by srsue log: 'Network attach successful')"
fi

echo "== check 2: UE got an IP in 10.45.0.0/16 =="
case "$UE_IP" in
  10.45.*) echo "OK: 4G UE IP is $UE_IP" ;;
  *) fail "UE IP $UE_IP is not in 10.45.0.0/16" ;;
esac

echo "== check 3: local breakout to the services subnet (10.46.0.0/24) =="
# Same real path as stack/core's verify.sh check 3 (1.3-a wired UPF as a
# genuine services_net member at 10.46.0.2, NAT'd from the UE subnet — no
# stand-in needed any more). The 4G user plane path this proves is
# eNB -> GTP-U -> SGW-U -> GTP-U -> UPF(ogstun, then NAT'd out to
# services_net) and back.
$RAN exec -T ue4g ip route add 10.46.0.0/24 dev tun_srsue 2>/dev/null || true
$RAN exec -T ue4g ping -c3 -W2 -I tun_srsue 10.46.0.2 \
  || fail "4G local breakout ping to 10.46.0.2 failed"
echo "OK: 4G local breakout ping succeeded"

echo "== check 4: 5G path regression (delegates to stack/core verify.sh) =="
(cd "$CORE_DIR" && ./verify.sh) || fail "5G path regressed with the 4G RAN present"

echo
echo "ALL CHECKS PASSED — 4G attach + breakout, and the 5G path still passes"
