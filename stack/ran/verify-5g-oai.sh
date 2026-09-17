#!/usr/bin/env bash
# ResCCOM 1.2-a(5G-alt) — OpenAirInterface ZMQ-equivalent (rfsimulator) gNB +
# nrUE verification against the real Open5GS 5GC.
#
# Same acceptance bar as verify-4g.sh: register, get an IP in the UE
# subnet, local-breakout ping the services subnet, then re-run stack/core's
# own verify.sh so an OAI change can never silently regress the primary
# UERANSIM path (both rigs coexist). [SIM] path only — rfsimulator is a
# software loopback, nothing here radiates RF.
#
# Deliberately its OWN test subscriber, IMSI 001010000000002, not the
# 001010000000001 every other rig in this repo shares -- tried the shared
# IMSI first and it broke the GTP-U data path for real: `resccom-sim db
# sync` used to do a full reconcile via Mongo `replaceOne` even when the
# IMSI's document content didn't change, and replacing the subscriber
# document out from under an *actively PDU-sessioned* UE leaves Open5GS's
# SMF/UPF with a PFCP session the new registration can't reuse --
# registration and PDU Session Establishment both reported success, but
# the UPF genuinely could not route to the UE afterwards (verified with
# `docker compose exec upf ping <ue-ip>` -- 100% loss, reproduced twice).
# Giving OAI's rig its own IMSI sidesteps that RAT-conflict class of
# problem entirely; keeping it even after WBS 3.2-e's fixes below still
# gives two independently-attached subscribers to prove multi-rig
# coexistence with, which is what checks 1-4 below now actually do.
#
# WBS 3.2-e fixed the other, structural half of this: every rig used to
# `rm -f` this shared store before adding just its own IMSI, so whichever
# rig's `db sync` ran last silently deleted every other rig's subscriber
# out of Mongo -- found in review when this script's own IMSI
# (…0002) turned up deleted after core/verify.sh ran, even though the OAI
# UE's PDU session was still alive at the network layer (Open5GS doesn't
# tear down an established session just because its Mongo document
# disappears). Fixed two ways: `sub add --if-missing` below never wipes
# the store, so it stays the union of every rig's test subscribers; and
# `db sync` (resccom_sim/sync.py) now skips `replaceOne` entirely for a
# document that's already correct, so a rig re-syncing an unrelated IMSI
# is a genuine no-op for this one. So check 4's delegation to
# core/verify.sh no longer reconciles 002 out of Mongo -- both IMSIs
# survive it, which is this script's own multi-rig acceptance bar
# (sim-tools/TASKS.md 3.2-e).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

CORE_DIR=../core
RAN="docker compose -f compose.5g-oai.yaml"

fail() { echo "FAIL: $1" >&2; exit 1; }

echo "== bringing up the core (delegates to stack/core) =="
(cd "$CORE_DIR" && docker compose up -d) || fail "stack/core failed to come up"

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

echo "== loading the OAI rig's own test subscriber (IMSI 001010000000002) via resccom-sim =="
command -v resccom-sim >/dev/null 2>&1 \
  || fail "resccom-sim not found on PATH -- pipx install ../../sim-tools (see sim-tools/README.md)"
(
  cd "$CORE_DIR"
  export RESCCOM_SIM_STORE="$(pwd)/.dev-subscribers.db.enc"
  export RESCCOM_SIM_PASSPHRASE="dev-only-ephemeral"
  # --if-missing, not `rm -f` + add: see this script's header comment
  # (WBS 3.2-e) -- this leaves 001, if the UERANSIM rig already added it
  # to this same shared store, untouched.
  resccom-sim sub add --test --imsi 001010000000002 --if-missing
  resccom-sim db sync --core-dir .
)

echo "== bringing up OAI gNB + nrUE (rfsimulator) =="
docker network inspect core_core_net >/dev/null 2>&1 \
  || fail "core_core_net network not found -- is stack/core up under its own compose project?"
$RAN down 2>/dev/null || true
$RAN up -d

echo "== check 1: nrUE attach + PDU session (rfsimulator can take a while under load) =="
# Polls the container's live network state (exec'd fresh each iteration),
# not `docker compose logs` -- the latter has already been caught on this
# exact host giving stale/empty output to a *script* even when the
# container's real state (and an interactive re-run of the identical
# command) already shows success; see README.md's "5G ZMQ rig" writeup for
# the same Docker Desktop log-delivery quirk documented against gnb5g. The
# nr-ue log line is kept below as best-effort corroboration only, never as
# the pass/fail gate.
attached=0
UE_IP=""
for _ in $(seq 1 60); do
  UE_IP=$($RAN exec -T nrue-oai ip -4 -o addr show oaitun_ue1 2>/dev/null | awk '{print $4}' | cut -d/ -f1 || true)
  if [ -n "$UE_IP" ]; then attached=1; break; fi
  sleep 2
done
[ "$attached" -eq 1 ] \
  || fail "nrUE did not bring up oaitun_ue1 (no PDU session established) -- check: docker compose -f compose.5g-oai.yaml logs nrue-oai"
echo "OK: nrUE brought up oaitun_ue1"
if $RAN logs nrue-oai 2>&1 | grep -q "TUN Interface oaitun_ue1 successfully configured"; then
  echo "   (corroborated by nr-ue log: 'TUN Interface oaitun_ue1 successfully configured')"
fi

echo "== check 2: UE got an IP in 10.45.0.0/16 =="
case "$UE_IP" in
  10.45.*) echo "OK: 5G-OAI UE IP is $UE_IP" ;;
  *) fail "UE IP $UE_IP is not in 10.45.0.0/16" ;;
esac

echo "== check 3: local breakout to the services subnet (10.46.0.0/24) =="
$RAN exec -T nrue-oai ip route add 10.46.0.0/24 dev oaitun_ue1 2>/dev/null || true
$RAN exec -T nrue-oai ping -c3 -W2 -I oaitun_ue1 10.46.0.2 \
  || fail "5G-OAI local breakout ping to 10.46.0.2 failed"
echo "OK: 5G-OAI local breakout ping succeeded"

echo "== check 4: primary (UERANSIM) 5G path regression (delegates to stack/core verify.sh) =="
echo "   (core/verify.sh adds its own IMSI 001010000000001 with --if-missing"
echo "   into this same shared store, not a wipe -- see this script's header"
echo "   comment (WBS 3.2-e): this rig's own 002 stays in Mongo throughout)"
(cd "$CORE_DIR" && ./verify.sh) || fail "5G path (UERANSIM) regressed with the OAI RAN present"

echo "== check 5: multi-rig acceptance -- both IMSIs survived, Mongo holds both =="
MONGO_IMSIS=$(cd "$CORE_DIR" && docker compose exec -T mongo mongosh --quiet mongodb://localhost/open5gs \
  --eval "db.subscribers.countDocuments({ imsi: { \$in: ['001010000000001', '001010000000002'] } })")
[ "$MONGO_IMSIS" = "2" ] \
  || fail "expected both 001010000000001 and 001010000000002 in Mongo after the regression check, found $MONGO_IMSIS"
OAI_UE_IP=$($RAN exec -T nrue-oai ip -4 -o addr show oaitun_ue1 2>/dev/null | awk '{print $4}' | cut -d/ -f1 || true)
[ -n "$OAI_UE_IP" ] || fail "OAI UE lost its PDU session (oaitun_ue1 has no address) after the regression check"
echo "OK: Mongo holds both IMSIs, and the OAI UE's PDU session ($OAI_UE_IP) survived"
echo "    the UERANSIM regression check"

echo
echo "ALL CHECKS PASSED -- OAI rfsimulator attach + breakout, the primary"
echo "UERANSIM 5G path still passes, and both rigs' subscribers/sessions"
echo "survived running back to back (WBS 3.2-e)"
