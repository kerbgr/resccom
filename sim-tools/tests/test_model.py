import pytest

from resccom_sim.model import TEST_KEY, TEST_OPC, Subscriber, SubscriberError, generate_test_imsi


def test_valid_subscriber_roundtrip():
    sub = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC, label="test-1")
    assert sub.imsi == "001010000000001"
    assert sub.key == TEST_KEY
    assert sub.created_at  # ISO timestamp, set by default_factory


def test_lbo_roaming_allowed_defaults_true():
    # RFC-0003 D1: Local Breakout is the project default for a roaming session.
    sub = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC)
    assert sub.lbo_roaming_allowed is True


def test_lbo_roaming_allowed_can_opt_out_to_home_routed():
    sub = Subscriber(imsi="001010000000001", key=TEST_KEY, opc=TEST_OPC, lbo_roaming_allowed=False)
    assert sub.lbo_roaming_allowed is False


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("imsi", "12345"),
        ("imsi", "abcdefghijklmno"),
        ("key", "not-hex"),
        ("key", "AB" * 15),
        ("opc", "zz" * 16),
        ("amf", "not-hex"),
    ],
)
def test_rejects_invalid_fields(field_name, value):
    fields = {"imsi": "001010000000001", "key": TEST_KEY, "opc": TEST_OPC, "amf": "8000"}
    fields[field_name] = value
    with pytest.raises(SubscriberError):
        Subscriber(**fields)


def test_generate_test_imsi_avoids_collisions():
    first = generate_test_imsi(set())
    second = generate_test_imsi({first})
    assert first != second
    assert first.startswith("00101")
    assert second.startswith("00101")
    assert len(first) == 15
