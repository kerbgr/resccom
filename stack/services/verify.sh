#!/usr/bin/env bash
# ResCCOM 1.3-a/1.3-b/1.3-c/1.3-d/1.3-e/1.3-f — local DNS, library.island's
# real Kiwix content, chat.island's real Matrix E2EE messaging,
# talk.island's real audio calling, and portal.island's live status page:
# from the simulated UE, `.island` names resolve to the services subnet
# through the real (NAT'd) UE<->UPF->services_net path stack/core 1.3-a
# wired up — no stand-in involved — library.island proxies to Project
# NOMAD's Kiwix app (1.3-b), chat.island serves a real Synapse+Element
# Web deployment that two fresh accounts can exchange genuine E2EE
# messages over (1.3-c), talk.island serves a real Jitsi Meet deployment
# two browsers can hold an audio call over, with live RTP verified via
# getStats() (1.3-d), and portal.island renders live service/WAN status
# server-side, visible to plain curl with no JS (1.3-e). Check 8 below
# asserts portal's reported WAN state against an independent, live
# measurement rather than assuming WAN is up — this script runs
# unmodified with real WAN genuinely dropped as part of
# ../backhaul/unplug-test.sh (1.4-b), which is also this repo's first
# literal "unplug the cable" test (see that script's own header comment;
# 1.3-a's forward-failure check below only ever bounded latency, since a
# literal test didn't exist yet at 1.3 time).
#
# Bring-up itself (1.3-f) delegates to the top-level island.sh — this
# script's own job is what comes after: driving the UERANSIM simulator
# through the exact scenario 1.3-f's acceptance criterion describes
# (registers, browses library.island, sends an E2EE message), plus the
# fuller checks 1.3-a..e added along the way. This *is* how island.sh
# itself gets exercised, not a separate thing from it.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

CORE_DIR=../core

fail() { echo "FAIL: $1" >&2; exit 1; }

echo "== bringing up the island (delegates to island.sh) =="
../../island.sh up

echo "== bringing up UERANSIM gNB + UE =="
# Always recreate the pair, matching stack/ran/verify-4g.sh's own
# documented reasoning: a UE left running from an earlier session can
# silently lose its NGAP/PDU-session state (gNB logs "AMF selection...
# failed" / "PDU session not found") while its interface still shows a
# stale route, which a plain `up -d` won't notice or fix since it leaves
# already-running containers alone. Recreating is what actually makes
# this deterministic.
(cd "$CORE_DIR" && docker compose -f compose.yaml -f compose.sim.yaml stop gnb ue 2>/dev/null || true)
(cd "$CORE_DIR" && docker compose -f compose.yaml -f compose.sim.yaml rm -f gnb ue 2>/dev/null || true)
(cd "$CORE_DIR" && docker compose -f compose.yaml -f compose.sim.yaml up -d gnb ue)

UE="docker compose -f $CORE_DIR/compose.yaml -f $CORE_DIR/compose.sim.yaml"

echo "== check 1: UE registration + PDU session =="
# Polls the container's live interface state (exec'd fresh each
# iteration), not `docker compose logs` -- see stack/ran/verify-5g-oai.sh's
# header for why a script-driven log poll has been unreliable on this
# host. The log line is kept below as best-effort corroboration only,
# never the pass/fail gate.
registered=0
for _ in $(seq 1 15); do
  if $UE exec -T ue ip -4 -o addr show uesimtun0 2>/dev/null | grep -q .; then
    registered=1
    break
  fi
  sleep 2
done
[ "$registered" -eq 1 ] || fail "UE did not bring up uesimtun0 (no PDU session established)"
echo "OK: UE brought up uesimtun0"
if $UE logs ue 2>&1 | grep -q "Initial Registration is successful"; then
  echo "   (corroborated by ue log: 'Initial Registration is successful')"
fi

echo "== check 2: route the services subnet over the PDU session =="
# nr-ue's PDU session only auto-installs the route to its own assigned
# subnet, not to 10.46.0.0/24 — a real device's operator would provision
# this via routing advertisement; the sim UE needs it added explicitly.
$UE exec -T ue ip route add 10.46.0.0/24 dev uesimtun0 2>/dev/null || true

echo "== check 3: dig portal.island @10.46.0.53 resolves within the services subnet =="
RESULT=$($UE exec -T ue dig +short +time=3 +tries=2 portal.island @10.46.0.53)
[ -n "$RESULT" ] || fail "dig returned nothing for portal.island"
case "$RESULT" in
  10.46.0.*) echo "OK: portal.island -> $RESULT" ;;
  *) fail "portal.island resolved to $RESULT, not 10.46.0.x" ;;
esac

echo "== check 4: forward/upstream failure is a clean, fast SERVFAIL, not a hang =="
# This bounds a single query's wall time regardless of whether WAN is
# currently reachable — no query should ever hang either way — rather
# than asserting on the actual SERVFAIL/fallback path itself, which
# depends on which real state WAN happens to be in when this runs. The
# .island result above already proves that path is unaffected either
# way, since it's a separate, non-fallthrough server block in
# config/coredns/Corefile (see its own comment for why); ../backhaul/
# unplug-test.sh (1.4-b) is what actually drops real WAN and confirms
# the forwarder's fallback behavior under that condition.
START=$(date +%s)
$UE exec -T ue dig +tries=1 +time=5 unresolvable-example.invalid @10.46.0.53 >/dev/null 2>&1 || true
ELAPSED=$(( $(date +%s) - START ))
[ "$ELAPSED" -le 8 ] || fail "a single query took ${ELAPSED}s — that's a hang, not a clean failure"
echo "OK: query returned within ${ELAPSED}s"

echo "== check 5: curl http://library.island returns real Kiwix content =="
# A real device gets 10.46.0.53 pushed as its DNS server via PCO; the sim
# UE doesn't wire that up automatically, so point its resolver there
# directly — this is what lets a plain `curl http://library.island` (no
# explicit @server, unlike the dig checks above) resolve at all.
$UE exec -T ue sh -c "echo 'nameserver 10.46.0.53' > /etc/resolv.conf"
BODY=$($UE exec -T ue curl -s --max-time 10 http://library.island/)
echo "$BODY" | grep -qi "kiwix" || fail "library.island did not return Kiwix content"
echo "OK: library.island served Kiwix's landing page"

echo "== check 6: chat.island — two fresh accounts exchange a real E2EE message =="
# Real E2E crypto (Olm/Megolm), not just "a message got delivered": this
# registers two brand-new accounts, sends a message, decrypts it with an
# independently-keyed recipient client, and separately confirms over the
# raw client-server API that what Synapse actually stored is ciphertext
# (m.room.encrypted), never the plaintext body. See
# verify-matrix-e2ee.py's own docstring for the detail. Needs
# matrix-nio[e2e] + httpx, installed fresh into a throwaway container —
# not a repo dependency, so this is the only place that installs them.
# Can take several minutes on a repeat run: Synapse's registration rate
# limiter (rc_registration) throttles rapid re-runs from the same IP,
# and matrix-nio's client just backs off and retries rather than
# failing — slow, not broken.
docker run --rm --network resccom_services_net \
  -v "$(pwd)/verify-matrix-e2ee.py:/verify.py:ro" \
  python:3.12-slim sh -c "pip install --quiet matrix-nio[e2e] httpx && python3 /verify.py" \
  || fail "Matrix E2EE verification failed"

echo "== check 7: talk.island — two browsers hold a real audio call =="
# Two containers, not one: `npm install playwright` itself needs WAN
# (fetches from the real npm registry — this repo doesn't vendor it),
# but the actual call must be provably WAN-free. So install once on
# services_net (which does have WAN, for exactly this kind of tooling
# fetch — see README.md's own services_net note) into a reusable named
# volume, then run the real test in a SEPARATE container on
# `--network container:core-ue-1` — literally sharing the UE container's
# own network namespace (its actual uesimtun0 tunnel, its actual
# 10.45.0.x source address), the most literal reading of the acceptance
# criterion's "on the UE subnet". Caught live during development: running
# the *install* step against that namespace instead fails outright
# (ENETUNREACH — core_net's own path has no WAN route at all), which is
# exactly why the split exists. See verify-jitsi-call.js's own docstring
# for what the check itself proves (real getStats(), not just "both
# joined").
docker run --rm --network resccom_services_net \
  -v resccom-playwright-cache:/work \
  -w /work mcr.microsoft.com/playwright:v1.63.0-noble \
  npm install playwright@1.63.0 --no-audit --no-fund \
  || fail "could not install playwright (needs WAN — see comment above)"
docker run --rm --network "container:core-ue-1" \
  -v resccom-playwright-cache:/work \
  -v "$(pwd)/verify-jitsi-call.js:/work/verify.js:ro" \
  -w /work mcr.microsoft.com/playwright:v1.63.0-noble \
  node verify.js \
  || fail "Jitsi audio call verification failed"

echo "== check 8: portal.island renders live status, no JS required =="
# Plain curl (no JS execution) is 1.3-e's own acceptance test — status
# has to be server-rendered into the HTML itself, not fetched
# client-side after load, or this would only ever see the empty shell.
#
# What "WAN up" should mean here is measured independently, not assumed:
# earlier versions of this check hardcoded "up" (true on a 1.3-era dev
# host, but a real assumption, not a fact this script could actually
# guarantee). 1.4-b's unplug-test.sh now re-runs this exact script with
# real WAN genuinely dropped for the standing island (see its own header
# comment) — so this asserts portal's *reported* state agrees with an
# independently-measured *real* one, from portal's own container, using
# the same probe portal.island's own code makes (config/portal/server.py's
# WAN_PROBE_HOST/PORT) — not from wherever this script happens to run,
# which may have a completely different WAN path than portal's container
# does.
REAL_WAN_UP=$(docker exec services-portal-1 python3 -c "
import socket
try:
    socket.create_connection(('1.1.1.1', 443), timeout=3)
    print('true')
except OSError:
    print('false')
")
EXPECT_TEXT="down"; [ "$REAL_WAN_UP" = "true" ] && EXPECT_TEXT="up"
PORTAL_BODY=$($UE exec -T ue curl -s --max-time 10 http://portal.island/)
echo "$PORTAL_BODY" | grep -qi "Internet (WAN) uplink: $EXPECT_TEXT" \
  || fail "portal.island's reported WAN state didn't match reality (expected '$EXPECT_TEXT')"
echo "$PORTAL_BODY" | grep -qi "not anonymous" \
  || fail "portal.island is missing its SECURITY.md-constrained copy"
echo "OK: portal.island served live, server-rendered status (WAN reported as '$EXPECT_TEXT', matching reality)"

STATUS_JSON=$($UE exec -T ue curl -s --max-time 10 http://portal.island/status)
REAL_WAN_UP="$REAL_WAN_UP" STATUS_JSON="$STATUS_JSON" python3 -c "
import json, os
d = json.loads(os.environ['STATUS_JSON'])
expect = os.environ['REAL_WAN_UP'] == 'true'
assert d['wan_up'] is expect, f\"expected wan_up: {expect}, got {d['wan_up']}\"
assert d['dns_up'] is True, 'expected dns_up: true'
assert len(d['services']) == 3, f\"expected 3 services, got {len(d['services'])}\"
assert all(s['up'] for s in d['services']), f\"expected all services up: {d['services']}\"
" || fail "portal.island's /status JSON did not match reality"
echo "OK: portal.island's /status JSON matches — WAN='$EXPECT_TEXT' (real), all services up"

echo
echo "ALL CHECKS PASSED"
