import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from requested.replay_terms import apply_terms

SCHEMA = {
    "fields": {
        "supply_voltage_max": {"type": "number", "unit": "V", "aliases": ["Supply voltage"]},
        "deductible_family": {"type": "number", "unit": "USD"},
    }
}


def test_terms_add_aliases_columns_and_markers() -> None:
    out = apply_terms(
        SCHEMA,
        {
            "supply_voltage_max": {"aliases": ["Supply voltage", "Max supply"], "columns": ["Max"]},
            "deductible_family": {"markers": ["family"]},
        },
    )
    assert out["fields"]["supply_voltage_max"]["aliases"] == ["Supply voltage", "Max supply"]
    assert out["fields"]["supply_voltage_max"]["columns"] == ["Max"]
    assert out["fields"]["deductible_family"]["markers"] == ["family"]
    assert SCHEMA["fields"]["supply_voltage_max"]["aliases"] == ["Supply voltage"]


def test_terms_refuse_an_unknown_field_and_a_second_column_list() -> None:
    with pytest.raises(ValueError, match="unknown field"):
        apply_terms(SCHEMA, {"ph": {"aliases": ["pH value"]}})
    once = apply_terms(SCHEMA, {"supply_voltage_max": {"columns": ["Max"]}})
    with pytest.raises(ValueError, match="already has columns"):
        apply_terms(once, {"supply_voltage_max": {"columns": ["Max."]}})
