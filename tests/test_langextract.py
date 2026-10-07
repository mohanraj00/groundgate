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
        "evidence": [{"start": start, "end": start + 6, "text": "$7,000"}],
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
    start = text.index("$8,000")
    assert c["evidence"] == [{"start": start, "end": start + 6, "text": "$8,000"}]
    (d,) = admit_document(annotated, SCHEMA).decisions
    assert (d.outcome, d.codes) == ("rejected", ("VALUE_NOT_IN_EVIDENCE",))
    unnamed = lx.data.AnnotatedDocument(text=text, extractions=aligned)
    assert admit_document(unnamed, SCHEMA).document_id is None  # not LangExtract's random id
    assert admit_document(unnamed, SCHEMA, document_id="x").document_id == "x"


def test_role_attributes_become_quotes() -> None:
    at = TEXT.index("$7,000")
    texts = {"sign_text": "minus", "scale_text": "thousands", "unit_text": "$",
             "key_text": "Café", "field_text": "limit"}  # fmt: skip
    (c,) = to_candidates(doc(x("limit", "$7,000", at, "7000", **texts)))
    value, *roles = c["evidence"]
    assert value == {"start": at + 1, "end": at + 7, "text": "$7,000"}
    assert roles == [
        {"role": "sign", "text": "minus"},
        {"role": "scale", "text": "thousands"},
        {"role": "unit", "text": "$"},
        {"role": "key", "text": "Café"},
        {"role": "field", "text": "limit"},
    ]
    # blank or not text: no item
    (c,) = to_candidates(doc(x("limit", "$7,000", at, key_text=" ", scale_text=3, field_text=None)))
    assert c["evidence"] == [value]


def test_outside_attributes_become_outside_items() -> None:
    at = TEXT.index("$7,000")
    source = {"source_url": "https://example.org/limits", "source_retrieved": "2026-10-01",
              "source_quote": "The limit is $7,000."}  # fmt: skip
    external = {"source": "external", "url": "https://example.org/limits",
                "retrieved": "2026-10-01", "text": "The limit is $7,000."}  # fmt: skip
    knowledge = {"source": "knowledge", "text": "The limit is $7,000 (IRC 219)."}
    ext = x("limit", "$7,000", at, "7000", knowledge=knowledge["text"], **source)
    (c,) = to_candidates(doc(ext))
    assert c["evidence"][1:] == [external, knowledge]
    for member in source:  # all three or no external item
        (c,) = to_candidates(doc(x("limit", "$7,000", at, **{**source, member: ""})))
        assert len(c["evidence"]) == 1


def test_an_unaligned_extraction_keeps_only_its_outside_items() -> None:
    ext = x("limit", "$9,000", None, "9000", unit="USD", key_text="Café", knowledge="It is $9,000.")
    (c,) = to_candidates(doc(ext))
    assert c["evidence"] == [{"source": "knowledge", "text": "It is $9,000."}]
    (d,) = admit_document(doc(ext), SCHEMA).decisions
    assert (d.outcome, d.codes) == ("needs_verification", ("EVIDENCE_STATED",))
    (c,) = to_candidates(doc(x("limit", "$9,000", None, "9000", key_text="Café")))
    assert "evidence" not in c  # no value item and no outside item: NO_EVIDENCE, as before


def test_the_app_renames_the_evidence_attributes() -> None:
    at = TEXT.index("$7,000")
    ext = x("limit", "$7,000", at, "7000", row="limit", key_text="Café", note="It is $7,000.")
    (c,) = to_candidates(doc(ext), attributes={"field_text": "row", "knowledge": "note"})
    assert c["evidence"][1:] == [
        {"role": "key", "text": "Café"},
        {"role": "field", "text": "limit"},
        {"source": "knowledge", "text": "It is $7,000."},
    ]
    (c,) = to_candidates(doc(ext), attributes={"key_text": "label"})
    assert c["evidence"][1:] == []  # "key_text" is not read once it is renamed
    with pytest.raises(ValueError, match="unknown evidence attributes"):
        to_candidates(doc(ext), attributes={"key": "label"})


TABLE = (
    "Year Ended December 31,\n(in thousands)\n\n2025\n\n2024\n\n"
    "Revenue\n\n$\n\n46,016\n\n$\n\n434,433\n\n"
    "Loss from operations\n\n$\n\n(140,102\n)\n\n$\n\n(105,198\n)"
)
TABLE_SCHEMA = {
    "fields": {
        name: {"type": "integer", "unit": "USD", "keys": ["2025", "2024"], "multiple": True,
               "aliases": [alias]}
        for name, alias in (("revenue", "revenue"), ("op_income", "loss from operations"))
    }
}  # fmt: skip


def test_a_table_value_is_admitted_with_its_cited_parts() -> None:
    def cell(cls: str, quote: str, value: str, key: str, **texts: str) -> Any:
        return x(cls, quote, TABLE.index(quote), value, unit="USD", key=key, **texts)

    scale = {"scale_text": "(in thousands"}
    extractions = [
        cell("revenue", "434,433", "434433000", "2024", field_text="Revenue", key_text="2024",
             **scale),
        cell("revenue", "434,433", "434433000", "2025", field_text="Revenue", key_text="2025",
             **scale),
        cell("op_income", "105,198", "-105198000", "2024", field_text="Loss from operations",
             key_text="2024", unit_text="$", **scale),
        cell("revenue", "434,433", "434433000", "2024"),
    ]  # fmt: skip
    receipt = admit_document({"text": TABLE, "extractions": extractions}, TABLE_SCHEMA)
    got = sorted((d.candidate_id, d.outcome, d.codes) for d in receipt.decisions)
    assert got == [
        (0, "admitted", ("VALUE_DERIVED", "KEY_CITED")),
        (1, "needs_verification", ("KEY_NOT_AT_VALUE", "VALUE_DERIVED")),  # the wrong column
        (2, "admitted", ("VALUE_DERIVED", "KEY_CITED")),
        (3, "needs_verification", ("PART_MISSING", "KEY_NOT_AT_VALUE")),  # nothing cited
    ]


def test_admit_document_passes_the_packet_members_to_admit() -> None:
    from groundgate.adapters.langextract import admit_document

    attrs = {
        "value": "40",
        "unit": "USD",
        "source_url": "https://example.org/fees",
        "source_quote": "The fee is $40.",
        "source_retrieved": "2026-10-01",
    }
    ext = {"extraction_class": "fee", "extraction_text": "x", "char_interval": None}
    doc = {"text": "The fee is $40.", "extractions": [{**ext, "attributes": attrs}]}
    schema = {"fields": {"fee": {"type": "integer", "unit": "USD"}}}
    policy = {"sources": {"external": {"allow": ["document-domain"]}}}
    r = admit_document(doc, schema, policy, document_source="https://example.org/doc")
    d = r.to_dict()
    assert d["document"]["source"] == "https://example.org/doc"
    assert d["decisions"][0]["codes"] == ["ADMITTED_BY_POLICY"]
