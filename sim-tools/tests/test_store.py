import sqlite3

import pytest

from resccom_sim.crypto import DecryptionError
from resccom_sim.model import TEST_KEY, TEST_OPC, Subscriber
from resccom_sim.store import SCHEMA, SubscriberConflictError, SubscriberExistsError, SubscriberStore


def test_add_list_roundtrip_survives_reopen(tmp_path):
    path = tmp_path / "subscribers.db.enc"
    SubscriberStore(path, "correct horse battery staple").add(
        Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC, label="alice")
    )

    subs = SubscriberStore(path, "correct horse battery staple").list_all()
    assert [s.imsi for s in subs] == ["001010000000001"]
    assert subs[0].label == "alice"


def test_store_file_is_ciphertext_not_a_plain_sqlite_db(tmp_path):
    path = tmp_path / "subscribers.db.enc"
    SubscriberStore(path, "correct horse battery staple").add(
        Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC)
    )

    raw = path.read_bytes()
    assert not raw.startswith(b"SQLite format 3")
    assert TEST_KEY.encode() not in raw
    assert TEST_OPC.encode() not in raw


def test_wrong_passphrase_cannot_decrypt(tmp_path):
    path = tmp_path / "subscribers.db.enc"
    SubscriberStore(path, "right-passphrase").add(Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC))

    with pytest.raises(DecryptionError):
        SubscriberStore(path, "wrong-passphrase").list_all()


def test_duplicate_imsi_rejected(tmp_path):
    path = tmp_path / "subscribers.db.enc"
    store = SubscriberStore(path, "passphrase")
    sub = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC)
    store.add(sub)
    with pytest.raises(SubscriberExistsError):
        store.add(sub)


def test_remove(tmp_path):
    path = tmp_path / "subscribers.db.enc"
    store = SubscriberStore(path, "passphrase")
    store.add(Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC))

    assert store.remove("001010000000001") is True
    assert store.list_all() == []
    assert store.remove("001010000000001") is False


def test_add_if_missing_inserts_new(tmp_path):
    path = tmp_path / "subscribers.db.enc"
    store = SubscriberStore(path, "passphrase")
    sub = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC)

    assert store.add_if_missing(sub) is True
    assert [s.imsi for s in store.list_all()] == ["001010000000001"]


def test_add_if_missing_is_a_noop_for_an_identical_subscriber(tmp_path):
    path = tmp_path / "subscribers.db.enc"
    store = SubscriberStore(path, "passphrase")
    sub = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC, label="alice")
    store.add_if_missing(sub)

    again = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC, label="alice")
    assert store.add_if_missing(again) is False
    assert len(store.list_all()) == 1


def test_add_if_missing_conflicts_on_different_fields(tmp_path):
    path = tmp_path / "subscribers.db.enc"
    store = SubscriberStore(path, "passphrase")
    store.add_if_missing(Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC, label="alice"))

    conflicting = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC, label="bob")
    with pytest.raises(SubscriberConflictError):
        store.add_if_missing(conflicting)
    # the conflict must not have overwritten the existing row
    assert store.list_all()[0].label == "alice"


def test_add_if_missing_conflicts_on_different_roaming_mode(tmp_path):
    path = tmp_path / "subscribers.db.enc"
    store = SubscriberStore(path, "passphrase")
    store.add_if_missing(Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC))

    conflicting = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC, lbo_roaming_allowed=False)
    with pytest.raises(SubscriberConflictError):
        store.add_if_missing(conflicting)


def test_lbo_roaming_allowed_defaults_true_and_survives_reopen(tmp_path):
    path = tmp_path / "subscribers.db.enc"
    SubscriberStore(path, "passphrase").add(Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC))

    subs = SubscriberStore(path, "passphrase").list_all()
    assert subs[0].lbo_roaming_allowed is True


def test_add_home_routed_subscriber_survives_reopen(tmp_path):
    path = tmp_path / "subscribers.db.enc"
    SubscriberStore(path, "passphrase").add(
        Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC, lbo_roaming_allowed=False)
    )

    subs = SubscriberStore(path, "passphrase").list_all()
    assert subs[0].lbo_roaming_allowed is False


def test_set_lbo_roaming_allowed_flips_an_existing_subscriber(tmp_path):
    path = tmp_path / "subscribers.db.enc"
    store = SubscriberStore(path, "passphrase")
    store.add(Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC))

    assert store.set_lbo_roaming_allowed("001010000000001", False) is True
    assert store.list_all()[0].lbo_roaming_allowed is False

    assert store.set_lbo_roaming_allowed("001010000000001", True) is True
    assert store.list_all()[0].lbo_roaming_allowed is True


def test_set_lbo_roaming_allowed_reports_missing_subscriber(tmp_path):
    path = tmp_path / "subscribers.db.enc"
    store = SubscriberStore(path, "passphrase")
    assert store.set_lbo_roaming_allowed("001010000000001", False) is False


def test_a_store_written_before_the_lbo_field_existed_loads_as_true(tmp_path):
    # Simulates a store on disk from before this field was added: same
    # SCHEMA minus the lbo_roaming_allowed column. "records written before
    # this field load as True" (TASKS.md 3.3-c v2e).
    from resccom_sim.crypto import encrypt

    old_schema = SCHEMA.replace("lbo_roaming_allowed INTEGER NOT NULL DEFAULT 1,\n    ", "")
    assert "lbo_roaming_allowed" not in old_schema

    conn = sqlite3.connect(":memory:")
    conn.executescript(old_schema)
    conn.execute(
        "INSERT INTO subscribers (imsi, key, opc, amf, label, node_class_notes, created_at)"
        " VALUES (?, ?, ?, ?, '', '', 'then')",
        ("001010000000001", TEST_KEY, TEST_OPC, "8000"),
    )
    conn.commit()
    plaintext = conn.serialize()
    conn.close()

    path = tmp_path / "subscribers.db.enc"
    path.write_bytes(encrypt(plaintext, "passphrase"))

    store = SubscriberStore(path, "passphrase")
    subs = store.list_all()
    assert subs[0].imsi == "001010000000001"
    assert subs[0].lbo_roaming_allowed is True

    # and the migrated store is still fully usable afterwards
    store.add(Subscriber(imsi="001010000000002", key=TEST_KEY, opc=TEST_OPC, lbo_roaming_allowed=False))
    subs = SubscriberStore(path, "passphrase").list_all()
    assert {s.imsi: s.lbo_roaming_allowed for s in subs} == {
        "001010000000001": True,
        "001010000000002": False,
    }
