"""`island-init new` CLI (2.1-c). Every test points --out/--secrets-dir at
tmp_path so running the suite never touches the real repo's generated
island-init/island.yaml or secrets/."""
from pathlib import Path

import pytest
from click.testing import CliRunner

from island_init.cli import main
from island_init.yaml_io import load

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent.parent


def _repo_or_skip():
    if not (REPO_ROOT / "island-init" / "island.example.yaml").exists():
        pytest.skip("not run from inside a ResCCOM checkout")


def test_new_lab_writes_island_yaml_and_keys_and_passes_check(tmp_path):
    _repo_or_skip()
    out = tmp_path / "island.yaml"
    secrets_dir = tmp_path / "secrets"
    result = CliRunner().invoke(
        main,
        [
            "new",
            "--lab",
            "--repo-root",
            str(REPO_ROOT),
            "--out",
            str(out),
            "--secrets-dir",
            str(secrets_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert (secrets_dir / "lab" / "signing.key").exists()
    assert (secrets_dir / "lab" / "wireguard.key").exists()

    check_result = CliRunner().invoke(main, ["check", str(out), "--repo-root", str(tmp_path)])
    assert check_result.exit_code == 0, check_result.output


def test_new_requires_exactly_one_of_lab_or_allocation(tmp_path):
    result = CliRunner().invoke(main, ["new", "--out", str(tmp_path / "island.yaml")])
    assert result.exit_code != 0
    assert "exactly one" in result.output

    result = CliRunner().invoke(
        main,
        [
            "new",
            "--lab",
            "--allocation",
            str(FIXTURES / "allocation.example.yaml"),
            "--out",
            str(tmp_path / "island.yaml"),
        ],
    )
    assert result.exit_code != 0
    assert "exactly one" in result.output


def test_new_file_builds_from_an_arbitrary_island_yaml_shaped_source(tmp_path):
    """3.3-b follow-up 1: --lab generalized to any source file -- the
    two-island harness uses this to build island B's identity from
    island.example.b.yaml, not island.example.yaml."""
    _repo_or_skip()
    source = REPO_ROOT / "island-init" / "island.example.b.yaml"
    if not source.exists():
        pytest.skip("island.example.b.yaml not present in this checkout")
    out = tmp_path / "island.yaml"
    secrets_dir = tmp_path / "secrets"
    result = CliRunner().invoke(
        main,
        ["new", "--file", str(source), "--out", str(out), "--secrets-dir", str(secrets_dir)],
    )
    assert result.exit_code == 0, result.output
    data = load(out)
    assert data["island"]["id"] == "island-b"
    assert (secrets_dir / "island-b" / "wireguard.key").exists()

    check_result = CliRunner().invoke(main, ["check", str(out), "--repo-root", str(tmp_path)])
    assert check_result.exit_code == 0, check_result.output


def test_new_requires_exactly_one_of_lab_file_or_allocation(tmp_path):
    result = CliRunner().invoke(
        main,
        [
            "new",
            "--lab",
            "--file",
            str(FIXTURES / "allocation.example.yaml"),
            "--out",
            str(tmp_path / "island.yaml"),
        ],
    )
    assert result.exit_code != 0
    assert "exactly one" in result.output


def test_new_allocation_interactive_flow_produces_a_checkable_production_island(tmp_path):
    out = tmp_path / "island.yaml"
    secrets_dir = tmp_path / "secrets"
    prompts = "\n".join(
        [
            "example-atoll",  # id
            "Example Atoll Association",  # display name
            "FR",  # country
            "b",  # node class
            "production",  # profile
            "Example Atoll Association",  # portal association name
            "VHF ch. 16",  # operator contact
        ]
    )
    result = CliRunner().invoke(
        main,
        [
            "new",
            "--allocation",
            str(FIXTURES / "allocation.example.yaml"),
            "--out",
            str(out),
            "--secrets-dir",
            str(secrets_dir),
        ],
        input=prompts + "\n",
    )
    assert result.exit_code == 0, result.output
    data = load(out)
    assert data["island"]["id"] == "example-atoll"
    assert data["profile"] == "production"
    assert data["allocations"]["dns_zone"] == "example-atoll.islands.arpa"

    check_result = CliRunner().invoke(main, ["check", str(out), "--repo-root", str(tmp_path)])
    assert check_result.exit_code == 0, check_result.output


def test_new_lab_output_tampered_then_fails_check(tmp_path):
    _repo_or_skip()
    out = tmp_path / "island.yaml"
    CliRunner().invoke(
        main,
        [
            "new",
            "--lab",
            "--repo-root",
            str(REPO_ROOT),
            "--out",
            str(out),
            "--secrets-dir",
            str(tmp_path / "secrets"),
        ],
    )
    text = out.read_text().replace("country: XX", "country: ZZ")
    out.write_text(text)

    result = CliRunner().invoke(main, ["check", str(out), "--repo-root", str(tmp_path)])
    assert result.exit_code == 1
    assert "signature" in result.output
    assert "tampered" in result.output
