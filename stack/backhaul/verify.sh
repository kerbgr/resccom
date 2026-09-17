#!/usr/bin/env bash
# ResCCOM 1.4-a — the WAN-uplink failover rig's own acceptance test.
#
# Brings up wan-edge with its three simulated uplinks (fixed > satellite
# > ptp), then does exactly what TASKS.md 1.4-a's acceptance criteria
# describe: kills the active uplink and confirms failover within 30s,
# repeats until all three are dead, confirms the rest of the island
# (stack/core + stack/services) is completely unaffected by re-running
# its own acceptance checks, then reconnects everything and confirms
# failback. "Killing" an uplink is `docker network disconnect` — the
# same veth-out-of-a-netns mechanism a real unplug would trigger, just
# driven by us instead of a physical event; see README.md "Why
# containers, not real interfaces" for why this dev machine (no
# manageable host WAN — macOS/Docker Desktop) tests the abstraction this
# way instead of against real NICs.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

COMPOSE="docker compose -f compose.yaml"
CONTAINER=backhaul-wan-edge-1
FAILOVER_BUDGET=30

fail() { echo "FAIL: $1" >&2; exit 1; }

active_uplink() {
  docker exec "$CONTAINER" python3 -c "
import urllib.request as u, json
print(json.load(u.urlopen('http://127.0.0.1:8080/status', timeout=3))['active'])
" 2>/dev/null
}

wait_for_active() {
  local want="$1" waited=0
  while [ "$waited" -lt "$FAILOVER_BUDGET" ]; do
    [ "$(active_uplink)" = "$want" ] && { echo "OK: active uplink is '$want' (after ${waited}s)"; return 0; }
    sleep 1
    waited=$((waited + 1))
  done
  fail "active uplink did not become '$want' within ${FAILOVER_BUDGET}s (last seen: '$(active_uplink)')"
}

echo "== bringing up the island first (backhaul depends on core 1.1-c + services 1.3-a) =="
../../island.sh up

echo "== bringing up stack/backhaul (wan-edge + 3 simulated uplinks) =="
$COMPOSE up -d --build
healthy=0
for _ in $(seq 1 20); do
  h=$($COMPOSE ps --format json | python3 -c "
import sys, json
lines = [json.loads(l) for l in sys.stdin if l.strip()]
print(lines[0].get('Health', '') if lines else '')
")
  [ "$h" = "healthy" ] && { healthy=1; break; }
  sleep 2
done
[ "$healthy" -eq 1 ] || fail "wan-edge never became healthy"

echo "== check 1: with every uplink attached, the highest-priority one ('fixed') is active =="
wait_for_active fixed

echo "== check 2: killing the active uplink fails over within ${FAILOVER_BUDGET}s =="
docker network disconnect backhaul_wan_fixed_net "$CONTAINER"
wait_for_active satellite

echo "== check 3: killing the new active uplink fails over again within ${FAILOVER_BUDGET}s =="
docker network disconnect backhaul_wan_sat_net "$CONTAINER"
wait_for_active ptp

echo "== check 4: killing the last uplink leaves none active =="
docker network disconnect backhaul_wan_ptp_net "$CONTAINER"
wait_for_active None

echo "== check 5: wan-edge's own status endpoint stays reachable on services_net =="
# services_net is a directly connected subnet on wan-edge, never reached
# via its default route — losing every uplink doesn't touch this at all,
# which is D5 demonstrated inside the rig itself before check 6 even
# gets to the rest of the island.
docker exec services-portal-1 python3 -c "
import urllib.request as u
u.urlopen('http://10.46.0.90:8080/status', timeout=3)
" || fail "wan-edge's /status became unreachable from services_net with all uplinks dead"
echo "OK: /status still reachable from services_net"

echo "== check 6: island fully functional with all uplinks dead (re-run services acceptance checks) =="
../services/verify.sh || fail "stack/services/verify.sh failed with every backhaul uplink dead"

echo "== check 7: reconnecting every uplink fails back to 'fixed' within ${FAILOVER_BUDGET}s =="
docker network connect --ip 10.90.1.2 backhaul_wan_fixed_net "$CONTAINER"
docker network connect --ip 10.90.2.2 backhaul_wan_sat_net "$CONTAINER"
docker network connect --ip 10.90.3.2 backhaul_wan_ptp_net "$CONTAINER"
wait_for_active fixed

echo
echo "ALL CHECKS PASSED"
