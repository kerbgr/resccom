from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from resccom_sim.model import TEST_KEY, TEST_OPC, Subscriber
from resccom_sim.roaming import (
    ImportResult,
    PolicyRecord,
    RoamingExportError,
    RoamingImportError,
    _import_script,
    _inbound_doc_js,
    export_policy_records,
    read_import_file,
    run_import,
    run_list,
    run_remove,
    write_export_file,
)


def test_export_defaults_to_lbo_roaming_allowed_subscribers():
    lbo = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC)
    hr = Subscriber(imsi="001010000000002", key=TEST_KEY, opc=TEST_OPC, lbo_roaming_allowed=False)

    records = export_policy_records([lbo, hr])

    assert [r.imsi for r in records] == ["001010000000001"]


def test_export_by_imsi_selects_named_subscribers():
    lbo = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC)
    records = export_policy_records([lbo], imsis=["001010000000001"])
    assert records == [PolicyRecord(imsi="001010000000001", lbo_roaming_allowed=True)]


def test_export_by_imsi_errors_on_missing_subscriber():
    with pytest.raises(RoamingExportError, match="no such subscriber"):
        export_policy_records([], imsis=["001010000000099"])


def test_export_by_imsi_errors_on_home_routed_subscriber():
    hr = Subscriber(imsi="001010000000002", key=TEST_KEY, opc=TEST_OPC, lbo_roaming_allowed=False)
    with pytest.raises(RoamingExportError, match="Home-Routed"):
        export_policy_records([hr], imsis=["001010000000002"])


def test_policy_record_to_dict_has_no_security_fields():
    record = PolicyRecord(imsi="001010000000001", lbo_roaming_allowed=True)
    d = record.to_dict()
    assert set(d.keys()) == {"imsi", "lbo_roaming_allowed"}
    for key in ("security", "k", "opc", "op", "amf", "key"):
        assert key not in d


def test_write_export_file_round_trips_through_read_import_file(tmp_path):
    records = [PolicyRecord(imsi="001010000000001", lbo_roaming_allowed=True)]
    out = tmp_path / "export.json"

    write_export_file(records, out)
    text = out.read_text()
    for forbidden in ("security", "\"k\"", "opc", "\"op\"", TEST_KEY, TEST_OPC):
        assert forbidden not in text

    read_back = read_import_file(out)
    assert read_back == records


def test_import_refuses_record_with_security_block():
    from resccom_sim.roaming import _validate_record

    with pytest.raises(RoamingImportError, match="credential-like"):
        _validate_record({"imsi": "001010000000001", "security": {"k": TEST_KEY}})


@pytest.mark.parametrize("bad_key", ["k", "opc", "op", "amf", "SECURITY"])
def test_import_refuses_record_with_any_credential_like_field(bad_key):
    from resccom_sim.roaming import _validate_record

    with pytest.raises(RoamingImportError, match="credential-like"):
        _validate_record({"imsi": "001010000000001", bad_key: "deadbeef"})


def test_import_refuses_record_with_invalid_imsi():
    from resccom_sim.roaming import _validate_record

    with pytest.raises(RoamingImportError, match="imsi"):
        _validate_record({"imsi": "not-an-imsi"})


def test_import_read_file_refuses_a_credentialed_record_before_touching_mongo(tmp_path):
    bad_file = tmp_path / "leaked.json"
    bad_file.write_text('{"records": [{"imsi": "001010000000001", "security": {"k": "' + TEST_KEY + '"}}]}')

    with pytest.raises(RoamingImportError, match="credential-like"):
        read_import_file(bad_file)


def test_inbound_doc_js_has_no_security_key_and_is_marked():
    record = PolicyRecord(imsi="001010000099999", lbo_roaming_allowed=True)
    doc = _inbound_doc_js(record, "001", "01")

    assert "security" not in doc
    assert '"resccom_inbound_roamer": true' in doc
    assert '"home_plmn": { "mcc": "001", "mnc": "01" }' in doc
    assert '"imsi": "001010000099999"' in doc
    # PCF's own SM-Policy lookup (lib/dbi/session.c) needs this fragment.
    assert '"session"' in doc
    assert '"lbo_roaming_allowed": true' in doc


def test_import_script_skips_existing_unmarked_local_subscriber():
    record = PolicyRecord(imsi="001010000000001", lbo_roaming_allowed=True)
    script = _import_script([record], "001", "01")
    assert "existing.resccom_inbound_roamer !== true" in script
    assert "conflicts.push" in script


@patch("resccom_sim.roaming.subprocess.run")
def test_run_import_invokes_docker_compose_exec_mongo(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout='{"imported": 1, "conflicts": []}\n', stderr="")
    record = PolicyRecord(imsi="001010000000001", lbo_roaming_allowed=True)

    result = run_import([record], Path("/some/core/dir"), home_mcc="001", home_mnc="01")

    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd[:7] == ["docker", "compose", "exec", "-T", "mongo", "mongosh", "--quiet"]
    assert kwargs["cwd"] == Path("/some/core/dir")
    assert result == ImportResult(imported=1, conflicts=())


@patch("resccom_sim.roaming.subprocess.run")
def test_run_import_raises_on_conflicts(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0, stdout='{"imported": 0, "conflicts": ["001010000000001"]}\n', stderr=""
    )
    record = PolicyRecord(imsi="001010000000001", lbo_roaming_allowed=True)

    with pytest.raises(RoamingImportError, match="001010000000001"):
        run_import([record], Path("."), home_mcc="001", home_mnc="01")


def test_run_import_rejects_malformed_home_plmn():
    record = PolicyRecord(imsi="001010000000001", lbo_roaming_allowed=True)
    with pytest.raises(RoamingImportError, match="invalid --home-plmn"):
        run_import([record], Path("."), home_mcc="1", home_mnc="1")


@patch("resccom_sim.roaming.subprocess.run")
def test_run_list_parses_records(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout='[{"imsi": "001010000099999", "home_plmn": {"mcc": "001", "mnc": "01"}}]\n',
        stderr="",
    )
    records = run_list(Path("."))
    assert records[0]["imsi"] == "001010000099999"


@patch("resccom_sim.roaming.subprocess.run")
def test_run_remove_reports_deleted_count(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout='{"deleted": 1}\n', stderr="")
    assert run_remove("001010000099999", Path(".")) is True


@patch("resccom_sim.roaming.subprocess.run")
def test_run_remove_returns_false_for_nothing_deleted(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout='{"deleted": 0}\n', stderr="")
    assert run_remove("001010000099999", Path(".")) is False
