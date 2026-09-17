#!/usr/bin/env python3
"""ResCCOM 1.4-a — wand: the WAN-uplink failover daemon + status endpoint.

Runs inside wan-edge (../compose.yaml, ../Dockerfile). One thread
continuously health-checks every configured uplink (uplinks.yaml) and
keeps the container's own default route pointed at the highest-priority
*healthy* one — "mwan3-style scripts" (TASKS.md 1.4-a step 2), chosen
over systemd-networkd because the failover unit here is a handful of
`ip route`/`ip rule` calls a plain loop can drive and poll directly,
which is easier to test deterministically (see ../verify.sh) than
reasoning about systemd-networkd's own reconnect/backoff timers. A
second thread serves GET /status as plain JSON (same shape/reasoning as
../../services/config/portal/server.py's own /status) for the portal's
status display and for ../verify.sh's own polling.

Health check, per uplink, per pass:
  1. Link check — ping the uplink's own gateway, bound to that uplink's
     interface (`ping -I`). This is what a simulated "unplug"
     (`docker network disconnect`, see ../verify.sh) breaks instantly:
     the interface disappears, find_iface() stops finding it, and the
     uplink is marked unhealthy before ping is even attempted again.
  2. Path check — resolve a real hostname against a public resolver,
     sourced from that uplink's own address (`dig -b`). A link can be up
     (Docker network still attached) while the path beyond it is dead
     (e.g. the simulated satellite CPE's own upstream is out) — the link
     check alone can't see that, only routing this specific query out
     this specific uplink can.

Both checks need every uplink's traffic to actually leave via ITS OWN
interface regardless of which uplink currently holds the main default
route — Docker only ever puts one attached network on that route. Each
uplink therefore gets its own routing table (`ip route ... table N`) plus
a source-address `ip rule` pinning that uplink's own IP to its own table
(setup_policy_routing) — the standard Linux policy-routing technique
mwan3 itself is built on, just driven directly here instead of through
mwan3's own config format.

1.4-c — QoS ("emergency traffic wins"): whenever an uplink becomes the
active one, setup_qos() shapes its egress to that uplink's own configured
bandwidth_kbit (uplinks.yaml) with three strict-priority HTB classes —
PEMEA/112 (reserved, no live match yet — Phase 4, WBS 4.3), Matrix +
operational coordination (TCP 8448, the Matrix federation port), and
everything else (HTB's own default class). TASKS.md's own suggestion was
"tc/cake-based"; this dev machine's kernel (Docker Desktop's LinuxKit VM)
has neither `cake` nor even `fq_codel` built in (confirmed: `tc qdisc add
... cake`/`fq_codel` both fail "Specified qdisc kind is unknown"), so
this uses HTB + SFQ instead — see ../README.md "QoS: emergency traffic
wins (1.4-c)" for the fuller reasoning, including why HTB's *strict*
class priority arguably matches "emergency traffic wins" more directly
than cake's fairness-oriented diffserv tins would have anyway.
"""
import json
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

CONFIG_PATH = "/app/uplinks.yaml"
STATUS_PORT = 8080
CHECK_INTERVAL = 3.0
PROBE_TIMEOUT = 2  # whole seconds — both ping -W and dig +time want an integer
DNS_PROBE_RESOLVER = "1.1.1.1"
DNS_PROBE_NAME = "one.one.one.one"
# First unused table IDs on a stock Debian image (0-255 has reserved
# ones like 254/main, 255/local) — plenty of headroom below 253.
FIRST_TABLE_ID = 101

# 1.4-c — QoS. Matrix's own server-server (federation) API port — a real,
# documented port (matrix.org spec), not an invented one — is the only
# tier-2 traffic this deployment can actually classify today; the
# PEMEA/112 tier (highest priority) is reserved but has no live match
# rule yet, since no PEMEA integration (WBS 4.3, Phase 4) exists in this
# codebase to generate that traffic — see ../README.md.
MATRIX_FEDERATION_PORT = 8448
# HTB class IDs, and each one's guaranteed share of the uplink's own
# bandwidth_kbit — all three get `ceil` = the full link, so a quiet
# higher class never wastes capacity a busy lower one could use; the
# *guaranteed* rate (not the ceiling) is what actually protects a class
# under contention, which is what TASKS.md 1.4-c's acceptance criterion
# tests. Order here is priority order (0 = served first).
QOS_CLASSES = [
    # (classid, htb prio, guaranteed % of link, name)
    ("1:10", 0, 20, "pemea"),      # reserved — see MATRIX_FEDERATION_PORT comment
    ("1:20", 1, 30, "matrix"),
    ("1:30", 2, 50, "default"),    # HTB's "default 30" catches everything unmarked
]

state_lock = threading.Lock()
state = {"uplinks": {}, "active": None, "changed_at": None}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 1, "", "timeout")


def load_uplinks():
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    uplinks = []
    for i, u in enumerate(cfg["uplinks"]):
        uplinks.append({
            "name": u["name"],
            "self_ip": u["self_ip"],
            "gateway": u["gateway"],
            "bandwidth_kbit": u["bandwidth_kbit"],
            "priority": i,
            "table": FIRST_TABLE_ID + i,
            "iface": None,
        })
    return uplinks


def find_iface(self_ip):
    """Which interface currently holds this uplink's static address —
    discovered at runtime rather than assumed (e.g. "eth1") because
    compose lets us pin each network's IP but not its in-container
    interface name, and a `docker network disconnect`/`connect` cycle
    (../verify.sh's own "unplug"/"replug") is not guaranteed to hand the
    reconnecting network back the same ethN it had before."""
    out = sh(["ip", "-o", "-4", "addr", "show"]).stdout
    for line in out.splitlines():
        # e.g. "3: eth1    inet 10.90.1.2/28 brd ... scope global eth1"
        parts = line.split()
        if len(parts) >= 4 and parts[3].split("/")[0] == self_ip:
            return parts[1]
    return None


def setup_policy_routing(up):
    """Idempotent: (re)point this uplink's dedicated table at its own
    gateway/interface and (re)pin its own source address to that table.
    Safe to call every time an uplink's interface is (re)discovered,
    including after a simulated replug where the interface may have come
    back as a different ethN than before."""
    iface, gw, table, ip = up["iface"], up["gateway"], up["table"], up["self_ip"]
    sh(["ip", "route", "replace", "default", "via", gw, "dev", iface, "table", str(table)])
    sh(["ip", "rule", "del", "from", ip])  # drop any stale rule first (e.g. pointing at an old table)
    sh(["ip", "rule", "add", "from", ip, "table", str(table)])


def ping_ok(iface, target):
    r = sh(["ping", "-I", iface, "-c", "1", "-W", str(PROBE_TIMEOUT), target])
    return r.returncode == 0


def dns_probe_ok(self_ip):
    r = sh([
        "dig", f"+time={int(PROBE_TIMEOUT)}", "+tries=1",
        "-b", self_ip, f"@{DNS_PROBE_RESOLVER}", DNS_PROBE_NAME,
    ])
    return r.returncode == 0 and "status: NOERROR" in r.stdout


def check_uplink(up):
    if up["iface"] is None:
        up["iface"] = find_iface(up["self_ip"])
        if up["iface"] is not None:
            setup_policy_routing(up)
    if up["iface"] is None:
        return False  # not attached right now — the simulated "unplugged" state
    if not ping_ok(up["iface"], up["gateway"]):
        # Interface still attached but the link itself is dead — re-probe
        # for a fresh iface name next pass in case it was actually a
        # disconnect/reconnect rather than a genuine link failure.
        up["iface"] = None
        return False
    return dns_probe_ok(up["self_ip"])


def setup_qos(iface, bandwidth_kbit):
    """(Re)apply 1.4-c's HTB+SFQ shaping to this uplink's own egress —
    see the module docstring for why HTB/SFQ instead of TASKS.md's
    suggested cake. Idempotent and safe to call on every active-uplink
    change: `tc qdisc replace` on a fresh interface is exactly the same
    as adding it new, and the classification chain is flushed and
    rebuilt each time rather than tracking per-interface rule diffs —
    simpler, and correct even across a failover where the new active
    interface has a different ethN than the old one had (see
    find_iface's own docstring for why that's not guaranteed stable)."""
    # See ../Dockerfile's ethtool comment: without this, HTB rate-limits
    # by GSO superpacket count, not real wire packet count, and egress
    # can run multiple times faster than the configured rate.
    sh(["ethtool", "-K", iface, "gso", "off", "gro", "off", "tso", "off"])
    sh(["tc", "qdisc", "replace", "dev", iface, "root", "handle", "1:", "htb", "default", "30"])
    sh(["tc", "class", "replace", "dev", iface, "parent", "1:", "classid", "1:1",
        "htb", "rate", f"{bandwidth_kbit}kbit", "ceil", f"{bandwidth_kbit}kbit"])
    for classid, prio, share_pct, _label in QOS_CLASSES:
        rate_kbit = max(1, bandwidth_kbit * share_pct // 100)
        sh(["tc", "class", "replace", "dev", iface, "parent", "1:1", "classid", classid,
            "htb", "rate", f"{rate_kbit}kbit", "ceil", f"{bandwidth_kbit}kbit", "prio", str(prio)])
        # sfq leaves: fairness *within* a class (many small Matrix
        # messages, say) without that being this task's own concern —
        # HTB's classes are what enforce the cross-class priority.
        sh(["tc", "qdisc", "replace", "dev", iface, "parent", classid,
            "handle", f"{classid.split(':')[1]}:", "sfq", "perturb", "10"])

    # A fixed, named chain (flushed and rebuilt, not diffed) so a
    # changed active interface never leaves a stale rule pointing at an
    # interface that's no longer the one carrying traffic.
    sh(["iptables", "-t", "mangle", "-N", "WAND_QOS"])  # no-op (ignored) if it already exists
    sh(["iptables", "-t", "mangle", "-F", "WAND_QOS"])
    sh(["iptables", "-t", "mangle", "-A", "WAND_QOS", "-o", iface, "-p", "tcp",
        "--dport", str(MATRIX_FEDERATION_PORT), "-j", "CLASSIFY", "--set-class", "1:20"])
    sh(["iptables", "-t", "mangle", "-A", "WAND_QOS", "-o", iface, "-p", "tcp",
        "--sport", str(MATRIX_FEDERATION_PORT), "-j", "CLASSIFY", "--set-class", "1:20"])
    if sh(["iptables", "-t", "mangle", "-C", "POSTROUTING", "-j", "WAND_QOS"]).returncode != 0:
        sh(["iptables", "-t", "mangle", "-A", "POSTROUTING", "-j", "WAND_QOS"])


def set_active(name, uplinks_by_name):
    sh(["ip", "route", "del", "default"])
    if name is not None:
        up = uplinks_by_name[name]
        sh(["ip", "route", "replace", "default", "via", up["gateway"], "dev", up["iface"]])
        setup_qos(up["iface"], up["bandwidth_kbit"])
    with state_lock:
        state["active"] = name
        state["changed_at"] = now_iso()


def monitor_loop(uplinks):
    uplinks_by_name = {u["name"]: u for u in uplinks}
    while True:
        healthy = []
        for up in uplinks:
            ok = check_uplink(up)
            with state_lock:
                state["uplinks"][up["name"]] = {
                    "priority": up["priority"],
                    "healthy": ok,
                    "attached": up["iface"] is not None,
                    "last_checked": now_iso(),
                }
            if ok:
                healthy.append(up)

        best = min(healthy, key=lambda u: u["priority"]) if healthy else None
        with state_lock:
            current = state["active"]
        best_name = best["name"] if best else None
        if best_name != current:
            set_active(best_name, uplinks_by_name)

        time.sleep(CHECK_INTERVAL)


class Handler(BaseHTTPRequestHandler):
    server_version = "wand/1.4-a"

    def do_GET(self):
        if self.path.rstrip("/") != "/status":
            self.send_response(404)
            self.end_headers()
            return
        with state_lock:
            body = json.dumps(state).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    uplinks = load_uplinks()
    with state_lock:
        for u in uplinks:
            state["uplinks"][u["name"]] = {
                "priority": u["priority"], "healthy": False,
                "attached": False, "last_checked": None,
            }
    threading.Thread(target=monitor_loop, args=(uplinks,), daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", STATUS_PORT), Handler).serve_forever()
