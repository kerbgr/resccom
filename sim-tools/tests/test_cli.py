from click.testing import CliRunner

from resccom_sim.cli import main
from resccom_sim.model import TEST_KEY, TEST_OPC


def _env(store_path):
    return {"RESCCOM_SIM_PASSPHRASE": "test-passphrase", "RESCCOM_SIM_STORE": str(store_path)}


def test_sub_add_test_then_list(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")

    added = runner.invoke(main, ["sub", "add", "--test"], env=env)
    assert added.exit_code == 0, added.output
    assert "added 001010000000001" in added.output

    listed = runner.invoke(main, ["sub", "list"], env=env)
    assert listed.exit_code == 0, listed.output
    assert "001010000000001" in listed.output
    assert TEST_KEY not in listed.output  # secrets hidden without --show-secrets
    assert TEST_OPC not in listed.output


def test_sub_list_show_secrets(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")
    runner.invoke(main, ["sub", "add", "--test"], env=env)

    listed = runner.invoke(main, ["sub", "list", "--show-secrets"], env=env)
    assert TEST_KEY in listed.output
    assert TEST_OPC in listed.output


def test_sub_add_defaults_to_local_breakout_shown_in_list(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")
    runner.invoke(main, ["sub", "add", "--test"], env=env)

    listed = runner.invoke(main, ["sub", "list"], env=env)
    assert "LBO" in listed.output


def test_sub_add_home_routed_shown_in_list(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")
    runner.invoke(main, ["sub", "add", "--test", "--home-routed"], env=env)

    listed = runner.invoke(main, ["sub", "list"], env=env)
    assert "HR" in listed.output


def test_sub_show_displays_roaming_policy(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")
    runner.invoke(main, ["sub", "add", "--test"], env=env)

    shown = runner.invoke(main, ["sub", "show", "001010000000001"], env=env)
    assert shown.exit_code == 0, shown.output
    assert "Local Breakout" in shown.output
    assert "lbo_roaming_allowed=true" in shown.output


def test_sub_show_missing_subscriber_errors(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")

    result = runner.invoke(main, ["sub", "show", "001010000000001"], env=env)
    assert result.exit_code != 0


def test_sub_edit_home_routed_and_back(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")
    runner.invoke(main, ["sub", "add", "--test"], env=env)

    edited = runner.invoke(main, ["sub", "edit", "001010000000001", "--home-routed"], env=env)
    assert edited.exit_code == 0, edited.output
    assert "lbo_roaming_allowed=false" in edited.output
    assert "Home-Routed" in runner.invoke(main, ["sub", "show", "001010000000001"], env=env).output

    back = runner.invoke(main, ["sub", "edit", "001010000000001"], env=env)
    assert back.exit_code == 0, back.output
    assert "lbo_roaming_allowed=true" in back.output


def test_sub_edit_missing_subscriber_errors(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")

    result = runner.invoke(main, ["sub", "edit", "001010000000001", "--home-routed"], env=env)
    assert result.exit_code != 0


def test_sub_add_duplicate_test_imsi_increments(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")

    runner.invoke(main, ["sub", "add", "--test"], env=env)
    second = runner.invoke(main, ["sub", "add", "--test"], env=env)
    assert second.exit_code == 0, second.output
    assert "added 001010000000002" in second.output


def test_sub_remove(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")
    runner.invoke(main, ["sub", "add", "--test"], env=env)

    removed = runner.invoke(main, ["sub", "remove", "001010000000001"], env=env)
    assert removed.exit_code == 0, removed.output

    listed = runner.invoke(main, ["sub", "list"], env=env)
    assert "(no subscribers)" in listed.output


def test_wrong_passphrase_is_rejected(tmp_path):
    runner = CliRunner()
    store_path = tmp_path / "subscribers.db.enc"
    runner.invoke(main, ["sub", "add", "--test"], env=_env(store_path))

    wrong_env = dict(_env(store_path), RESCCOM_SIM_PASSPHRASE="wrong-passphrase")
    result = runner.invoke(main, ["sub", "list"], env=wrong_env)
    assert result.exit_code != 0


def test_stub_commands_fail_clearly_with_wbs_pointer(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")

    for args, wbs in [
        (["sub", "export"], "3.2-d"),
        (["sim", "program"], "3.2-c"),
        (["sim", "verify"], "3.2-c"),
    ]:
        result = runner.invoke(main, args, env=env)
        assert result.exit_code != 0
        assert wbs in result.output


def test_db_sync_calls_run_sync_with_local_subscribers(tmp_path, monkeypatch):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")
    runner.invoke(main, ["sub", "add", "--test"], env=env)

    calls = {}

    def fake_run_sync(subscribers, core_dir):
        calls["subscribers"] = subscribers
        calls["core_dir"] = core_dir
        from resccom_sim.sync import SyncResult

        return SyncResult(added=1, updated=0, unchanged=0, removed=0)

    monkeypatch.setattr("resccom_sim.cli.run_sync", fake_run_sync)

    result = runner.invoke(main, ["db", "sync", "--core-dir", "/tmp/core"], env=env)
    assert result.exit_code == 0, result.output
    assert [s.imsi for s in calls["subscribers"]] == ["001010000000001"]
    assert str(calls["core_dir"]) == "/tmp/core"
    assert "added=1 updated=0 unchanged=0 removed=0" in result.output


def test_sub_add_if_missing_is_a_noop_for_an_identical_subscriber(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")

    first = runner.invoke(main, ["sub", "add", "--test", "--imsi", "001010000000001", "--if-missing"], env=env)
    assert first.exit_code == 0, first.output
    assert "added 001010000000001" in first.output

    second = runner.invoke(main, ["sub", "add", "--test", "--imsi", "001010000000001", "--if-missing"], env=env)
    assert second.exit_code == 0, second.output
    assert "already present: 001010000000001" in second.output
    assert len(runner.invoke(main, ["sub", "list"], env=env).output.strip().splitlines()) == 1


def test_sub_add_if_missing_conflicts_on_a_different_subscriber(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")

    runner.invoke(main, ["sub", "add", "--test", "--imsi", "001010000000001", "--label", "alice", "--if-missing"], env=env)
    conflict = runner.invoke(
        main, ["sub", "add", "--test", "--imsi", "001010000000001", "--label", "bob", "--if-missing"], env=env
    )
    assert conflict.exit_code != 0
    assert "001010000000001" in conflict.output


def test_db_sync_reports_sync_errors(tmp_path, monkeypatch):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")

    from resccom_sim.sync import SyncError

    def fake_run_sync(subscribers, core_dir):
        raise SyncError("mongosh failed: boom")

    monkeypatch.setattr("resccom_sim.cli.run_sync", fake_run_sync)

    result = runner.invoke(main, ["db", "sync"], env=env)
    assert result.exit_code != 0
    assert "mongosh failed" in result.output


def test_roaming_export_writes_file_with_no_secrets(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")
    runner.invoke(main, ["sub", "add", "--test"], env=env)
    out = tmp_path / "export.json"

    result = runner.invoke(main, ["roaming", "export", "--out", str(out)], env=env)
    assert result.exit_code == 0, result.output
    assert "exported 1" in result.output
    text = out.read_text()
    assert TEST_KEY not in text
    assert TEST_OPC not in text
    assert "security" not in text


def test_roaming_export_excludes_home_routed_subscribers_by_default(tmp_path):
    runner = CliRunner()
    env = _env(tmp_path / "subscribers.db.enc")
    runner.invoke(main, ["sub", "add", "--test", "--home-routed"], env=env)
    out = tmp_path / "export.json"

    result = runner.invoke(main, ["roaming", "export", "--out", str(out)], env=env)
    assert result.exit_code == 0, result.output
    assert "exported 0" in result.output


def test_roaming_import_calls_run_import_with_parsed_home_plmn(tmp_path, monkeypatch):
    runner = CliRunner()
    export_file = tmp_path / "export.json"
    export_file.write_text('{"records": [{"imsi": "001010000099999", "lbo_roaming_allowed": true}]}')

    calls = {}

    def fake_run_import(records, core_dir, *, home_mcc, home_mnc):
        calls["records"] = records
        calls["core_dir"] = core_dir
        calls["home_mcc"] = home_mcc
        calls["home_mnc"] = home_mnc
        from resccom_sim.roaming import ImportResult

        return ImportResult(imported=1, conflicts=())

    monkeypatch.setattr("resccom_sim.cli.run_import", fake_run_import)

    result = runner.invoke(
        main,
        ["roaming", "import", str(export_file), "--core-dir", "/tmp/core-b", "--home-plmn", "001/01"],
    )
    assert result.exit_code == 0, result.output
    assert calls["home_mcc"] == "001"
    assert calls["home_mnc"] == "01"
    assert str(calls["core_dir"]) == "/tmp/core-b"
    assert [r.imsi for r in calls["records"]] == ["001010000099999"]
    assert "imported 1" in result.output


def test_roaming_import_rejects_a_credentialed_file_before_calling_run_import(tmp_path, monkeypatch):
    runner = CliRunner()
    export_file = tmp_path / "leaked.json"
    export_file.write_text(
        '{"records": [{"imsi": "001010000099999", "security": {"k": "' + TEST_KEY + '"}}]}'
    )

    def fail_run_import(*args, **kwargs):
        raise AssertionError("run_import must not be called for a credentialed record")

    monkeypatch.setattr("resccom_sim.cli.run_import", fail_run_import)

    result = runner.invoke(
        main, ["roaming", "import", str(export_file), "--home-plmn", "001/01"]
    )
    assert result.exit_code != 0
    assert "credential-like" in result.output


def test_roaming_import_requires_home_plmn_shaped_as_mcc_slash_mnc(tmp_path):
    runner = CliRunner()
    export_file = tmp_path / "export.json"
    export_file.write_text('{"records": []}')

    result = runner.invoke(main, ["roaming", "import", str(export_file), "--home-plmn", "00101"])
    assert result.exit_code != 0
    assert "MCC/MNC" in result.output


def test_roaming_list_prints_inbound_roamer_records(monkeypatch):
    runner = CliRunner()

    def fake_run_list(core_dir):
        return [{"imsi": "001010000099999", "home_plmn": {"mcc": "001", "mnc": "01"}}]

    monkeypatch.setattr("resccom_sim.cli.run_list", fake_run_list)

    result = runner.invoke(main, ["roaming", "list"])
    assert result.exit_code == 0, result.output
    assert "001010000099999" in result.output
    assert "001/01" in result.output


def test_roaming_list_reports_empty(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr("resccom_sim.cli.run_list", lambda core_dir: [])

    result = runner.invoke(main, ["roaming", "list"])
    assert result.exit_code == 0, result.output
    assert "no inbound-roamer records" in result.output


def test_roaming_remove_reports_success(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr("resccom_sim.cli.run_remove", lambda imsi, core_dir: True)

    result = runner.invoke(main, ["roaming", "remove", "001010000099999"])
    assert result.exit_code == 0, result.output
    assert "removed 001010000099999" in result.output


def test_roaming_remove_errors_when_nothing_removed(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr("resccom_sim.cli.run_remove", lambda imsi, core_dir: False)

    result = runner.invoke(main, ["roaming", "remove", "001010000099999"])
    assert result.exit_code != 0
    assert "no inbound-roamer record" in result.output
