"""island-init apply (2.1-f): the host-side signing/render/restart half of
the Island Console's Apply flow. `subprocess.run` is monkeypatched in
every test that reaches `restart_for` -- this suite must never issue a
real `docker restart` against whatever happens to be running on the
machine it's executed on."""
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from island_init.apply import ApplyError, apply_draft
from island_init.cli import main
from island_init.render import TARGETS
from island_init.yaml_io import dump, load

REPO_ROOT = Path(__file__).parent.parent.parent


def _plain(data):
    """`load()`'s round-trip loader always returns ruamel's
    CommentedMap/CommentedSeq wrappers, which the plain "safe" dumper
    `dump()` uses cannot represent -- strip them via a JSON round-trip
    before building a draft to dump, same as island_init.apply._plain."""
    return json.loads(json.dumps(data))


def _repo_or_skip():
    if not (REPO_ROOT / "island-init" / "island.example.yaml").exists():
        pytest.skip("not run from inside a ResCCOM checkout")


def _new_lab_island(tmp_path):
    """A fresh, signed lab island.yaml + secrets dir, built the same way
    `island.sh` bootstraps one -- but entirely under tmp_path, never
    touching the real repo's island-init/island.yaml or secrets/."""
    island_yaml = tmp_path / "island.yaml"
    secrets_dir = tmp_path / "secrets"
    result = CliRunner().invoke(
        main,
        [
            "new",
            "--lab",
            "--repo-root",
            str(REPO_ROOT),
            "--out",
            str(island_yaml),
            "--secrets-dir",
            str(secrets_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    return island_yaml, secrets_dir


def _fake_repo_root(tmp_path):
    """apply_draft renders into a real directory tree -- a scratch one
    here, never REPO_ROOT, so a test run never writes into this repo's
    own committed stack/ configs. `write_all` (like the real render
    targets it writes today) assumes the destination directories already
    exist, so pre-create them the same way a real checkout already has
    stack/core/config/ etc."""
    d = tmp_path / "fake-repo"
    d.mkdir()
    for target_path, _template_path in TARGETS:
        (d / target_path).parent.mkdir(parents=True, exist_ok=True)
    (d / "island-init").mkdir(parents=True, exist_ok=True)
    return d


def test_apply_draft_signs_renders_and_clears_draft(tmp_path, monkeypatch):
    _repo_or_skip()
    island_yaml, secrets_dir = _new_lab_island(tmp_path)
    fake_repo_root = _fake_repo_root(tmp_path)

    restarted_containers = []
    monkeypatch.setattr(
        "island_init.apply.subprocess.run",
        lambda cmd, **kw: restarted_containers.append(cmd[2]),
    )

    current = _plain(load(island_yaml))
    draft = dict(current)
    draft["island"] = dict(draft["island"])
    draft["island"]["display_name"] = "Renamed via draft"
    draft_path = tmp_path / "draft.yaml"
    dump(draft, draft_path)

    result = apply_draft(draft_path, island_yaml, secrets_dir, fake_repo_root)

    assert not draft_path.exists()  # cleared on success
    assert "stack/core/config/amf.yaml" in result["changed"]
    assert restarted_containers  # restart_for actually ran (against the mock)

    signed = load(island_yaml)
    assert signed["island"]["display_name"] == "Renamed via draft"
    assert signed["signature"]  # freshly (re)signed

    check_result = CliRunner().invoke(main, ["check", str(island_yaml), "--repo-root", str(tmp_path)])
    assert check_result.exit_code == 0, check_result.output


def test_apply_draft_rejects_locked_identity_field_change(tmp_path, monkeypatch):
    _repo_or_skip()
    island_yaml, secrets_dir = _new_lab_island(tmp_path)
    fake_repo_root = _fake_repo_root(tmp_path)
    monkeypatch.setattr("island_init.apply.subprocess.run", lambda cmd, **kw: None)

    current = _plain(load(island_yaml))
    draft = dict(current)
    draft["island"] = dict(draft["island"])
    draft["island"]["id"] = "not-the-real-id"
    draft_path = tmp_path / "draft.yaml"
    dump(draft, draft_path)

    # build_candidate re-locks `id` back to the current value regardless
    # of what the draft says, so this applies cleanly under the
    # *original* id -- proving a draft can never smuggle an identity
    # change through, not that it fails outright.
    result = apply_draft(draft_path, island_yaml, secrets_dir, fake_repo_root)
    signed = load(island_yaml)
    assert signed["island"]["id"] == current["island"]["id"]
    assert result["changed"]


def test_apply_draft_fails_validation_cleanly_without_touching_island_yaml(tmp_path, monkeypatch):
    _repo_or_skip()
    island_yaml, secrets_dir = _new_lab_island(tmp_path)
    fake_repo_root = _fake_repo_root(tmp_path)
    monkeypatch.setattr("island_init.apply.subprocess.run", lambda cmd, **kw: None)

    before = island_yaml.read_text()
    draft = _plain(load(island_yaml))
    draft["sites"] = [
        {
            "id": "a",
            "name": "A",
            "lat": 0,
            "lon": 0,
            "height_m": 10,
            "cells": [
                {"rat": "lte", "band": "7", "earfcn": 1, "arfcn": None, "pci": 5,
                 "bandwidth_mhz": 5, "tx_power_dbm": None, "azimuth_deg": None,
                 "antenna_notes": "", "predicted_coverage": None, "measured_points": None},
                {"rat": "lte", "band": "7", "earfcn": 1, "arfcn": None, "pci": 5,
                 "bandwidth_mhz": 5, "tx_power_dbm": None, "azimuth_deg": None,
                 "antenna_notes": "", "predicted_coverage": None, "measured_points": None},
            ],
        }
    ]
    draft_path = tmp_path / "draft.yaml"
    dump(draft, draft_path)

    with pytest.raises(ApplyError, match="duplicate PCI"):
        apply_draft(draft_path, island_yaml, secrets_dir, fake_repo_root)

    assert island_yaml.read_text() == before  # untouched
    assert draft_path.exists()  # not cleared on failure


def test_apply_draft_missing_draft_raises():
    with pytest.raises(ApplyError, match="no pending draft"):
        apply_draft(Path("/nonexistent/draft.yaml"), Path("/nonexistent/island.yaml"), Path("/nonexistent"), Path("."))


def test_apply_cli_command(tmp_path, monkeypatch):
    _repo_or_skip()
    island_yaml, secrets_dir = _new_lab_island(tmp_path)
    fake_repo_root = _fake_repo_root(tmp_path)
    monkeypatch.setattr("island_init.apply.subprocess.run", lambda cmd, **kw: None)

    draft = _plain(load(island_yaml))
    draft["island"] = dict(draft["island"])
    draft["island"]["display_name"] = "Via CLI"
    draft_path = tmp_path / "draft.yaml"
    dump(draft, draft_path)

    result = CliRunner().invoke(
        main,
        [
            "apply",
            "--draft",
            str(draft_path),
            "--island-yaml",
            str(island_yaml),
            "--secrets-dir",
            str(secrets_dir),
            "--repo-root",
            str(fake_repo_root),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "signed and wrote" in result.output
    assert load(island_yaml)["island"]["display_name"] == "Via CLI"
