"""island_init.wizard (2.1-c): building, keying, and signing a fresh island.yaml."""
import json
from pathlib import Path

import pytest

from island_init.checks import run_semantic_checks
from island_init.crypto import generate_signing_keypair, generate_wireguard_keypair, verify_document
from island_init.schema import validate_schema
from island_init.wizard import apply_keys, build_island, load_allocation, load_lab_identity, write_secrets
from island_init.yaml_io import load

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = Path(__file__).parent.parent / "island.example.yaml"
REPO_ROOT = Path(__file__).parent.parent.parent


def _signed_lab_island():
    data = load_lab_identity(REPO_ROOT)
    signing = generate_signing_keypair()
    _wg_private, wg_public = generate_wireguard_keypair()
    apply_keys(data, signing, wg_public)
    return data, signing


def test_load_lab_identity_matches_example_minus_keys():
    if not EXAMPLE.exists():
        pytest.skip("not run from inside a ResCCOM checkout")
    example = json.loads(json.dumps(load(EXAMPLE)))
    lab = load_lab_identity(REPO_ROOT)
    assert lab == example  # no keys touched yet -- apply_keys does that


def test_apply_keys_fills_fields_and_produces_valid_signature():
    if not EXAMPLE.exists():
        pytest.skip("not run from inside a ResCCOM checkout")
    data, _signing = _signed_lab_island()
    assert data["island"]["signing_key_fingerprint"].startswith("SHA256:")
    assert data["island"]["signing_public_key"]
    assert data["island"]["overlay"]["wireguard_public_key"]
    assert data["signature"]["algorithm"] == "ed25519"
    verify_document(data)  # raises on failure


def test_lab_island_passes_schema_and_semantic_checks():
    if not EXAMPLE.exists():
        pytest.skip("not run from inside a ResCCOM checkout")
    data, _signing = _signed_lab_island()
    assert validate_schema(data) == []
    assert run_semantic_checks(data, data) == []


def test_lab_island_survives_a_yaml_round_trip(tmp_path):
    """Signing happens on the in-memory plain dict; verification later
    happens on whatever a fresh `island-init check` loads off disk via
    ruamel. This is the seam where a type mismatch (e.g. int vs float)
    could silently break every signature -- prove it doesn't."""
    if not EXAMPLE.exists():
        pytest.skip("not run from inside a ResCCOM checkout")
    data, _signing = _signed_lab_island()

    from island_init.yaml_io import dump

    out = tmp_path / "island.yaml"
    dump(data, out)
    reloaded = load(out)
    verify_document(reloaded)  # raises on failure

    tampered = load(out)
    tampered["island"]["country"] = "ZZ"
    from island_init.crypto import SignatureVerificationError

    with pytest.raises(SignatureVerificationError):
        verify_document(tampered)


def test_load_allocation_reads_the_allocations_block():
    allocation = load_allocation(FIXTURES / "allocation.example.yaml")
    assert allocation["plmn"] == {"mcc": "999", "mnc": "70"}
    assert allocation["dns_zone"] == "example-atoll.islands.arpa"


def test_build_island_with_pasted_allocation_passes_schema_and_semantic_checks():
    allocation = load_allocation(FIXTURES / "allocation.example.yaml")
    data = build_island(
        island_id="example-atoll",
        display_name="Example Atoll Association",
        country="FR",
        node_classes=["b"],
        profile="production",
        allocations=allocation,
        portal_association_name="Example Atoll Association",
        portal_operator_contact="VHF ch. 16",
    )
    signing = generate_signing_keypair()
    _wg_private, wg_public = generate_wireguard_keypair()
    apply_keys(data, signing, wg_public)

    assert validate_schema(data) == []
    assert run_semantic_checks(data, data) == []  # production profile, fully filled in


def test_write_secrets_writes_private_keys_with_restricted_permissions(tmp_path):
    signing = generate_signing_keypair()
    wg_private, _wg_public = generate_wireguard_keypair()
    signing_path, wg_path = write_secrets(tmp_path, "example-atoll", signing, wg_private)

    assert signing_path.read_text().strip() == signing.private_key_b64()
    assert wg_path.read_text().strip() == wg_private
    assert (signing_path.stat().st_mode & 0o777) == 0o600
    assert (wg_path.stat().st_mode & 0o777) == 0o600
