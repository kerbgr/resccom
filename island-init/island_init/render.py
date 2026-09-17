"""island-init render (2.1-b): island.yaml -> the existing service configs.

Only the handful of values RFC-0005 D1 actually assigns per-island (PLMN,
TAC, UE/services subnets, DNS zone, Diameter realm, backhaul uplinks,
portal association info, radio-site geometry) are substituted into each
target file -- everything else (container-internal addresses, security
algorithm orders, comment prose not about a rendered value) is left
exactly as the file already reads, so a lab-profile render reproduces
today's committed configs (TASKS.md's "golden rule").
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from ipaddress import ip_network
from pathlib import Path
from typing import Any

import jinja2

TEMPLATES_DIR = "templates"

# Docker-network addresses for each known uplink name (stack/backhaul/compose.yaml's
# own ipam blocks) -- not part of island.yaml, since they're container plumbing,
# not per-island allocation. A name outside this map has no known address yet
# (adding one is a compose.yaml change first, per that file's own header comment).
UPLINK_ADDRS: dict[str, tuple[str, str]] = {
    "fixed": ("10.90.1.2", "10.90.1.1"),
    "satellite": ("10.90.2.2", "10.90.2.1"),
    "ptp": ("10.90.3.2", "10.90.3.1"),
}

# Fixed last-octet offsets within allocations.services_prefix (today's
# stack/services/config/coredns/island.zone assignments).
SERVICE_IP_OFFSETS = {"dns": 53, "portal": 10, "library": 11, "chat": 20, "talk": 30, "console": 40}

# UPF's own second address, on services_net (not a DNS-visible service --
# stack/core/compose.yaml's own breakout-NAT gateway; see its ENABLE_NAT
# comment).
UPF_SERVICES_OFFSET = 2

# 3.3-b follow-up 2: wg-overlay's and a peered amf's own second addresses,
# on services_net -- found live: both previously joined with a dynamic
# (Docker-assigned) address, which stack/backhaul/unplug-test.sh's
# fixed-IP WAN_TOUCHING_IPS guard has no way to see, so it under-covered
# exactly the two containers that talk to the outside once federation is
# peered. Fixed like every other services_net member now.
WG_OVERLAY_SERVICES_OFFSET = 45
AMF_SERVICES_OFFSET = 5
# 3.3-c v2: SEPP is now the only container that originates cross-island
# traffic (N32, to a peer's SEPP) -- AMF talks to its own local SEPP over
# plain core_net and never touches the overlay directly, so this fixed
# services_net address replaces amf_services_ip's old peered-only role
# rather than sitting alongside it.
SEPP_SERVICES_OFFSET = 46

# WireGuard's IANA-registered default port (3.3-b). The container-internal
# listen port stays this fixed value always; stack/federation/compose.yaml's
# *host-published* port is separately env-var-defaulted so two co-located
# islands' wg-overlay containers don't collide (same WG_LISTEN_PORT-named
# override pattern as AMF_NGAP_PORT, SERVICES_NET_NAME).
WG_LISTEN_PORT = 51820

# 3.3-a: fixed last-octet offsets within node.internal_base's first /24
# (core_net) -- today's stack/core/compose.yaml ipv4_address assignments,
# now derived instead of hardcoded so a second island's node.internal_base
# (e.g. 10.20.0.0/16) doesn't collide with this one's on the same host.
NODE_IP_OFFSETS = {
    "mongo": 2,
    "smf": 4,
    "amf": 5,
    "upf": 7,
    "nrf": 10,
    "ausf": 11,
    "udm": 12,
    "pcf": 13,
    "nssf": 14,
    "bsf": 15,
    "udr": 20,
    "mme": 30,
    "sgwc": 31,
    "sgwu": 32,
    "hss": 33,
    "pcrf": 34,
    # 3.3-c v2: SEPP's own core_net address -- one, like every other NF
    # here (a container only ever gets one core_net IP in this stack).
    # Upstream's own roaming examples (configs/examples/5gc-no-scp-sepp*
    # .yaml.in) give SBI/N32-c/N32-f three separate addresses instead,
    # but that's an artifact of running all three PLMNs' NFs as loopback
    # aliases on one host, not a 3GPP requirement -- found live, giving
    # sepp a second/third core_net address the same way fails to bind
    # ("Cannot assign requested address": Docker only assigns the one
    # ipv4_address a compose service declares). SEPP_N32C_PORT/
    # SEPP_N32F_PORT below carry the same three-listener split on one
    # address + three ports instead.
    "sepp": 16,
}

SEPP_N32C_PORT = 7778
SEPP_N32F_PORT = 7779

# 3.3-c v2d: matches upstream's own home-PLMN roaming example
# (configs/examples/5gc-no-scp-sepp2-001-01.yaml.in, v2.8.0, fetched and
# read directly, not assumed) -- every NF that a *foreign* PLMN's AMF
# needs to discover (NRF itself, plus AUSF/UDM/SMF/NSSF) is addressed by
# its 3GPP FQDN as its own PRIMARY sbi.server listener there, with the
# plain core_net IP:7777 line commented out. AMF/PCF/BSF/UDR/SEPP keep
# their own plain IP:7777 listener in that same upstream file, unchanged
# -- they are never themselves the *target* of this kind of cross-PLMN
# lookup, so giving them an FQDN listener too would deviate from
# upstream for no reason. All ten still get an FQDN name (used for
# extra_hosts and, for the plain-IP five, nothing else) since any of
# them may originate a client.nrf.uri request.
FQDN_NF_NAMES = ("nrf", "ausf", "udm", "udr", "amf", "smf", "pcf", "nssf", "bsf", "sepp")
# Only these four (plus NRF, whose FQDN is its only listener) get their
# FQDN as sbi.server.address, on the DEFAULT port 80 -- no explicit
# `port:` line -- exactly as upstream's example. The FQDN in the profile
# is what makes ogs_sbi_fqdn_in_vplmn() fire (lib/sbi/context.c:3107);
# the default port matters too, found live in 3.3-c v2d: the home SEPP
# rebuilds its forwarding target from the bare FQDN in
# 3gpp-Sbi-Target-apiRoot (src/sepp/sbi-path.c), so a cross-island
# request always lands on port 80 whatever port discovery reported.
FQDN_ADDRESSED_NFS = ("ausf", "udm", "smf", "nssf")

# 3.3-c v2: gradiant/open5gs ships three SEPP TLS identities as fixed
# dev/example certs (/opt/open5gs/etc/open5gs/tls/sepp{1,2,3}.{key,crt},
# a shared ca.crt) tied to upstream's own three-PLMN roaming example
# (configs/examples/5gc-sepp*-{999-70,001-01,315-010}.yaml.in) -- not
# secrets (CLAUDE.md), upstream's own published dev PKI, reused
# unmodified exactly like udm.yaml.j2's hnet keys already are. This lab
# only ever has two islands, so only sepp1/sepp2 are used; a third island
# or any PLMN outside this pair has no matching cert and render refuses
# rather than silently mismatching an identity to a cert (a wrong pairing
# would just fail TLS at N32 handshake time with a less useful error).
SEPP_CERT_BY_PLMN = {
    ("999", "70"): "sepp1",
    ("001", "01"): "sepp2",
}

# (repo-relative target path, template path relative to TEMPLATES_DIR), in
# write/diff order.
TARGETS: list[tuple[str, str]] = [
    # 3.3-a: compose.yaml first -- it's the one file that declares core_net
    # itself (subnet + every NF's ipv4_address), so a second island's
    # node.internal_base takes effect here before any NF config that only
    # ever *references* those same addresses.
    ("stack/core/compose.yaml", "stack/core/compose.yaml.j2"),
    ("stack/core/config/amf.yaml", "stack/core/config/amf.yaml.j2"),
    ("stack/core/config/sepp.yaml", "stack/core/config/sepp.yaml.j2"),
    ("stack/core/config/mme.yaml", "stack/core/config/mme.yaml.j2"),
    ("stack/core/config/nrf.yaml", "stack/core/config/nrf.yaml.j2"),
    ("stack/core/config/ausf.yaml", "stack/core/config/ausf.yaml.j2"),
    ("stack/core/config/udm.yaml", "stack/core/config/udm.yaml.j2"),
    ("stack/core/config/udr.yaml", "stack/core/config/udr.yaml.j2"),
    ("stack/core/config/nssf.yaml", "stack/core/config/nssf.yaml.j2"),
    ("stack/core/config/pcf.yaml", "stack/core/config/pcf.yaml.j2"),
    ("stack/core/config/bsf.yaml", "stack/core/config/bsf.yaml.j2"),
    ("stack/core/config/sgwc.yaml", "stack/core/config/sgwc.yaml.j2"),
    ("stack/core/config/sgwu.yaml", "stack/core/config/sgwu.yaml.j2"),
    ("stack/core/config/smf.yaml", "stack/core/config/smf.yaml.j2"),
    ("stack/core/config/upf.yaml", "stack/core/config/upf.yaml.j2"),
    (
        "stack/core/config/freeDiameter/hss.conf",
        "stack/core/config/freeDiameter/hss.conf.j2",
    ),
    (
        "stack/core/config/freeDiameter/mme.conf",
        "stack/core/config/freeDiameter/mme.conf.j2",
    ),
    (
        "stack/core/config/freeDiameter/pcrf.conf",
        "stack/core/config/freeDiameter/pcrf.conf.j2",
    ),
    (
        "stack/core/config/freeDiameter/smf.conf",
        "stack/core/config/freeDiameter/smf.conf.j2",
    ),
    (
        "stack/services/config/coredns/island.zone",
        "stack/services/config/coredns/island.zone.j2",
    ),
    # 2.1-g: rendered under data/ (gitignored), not config/ -- this is a
    # per-deployment output of whatever island.yaml render was pointed at
    # (association name/operator contact for a real island), not shared
    # project state. A real `island.sh apply` must never dirty or leak
    # this into the repository's history. See TARGETS's own note at the
    # bottom of this module and stack/services/config/portal/
    # settings.example.json (the tracked golden-rule comparison fixture,
    # rendered once from island.example.yaml and never touched by apply).
    (
        "stack/services/data/portal/settings.json",
        "stack/services/config/portal/settings.json.j2",
    ),
    ("stack/backhaul/config/uplinks.yaml", "stack/backhaul/config/uplinks.yaml.j2"),
    # 3.3-b: the overlay module. No secret ever appears in either of these
    # -- see stack/federation/config/wg-up.sh.j2's own header.
    ("stack/federation/compose.yaml", "stack/federation/compose.yaml.j2"),
    # 2.1-g follow-up (3.3-b follow-up 1, found live): wg-up.sh's content
    # depends on overlay.wireguard_public_key, which -- unlike everything
    # else render v0 touches -- is freshly random on every `island-init
    # new`. Rendering it to a tracked path meant `island.sh up`'s routine
    # render_instance_outputs (2.1-g) dirtied the tree on a real
    # instance's very first render, the exact class of bug 2.1-g fixed
    # for portal settings/LIS geometry. Same fix: a gitignored data/
    # path, with config/wg-up.example.sh as the tracked golden-rule
    # snapshot (rendered once from island.example.yaml, whose null key
    # means no assertion block -- see EXAMPLE_SNAPSHOTS's own comment in
    # tests/test_render.py).
    ("stack/federation/data/wg-up.sh", "stack/federation/config/wg-up.sh.j2"),
]

# lis-geometry.json (RFC-0004 D3) has no prior committed format to match --
# no LIS consumer exists yet (WBS 4.3 is open) -- so it's built directly as
# data, not templated against a legacy file.
#
# 2.1-g: rendered to island-init/data/ (gitignored), the same
# per-deployment-output reasoning as the portal settings target above --
# island-init/lis-geometry.example.json is the tracked golden-rule
# comparison fixture.
LIS_GEOMETRY_TARGET = "island-init/data/lis-geometry.json"


class RenderError(Exception):
    """island.yaml is schema/semantically valid but render v0 can't handle it."""


@dataclass(frozen=True, slots=True)
class RenderedFile:
    path: str  # repo-relative
    content: str
    existing: str | None  # None if the file doesn't exist yet

    @property
    def changed(self) -> bool:
        return self.existing != self.content


def _env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.PackageLoader("island_init", TEMPLATES_DIR),
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )


def build_context(data: Any) -> dict[str, Any]:
    plmn = data["allocations"]["plmn"]
    tac_range = data["allocations"]["tac_range"]
    if tac_range[0] != tac_range[1]:
        raise RenderError(
            f"render v0 only supports a single TAC (tac_range[0] == tac_range[1]); "
            f"got {list(tac_range)} -- multi-TAC islands need a render v1 template change"
        )

    ue_net = ip_network(data["allocations"]["ue_prefix"]["v4"], strict=False)
    services_net = ip_network(data["allocations"]["services_prefix"], strict=False)
    realm = data["allocations"]["realm"]
    dns_zone = data["allocations"]["dns_zone"]

    # 3.3-a: node-internal addressing. core_net is the first /24 of
    # node.internal_base -- for the lab value (10.10.0.0/16) that's
    # 10.10.0.0/24, today's core_net unchanged (golden rule); a second
    # island's own internal_base (e.g. 10.20.0.0/16) derives a disjoint
    # core_net (10.20.0.0/24) with no template change needed.
    node_internal_base = ip_network(data["node"]["internal_base"], strict=False)
    core_net = ip_network(f"{node_internal_base.network_address}/24")

    # 3.3-c v2c: lab-only debug knob -- defaults to "info" (Open5GS's own
    # apparent default; every NF here has only ever logged at INFO level),
    # and templates only ever emit a `level:` line when this differs from
    # that default, so a default-level island's render is untouched
    # (golden rule).
    log_level = data["node"].get("log_level", "info")

    def svc_ip(offset: int) -> str:
        return str(services_net.network_address + offset)

    def node_ip(offset: int) -> str:
        return str(core_net.network_address + offset)

    uplinks = sorted(data["backhaul"]["uplinks"], key=lambda u: u["priority"])
    for uplink in uplinks:
        if uplink["name"] not in UPLINK_ADDRS:
            raise RenderError(
                f"render v0 has no known self_ip/gateway for uplink {uplink['name']!r} "
                f"(only {sorted(UPLINK_ADDRS)} exist as Docker networks in "
                "stack/backhaul/compose.yaml today)"
            )

    services = data.get("services") or {}

    # 3.3-b: this island's own overlay tunnel address is required for
    # render v0 -- stack/federation/compose.yaml's wg-overlay container
    # always renders (even with an empty allow-list) and needs one.
    overlay = (data.get("island") or {}).get("overlay") or {}
    overlay_address = overlay.get("address")
    if not overlay_address:
        raise RenderError(
            "island.overlay.address is required for render v0 (stack/federation's "
            "wg-overlay needs its own tunnel address, e.g. '10.99.0.1/24') -- "
            "set it before rendering"
        )

    peers_raw = data["federation"]["peers"]
    # 3.3-b follow-up 4: rendered as a literal into wg-up.sh so it can
    # assert, at startup, that the mounted private key actually matches
    # what island.yaml declares -- nullable (unlike overlay_address): a
    # freshly-built island.yaml with no key generated yet still renders
    # fine, it just skips that assertion (see checks.py's
    # check_wireguard_key_matches for the equivalent check at `check`/
    # `render` time).
    overlay_public_key = overlay.get("wireguard_public_key")

    # 3.3-c v2: each peer's SEPP address is derived the same way this
    # island's own NRF/AUSF/UDM addresses are -- a fixed offset within
    # the peer's own node_internal_base (already a required peer field)
    # -- so no new peer field is needed to carry it. receiver_id is the
    # identity SEPP puts in its own N32 handshake ("sepp1.localdomain"/
    # "sepp2.localdomain" upstream) and is looked up from the *peer's*
    # plmn since it names the peer, not this island.
    peers = []
    for p in peers_raw:
        peer_core_net = ip_network(f"{ip_network(p['node_internal_base'], strict=False).network_address}/24")
        peer_plmn = p["plmn"]
        peer_cert = SEPP_CERT_BY_PLMN.get((peer_plmn["mcc"], peer_plmn["mnc"]))
        if not peer_cert:
            raise RenderError(
                f"no bundled SEPP TLS identity for peer {p['name']!r}'s PLMN "
                f"{peer_plmn['mcc']}/{peer_plmn['mnc']} -- SEPP_CERT_BY_PLMN only "
                f"covers {sorted(SEPP_CERT_BY_PLMN)} (gradiant/open5gs's own bundled "
                "example certs); a third lab island or a real deployment needs real "
                "per-island PKI (WBS 3.4), not this lab shortcut"
            )
        peers.append({
            **p,
            "sepp_ip": str(peer_core_net.network_address + NODE_IP_OFFSETS["sepp"]),
            # n32.client.sepp[].receiver: names the *peer's* own SEPP
            # identity, per upstream's example pairing.
            "receiver_id": f"{peer_cert}.localdomain",
        })

    my_sepp_cert = SEPP_CERT_BY_PLMN.get((plmn["mcc"], plmn["mnc"]))
    if peers and not my_sepp_cert:
        raise RenderError(
            f"no bundled SEPP TLS identity for this island's own PLMN {plmn['mcc']}/{plmn['mnc']} "
            f"-- SEPP_CERT_BY_PLMN only covers {sorted(SEPP_CERT_BY_PLMN)}; see peer-side error "
            "for why this is a deliberate lab limit, not a bug"
        )
    # n32.server.sender: names *this* island's own SEPP identity.
    my_sender_id = f"{my_sepp_cert}.localdomain" if my_sepp_cert else None

    # 3.3-c v2d: the 3GPP FQDN convention Open5GS's own NRF uses for
    # inter-PLMN discovery (ogs_nrf_fqdn_from_plmn_id, TS23.003) -- mnc
    # is always zero-padded to 3 digits regardless of its real length
    # (matches what's observed live: PLMN 001/01 -> "mnc001", not
    # "mnc01"). Every core NF's FQDN, not just NRF's (see
    # FQDN_NF_NAMES above) -- this lab runs no DNS server on core_net, so
    # every core container needs extra_hosts entries (compose.yaml.j2)
    # mapping every one of these to its fixed core_net address, the same
    # role a real deployment's DNS plays for this same convention
    # (TS23.003) once it goes beyond one host.
    domain = f"5gc.mnc{plmn['mnc'].zfill(3)}.mcc{plmn['mcc']}.3gppnetwork.org"
    fqdns = {name: f"{name}.{domain}" for name in FQDN_NF_NAMES}
    fqdn_hosts = [
        {"fqdn": fqdns[name], "ip": node_ip(NODE_IP_OFFSETS[name])} for name in FQDN_NF_NAMES
    ]

    context = {
        "island_id": data["island"]["id"],
        "overlay_address": overlay_address,
        "overlay_public_key": overlay_public_key,
        "wg_listen_port": WG_LISTEN_PORT,
        "peers": peers,
        "mcc": plmn["mcc"],
        "mnc": plmn["mnc"],
        "tac": tac_range[0],
        "ue_subnet": str(ue_net),
        "ue_gateway": str(ue_net.network_address + 1),
        "ue_gateway_cidr": f"{ue_net.network_address + 1}/{ue_net.prefixlen}",
        "services_subnet": str(services_net),
        "core_net_subnet": str(core_net),
        "upf_services_ip": svc_ip(UPF_SERVICES_OFFSET),
        "wg_overlay_services_ip": svc_ip(WG_OVERLAY_SERVICES_OFFSET),
        "amf_services_ip": svc_ip(AMF_SERVICES_OFFSET),
        "sepp_services_ip": svc_ip(SEPP_SERVICES_OFFSET),
        "sepp_cert": my_sepp_cert,
        "sepp_sender_id": my_sender_id,
        "fqdn_hosts": fqdn_hosts,
        "sepp_n32c_port": SEPP_N32C_PORT,
        "sepp_n32f_port": SEPP_N32F_PORT,
        "log_level": log_level,
        "realm": realm,
        "dns_zone": dns_zone,
        "dns_ip": svc_ip(SERVICE_IP_OFFSETS["dns"]),
        "portal_ip": svc_ip(SERVICE_IP_OFFSETS["portal"]),
        "library_ip": svc_ip(SERVICE_IP_OFFSETS["library"]),
        "chat_ip": svc_ip(SERVICE_IP_OFFSETS["chat"]),
        "talk_ip": svc_ip(SERVICE_IP_OFFSETS["talk"]),
        "console_ip": svc_ip(SERVICE_IP_OFFSETS["console"]),
        "uplinks": uplinks,
        "uplink_addrs": UPLINK_ADDRS,
        "association_name": services.get("portal_association_name"),
        "operator_contact": services.get("portal_operator_contact"),
    }
    context.update({f"{name}_ip": node_ip(offset) for name, offset in NODE_IP_OFFSETS.items()})
    context.update({f"{name}_fqdn": fqdn for name, fqdn in fqdns.items()})
    return context


def build_lis_geometry(data: Any) -> str:
    """RFC-0004 D3's node-config geometry record: a straight projection of
    island.yaml's own sites[]/cells[] -- render adds nothing here that
    isn't already in island.yaml."""
    doc = {
        "_comment": "Rendered from island.yaml by island-init render -- do not hand-edit.",
        "island_id": data["island"]["id"],
        "sites": data.get("sites") or [],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def render_all(data: Any, repo_root: Path) -> list[RenderedFile]:
    env = _env()
    context = build_context(data)

    files: list[RenderedFile] = []
    for target_path, template_path in TARGETS:
        template = env.get_template(template_path)
        content = template.render(**context)
        existing_path = repo_root / target_path
        existing = existing_path.read_text(encoding="utf-8") if existing_path.exists() else None
        files.append(RenderedFile(path=target_path, content=content, existing=existing))

    lis_content = build_lis_geometry(data)
    lis_path = repo_root / LIS_GEOMETRY_TARGET
    lis_existing = lis_path.read_text(encoding="utf-8") if lis_path.exists() else None
    files.append(RenderedFile(path=LIS_GEOMETRY_TARGET, content=lis_content, existing=lis_existing))

    return files


def write_all(files: list[RenderedFile], repo_root: Path) -> list[RenderedFile]:
    """Writes every changed file; returns the subset actually written.

    Creates the target's parent directory if needed (2.1-g: the
    gitignored data/ destinations for per-deployment outputs don't exist
    on a fresh checkout -- island.sh up's first render must be able to
    create them, not assume a human already ran `mkdir -p`)."""
    written = []
    for f in files:
        if f.changed:
            path = repo_root / f.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f.content, encoding="utf-8")
            written.append(f)
    return written


def format_diff(files: list[RenderedFile]) -> str:
    """The exact text `island-init render --diff` prints -- shared with the
    Island Console (2.1-d) so "render --diff from the console equals the
    CLI's output" holds by construction, not by two implementations kept
    in sync by hand."""
    import difflib

    changed = [f for f in files if f.changed]
    if not changed:
        return "no changes\n"
    parts = []
    for f in changed:
        existing_lines = (f.existing or "").splitlines(keepends=True)
        new_lines = f.content.splitlines(keepends=True)
        diff = difflib.unified_diff(existing_lines, new_lines, fromfile=f"a/{f.path}", tofile=f"b/{f.path}")
        parts.append("".join(diff))
    return "".join(parts)
