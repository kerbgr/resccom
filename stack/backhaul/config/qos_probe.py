#!/usr/bin/env python3
"""ResCCOM 1.4-c — qos_probe: the peer + client roles for qos-test.sh.

Not part of wan-edge's own standing image behavior (wand.py never
imports or runs this) — it's throwaway test scaffolding qos-test.sh
mounts into two ephemeral containers built from the same wan-edge image,
matching the "heavy stuff lives in the verify/test script, not the
module itself" pattern ../verify.sh and ../unplug-test.sh already use.

Three roles:
  serve  — runs on the "peer" container (stands in for a remote endpoint
           reached over the uplink): a latency-echo TCP server on
           MATRIX_FEDERATION_PORT (accept+close is enough to time a
           round trip — this isn't testing Matrix itself, just whether
           traffic classified the same way real Matrix federation
           traffic would be gets through under contention), and a sink
           on BULK_PORT that reads and discards whatever the client
           sends it.
  probe  — runs on the "client" container: times `count` back-to-back
           connect+close round trips against the echo port and reports
           min/avg/max/p95 in milliseconds, as JSON on stdout.
  bulk   — runs on the "client" container: sends `bulk-mb` of data to
           the peer's sink, reporting elapsed time and throughput.

Deliberately a client->peer *upload* for the bulk role, not a literal
download, even though TASKS.md 1.4-c's own acceptance text says "a bulk
download" — see ../README.md "QoS: emergency traffic wins (1.4-c)" for
why: `tc` only shapes a given interface's own egress, so wand.py's
shaping (applied to wan-edge's uplink-facing interface, the one actually
constrained) only ever governs traffic *leaving toward the uplink*. A
literal download's bulk payload flows the other way (peer -> client) and
would need shaping on a second, client-facing interface that has nothing
to do with the uplink being tested. Client -> peer traffic is what
genuinely contends with the client -> peer Matrix-probe traffic on the
SAME shaped, classified egress — which is the actual mechanism TASKS.md
1.4-c asks for ("classify and prioritize on constrained uplinks").
"""
import argparse
import json
import socket
import statistics
import sys
import threading
import time

MATRIX_FEDERATION_PORT = 8448
BULK_PORT = 5001


def serve():
    def bulk_sink():
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", BULK_PORT))
        srv.listen(5)
        while True:
            conn, _ = srv.accept()
            total = 0
            try:
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    total += len(chunk)
            except OSError:
                pass
            finally:
                conn.close()

    def echo_server():
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", MATRIX_FEDERATION_PORT))
        srv.listen(20)
        while True:
            conn, _ = srv.accept()
            conn.close()  # accept+close is enough to time a round trip

    threading.Thread(target=bulk_sink, daemon=True).start()
    threading.Thread(target=echo_server, daemon=True).start()
    print(f"serving: echo on {MATRIX_FEDERATION_PORT}, bulk sink on {BULK_PORT}", flush=True)
    while True:
        time.sleep(3600)


def probe(host, count):
    samples = []
    for _ in range(count):
        start = time.monotonic()
        try:
            with socket.create_connection((host, MATRIX_FEDERATION_PORT), timeout=5):
                pass
            samples.append((time.monotonic() - start) * 1000)
        except OSError:
            samples.append(None)
        time.sleep(0.2)
    ok = [s for s in samples if s is not None]
    if not ok:
        print(json.dumps({"count": len(samples), "failed": len(samples), "avg_ms": None}))
        return
    ok.sort()
    print(json.dumps({
        "count": len(samples),
        "failed": len(samples) - len(ok),
        "min_ms": round(ok[0], 1),
        "avg_ms": round(statistics.mean(ok), 1),
        "max_ms": round(ok[-1], 1),
        "p95_ms": round(ok[int(len(ok) * 0.95)] if len(ok) > 1 else ok[0], 1),
    }))


def bulk(host, bulk_mb):
    payload = b"x" * (1024 * 1024)
    start = time.monotonic()
    total = 0
    with socket.create_connection((host, BULK_PORT), timeout=60) as s:
        for _ in range(bulk_mb):
            s.sendall(payload)
            total += len(payload)
    elapsed = time.monotonic() - start
    kbps = (total / 1024) / elapsed if elapsed > 0 else 0
    print(f"uploaded {total} bytes in {elapsed:.1f}s ({kbps:.0f} KB/s)", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("role", choices=["serve", "probe", "bulk"])
    p.add_argument("--host", default="")
    p.add_argument("--bulk-mb", type=int, default=6)
    p.add_argument("--count", type=int, default=15)
    args = p.parse_args()
    if args.role == "serve":
        serve()
    elif args.role == "probe":
        probe(args.host, args.count)
    elif args.role == "bulk":
        bulk(args.host, args.bulk_mb)
    else:
        sys.exit(1)
