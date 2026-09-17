#!/usr/bin/env bash
# ResCCOM 1.4-b — the unplug test: standing CI-of-the-island.
#
# This is the repo's first *literal* "unplug the cable" test — every
# earlier WAN-down check (stack/services/README.md's own "Known
# limitations", 1.4-a's verify.sh) either bounded latency, retargeted one
# config value to a black-holed address, or disconnected backhaul's own
# simulated uplinks without touching the rest of the island's real WAN
# path. This drops real WAN, at the host level, for every standing island
# container that has one, using Docker's own documented hook for custom
# firewall rules (the DOCKER-USER chain in iptables — rules there survive
# Docker's own chain management and apply before Docker's rules run) —
# added via a throwaway `--net=host --privileged` container built from
# the same wan-edge image 1.4-a already produces (../Dockerfile), since
# this dev machine's actual "host" for Docker's networking purposes is
# Docker Desktop's own Linux VM, not the macOS layer above it.
#
# Only the *standing* island containers' own fixed addresses are
# targeted (WAN_TOUCHING_IPS below) — not stack/services/verify.sh's own
# throwaway pip/npm containers (the Matrix E2EE and Jitsi-call checks'
# test-tooling installs), which get dynamic addresses Docker assigns
# outside this list and so keep real WAN access. That split is
# deliberate, not a loophole: those installs fetch THIRD-PARTY TEST
# TOOLING for this CI harness's own use (verify.sh's own comments already
# call this out — "not a repo dependency, so this is the only place that
# installs them"), a concern orthogonal to whether the ISLAND needs WAN,
# which is exactly what this script exists to settle. Confirmed live
# (see README.md "Verification performed"): a plain throwaway container
# on services_net keeps real WAN throughout this test.
#
# Because this changes real, host-level firewall state (not just this
# project's own containers), it cleans up via `trap` on any exit path —
# if this script is ever killed outright (SIGKILL) mid-run, restore
# manually with the same iptables_helper/restore_wan commands below
# against each address in WAN_TOUCHING_IPS.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

HELPER_IMAGE=resccom/wan-edge:1.4-a
BUDGET=30

fail() { echo "FAIL: $1" >&2; exit 1; }

# Fixed addresses of every standing island component with any WAN path —
# see ../core/compose.yaml (upf's services_net address), ../services/
# compose.yaml (dns, portal, nomad-gateway, matrix-gateway, console) and
# ./compose.yaml (wan-edge + its 3 uplinks) for the source of truth on
# each. check_wan_touching_ips_complete() below re-derives this same set
# from those three files on every run and fails loudly if this list ever
# drifts from it — added after this list was found to be missing upf,
# nomad-gateway and matrix-gateway (all fixed-address services on
# services_net, hence WAN-capable via Docker's own NAT, same as dns/
# portal, even though nothing in their own config currently reaches out).
# console (10.46.0.40) found missing the same way during 3.3-b follow-up
# 2's review -- this guard should have already caught it and didn't,
# since check_wan_touching_ips_complete() itself wasn't run again after
# 2.1-d added the console service.
# 10.46.0.45 (wg-overlay) and 10.46.0.5 (a peered amf, 3.3-b follow-up 2):
# both are services_net members with a fixed address now specifically so
# this guard can see them -- see island_init/render.py's
# WG_OVERLAY_SERVICES_OFFSET/AMF_SERVICES_OFFSET and their own comments.
# amf's is listed even though the committed lab profile (no peer
# allow-listed) never renders it, so a local peered re-render doesn't
# immediately trip check_wan_touching_ips_complete's "declared but
# missing" case for an address this file already knows about.
WAN_TOUCHING_IPS=(10.46.0.53 10.46.0.10 10.46.0.11 10.46.0.20 10.46.0.90 10.46.0.2 10.46.0.30 10.46.0.31 10.46.0.32 10.90.1.2 10.90.2.2 10.90.3.2 10.46.0.45 10.46.0.5 10.46.0.40)

# Guards against WAN_TOUCHING_IPS silently drifting out of date (see its
# own comment above) — parses the three compose files for every service
# with a fixed `ipv4_address:` on a network that isn't `internal: true`
# (i.e. genuinely WAN-capable, the same reasoning ../README.md's "Why
# containers, not real interfaces" applies to services_net/wan_*_net),
# and fails loudly if any such address is missing from the list. Plain
# line-based parsing, not a YAML library: this host has no PyYAML
# installed and every other script in this repo already avoids that
# dependency (python3 stdlib only) — safe here because all three compose
# files share one consistent 2-space indent style (confirmed by reading
# them), which is all this needs.
check_wan_touching_ips_complete() {
  local missing
  if ! missing=$(python3 - "${WAN_TOUCHING_IPS[@]}" <<'PY'
import re, sys

# Every compose file that can attach a container to an island network —
# including the separate jitsi/nomad compose projects (jitsi's gateway,
# jvb and coturn hold fixed services_net addresses; this list previously
# omitted that file and the guard under-covered exactly the way it exists
# to prevent) and stack/federation's own compose file (3.3-b follow-up 2:
# wg-overlay, and a peered amf, are services_net members too).
COMPOSE_FILES = [
    "../core/compose.yaml",
    "../services/compose.yaml",
    "../services/jitsi/compose.yaml",
    "../services/nomad/compose.yaml",
    "../federation/compose.yaml",
    "./compose.yaml",
]

def default_of(v):
    # `${VAR:-10.46.0.30}` (jitsi's style) -> its default; plain IPs pass through
    m = re.fullmatch(r"\$\{[^:}]+:-([^}]+)\}", v)
    return m.group(1) if m else v

def parse(path):
    # Indent-agnostic: track a stack of (indent, key) for open mappings
    # instead of assuming any one file's indent width (core/services use
    # 2 spaces, jitsi's uses 4). Tracks every (service, network)
    # membership seen -- not just ones with a fixed ipv4_address -- so a
    # *dynamic* membership (bare `- network_name` list form, or
    # `network_name: {}`/no ipv4_address child) on a non-internal network
    # is visible too (3.3-b follow-up 2: found live, wg-overlay and a
    # peered amf both joined services_net this way and were completely
    # invisible to the old ipv4_address-only parse).
    internal_nets, ips, memberships = set(), {}, set()
    stack = []
    for raw in open(path):
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        line = raw.rstrip("\n")
        indent = len(line) - len(line.lstrip(" "))
        s = line.strip()
        is_list_item = s.startswith("- ")
        if is_list_item:
            s, indent = s[2:], indent + 2
        m = re.match(r"^([\w.${}-]+):\s*(.*)$", s)
        if m:
            key, val = m.group(1), m.group(2).strip()
        elif is_list_item:
            # A bare "- network_name" list entry: no colon, so it never
            # matched the key/value regex at all before -- invisible.
            key, val = s, None
        else:
            continue
        while stack and stack[-1][0] >= indent:
            stack.pop()
        keys = [k for _, k in stack]
        is_service_network_key = len(keys) >= 3 and keys[0] == "services" and keys[-1] == "networks"
        if key == "ipv4_address" and val:
            if len(keys) >= 4 and keys[0] == "services" and keys[-2] == "networks":
                ips[(path, keys[1], keys[-1])] = default_of(val)
        elif key == "internal" and val == "true":
            if len(keys) >= 2 and keys[0] == "networks":
                internal_nets.add(keys[1])
        elif is_service_network_key:
            memberships.add((path, keys[1], key))
        if val is None:
            continue  # bare list item: nothing to open on the stack
        if not val or val == "{}":
            stack.append((indent, key))
    return internal_nets, ips, memberships

all_internal, all_ips, all_memberships = set(), {}, set()
for f in COMPOSE_FILES:
    internal, ips, memberships = parse(f)
    all_internal |= internal
    all_ips.update(ips)
    all_memberships |= memberships

declared = set(sys.argv[1:])
problems = []
for (f, svc, net), ip in sorted(all_ips.items()):
    if net not in all_internal and ip not in declared:
        problems.append(f"{ip}\t{svc}\t{net}\t{f}\tmissing")
for f, svc, net in sorted(all_memberships):
    if net not in all_internal and (f, svc, net) not in all_ips:
        problems.append(f"-\t{svc}\t{net}\t{f}\tdynamic")
for line in problems:
    print(line)
sys.exit(1 if problems else 0)
PY
  ); then
    fail "WAN_TOUCHING_IPS does not fully cover WAN-capable service(s) — this test would leave real WAN access reachable for:
$(echo "$missing" | awk -F'\t' '{
  if ($5 == "dynamic") printf "  - %s (%s, %s): dynamic membership, no fixed ipv4_address — give it one so it can be added to WAN_TOUCHING_IPS\n", $2, $3, $4;
  else printf "  - %s (%s, %s): %s not in WAN_TOUCHING_IPS\n", $2, $3, $4, $1
}')
Fix each: add a missing fixed address to WAN_TOUCHING_IPS above, or give a dynamic membership a fixed ipv4_address (3.3-b follow-up 2) and then add it."
  fi
  echo "OK: WAN_TOUCHING_IPS covers every service on a non-internal network"
}

iptables_helper() {
  docker run --rm --net=host --cap-add=NET_ADMIN --privileged \
    --entrypoint iptables "$HELPER_IMAGE" "$@"
}

# The Docker host-gateway address (what `host.docker.internal` resolves
# to inside containers) is exempted from the drop: it is an ON-ISLAND
# path, not WAN — the nomad-gateway proxy legitimately reaches Project
# NOMAD's host-published Kiwix port through it (see
# ../services/config/nomad-gateway/nginx.conf), and on a production
# single-host node that same hop is effectively loopback. It sits outside
# 10.0.0.0/8 (192.168.65.x on Docker Desktop, 172.17.0.1-style on plain
# Linux), which is exactly why the plain `! -d 10.0.0.0/8` drop caught it
# once nomad-gateway joined WAN_TOUCHING_IPS and library.island broke
# under the test. Resolved at runtime, never hardcoded, so this works on
# both Docker Desktop and Linux hosts. Traffic to that single /32 cannot
# reach the internet — only services the host itself publishes.
hostgw_ip() {
  docker run --rm --add-host host.docker.internal:host-gateway \
    --entrypoint getent "$HELPER_IMAGE" ahostsv4 host.docker.internal | awk '{print $1; exit}'
}

drop_wan() {
  echo "== dropping real WAN routes for the standing island (DOCKER-USER, host-level) =="
  HOSTGW=$(hostgw_ip)
  [ -n "$HOSTGW" ] || fail "could not resolve the Docker host-gateway address for the on-island exemption"
  for ip in "${WAN_TOUCHING_IPS[@]}"; do
    iptables_helper -I DOCKER-USER 1 -s "$ip" ! -d 10.0.0.0/8 -j DROP
  done
  # Inserted last so it lands at position 1, above every DROP.
  iptables_helper -I DOCKER-USER 1 -d "$HOSTGW/32" -j RETURN
}

restore_wan() {
  echo "== restoring WAN routes =="
  if [ -n "${HOSTGW:-}" ]; then
    iptables_helper -D DOCKER-USER -d "$HOSTGW/32" -j RETURN 2>/dev/null || true
  fi
  for ip in "${WAN_TOUCHING_IPS[@]}"; do
    iptables_helper -D DOCKER-USER -s "$ip" ! -d 10.0.0.0/8 -j DROP 2>/dev/null || true
  done
}
trap restore_wan EXIT

portal_reports_wan_up() {
  docker exec services-portal-1 python3 -c "
import socket
try:
    socket.create_connection(('1.1.1.1', 443), timeout=2)
    print('true')
except OSError:
    print('false')
" 2>/dev/null
}

wan_edge_active() {
  docker exec backhaul-wan-edge-1 python3 -c "
import urllib.request as u, json
print(json.load(u.urlopen('http://127.0.0.1:8080/status', timeout=3))['active'])
" 2>/dev/null
}

check_wan_touching_ips_complete

echo "== bringing up the island + backhaul (WAN present) =="
../../island.sh up
docker compose -f compose.yaml up -d --build

drop_wan

echo "== confirming the drop actually took effect =="
up="true"
for _ in $(seq 1 "$BUDGET"); do
  up=$(portal_reports_wan_up)
  [ "$up" = "false" ] && break
  sleep 1
done
[ "$up" = "false" ] || fail "portal still reports WAN reachable after dropping routes — drop did not take effect"
echo "OK: portal confirms WAN is genuinely unreachable"

echo "== bonus consistency check: wan-edge's own uplinks agree (1.4-a) =="
# Not required by this task's own acceptance text — free evidence that a
# real routes-level drop (here) and a simulated disconnect (1.4-a's own
# verify.sh) agree on the outcome.
active="unknown"
for _ in $(seq 1 "$BUDGET"); do
  active=$(wan_edge_active)
  [ "$active" = "None" ] && break
  sleep 1
done
if [ "$active" != "None" ]; then
  echo "WARN: wan-edge still reports active uplink '$active' ${BUDGET}s after the real drop — non-fatal to this test, see README"
else
  echo "OK: wan-edge also reports no healthy uplink"
fi

echo "== running the full M1-sim acceptance set with real WAN dropped =="
echo "-- stack/core --"
../core/verify.sh || fail "stack/core/verify.sh failed with WAN dropped"
echo "-- stack/services --"
../services/verify.sh || fail "stack/services/verify.sh failed with WAN dropped"

restore_wan
trap - EXIT

echo "== verifying recovery + failback =="
up="false"
for _ in $(seq 1 "$BUDGET"); do
  up=$(portal_reports_wan_up)
  [ "$up" = "true" ] && break
  sleep 1
done
[ "$up" = "true" ] || fail "portal did not recover WAN reachability within ${BUDGET}s of restoring routes"
echo "OK: portal recovered WAN reachability"

active="unknown"
for _ in $(seq 1 "$BUDGET"); do
  active=$(wan_edge_active)
  [ "$active" = "fixed" ] && break
  sleep 1
done
[ "$active" = "fixed" ] || fail "wan-edge did not fail back to 'fixed' within ${BUDGET}s of restoring routes"
echo "OK: wan-edge failed back to 'fixed'"

echo
echo "ALL CHECKS PASSED"
