#!/usr/bin/env bash
# ResCCOM 1.2-a (5G half) — srsRAN Project ZMQ gNB verification against the
# 5G core's AMF.
#
# Unlike verify-4g.sh this CANNOT check register/IP/local-breakout: there is
# no UE in compose.5g.yaml, and none is available from an upstream this
# project is allowed to consume (see README.md "5G ZMQ rig — negative
# finding" for the full evidence trail). What this script CAN and does
# check for real: does the srsRAN Project gNB start under the ZMQ device
# with our config, and does the Open5GS AMF accept its NGAP association
# with no NG-Setup failure. As of the last run recorded in README.md, it
# does not get that far — a packaging bug in gradiant/srsran-5g's
# entrypoint corrupts the gNB's YAML config before the binary ever starts,
# for any ZMQ-mode configuration, not just ours. This script therefore
# fails informatively rather than faking a pass; if the upstream image
# entrypoint is ever fixed, the same script starts passing the NG-Setup
# check without modification.
#
# [SIM] path only — nothing here radiates RF.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

CORE_DIR=../core
RAN="docker compose -f compose.5g.yaml"

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

echo "== bringing up srsRAN 5G gNB (ZMQ virtual radio, no UE — see README) =="
docker network inspect core_core_net >/dev/null 2>&1 \
  || fail "core_core_net network not found — is stack/core up under its own compose project?"
$RAN down 2>/dev/null || true
$RAN up -d

echo "== check: gNB process comes up and stays up (no config/parse crash loop) =="
CID=$($RAN ps -q gnb5g)
[ -n "$CID" ] || fail "gnb5g container did not get created"
stable=0
exitcode=""
for i in $(seq 1 15); do
  sleep 2
  restarts=$(docker inspect -f '{{.RestartCount}}' "$CID" 2>/dev/null || echo 0)
  exitcode=$(docker inspect -f '{{.State.ExitCode}}' "$CID" 2>/dev/null || echo "")
  if [ "$i" -eq 15 ] && [ "${restarts:-0}" = "0" ]; then
    stable=1
  fi
done

if [ "$stable" -eq 1 ]; then
  echo "OK: gNB process is up and stable (config parsed, binary running)"
else
  # `docker inspect` (RestartCount/ExitCode) has been reliable on this host
  # throughout every run this rig was tested against; `docker logs` on the
  # same container ID, queried from a script rather than interactively,
  # has not — it has repeatedly come back empty here even 60+ seconds
  # after `docker inspect` already showed the crash, for reasons that look
  # like a Docker Desktop log-delivery quirk rather than the error somehow
  # going away (manually re-running `docker logs` against the very same ID
  # moments later always shows it). So: best-effort log grep for
  # corroboration, but the pass/fail call is made on the exit code, which
  # this rig has reproduced as exit 103 every single time (dozens of
  # restarts, this session) for exactly one cause — see README.md "5G ZMQ
  # rig — negative finding" for the full evidence trail, gathered
  # interactively against these same container IDs.
  saw_parse_error=0
  docker logs "$CID" 2>&1 | grep -qF "Error parsing YAML configuration file" && saw_parse_error=1
  if [ "$exitcode" = "103" ] || [ "$saw_parse_error" -eq 1 ]; then
    echo "FAIL: gNB never started — upstream gradiant/srsran-5g entrypoint" >&2
    echo "      corrupts its own YAML config in ZMQ mode (yaml-cpp: illegal" >&2
    echo "      map value, exit code 103). This is not our config and not" >&2
    echo "      this host — it is a reproducible packaging bug in every" >&2
    echo "      published tag since 2024 (unchanged entrypoint.sh, checked" >&2
    echo "      through 25_10). Full negative-finding writeup: README.md" >&2
    echo "      \"5G ZMQ rig — negative finding\"." >&2
    exit 1
  fi
  fail "gNB container did not stay up (restarts=$restarts, exit=$exitcode) — check: docker compose -f compose.5g.yaml logs gnb5g"
fi

echo "== check: AMF accepted the gNB's NGAP association, no NG-Setup failure =="
# Left as a log-grep gate, deliberately, unlike the live-state checks WBS
# 3.2-e added elsewhere (verify-4g.sh, verify-5g-oai.sh, core/verify.sh,
# services/verify.sh all poll a live tunnel interface instead): there is
# no gNB-side interface to poll here (no UE/PDU session exists in this
# rig -- see this script's own header), and NG-Setup accept/reject is an
# NGAP application-layer outcome, not visible in kernel-level SCTP
# association state (the SCTP association itself can stay up either way).
# Moot in practice today regardless: this rig has never reached the AMF
# at all, crashing first on the upstream YAML bug documented below.
assoc=0
for _ in $(seq 1 15); do
  if (cd "$CORE_DIR" && docker compose logs amf 2>&1 | grep -q "\[Added\] Number of gNBs is now"); then
    assoc=1
    break
  fi
  sleep 2
done
[ "$assoc" -eq 1 ] || fail "AMF never logged a gNB association — NGAP/SCTP never connected"
if (cd "$CORE_DIR" && docker compose logs amf 2>&1 | grep -q "NG-Setup failure"); then
  fail "AMF rejected the gNB's NG Setup — see: (cd $CORE_DIR && docker compose logs amf) for the cause"
fi
echo "OK: AMF has the gNB associated with no NG-Setup failure logged"

echo
echo "== check: register + local-breakout (NOT RUN) =="
echo "No UE exists in this rig and none is available from an approved"
echo "upstream (srsRAN Project ships no UE app; UERANSIM has no PHY/ZMQ"
echo "layer). See README.md \"5G ZMQ rig — negative finding\"."
echo
echo "PARTIAL: gNB<->AMF path verified; UE attach + local-breakout not"
echo "         achievable with this project's approved upstreams. Full"
echo "         1.2-a acceptance criteria for the 5G half are NOT met."
exit 1
