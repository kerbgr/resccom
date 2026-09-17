"""`island-init check` CLI (2.1-a acceptance criteria, verbatim)."""
from pathlib import Path

from click.testing import CliRunner

from island_init.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = Path(__file__).parent.parent / "island.example.yaml"


def test_check_passes_on_island_example_yaml():
    result = CliRunner().invoke(main, ["check", str(EXAMPLE)])
    assert result.exit_code == 0
    assert "OK" in result.output


def test_check_fails_on_duplicated_pci_naming_field_and_line():
    result = CliRunner().invoke(main, ["check", str(FIXTURES / "bad_duplicate_pci.yaml")])
    assert result.exit_code == 1
    assert "sites[0].cells[1].pci" in result.output
    assert "duplicate PCI" in result.output
    # "...:<line>: ..." -- a line number was named, not just the field.
    assert any(part.strip().isdigit() for part in result.output.split(":")[:3])


def test_check_fails_on_test_plmn_under_production_profile_naming_field_and_line():
    result = CliRunner().invoke(
        main, ["check", str(FIXTURES / "bad_production_test_plmn.yaml")]
    )
    assert result.exit_code == 1
    assert "allocations.plmn.mcc" in result.output
    assert "test PLMN" in result.output


def test_check_passes_on_valid_production_fixture():
    result = CliRunner().invoke(main, ["check", str(FIXTURES / "valid_production.yaml")])
    assert result.exit_code == 0


def test_check_fails_on_overlapping_prefixes():
    result = CliRunner().invoke(main, ["check", str(FIXTURES / "bad_prefix_overlap.yaml")])
    assert result.exit_code == 1
    assert "allocations.services_prefix" in result.output


def test_check_fails_on_drifted_wireguard_key(tmp_path):
    """3.3-b follow-up 4, end to end through the CLI: --repo-root points
    `check` at a secrets/ whose key file doesn't match island.yaml's
    declared public key."""
    import json

    from island_init.crypto import generate_wireguard_keypair
    from island_init.yaml_io import dump, load

    island_yaml = tmp_path / "island.yaml"
    data = json.loads(json.dumps(load(EXAMPLE)))  # strip ruamel wrappers before dump()
    data["island"]["overlay"]["wireguard_public_key"] = "a-declared-pubkey-that-wont-match"
    dump(data, island_yaml)

    priv, _real_pub = generate_wireguard_keypair()
    key_dir = tmp_path / "secrets" / "lab"
    key_dir.mkdir(parents=True)
    (key_dir / "wireguard.key").write_text(priv + "\n")

    result = CliRunner().invoke(main, ["check", str(island_yaml), "--repo-root", str(tmp_path)])
    assert result.exit_code == 1
    assert "island.overlay.wireguard_public_key" in result.output
    assert "drifted" in result.output


def test_migrate_then_check_passes_on_a_pre_3_3_a_document(tmp_path):
    """3.3-b follow-up 5, end to end: a document missing fields schema v0
    now requires fails `check` (broken silently before this task) but
    passes after `migrate`."""
    from island_init.yaml_io import dump, load

    data = load(EXAMPLE)
    plain = __import__("json").loads(__import__("json").dumps(data))
    del plain["node"]
    del plain["federation"]["peers"]
    old = tmp_path / "island.yaml"
    dump(plain, old)

    stale_check = CliRunner().invoke(main, ["check", str(old)])
    assert stale_check.exit_code == 1

    migrate_result = CliRunner().invoke(main, ["migrate", str(old)])
    assert migrate_result.exit_code == 0, migrate_result.output
    assert "filled in: node.internal_base" in migrate_result.output
    assert "filled in: federation.peers" in migrate_result.output

    fresh_check = CliRunner().invoke(main, ["check", str(old)])
    assert fresh_check.exit_code == 0, fresh_check.output


def test_migrate_reports_already_current_document_unchanged():
    result = CliRunner().invoke(main, ["migrate", str(EXAMPLE)])
    assert result.exit_code == 0
    assert "already current" in result.output
