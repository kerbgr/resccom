"""island-init render (2.1-b): unit coverage + the golden-rule check against
the real repo (skipped if this checkout's stack/ layout has moved)."""
from pathlib import Path

import pytest

from island_init.render import RenderError, build_context, render_all
from island_init.yaml_io import load

EXAMPLE = Path(__file__).parent.parent / "island.example.yaml"
REPO_ROOT = Path(__file__).parent.parent.parent

# 2.1-g: these two render targets are per-deployment outputs, rendered to
# a gitignored data/ location that won't exist (or may hold a different
# instance's content) on an arbitrary checkout -- comparing them via
# RenderedFile.changed (which diffs against whatever's live at that
# gitignored path) would be meaningless. Their golden-rule baseline is
# instead a dedicated tracked snapshot, rendered once from
# island.example.yaml and never touched by `island-init apply`.
EXAMPLE_SNAPSHOTS = {
    "stack/services/data/portal/settings.json": "stack/services/config/portal/settings.example.json",
    "island-init/data/lis-geometry.json": "island-init/lis-geometry.example.json",
    # 3.3-b follow-up 1: wg-up.sh joined this category once its content
    # started depending on overlay.wireguard_public_key -- freshly random
    # on every `island-init new`, unlike everything else render v0
    # touches (see render.py's own TARGETS comment on this entry).
    "stack/federation/data/wg-up.sh": "stack/federation/config/wg-up.example.sh",
}


def test_build_context_from_lab_example():
    data = load(EXAMPLE)
    ctx = build_context(data)
    assert ctx["mcc"] == "001"
    assert ctx["mnc"] == "01"
    assert ctx["tac"] == 1
    assert ctx["ue_subnet"] == "10.45.0.0/16"
    assert ctx["ue_gateway"] == "10.45.0.1"
    assert ctx["dns_ip"] == "10.46.0.53"
    assert ctx["portal_ip"] == "10.46.0.10"
    assert ctx["library_ip"] == "10.46.0.11"
    assert ctx["chat_ip"] == "10.46.0.20"
    assert ctx["talk_ip"] == "10.46.0.30"
    assert ctx["realm"] == "localdomain"
    assert ctx["dns_zone"] == "island"
    assert [u["name"] for u in ctx["uplinks"]] == ["fixed", "satellite", "ptp"]
    # 3.3-b
    assert ctx["island_id"] == "lab"
    assert ctx["overlay_address"] == "10.99.0.1/24"
    assert ctx["wg_listen_port"] == 51820
    assert ctx["peers"] == []


def test_build_context_requires_overlay_address():
    data = load(EXAMPLE)
    data["island"]["overlay"]["address"] = None
    with pytest.raises(RenderError, match="overlay.address"):
        build_context(data)


def test_build_context_rejects_tac_range():
    data = load(EXAMPLE)
    data["allocations"]["tac_range"] = [1, 5]
    with pytest.raises(RenderError, match="single TAC"):
        build_context(data)


def test_build_context_rejects_unknown_uplink_name():
    data = load(EXAMPLE)
    data["backhaul"]["uplinks"][0]["name"] = "microwave"
    with pytest.raises(RenderError, match="microwave"):
        build_context(data)


def test_render_allow_lists_a_peer(tmp_path):
    """3.3-b: a non-empty federation.peers[] reaches both new render
    targets -- the wg-overlay peer/allowed-ips line and (3.3-c v2) the
    sepp service's compose/config rendering (island_with_peer.yaml has
    node.internal_base 10.10.0.0/16, i.e. this checks the *other*
    island's-eye view without needing a second real fixture). The peer's
    plmn is 999/70 (island A's own fixture is 001/01) so
    SEPP_CERT_BY_PLMN resolves both sides without a RenderError."""
    data = load(EXAMPLE)
    data["federation"]["peers"] = [
        {
            "name": "island-b",
            "endpoint": "203.0.113.2:51820",
            "public_key": "4a2p6PxfWpBJx+DUChxZJ8YjCJz7d1234567890abc=",
            "node_internal_base": "10.20.0.0/16",
            "services_prefix": "10.48.0.0/24",
            "plmn": {"mcc": "999", "mnc": "70"},
        }
    ]
    files = render_all(data, tmp_path)
    by_path = {f.path: f.content for f in files}

    wg_up = by_path["stack/federation/data/wg-up.sh"]
    assert (
        "wg set wg0 peer 4a2p6PxfWpBJx+DUChxZJ8YjCJz7d1234567890abc= "
        "endpoint 203.0.113.2:51820 allowed-ips 10.20.0.0/16,10.48.0.0/24 "
        "persistent-keepalive 25" in wg_up
    )
    assert "ip route add 10.20.0.0/16 dev wg0" in wg_up
    assert "ip route add 10.48.0.0/24 dev wg0" in wg_up
    # 3.3-c v2: the forward-filter now allows only this island's own
    # SEPP (offset 16 within its own core_net 10.10.0.0/24) on its
    # N32-c/N32-f ports, not NRF/AUSF/UDM.
    assert "iptables -A FORWARD -i wg0 -d 10.10.0.16 -p tcp --dport 7778 -j ACCEPT" in wg_up
    assert "iptables -A FORWARD -i wg0 -d 10.10.0.16 -p tcp --dport 7779 -j ACCEPT" in wg_up
    assert "10.10.0.10 -p tcp --dport 7777" not in wg_up  # nrf, no longer filtered in

    compose = by_path["stack/core/compose.yaml"]
    # amf no longer touches the overlay directly (3.3-c v2: sepp does).
    assert "cap_add:\n      - NET_ADMIN" not in compose.split("sepp:")[0]
    assert "  sepp:\n    image: gradiant/open5gs:2.8.0" in compose
    assert "cap_add:\n      - NET_ADMIN" in compose
    # 3.3-b follow-up 2: a fixed address, not a bare/dynamic membership
    # (stack/backhaul/unplug-test.sh's WAN_TOUCHING_IPS guard needs one).
    assert "services_net:\n        ipv4_address: 10.46.0.46\n" in compose

    sepp_yaml = by_path["stack/core/config/sepp.yaml"]
    assert "private_key: /opt/open5gs/etc/open5gs/tls/sepp2.key" in sepp_yaml
    assert "receiver: sepp1.localdomain" in sepp_yaml
    assert "uri: http://10.20.0.16:7778" in sepp_yaml
    assert "uri: http://10.20.0.16:7779" in sepp_yaml

    amf_yaml = by_path["stack/core/config/amf.yaml"]
    assert "access_control" in amf_yaml
    assert "mcc: 999" in amf_yaml and "mnc: 70" in amf_yaml


def test_render_wg_up_asserts_key_matches_when_public_key_declared(tmp_path):
    """3.3-b follow-up 4: rendered only when overlay.wireguard_public_key
    is set -- a freshly-built island.yaml with no key generated yet still
    renders (the golden-rule lab fixture has no key declared at all)."""
    data = load(EXAMPLE)
    data["island"]["overlay"]["wireguard_public_key"] = "TESTPUBKEY123="
    files = render_all(data, tmp_path)
    wg_up = next(f.content for f in files if f.path == "stack/federation/data/wg-up.sh")
    assert 'ACTUAL_PUBLIC_KEY=$(wg pubkey < /run/secrets/wireguard.key)' in wg_up
    assert '"$ACTUAL_PUBLIC_KEY" != "TESTPUBKEY123="' in wg_up


def test_render_wg_up_has_no_assertion_when_no_public_key_declared(tmp_path):
    data = load(EXAMPLE)
    assert data["island"]["overlay"]["wireguard_public_key"] is None
    files = render_all(data, tmp_path)
    wg_up = next(f.content for f in files if f.path == "stack/federation/data/wg-up.sh")
    assert "ACTUAL_PUBLIC_KEY" not in wg_up


def test_render_lab_against_real_repo_is_byte_identical_except_headers():
    """The golden rule (TASKS.md 2.1-b, revised 2.1-g): island-init render
    --lab must reproduce every already-committed file byte-for-byte, once
    the header lines this task introduces are themselves part of the
    committed baseline. Skips gracefully if run from a checkout where
    this task's render hasn't been applied/committed yet, or the repo
    layout moved.

    Per-deployment outputs (EXAMPLE_SNAPSHOTS) are compared against their
    dedicated tracked snapshot instead of `RenderedFile.changed` -- see
    that dict's own comment."""
    if not (REPO_ROOT / "stack" / "core" / "compose.yaml").exists():
        pytest.skip("not run from inside a ResCCOM checkout")

    data = load(EXAMPLE)
    files = render_all(data, REPO_ROOT)

    unexpected_changes = []
    for f in files:
        snapshot_path = EXAMPLE_SNAPSHOTS.get(f.path)
        if snapshot_path is not None:
            expected = (REPO_ROOT / snapshot_path).read_text(encoding="utf-8")
            if f.content != expected:
                unexpected_changes.append(f.path)
        elif f.changed:
            unexpected_changes.append(f.path)

    assert unexpected_changes == [], (
        "island-init render --lab --diff produced unexpected changes in "
        f"{unexpected_changes} -- if this is a deliberate render-template "
        "change, commit the re-rendered files (or their EXAMPLE_SNAPSHOTS "
        "counterpart) in the same change so the golden rule holds again."
    )
