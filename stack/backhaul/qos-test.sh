#!/usr/bin/env bash
# ResCCOM 1.4-c — QoS: emergency traffic wins.
#
# TASKS.md 1.4-c's acceptance criterion: "with the uplink artificially
# constrained (e.g. 2 Mbit), a bulk download does not starve Matrix
# message delivery (measure and record latency)." wand.py's own
# uplinks.yaml already sets `fixed`'s bandwidth_kbit to that exact 2000
# (2Mbit) example (see its own comment) — this script doesn't inject a
# separate constrained value, it exercises the module's real standing
# default.
#
# Traffic actually needs to flow through wan-edge for any of this to
# mean anything (1.4-a's own README flagged this as the one thing 1.4-c
# would need that 1.4-a/b deliberately didn't build). This script adds
# an EPHEMERAL "downstream clients" network + two throwaway containers —
# a "peer" (stands in for a remote endpoint reached over the uplink) and
# a "client" (stands in for a LAN device behind this router) — entirely
# separate from services_net/the real UE, so none of this touches the
# already-verified M1 island. wan-edge forwards between the two
# (net.ipv4.ip_forward=1, ../compose.yaml) exactly like a real router
# would.
#
# The "bulk" traffic is implemented as a client -> peer *upload*, not a
# literal download, even though the acceptance text says "download" —
# see config/qos_probe.py's own docstring for why: `tc` only shapes a
# given interface's own egress, and wand.py's shaping applies to
# wan-edge's uplink-facing interface (the one actually constrained). A
# literal download's bulk payload flows the other way and wouldn't be
# shaped by anything this task is actually testing. Confirmed live
# during development: a literal peer->client download transferred 6MB
# instantly (unshaped), while the upload direction was correctly capped
# to the configured rate once measured.
#
# Also confirmed live during development and fixed here: veth interfaces
# default to GSO/TSO/GRO on, which silently let HTB under-shape by
# ~2.4x (rate-limiting by GSO superpacket count, not real packet count)
# until wand.py's setup_qos() started disabling those offloads on the
# shaped interface first — see ../Dockerfile's own comment.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

IMG=resccom/wan-edge:1.4-a
EDGE=backhaul-wan-edge-1
PEER=backhaul-wan-peer
CLIENT=backhaul-wan-client
CLIENTS_NET=backhaul_wan_clients_net
CLIENTS_SUBNET=10.90.9.0/28
CLIENTS_GW=10.90.9.1
EDGE_CLIENTS_IP=10.90.9.2
CLIENT_IP=10.90.9.3
FIXED_UPLINK_SELF_IP=10.90.1.2
PEER_IP=10.90.1.3
BULK_MB=6
PROBE_COUNT=15

fail() { echo "FAIL: $1" >&2; exit 1; }

cleanup() {
  docker rm -f "$PEER" "$CLIENT" 2>/dev/null || true
  docker network disconnect "$CLIENTS_NET" "$EDGE" 2>/dev/null || true
  docker network rm "$CLIENTS_NET" 2>/dev/null || true
}
trap cleanup EXIT

echo "== bringing up the island + backhaul =="
../../island.sh up
docker compose -f compose.yaml up -d --build

echo "== confirming 'fixed' is the active uplink (this test targets its 2Mbit lab-profile default) =="
active="unknown"
for _ in $(seq 1 30); do
  active=$(docker exec "$EDGE" python3 -c "
import urllib.request as u, json
print(json.load(u.urlopen('http://127.0.0.1:8080/status', timeout=3))['active'])
" 2>/dev/null)
  [ "$active" = "fixed" ] && break
  sleep 1
done
[ "$active" = "fixed" ] || fail "expected 'fixed' active for this test, got '$active' — bring its uplink back and retry"
echo "OK: 'fixed' is active"

echo "== setting up the ephemeral downstream-clients rig =="
docker network create --subnet "$CLIENTS_SUBNET" --gateway "$CLIENTS_GW" "$CLIENTS_NET" >/dev/null
docker network connect --ip "$EDGE_CLIENTS_IP" "$CLIENTS_NET" "$EDGE"

docker run -d --rm --name "$PEER" --network backhaul_wan_fixed_net --ip "$PEER_IP" \
  --cap-add=NET_ADMIN -v "$(pwd)/config/qos_probe.py:/app/qos_probe.py:ro" \
  --entrypoint python3 "$IMG" /app/qos_probe.py serve >/dev/null
sleep 1
docker exec "$PEER" ip route add "$CLIENTS_SUBNET" via "$FIXED_UPLINK_SELF_IP"

docker run -d --rm --name "$CLIENT" --network "$CLIENTS_NET" --ip "$CLIENT_IP" \
  --cap-add=NET_ADMIN -v "$(pwd)/config/qos_probe.py:/app/qos_probe.py:ro" \
  --entrypoint sleep "$IMG" infinity >/dev/null
# The clients network's Docker-assigned gateway (.1) is Docker's own
# bridge veth, not wan-edge (Docker reserves that address for itself
# even when a custom --gateway is given — confirmed live) — so the
# client's default route is overridden here to actually go through
# wan-edge ($EDGE_CLIENTS_IP), the same way a real LAN client's route to
# its router works.
docker exec "$CLIENT" ip route replace default via "$EDGE_CLIENTS_IP"

docker exec "$CLIENT" python3 -c "
import socket
with socket.create_connection(('$PEER_IP', 8448), timeout=3):
    pass
" || fail "client cannot reach the peer through wan-edge — rig setup is broken"
echo "OK: client -> wan-edge -> peer path confirmed"

probe() { docker exec "$CLIENT" python3 /app/qos_probe.py probe --host "$PEER_IP" --count "$PROBE_COUNT"; }

run_scenario() {
  local label="$1"
  echo "-- $label: baseline (no bulk traffic) --" >&2
  local baseline
  baseline=$(probe)
  echo "$baseline" >&2

  echo "-- $label: bulk upload running, probing under contention --" >&2
  docker exec "$CLIENT" python3 /app/qos_probe.py bulk --host "$PEER_IP" --bulk-mb "$BULK_MB" >&2 &
  local bulk_pid=$!
  sleep 1
  local under_load
  under_load=$(probe)
  echo "$under_load" >&2
  wait "$bulk_pid"

  echo "${baseline}|${under_load}"
}

echo "== scenario A: unclassified (Matrix-tier traffic gets no priority) =="
docker exec "$EDGE" iptables -t mangle -F WAND_QOS
result_a=$(run_scenario "unclassified")

echo "== scenario B: classified (wand.py's real, standing QoS — restored via an actual failover cycle, not re-added by hand) =="
# Forces wand.py's own set_active()/setup_qos() to run again for
# 'fixed' — the real production code path repopulates WAND_QOS, rather
# than this script re-adding the same rule by hand.
docker network disconnect backhaul_wan_fixed_net "$EDGE"
sleep 4
docker network connect --ip "$FIXED_UPLINK_SELF_IP" backhaul_wan_fixed_net "$EDGE"
for _ in $(seq 1 30); do
  a=$(docker exec "$EDGE" python3 -c "
import urllib.request as u, json
print(json.load(u.urlopen('http://127.0.0.1:8080/status', timeout=3))['active'])
" 2>/dev/null)
  [ "$a" = "fixed" ] && break
  sleep 1
done
[ "$a" = "fixed" ] || fail "'fixed' did not come back active after the restore cycle"
result_b=$(run_scenario "classified")

echo "== comparing =="
RESULT_A="$result_a" RESULT_B="$result_b" python3 -c "
import json, os

a_base, a_load = os.environ['RESULT_A'].split('|')
b_base, b_load = os.environ['RESULT_B'].split('|')
a_base, a_load, b_base, b_load = (json.loads(x) for x in (a_base, a_load, b_base, b_load))

print(f\"unclassified: baseline avg {a_base['avg_ms']}ms -> under load avg {a_load['avg_ms']}ms (max {a_load['max_ms']}ms)\")
print(f\"classified:   baseline avg {b_base['avg_ms']}ms -> under load avg {b_load['avg_ms']}ms (max {b_load['max_ms']}ms)\")

assert b_load['failed'] == 0, f'classified probes should not fail under load: {b_load}'
assert a_load['avg_ms'] > a_base['avg_ms'] * 2, (
    f\"the bulk transfer didn't actually create contention (unclassified load avg \"
    f\"{a_load['avg_ms']}ms wasn't clearly worse than its own baseline {a_base['avg_ms']}ms) \"
    f\"— this test proves nothing without real contention first\"
)
assert b_load['avg_ms'] < a_load['avg_ms'], (
    f\"QoS classification did not improve latency under load: \"
    f\"classified {b_load['avg_ms']}ms vs unclassified {a_load['avg_ms']}ms\"
)
print(f\"OK: classification cut latency under identical load from {a_load['avg_ms']}ms to {b_load['avg_ms']}ms\")
"

echo
echo "ALL CHECKS PASSED"
