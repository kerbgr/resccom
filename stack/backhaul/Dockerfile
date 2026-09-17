# ResCCOM 1.4-a — wan-edge: the WAN-uplink failover daemon's runtime.
#
# A custom image, not "mount a script into a stock image" (the pattern
# every other component in this repo uses, e.g.
# ../services/config/portal/server.py) — wand.py shells out to iproute2
# (policy-routing tables/rules — see README.md "Why containers, not real
# interfaces"), iputils-ping and dnsutils (the per-uplink health probe),
# none of which the stock python:3.12 image ships. debian:12-slim matches
# CLAUDE.md's own deployment target (Debian 12+), so this is the same
# base OS the failover logic would eventually run directly on outside a
# container, not a different environment to re-validate against later.
#
# iptables is here for a second, unrelated reason: ../unplug-test.sh
# (1.4-b) reuses this same image as a throwaway `--net=host --privileged`
# helper to add/remove the real DOCKER-USER firewall rules that drop the
# island's actual WAN routes — see its own header comment. wand.py itself
# never calls iptables for that purpose.
#
# ethtool is for 1.4-c's QoS shaping: veth interfaces (what every
# uplink here actually is) default to GSO/TSO/GRO on, which lets the
# kernel hand a qdisc one "superpacket" that only gets segmented into
# real wire-sized packets *after* it's already past the qdisc — HTB then
# rate-limits by superpacket count, not real packet count, and
# egress can run multiple times faster than the configured rate.
# Confirmed live during development (a 2000kbit-capped class sustained
# ~4.8Mbit/s until offloads were turned off on the shaped interface).
# wand.py's setup_qos() disables them there before applying any shaping.
FROM debian:12.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      iproute2 iputils-ping dnsutils iptables ethtool python3 python3-yaml \
    && rm -rf /var/lib/apt/lists/*

COPY config/wand.py /app/wand.py
WORKDIR /app
ENTRYPOINT ["python3", "/app/wand.py"]
