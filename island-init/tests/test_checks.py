"""Semantic-rule coverage (2.1-a acceptance: "every semantic rule")."""
from pathlib import Path

from island_init.checks import (
    check_pci_uniqueness,
    check_prefix_overlap,
    check_production_profile,
    check_signature,
    check_wireguard_key_matches,
    run_semantic_checks,
)
from island_init.crypto import generate_signing_keypair, generate_wireguard_keypair, sign_document
from island_init.yaml_io import load

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = Path(__file__).parent.parent / "island.example.yaml"


def test_lab_example_has_no_semantic_issues():
    data = load(EXAMPLE)
    assert run_semantic_checks(data, data) == []


def test_valid_production_fixture_has_no_semantic_issues():
    data = load(FIXTURES / "valid_production.yaml")
    assert run_semantic_checks(data, data) == []


# -- 1. PCI uniqueness ------------------------------------------------------


def test_duplicate_pci_is_rejected_with_field_and_line():
    data = load(FIXTURES / "bad_duplicate_pci.yaml")
    issues = check_pci_uniqueness(data, data)
    assert len(issues) == 1
    assert issues[0].field == "sites[0].cells[1].pci"
    assert "duplicate PCI 1" in issues[0].message
    assert issues[0].line is not None


def test_unique_pcis_pass():
    data = load(EXAMPLE)
    assert check_pci_uniqueness(data, data) == []


# -- 2. prefix overlap --------------------------------------------------


def test_overlapping_prefixes_are_rejected():
    data = load(FIXTURES / "bad_prefix_overlap.yaml")
    issues = check_prefix_overlap(data, data)
    assert len(issues) == 1
    assert issues[0].field == "allocations.services_prefix"
    assert issues[0].line is not None


def test_non_overlapping_prefixes_pass():
    data = load(EXAMPLE)
    assert check_prefix_overlap(data, data) == []


# -- 3. production profile rules -----------------------------------------


def test_production_profile_rejects_test_plmn_with_field_and_line():
    data = load(FIXTURES / "bad_production_test_plmn.yaml")
    issues = check_production_profile(data, data)
    fields = {i.field for i in issues}
    assert "allocations.plmn.mcc" in fields
    plmn_issue = next(i for i in issues if i.field == "allocations.plmn.mcc")
    assert "test PLMN" in plmn_issue.message
    assert plmn_issue.line is not None


def test_production_profile_rejects_test_imsi_block():
    data = load(FIXTURES / "bad_production_test_plmn.yaml")
    issues = check_production_profile(data, data)
    assert any(i.field == "allocations.imsi_block" for i in issues)


def test_production_profile_rejects_null_signing_key():
    data = load(FIXTURES / "bad_production_test_plmn.yaml")
    issues = check_production_profile(data, data)
    assert any(i.field == "island.signing_key_fingerprint" for i in issues)


def test_production_profile_rejects_null_wireguard_key():
    data = load(FIXTURES / "bad_production_test_plmn.yaml")
    issues = check_production_profile(data, data)
    assert any(i.field == "island.overlay.wireguard_public_key" for i in issues)


def test_production_profile_rejects_placeholder_association_name():
    data = load(FIXTURES / "bad_production_test_plmn.yaml")
    issues = check_production_profile(data, data)
    assert any(i.field == "services.portal_association_name" for i in issues)


def test_production_profile_rejects_missing_operator_contact():
    data = load(FIXTURES / "bad_production_test_plmn.yaml")
    issues = check_production_profile(data, data)
    assert any(i.field == "services.portal_operator_contact" for i in issues)


def test_lab_profile_is_exempt_from_production_rules():
    data = load(EXAMPLE)
    assert check_production_profile(data, data) == []


def test_production_profile_rejects_null_signing_public_key():
    data = load(FIXTURES / "bad_production_test_plmn.yaml")
    issues = check_production_profile(data, data)
    assert any(i.field == "island.signing_public_key" for i in issues)


def test_production_profile_requires_a_signature():
    data = load(FIXTURES / "bad_production_test_plmn.yaml")
    issues = check_production_profile(data, data)
    assert any(i.field == "signature" for i in issues)


# -- 4. signature verification --------------------------------------------


def test_check_signature_passes_when_absent():
    data = load(EXAMPLE)
    assert check_signature(data, data) == []


def test_check_signature_passes_when_valid():
    keypair = generate_signing_keypair()
    data = {"island": {"signing_public_key": keypair.public_key_b64}, "profile": "lab"}
    data["signature"] = sign_document(data, keypair)
    assert check_signature(data, data) == []


def test_check_signature_fails_when_tampered_with_field_named():
    keypair = generate_signing_keypair()
    data = {"island": {"signing_public_key": keypair.public_key_b64}, "profile": "lab"}
    data["signature"] = sign_document(data, keypair)
    data["profile"] = "production"  # tamper after signing
    issues = check_signature(data, data)
    assert len(issues) == 1
    assert issues[0].field == "signature"
    assert "tampered" in issues[0].message


# -- 5. WireGuard key drift (3.3-b follow-up 4) ------------------------------


def _island_with_declared_pubkey(pub: str | None) -> dict:
    return {"island": {"id": "lab", "overlay": {"wireguard_public_key": pub}}}


def test_wireguard_key_check_skips_without_secrets_dir():
    data = _island_with_declared_pubkey("anything")
    assert check_wireguard_key_matches(data, data, None) == []


def test_wireguard_key_check_skips_when_no_key_declared(tmp_path):
    data = _island_with_declared_pubkey(None)
    assert check_wireguard_key_matches(data, data, tmp_path) == []


def test_wireguard_key_check_skips_when_key_file_absent(tmp_path):
    data = _island_with_declared_pubkey("some-declared-pubkey")
    assert check_wireguard_key_matches(data, data, tmp_path) == []


def test_wireguard_key_check_passes_when_key_matches(tmp_path):
    priv, pub = generate_wireguard_keypair()
    key_dir = tmp_path / "lab"
    key_dir.mkdir()
    (key_dir / "wireguard.key").write_text(priv + "\n")
    data = _island_with_declared_pubkey(pub)
    assert check_wireguard_key_matches(data, data, tmp_path) == []


def test_wireguard_key_check_fails_when_key_drifted(tmp_path):
    priv, _real_pub = generate_wireguard_keypair()
    key_dir = tmp_path / "lab"
    key_dir.mkdir()
    (key_dir / "wireguard.key").write_text(priv + "\n")
    data = _island_with_declared_pubkey("a-stale-declared-pubkey")
    issues = check_wireguard_key_matches(data, data, tmp_path)
    assert len(issues) == 1
    assert issues[0].field == "island.overlay.wireguard_public_key"
    assert "drifted" in issues[0].message
