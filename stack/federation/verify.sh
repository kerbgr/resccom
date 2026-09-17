#!/usr/bin/env bash
# ResCCOM 3.3-b — federation overlay verification rig.
# Updated 3.3-c v2 (RFC-0003 D1 amendment): tests SEPP N32 reachability,
# not direct NRF/UDM reachability -- the forward-filter (3.3-b follow-up
# 3) no longer lets tunnel-origin traffic reach anything else, and SEPP
# is now the only container that originates cross-island traffic at all
# (AMF talks to its own local SEPP over plain core_net; see
# stack/core/compose.yaml.j2's sepp service comment).
#
# Assumes THIS island's stack/core is already up (stack/core/verify.sh or
# island.sh up) and stack/federation/compose.yaml + data/wg-up.sh have
# already been rendered by island-init from an island.yaml carrying at
# least one federation.peers[] entry. Brings up wg-overlay, injects a
# route for each peer's announced prefixes into the sepp container, then
# checks that each peer's SEPP N32-c and N32-f ports answer over the
# tunnel. Discovers peers from data/wg-up.sh's own rendered comments
# (`# peer: name=... node_internal_base=... services_prefix=...`) rather
# than re-parsing island.yaml -- no YAML dependency needed here, same
# spirit as stack/core/verify.sh deriving its expected subnets from
# already-rendered config instead of hardcoding them.
#
# sepp routes via wg-overlay's *services_net* address, not its core_net
# one: core_net's `internal: true` (1.1-c) drops any bridged packet whose
# destination isn't itself a core_net member, even for two containers
# already on that same bridge (found live) -- services_net carries no
# such restriction, and sepp joins it for exactly this (only when a peer
# is allow-listed; see compose.yaml.j2's sepp service comment).
#
# Exits non-zero on any failure. [SIM] path only -- nothing radiates.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

FED="docker compose -f compose.yaml"
# 3.3-c v2f: two-island.sh brings wg-overlay up with an extra -f
# compose.wan.yaml (the simulated-WAN bridge, WG_WAN_IP set). Without
# also including it here, `up -d` below would recompute wg-overlay's
# desired config from compose.yaml alone, see it no longer matches the
# running container (missing the wan_net membership), and recreate it
# without wan_net -- silently undoing the harness's own peering fix. A
# standalone/single-island `./verify.sh` never sets WG_WAN_IP, so this is
# a no-op there (golden rule: unaffected outside the two-island harness).
if [ -f compose.wan.yaml ] && [ -n "${WG_WAN_IP:-}" ]; then
  FED="$FED -f compose.wan.yaml"
fi
CORE="docker compose -f ../core/compose.yaml"

fail() { echo "FAIL: $1" >&2; exit 1; }

[ -f data/wg-up.sh ] || fail "data/wg-up.sh not rendered -- run island-init render first"

PEER_NODE_BASES=$(grep -oE 'node_internal_base=[0-9./]+' data/wg-up.sh | cut -d= -f2 || true)
if [ -z "$PEER_NODE_BASES" ]; then
  # 3.3-b follow-up 6: an unpeered island is a legitimate, common state
  # (the lab default) -- there being nothing to verify isn't a failure,
  # so this exits 0, not fail's exit 1.
  echo "no peers in island.yaml -- nothing to verify"
  exit 0
fi

SERVICES_SUBNET=$(awk '/^  services_net:/{f=1} f && /subnet:/{print $3; exit}' ../core/compose.yaml)

echo "== bringing up wg-overlay =="
$FED up -d

echo "== waiting for wg-overlay to bring up wg0 =="
ok=0
for _ in $(seq 1 15); do
  $FED exec -T wg-overlay wg show wg0 >/dev/null 2>&1 && { ok=1; break; }
  sleep 1
done
[ "$ok" -eq 1 ] || fail "wg-overlay never brought up wg0 -- check: $FED logs wg-overlay"
echo "OK: wg0 is up"

echo "== finding wg-overlay's own services_net address =="
WG_SVC_IP=$($FED exec -T wg-overlay sh -c "ip -4 -o addr show" | python3 -c "
import sys, ipaddress
net = ipaddress.ip_network('$SERVICES_SUBNET')
for line in sys.stdin:
    parts = line.split()
    if 'inet' in parts:
        addr = parts[parts.index('inet') + 1].split('/')[0]
        if ipaddress.ip_address(addr) in net:
            print(addr)
            break
")
[ -n "$WG_SVC_IP" ] || fail "could not find wg-overlay's own address on services_net ($SERVICES_SUBNET)"
echo "OK: wg-overlay is $WG_SVC_IP on services_net"

echo "== routing sepp -> each peer's node_internal_base via wg-overlay (over services_net) =="
for base in $PEER_NODE_BASES; do
  # --user root: the image's own process (and `exec` by default) runs as
  # the unprivileged `open5gs` user -- CAP_NET_ADMIN is in the
  # container's bounding set (from cap_add) but an unprivileged user's
  # effective set is empty regardless, so `ip route` needs root
  # explicitly (found live: "Operation not permitted" otherwise).
  $CORE exec -T --user root sepp ip route replace "$base" via "$WG_SVC_IP" \
    || fail "sepp could not add a route to $base via $WG_SVC_IP -- does sepp have cap_add: NET_ADMIN and services_net membership? (both only rendered when a peer is allow-listed -- re-render stack/core/compose.yaml too)"
  echo "OK: sepp routes $base via $WG_SVC_IP"
done

echo "== checking each peer's SEPP N32-c and N32-f ports over the overlay =="
# SEPP's one core_net address (offset 16 -- island_init/render.py's
# NODE_IP_OFFSETS, within the peer's own core_net, the first /24 of its
# node_internal_base), two ports (SEPP_N32C_PORT/SEPP_N32F_PORT, 7778/
# 7779 -- same address for both, not upstream's three separate
# addresses; see sepp.yaml.j2's own comment on why).
for base in $PEER_NODE_BASES; do
  targets=$(python3 -c "
import ipaddress
net = ipaddress.ip_network('$base')
core = ipaddress.ip_network(f'{net.network_address}/24')
print(f'{core.network_address + 16}:7778 {core.network_address + 16}:7779')
")
  for target in $targets; do
    ip="${target%:*}"; port="${target#*:}"
    $CORE exec -T sepp bash -c "echo -n > /dev/tcp/$ip/$port" \
      || fail "sepp could not reach $ip:$port over the overlay"
    echo "OK: sepp reached $ip:$port"
  done
done

echo
echo "ALL CHECKS PASSED"
