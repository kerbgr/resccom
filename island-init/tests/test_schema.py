"""Schema round-trip coverage (2.1-a acceptance: `pytest covers schema round-trip`)."""
from pathlib import Path

from island_init.schema import load_schema, validate_schema
from island_init.yaml_io import load

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = Path(__file__).parent.parent / "island.example.yaml"


def test_schema_loads_and_is_draft_2020_12():
    schema = load_schema()
    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["required"] == [
        "island",
        "allocations",
        "node",
        "sites",
        "services",
        "backhaul",
        "federation",
        "profile",
    ]


def test_example_lab_profile_round_trips_clean():
    data = load(EXAMPLE)
    assert validate_schema(data) == []


def test_valid_production_fixture_round_trips_clean():
    data = load(FIXTURES / "valid_production.yaml")
    assert validate_schema(data) == []


def test_missing_required_top_level_field_is_rejected():
    data = load(EXAMPLE)
    del data["backhaul"]
    issues = validate_schema(data)
    assert len(issues) == 1
    assert issues[0].field == "<root>"
    assert "backhaul" in issues[0].message


def test_unknown_field_is_rejected_additional_properties_false():
    data = load(EXAMPLE)
    data["totally_unexpected_field"] = "nope"
    issues = validate_schema(data)
    assert len(issues) == 1
    assert "totally_unexpected_field" in issues[0].message


def test_bad_profile_enum_value_is_rejected():
    data = load(EXAMPLE)
    data["profile"] = "staging"
    issues = validate_schema(data)
    assert any(i.field == "profile" for i in issues)


def test_wrong_type_for_pci_is_rejected():
    data = load(EXAMPLE)
    data["sites"][0]["cells"][0]["pci"] = "not-a-number"
    issues = validate_schema(data)
    assert any("sites[0].cells[0].pci" == i.field for i in issues)
