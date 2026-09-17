#!/usr/bin/env bash
# ResCCOM 1.1-c — UERANSIM verification rig (the M1-core gate).
#
# Brings up the core, loads the test subscriber, brings up UERANSIM's
# simulated gNB + one UE against it, and checks: registration succeeds,
# the UE gets an IP in the UE subnet, local breakout to the (not-yet-built)
# services subnet works, and none of it depended on a WAN path. Exits
# non-zero on any failure. [SIM] path only — no radio hardware involved.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

CORE="docker compose -f compose.yaml"
SIM="docker compose -f compose.yaml -f compose.sim.yaml"

fail() { echo "FAIL: $1" >&2; exit 1; }

echo "== bringing up the core =="
$CORE up -d

echo "== waiting for the core to report healthy =="
CORE_SERVICES="mongo nrf ausf udm udr pcf nssf bsf smf amf upf"
ok=0
for _ in $(seq 1 30); do
  unhealthy=$($CORE ps --format json | python3 -c "
import sys, json
lines = [json.loads(l) for l in sys.stdin if l.strip()]
print(' '.join(l['Name'] for l in lines if l.get('Health') not in ('healthy', '')))
")
  if [ -z "$unhealthy" ]; then
    ok=1
    break
  fi
  sleep 2
done
[ "$ok" -eq 1 ] || fail "core services never became healthy: $unhealthy"

echo "== loading the test subscriber (IMSI 001010000000001) via resccom-sim =="
command -v resccom-sim >/dev/null 2>&1 \
  || fail "resccom-sim not found on PATH -- pipx install ../../sim-tools (see sim-tools/README.md)"
export RESCCOM_SIM_STORE="$(pwd)/.dev-subscribers.db.enc"
export RESCCOM_SIM_PASSPHRASE="dev-only-ephemeral"
# --if-missing, not `rm -f` + add: this store is shared across every rig
# (stack/ran's 4G/OAI verify scripts, island.sh) so each rig adds only its
# own IMSI and leaves the others alone -- the store becomes the union of
# every rig's test subscribers, and `db sync` skips any document that's
# already correct instead of replaceOne-ing it (see sim-tools/TASKS.md
# 3.2-e and resccom_sim/sync.py's module docstring for why a same-content
# replaceOne alone is enough to break an active PDU session).
resccom-sim sub add --test --imsi 001010000000001 --if-missing
resccom-sim db sync --core-dir .

echo "== bringing up UERANSIM gNB + UE =="
$SIM up -d gnb ue

echo "== check 1: UE registration + PDU session =="
# Polls the container's live interface state (exec'd fresh each
# iteration), not `docker compose logs` -- the latter has been unreliable
# from a script on this host even when the container's real state already
# shows success (see stack/ran/verify-5g-oai.sh's header for the same
# Docker Desktop log-delivery quirk, documented there against gnb5g). A UE
# re-authenticating against reset subscriber state can also hit one SQN
# resync round-trip first (normal AKA behavior, not a failure) before
# registering, so poll instead of assuming a fixed delay. The log line is
# kept below as best-effort corroboration only, never the pass/fail gate.
registered=0
UE_IP=""
for _ in $(seq 1 30); do
  UE_IP=$($SIM exec -T ue ip -4 -o addr show uesimtun0 2>/dev/null | awk '{print $4}' | cut -d/ -f1 || true)
  if [ -n "$UE_IP" ]; then registered=1; break; fi
  sleep 2
done
[ "$registered" -eq 1 ] \
  || fail "UE did not bring up uesimtun0 (no PDU session established) -- check: docker compose -f compose.yaml -f compose.sim.yaml logs ue"
echo "OK: UE brought up uesimtun0"
if $SIM logs ue 2>&1 | grep -q "Initial Registration is successful"; then
  echo "   (corroborated by ue log: 'Initial Registration is successful')"
fi

# 3.3-a: derived from the rendered configs, not hardcoded -- a second
# island (stack/federation/TASKS.md) renders a different ue_prefix/
# services_prefix into this same tree layout, and this script is copied
# unchanged into that tree, so it must not assume the lab's own values.
UE_SUBNET=$(awk '/^  session:/{getline; print $3; exit}' config/smf.yaml)
SERVICES_SUBNET=$(awk '/^  services_net:/{f=1} f && /subnet:/{print $3; exit}' compose.yaml)
BREAKOUT_IP=$(awk '/^      services_net:/{f=1; next} f{print $2; exit}' compose.yaml)

echo "== check 2: UE got an IP in $UE_SUBNET =="
python3 -c "
import ipaddress, sys
sys.exit(0 if ipaddress.ip_address(sys.argv[1]) in ipaddress.ip_network(sys.argv[2]) else 1)
" "$UE_IP" "$UE_SUBNET" \
  && echo "OK: UE IP is $UE_IP" \
  || fail "UE IP $UE_IP is not in $UE_SUBNET"

echo "== check 3: local breakout to the services subnet ($SERVICES_SUBNET) =="
# 1.3-a wired this for real: UPF is a genuine second-network member of
# services_net ($BREAKOUT_IP) and NATs UE-sourced traffic to that address
# (see stack/core/compose.yaml's ENABLE_NAT comment on upf), so this is
# now UPF's actual router path, not a stand-in. The UE still needs an
# explicit route to the subnet — nr-ue's PDU session only auto-installs
# the route to its own assigned subnet, not to $SERVICES_SUBNET.
$SIM exec -T ue ip route add "$SERVICES_SUBNET" dev uesimtun0 2>/dev/null || true
$SIM exec -T ue ping -c3 -W2 -I uesimtun0 "$BREAKOUT_IP" \
  || fail "local breakout ping to $BREAKOUT_IP failed"
echo "OK: local breakout ping succeeded"

echo "== check 4: offline-first (no WAN path exists to remove) =="
# core_net is declared internal:true in compose.yaml, so there's no
# default route to a WAN out of these containers at all -- stronger than
# unplugging a cable, since the dependency never existed. Confirm it.
if $SIM exec -T nrf curl -m3 -sS -o /dev/null http://1.1.1.1/ 2>/dev/null; then
  fail "a core container reached the WAN -- core_net is not actually offline"
fi
echo "OK: no WAN path exists from core_net; registration and local ping above"
echo "    already happened without one"

echo
echo "ALL CHECKS PASSED"
