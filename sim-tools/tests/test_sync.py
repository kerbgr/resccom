from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from resccom_sim.model import TEST_KEY, TEST_OPC, Subscriber
from resccom_sim.sync import SyncError, SyncResult, run_sync, sync_script


def test_sync_script_upserts_local_subscribers_and_deletes_stale():
    sub = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC)
    script = sync_script([sub])
    assert "replaceOne" in script
    assert f'imsi: "{sub.imsi}"' in script
    assert f'"k": "{TEST_KEY}"' in script
    assert f'"opc": "{TEST_OPC}"' in script
    # 3.3-c v2h: reconcile-delete also excludes marked inbound-roamer records.
    assert f'imsi: {{ $nin: ["{sub.imsi}"] }},' in script
    assert "resccom_inbound_roamer: { $ne: true }" in script


def test_sync_script_writes_lbo_roaming_allowed_true_by_default():
    # RFC-0003 D1: Local Breakout by default; upstream's own field name
    # (docs/_docs/tutorial/05-roaming.md section 2).
    sub = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC)
    script = sync_script([sub])
    assert '"lbo_roaming_allowed": true' in script


def test_sync_script_writes_lbo_roaming_allowed_false_for_home_routed():
    sub = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC, lbo_roaming_allowed=False)
    script = sync_script([sub])
    assert '"lbo_roaming_allowed": false' in script


def test_sync_script_empty_store_deletes_everything():
    script = sync_script([])
    assert "const subs = [\n    \n];" in script
    assert "imsi: { $nin: [] }," in script
    assert "resccom_inbound_roamer: { $ne: true }" in script


def test_sync_script_never_upserts_or_deletes_marked_inbound_roamer_records():
    # 3.3-c v2h: an inbound-roamer record (roaming.py `roaming import`) is
    # owned by its home island's store, not this island's local sync.
    sub = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC)
    script = sync_script([sub])
    assert "existing.resccom_inbound_roamer === true" in script
    assert "continue;" in script


def test_sync_script_skips_unchanged_documents():
    sub = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC)
    script = sync_script([sub])
    # the unchanged-skip path must exist: an existing doc that canon()s equal
    # to the would-be doc is left alone, never replaceOne'd.
    assert "unchanged++" in script
    assert "canon(existing) === canon(sub.doc)" in script


def test_sync_script_ignores_core_managed_runtime_fields():
    # Open5GS writes these back into a live subscriber's document as a
    # normal side effect of registration/authentication (imeisv, sqn) or
    # 4G/HSS attach (mme_host/mm_realm/purge_flag) -- comparing them would
    # make an attached subscriber's otherwise-identical document look
    # "changed" and defeat the unchanged-skip above. Found live: see
    # sync.py's module docstring.
    script = sync_script([Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC)])
    for field in ("imeisv", "sqn", "mme_host", "mm_realm", "purge_flag"):
        assert f'"{field}"' in script


@patch("resccom_sim.sync.subprocess.run")
def test_run_sync_invokes_docker_compose_exec_mongo_in_core_dir(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0, stdout='{"added": 1, "updated": 0, "unchanged": 0, "removed": 0}\n', stderr=""
    )
    sub = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC)

    result = run_sync([sub], Path("/some/core/dir"))

    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd[:7] == ["docker", "compose", "exec", "-T", "mongo", "mongosh", "--quiet"]
    assert kwargs["cwd"] == Path("/some/core/dir")
    assert result == SyncResult(added=1, updated=0, unchanged=0, removed=0)


@patch("resccom_sim.sync.subprocess.run")
def test_run_sync_raises_sync_error_on_nonzero_exit(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="connection refused")
    with pytest.raises(SyncError, match="connection refused"):
        run_sync([], Path("."))


@patch("resccom_sim.sync.subprocess.run")
def test_run_sync_raises_sync_error_on_unparseable_output(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="not json\n", stderr="")
    with pytest.raises(SyncError, match="could not parse"):
        run_sync([], Path("."))


@patch("resccom_sim.sync.subprocess.run")
def test_run_sync_parses_unchanged_and_removed_counts(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0, stdout='{"added": 0, "updated": 0, "unchanged": 2, "removed": 1}\n', stderr=""
    )
    result = run_sync([], Path("."))
    assert result.unchanged == 2
    assert result.removed == 1
