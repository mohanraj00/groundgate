"""Date fields (SPEC §4.11, #612). The conformance vectors 159 to 162 hold the decisions."""

from __future__ import annotations

import time
from typing import Any

import pytest

import groundgate as gg
from groundgate.model import normal_date

DATE = {"type": "date", "formats": ["D/M/YYYY", "D Month YYYY"]}


def _cand(cid: str, value: Any, quote: str, field: str = "day", **extra: Any) -> dict[str, Any]:
    return {"id": cid, "field": field, "value": value, "evidence": [{"text": quote}], **extra}


def _decisions(text: str, schema: dict[str, Any], cands: list[dict[str, Any]]) -> dict[str, Any]:
    return {d.candidate_id: d for d in gg.admit(text, schema, cands).decisions}


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("2024-02-29", "2024-02-29"),
        ("0001-01-01", "0001-01-01"),
        ("9999-12-31", "9999-12-31"),
        ("2025-02-29", None),
        ("0000-01-01", None),
        ("2025-7-1", None),
        ("2025-07-01 ", None),
        ("\uff12025-07-01", None),
        ("2025-13-01", None),
        (20250701, None),
    ],
)
def test_normal_form(raw: object, want: str | None) -> None:
    assert normal_date(raw) == want


def test_schema_digest_holds_formats_only_on_a_date_field() -> None:
    schema = gg.Schema.from_dict({"fields": {"day": DATE, "n": {"type": "integer"}}})
    fields = schema.to_dict()["fields"]
    assert fields["day"]["formats"] == ["D/M/YYYY", "D Month YYYY"]
    assert fields["day"]["minimum"] is None
    assert "formats" not in fields["n"]


def test_rejected_decision_value() -> None:
    """A rejected decision carries the value in the normal form, or null (SPEC §5)."""
    got = _decisions(
        "Signed 1 July 2025.",
        {"fields": {"day": DATE}},
        [_cand("a", "2025-07-02", "1 July 2025"), _cand("b", "1 July 2025", "1 July 2025")],
    )
    assert (got["a"].value, got["a"].codes) == ("2025-07-02", ("VALUE_NOT_IN_EVIDENCE",))
    assert (got["b"].value, got["b"].codes) == (None, ("TYPE_INVALID",))


def test_keyed_date_field() -> None:
    """The key is read at the date mention, as at a number token."""
    text = "Renewal is on 1 July 2025. Expiry is on 30 June 2026."
    schema = {"fields": {"day": {**DATE, "keys": ["Renewal", "Expiry"], "multiple": True}}}
    got = _decisions(
        text,
        schema,
        [
            _cand("a", "2025-07-01", "1 July 2025", key="Renewal"),
            _cand("b", "2026-06-30", "30 June 2026", key="Renewal"),
        ],
    )
    assert got["a"].outcome == "admitted"
    assert "KEY_NOT_AT_VALUE" in got["b"].codes


def test_extractor_schema_asks_for_the_normal_form() -> None:
    out = gg.extractor_schema({"fields": {"day": DATE}})
    assert out["properties"]["candidates"]["items"]["properties"]["value"] == {
        "type": "string",
        "description": "The date as YYYY-MM-DD.",
    }


def test_long_runs_are_read_in_bounded_time() -> None:
    """A month name has at most 9 letters, so a long run of letters or digits costs one pass."""
    text = "a" * 200_000 + " 1/" + "9" * 200_000 + " 1 July 2025"
    start = time.monotonic()
    got = _decisions(
        text,
        {"fields": {"day": DATE}},
        [{"id": "a", "field": "day", "value": "2025-07-01",
          "evidence": [{"start": 0, "end": len(text)}]}],
    )  # fmt: skip
    assert got["a"].outcome == "admitted"
    assert time.monotonic() - start < 10


@pytest.mark.parametrize(
    ("field", "error"),
    [
        ({"type": "date"}, "formats"),
        ({"type": "date", "formats": ["YYYY-MM-DD"], "minimum": "2025-02-30"}, "minimum"),
        ({"type": "date", "formats": ["YYYY-MM-DD"], "unit": "d"}, "unit"),
        ({"type": "number", "formats": ["YYYY-MM-DD"]}, "only a date field"),
    ],
)
def test_invalid_date_field(field: dict[str, Any], error: str) -> None:
    with pytest.raises(gg.PacketError, match=error):
        gg.Schema.from_dict({"fields": {"day": field}})
