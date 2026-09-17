#!/bin/sh
# ResCCOM 3.3-b — brings up this island's wg0 interface directly via
# `ip`/`wg` (not wg-quick): the private key is read straight from the
# single mounted file (/run/secrets/wireguard.key, read-only -- see
# ../compose.yaml.j2's own header) via `wg set wg0 private-key <file>`,
# so the key's plaintext value is never written into this script, any
# other rendered file, or even transiently into a combined config file
# inside the container -- `wg set` reads it directly.
#
# Rendered from island.yaml by island-init render — do not hand-edit.
set -e

ip link add wg0 type wireguard
wg set wg0 private-key /run/secrets/wireguard.key listen-port 51820

ip addr add 10.99.0.1/24 dev wg0
ip link set up dev wg0


# net.ipv4.ip_forward is set by ../compose.yaml.j2's `sysctls:`, not here
# (a plain in-container sysctl write is permission-denied even with
# NET_ADMIN).
#
# Masquerade tunnel-origin traffic before it enters this island's own
# core_net (found live, 3.3-b): core_net's `internal: true` (1.1-c) drops
# any bridged packet whose source isn't itself a core_net member -- even
# between two containers already on that same bridge, since
# bridge-nf-call-iptables makes intra-bridge traffic subject to the same
# FORWARD-chain check. A peer's un-rewritten source address gets dropped
# right at that door; rewriting it to this container's own core_net
# address (this rule) makes the destination NF's reply directly routable
# back here without the NF needing a route of its own. Outbound
# (local -> tunnel) traffic needs no such rule: the peer's own allow-list
# already routes our *entire* node_internal_base/services_prefix, not
# just one address, so it can route a reply to whatever local address
# actually asked. services_net isn't `internal: true`, so it needs no
# masquerade either. (POSTROUTING can't match `-i`, only `-o` -- matching
# "destined into core_net but not already sourced from it" gets the same
# effect without needing to name core_net's own interface, which Docker
# doesn't guarantee stays eth0/eth1 in template-stable order.)
iptables -t nat -A POSTROUTING ! -s 10.10.0.0/24 -d 10.10.0.0/24 -j MASQUERADE

# 3.3-b follow-up 3 / threat model M8: the masquerade above makes a
# peer's traffic look locally-sourced so replies can route back, but on
# its own that also makes a peer reachable to *every* container on
# core_net, not just the ones roaming needs -- the allow-list
# (WireGuard's own allowed-ips, matched by `-i wg0` already implying an
# allow-listed peer) gates *which islands*, found live to gate nothing
# about *which services*. Forward-filter, narrowed in 3.3-c v2 (RFC-0003
# D1 amendment): a peer's own SEPP is now the only thing tunnel-origin
# traffic may reach, on its N32-c and N32-f ports (same address, two
# ports -- see sepp.yaml.j2's own comment on why one address, not
# upstream's three) -- NRF/AUSF/UDM are no longer directly reachable
# from the tunnel at all (SEPP is the sole cross-island NF; see
# stack/core/compose.yaml.j2's sepp service). HSS (the 4G equivalent)
# was never in this list -- 3.3-d hasn't rendered any Diameter routing
# over the overlay.

iptables -A FORWARD -i wg0 -d 10.10.0.0/24 -j DROP

exec tail -f /dev/null
