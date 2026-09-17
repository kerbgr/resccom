"""island-init new (2.1-c): build a fresh island.yaml (RFC-0005 D4's flow,
minus the parts later tasks own -- the Console's map editor for sites/cells
is 2.1-d, and there is no registry repo yet to fetch an allocation from, so
--allocation takes a pasted-in file shaped like island.yaml's own
`allocations` block instead)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .crypto import SigningKeypair, sign_document
from .yaml_io import load

# What every island brings up regardless of identity (island.sh's own
# service set) -- not registry-allocated, so not part of --allocation.
DEFAULT_SERVICES_ENABLED = {
    "library": True,
    "chat": True,
    "talk": True,
    "portal": True,
    "console": False,
    "pemea_ap": False,
}

# Mirrors stack/backhaul/config/uplinks.yaml's own defaults (render v0's
# only known uplink names -- see render.UPLINK_ADDRS).
DEFAULT_UPLINKS = [
    {"name": "fixed", "priority": 1, "bandwidth_kbit": 2000},
    {"name": "satellite", "priority": 2, "bandwidth_kbit": 1000},
    {"name": "ptp", "priority": 3, "bandwidth_kbit": 500},
]

# All opt-in, none shared by default (RFC-0006 D5).
DEFAULT_FEDERATION_ITEMS = [
    {"name": name, "share": False, "priority_class": "best_effort"}
    for name in ("content_library", "matrix_rooms", "incident_records", "coverage_polygon")
]

# 3.3-a: node-internal addressing (island.yaml's `node` block) is host-local
# plumbing, not a registry allocation (RFC-0005 D2 doesn't assign it) -- an
# --allocation file never carries it. Every island `new` builds gets this
# same default; an operator co-locating more than one island on one host
# (island-init/TASKS.md 3.3-a) edits internal_base by hand afterwards, the
# same way island.example.b.yaml does for the lab's second island.
DEFAULT_NODE_INTERNAL_BASE = "10.10.0.0/16"


class WizardError(Exception):
    pass


def _plain(data: Any) -> Any:
    """Strips ruamel CommentedMap/CommentedSeq wrappers via a JSON round-trip
    -- what's left is exactly what island-init new needs to build on: plain
    dict/list/str/int/float/bool/None."""
    return json.loads(json.dumps(data))


def load_identity_from_file(path: Path) -> dict:
    """island/allocations/sites/services/backhaul/federation straight off an
    arbitrary island.yaml-shaped file -- `new --file` (3.3-b follow-up 1)
    generalizes `new --lab` to any such source, e.g. a second lab island
    fixture (island.example.b.yaml) that isn't THE lab profile but still
    needs the same fresh-keys-and-sign treatment `new --lab` gives
    island.example.yaml."""
    if not path.exists():
        raise WizardError(f"{path} not found")
    return _plain(load(path))


def load_lab_identity(repo_root: Path) -> dict:
    """island/allocations/sites/services/backhaul/federation straight off the
    checked-in island.example.yaml, so `new --lab` reproduces it exactly
    (2.1-c acceptance) -- everything except the keys new --lab generates."""
    return load_identity_from_file(repo_root / "island-init" / "island.example.yaml")


def load_allocation(path: Path) -> dict:
    """A registry allocation file (RFC-0005 D2's per-island block: plmn,
    imsi_block, tac_range, ue_prefix, services_prefix, realm, dns_zone).
    No registry repo exists yet (WBS 0.3 follow-up per RFC-0005
    "Consequences"), so this is island-init's interim input format for
    pasting one in -- either the bare `allocations` object, or a full
    island.yaml-shaped file (only its `allocations` key is read)."""
    data = _plain(load(path))
    if "allocations" in data:
        data = data["allocations"]
    return data


def build_island(
    *,
    island_id: str,
    display_name: str,
    country: str,
    node_classes: list[str],
    profile: str,
    allocations: dict,
    portal_association_name: str | None,
    portal_operator_contact: str | None,
) -> dict:
    """A fresh island.yaml body, unsigned and keyless -- apply_keys() fills
    the rest. `sites` starts empty: no node OS image/RAN hardware exists
    yet to have surveyed one (the Console's map editor, 2.1-d, is how a
    real deployment would fill this in later)."""
    return {
        "profile": profile,
        "island": {
            "id": island_id,
            "display_name": display_name,
            "country": country,
            "node_classes": list(node_classes),
            "signing_key_fingerprint": None,
            "signing_public_key": None,
            "overlay": {"endpoint": None, "wireguard_public_key": None, "address": None},
        },
        "allocations": allocations,
        "node": {"internal_base": DEFAULT_NODE_INTERNAL_BASE},
        "sites": [],
        "services": {
            "enabled": dict(DEFAULT_SERVICES_ENABLED),
            "portal_association_name": portal_association_name,
            "portal_operator_contact": portal_operator_contact,
        },
        "backhaul": {"uplinks": [dict(u) for u in DEFAULT_UPLINKS]},
        # peers: [] (3.3-b) -- no island trusts a stranger by default
        # (RFC-0003 D2); allow-listing a peer is a later, deliberate act
        # (console/apply, not `new`).
        "federation": {"items": [dict(i) for i in DEFAULT_FEDERATION_ITEMS], "peers": []},
    }


def apply_keys(data: dict, signing: SigningKeypair, wireguard_public_key_b64: str) -> None:
    """Mutates `data` in place: fills island.signing_*/overlay.wireguard_public_key
    (which the signature must cover), then attaches a signature computed
    over the result."""
    data["island"]["signing_key_fingerprint"] = signing.fingerprint
    data["island"]["signing_public_key"] = signing.public_key_b64
    data["island"]["overlay"]["wireguard_public_key"] = wireguard_public_key_b64
    data["signature"] = sign_document(data, signing)


def write_secrets(
    secrets_dir: Path, island_id: str, signing: SigningKeypair, wireguard_private_key_b64: str
) -> tuple[Path, Path]:
    """Private keys only -- island.yaml itself carries just the public
    halves. `secrets_dir` (default <repo_root>/secrets) is covered by
    .gitignore's `secrets/` rule; the files themselves also match its
    `*.key` rule as a second line of defense."""
    island_secrets = secrets_dir / island_id
    island_secrets.mkdir(parents=True, exist_ok=True)
    signing_path = island_secrets / "signing.key"
    wg_path = island_secrets / "wireguard.key"
    signing_path.write_text(signing.private_key_b64() + "\n", encoding="utf-8")
    wg_path.write_text(wireguard_private_key_b64 + "\n", encoding="utf-8")
    signing_path.chmod(0o600)
    wg_path.chmod(0o600)
    return signing_path, wg_path
