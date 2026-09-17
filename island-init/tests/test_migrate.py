"""island-init migrate (3.3-b follow-up 5)."""
import json

import pytest

from island_init.crypto import generate_signing_keypair, sign_document
from island_init.migrate import MigrateError, migrate_document, resign
from island_init.wizard import DEFAULT_NODE_INTERNAL_BASE


def _pre_3_3_a_document() -> dict:
    """Shaped like an island.yaml generated before 3.3-a added `node` and
    3.3-b made `federation.peers` required -- both missing."""
    return {
        "profile": "lab",
        "island": {"id": "lab", "display_name": "Lab", "country": "XX", "node_classes": ["dev"]},
        "allocations": {
            "plmn": {"mcc": "001", "mnc": "01"},
            "imsi_block": "00101",
            "tac_range": [1, 1],
            "ue_prefix": {"v4": "10.45.0.0/16"},
            "services_prefix": "10.46.0.0/24",
            "realm": "localdomain",
            "dns_zone": "island",
        },
        "sites": [],
        "services": {
            "enabled": {
                "library": True, "chat": True, "talk": True,
                "portal": True, "console": False, "pemea_ap": False,
            },
            "portal_association_name": None,
            "portal_operator_contact": None,
        },
        "backhaul": {"uplinks": []},
        "federation": {"items": []},
    }


def test_migrate_fills_in_missing_node_and_peers():
    data = _pre_3_3_a_document()
    migrated, changed = migrate_document(data)
    assert migrated["node"] == {"internal_base": DEFAULT_NODE_INTERNAL_BASE}
    assert migrated["federation"]["peers"] == []
    assert migrated["island"]["overlay"] == {"endpoint": None, "wireguard_public_key": None, "address": None}
    assert set(changed) == {"node.internal_base", "federation.peers", "island.overlay.address"}


def test_migrate_is_idempotent():
    data = _pre_3_3_a_document()
    migrated, _ = migrate_document(data)
    migrated_again, changed_again = migrate_document(json.loads(json.dumps(migrated)))
    assert changed_again == []
    assert migrated_again == migrated


def test_migrate_leaves_already_current_document_untouched():
    data = _pre_3_3_a_document()
    data["node"] = {"internal_base": "10.10.0.0/16"}
    data["federation"]["peers"] = []
    data["island"]["overlay"] = {"endpoint": None, "wireguard_public_key": None, "address": "10.99.0.1/24"}
    migrated, changed = migrate_document(json.loads(json.dumps(data)))
    assert changed == []
    assert migrated["island"]["overlay"]["address"] == "10.99.0.1/24"


def test_resign_updates_signature_to_match_migrated_content(tmp_path):
    signing = generate_signing_keypair()
    data = _pre_3_3_a_document()
    data["island"]["signing_key_fingerprint"] = signing.fingerprint
    data["island"]["signing_public_key"] = signing.public_key_b64
    data["signature"] = sign_document(data, signing)

    secrets_dir = tmp_path / "secrets"
    (secrets_dir / "lab").mkdir(parents=True)
    (secrets_dir / "lab" / "signing.key").write_text(signing.private_key_b64() + "\n")

    migrated, changed = migrate_document(json.loads(json.dumps(data)))
    assert changed  # something was filled in, so the old signature is now stale
    resign(migrated, secrets_dir)

    from island_init.checks import check_signature

    assert check_signature(migrated, migrated) == []


def test_resign_fails_without_the_matching_private_key(tmp_path):
    signing = generate_signing_keypair()
    data = _pre_3_3_a_document()
    data["island"]["signing_key_fingerprint"] = signing.fingerprint
    data["island"]["signing_public_key"] = signing.public_key_b64
    data["signature"] = sign_document(data, signing)

    migrated, _ = migrate_document(json.loads(json.dumps(data)))
    with pytest.raises(MigrateError, match="does not exist"):
        resign(migrated, tmp_path / "secrets")
