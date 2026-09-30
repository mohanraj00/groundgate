from __future__ import annotations

from typing import Any

import pytest

import groundgate as gg
from groundgate.adapters.langextract import admit_document, to_candidates

TEXT = "Café limit: $7,000 ($8,000 at 50). Fee: $7,000."
SCHEMA = {
    "fields": {
        "limit": {"type": "integer", "unit": "USD"},
        "limit_50": {"type": "integer", "unit": "USD"},
    }
}


def x(cls: str, quote: str, start: int | None, value: str | None = None, **attrs: Any) -> Any:
    """An extraction in LangExtract's JSONL dict form."""
    if value is not None:
        attrs["value"] = value
    interval = None if start is None else {"start_pos": start, "end_pos": start + len(quote)}
    return {
        "extraction_class": cls,
        "extraction_text": quote,
        "char_interval": interval,
        "alignment_status": None if start is None else "match_exact",
        "attributes": attrs or None,
    }


def doc(*extractions: Any) -> dict[str, Any]:
    return {"document_id": "d1", "text": TEXT, "extractions": list(extractions)}


def test_offsets_become_utf8_bytes() -> None:
    (c,) = to_candidates(doc(x("limit", "$7,000", TEXT.index("$7,000"), "7000", unit="USD")))
    start = TEXT.encode().index(b"$7,000")
    assert TEXT.index("$7,000") == start - 1  # "é" is two bytes
    assert c == {
        "id": 0,
        "field": "limit",
        "value": "7000",
        "unit": "USD",
        "extraction_class": "limit",
        "alignment_status": "match_exact",
        "evidence": {"start": start, "end": start + 6, "text": "$7,000"},
    }


def test_the_value_attribute_is_checked_not_the_text() -> None:
    at = TEXT.index("$8,000")
    receipt = admit_document(
        doc(
            x("limit_50", "$8,000", at, "8000", unit="USD"),
            x("limit_50", "$8,000", at, "80000", unit="USD"),  # LangExtract: MATCH_EXACT
            x("limit", "$9,000", None, "9000", unit="USD"),  # LangExtract could not align it
        ),
        SCHEMA,
    )
    assert receipt.document_id == "d1"
    got = {(d.value, d.outcome, d.codes) for d in receipt.decisions}
    assert got == {
        ("8000", "admitted", ()),
        ("80000", "rejected", ("VALUE_NOT_IN_EVIDENCE",)),
        ("9000", "rejected", ("NO_EVIDENCE",)),
    }


def test_defaults_and_renames() -> None:
    at = TEXT.index("$7,000")
    (c,) = to_candidates(
        doc(x("base_limit", "$7,000", at, amount="7000", currency="USD")),
        fields={"base_limit": "limit"},
        value_attribute="amount",
        unit_attribute="currency",
    )
    assert (c["field"], c["value"], c["unit"]) == ("limit", "7000", "USD")
    (c,) = to_candidates(doc(x("limit", "$7,000", at)))
    assert c["value"] == "$7,000" and "unit" not in c and "key" not in c
    (c,) = to_candidates(doc(x("limit", "$7,000", at, key="under 50")))
    assert c["key"] == "under 50"
    (c,) = to_candidates(doc(x("limit", "$7,000", at, group="under 50")), key_attribute="group")
    assert c["key"] == "under 50"


def test_bad_documents() -> None:
    with pytest.raises(gg.PacketError, match="no text"):
        to_candidates({"extractions": []})
    with pytest.raises(gg.PacketError, match="NFC"):
        to_candidates({"text": "Café", "extractions": []})
    with pytest.raises(gg.PacketError, match="outside"):
        to_candidates(doc(x("limit", "$7,000", len(TEXT))))


def test_real_langextract_objects() -> None:
    lx = pytest.importorskip("langextract")
    from langextract.resolver import Resolver

    text = "The limit is $7,000 ($8,000 at age 50)."
    raw = [lx.data.Extraction("limit_50", "$8,000", attributes={"value": "80000", "unit": "USD"})]
    aligned = list(Resolver().align(raw, text, 0, 0))
    annotated = lx.data.AnnotatedDocument(document_id="real", text=text, extractions=aligned)
    (c,) = to_candidates(annotated)
    assert c["alignment_status"] == "match_exact"
    assert c["evidence"]["text"] == "$8,000"
    (d,) = admit_document(annotated, SCHEMA).decisions
    assert (d.outcome, d.codes) == ("rejected", ("VALUE_NOT_IN_EVIDENCE",))
    unnamed = lx.data.AnnotatedDocument(text=text, extractions=aligned)
    assert admit_document(unnamed, SCHEMA).document_id is None  # not LangExtract's random id
    assert admit_document(unnamed, SCHEMA, document_id="x").document_id == "x"
