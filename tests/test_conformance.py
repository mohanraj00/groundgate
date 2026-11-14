"""Run every conformance vector (SPEC §3) against the reference implementation."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate.cli import main
from groundgate.store import FolderStore
from groundgate.store import key as store_key
from groundgate.store.packets import admit_packet, put_reading

ROOT = Path(__file__).parent.parent / "conformance"
VECTORS = sorted((ROOT / "vectors").glob("*.json"))
INVALID = sorted((ROOT / "invalid").glob("*.json"))

REJECT_CODES = {
    "CANDIDATE_INVALID", "FIELD_UNKNOWN", "NULL_STRING_LITERAL", "TYPE_INVALID", "RANGE_INVALID",
    "UNIT_INVALID", "KEY_INVALID", "NO_EVIDENCE", "SPAN_INVALID", "VALUE_NOT_IN_EVIDENCE",
    "UNIT_NOT_IN_EVIDENCE", "QUOTE_NOT_FOUND", "SOURCE_REJECTED", "DATE_OUT_OF_RANGE",
    "DATE_FORMAT_UNDECLARED", "RECORD_INVALID", "SOURCE_NOT_READ",
    "PASSAGE_NOT_AT_HEADING", "PASSAGE_LABEL_MISMATCH", "PASSAGE_CUT_SHORT", "PASSAGE_OVERRUN",
}  # fmt: skip
FLAG_CODES = {
    "NON_VERBATIM_EVIDENCE", "QUALIFIED_VALUE", "SCALE_WORD", "KEY_NOT_AT_VALUE",
    "LOW_CONFIDENCE", "CONFLICTING_CANDIDATES", "EVIDENCE_REANCHORED", "MODEL_DOUBT",
    "MODEL_CLEARED", "KEY_CITED", "KEY_CITATION_INVALID", "PART_MISSING", "SIGN_CITATION_INVALID",
    "SCALE_CITATION_INVALID", "UNIT_CITATION_INVALID", "FIELD_CITATION_INVALID", "EVIDENCE_QUOTED",
    "EVIDENCE_STATED", "VALUE_DERIVED", "ADMITTED_BY_POLICY", "RELATION_FAILED",
    "COLUMN_NOT_AT_VALUE", "MARKER_OTHER_FIELD", "READ_DOUBT", "SIGN_DROPPED",
    "PASSAGE_NOT_READ",
    "NOT_CORROBORATED", "OTHER_SPAN", "DATE_AMBIGUOUS", "RECORD_NOT_ADMITTED",
}  # fmt: skip
RECORD_CODES = {
    "RECORD_MEMBER_MISSING", "RECORD_MEMBER_CONFLICT", "RECORD_SOURCE_MIXED",
    "SET_REPLACES_NOTHING", "SET_DUPLICATE", "SET_CONFLICT",
}  # fmt: skip


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _extra(v: dict[str, Any]) -> dict[str, Any]:
    """The optional packet members of a vector (SPEC §2.1)."""
    return {
        "references": v.get("references"),
        "document_source": v.get("document_source"),
        "packs": v.get("packs") or (),
        "doubt": v.get("doubt"),
        "completeness": v.get("completeness"),
        "outline": v.get("outline"),
    }


@pytest.mark.parametrize("path", VECTORS, ids=lambda p: p.stem)
def test_vector(path: Path) -> None:
    v = _load(path)
    js = v.get("judgments")
    receipt = gg.admit(
        v["document"], v["schema"], v["candidates"], v["policy"], None, js, **_extra(v)
    ).to_dict()
    by_sha = {d["candidate_sha256"]: d for d in receipt["decisions"]}
    for cand, want in zip(v["candidates"], v["expected"]["decisions"], strict=True):
        got = by_sha[gg.digest("candidate", cand)]
        label = cand.get("id") if isinstance(cand, dict) else repr(cand)
        assert (got["outcome"], got["codes"]) == (want["outcome"], want["codes"]), label
        if "missing" in want:
            assert got["missing"] == want["missing"], label
        if "proposer" in want:
            assert got["proposer"] == want["proposer"], label
        assert ("passage_sha256" in got) == ("passage_sha256" in want), label
        if "passage_sha256" in want:  # SPEC §4.17
            assert got["passage_sha256"] == want["passage_sha256"], label
        if "parts" in want:
            parts = [{"role": x["role"], "passed": x["passed"]} for x in got["parts"]]
            assert parts == want["parts"], label
        if "evidence_units" in want:  # null in a vector: the decision has no member (SPEC §5)
            assert got.get("evidence_units", None) == want["evidence_units"], label
            assert want["evidence_units"] is not None or "evidence_units" not in got, label
    assert receipt["coverage"] == v["expected"]["coverage"]
    assert receipt.get("relations") == v["expected"].get("relations")
    if "records" in v["expected"]:  # SPEC §4.12: the members, replaced, source and ref given
        got_records = receipt["records"]
        assert len(got_records) == len(v["expected"]["records"])
        for got_line, want_line in zip(got_records, v["expected"]["records"], strict=True):
            assert {k: got_line[k] for k in want_line} == want_line, want_line["record"]
    else:
        assert "records" not in receipt
    assert receipt.get("checks") == v["expected"].get("checks")
    assert receipt.get("completeness") == v["expected"].get("completeness")
    assert receipt.get("outline_sha256") == v["expected"].get("outline_sha256")
    args = (v["document"], v["schema"], v["candidates"], v["policy"], js)
    assert gg.verify(receipt, *args, **_extra(v)).ok


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.stem)
def test_invalid_packet(path: Path) -> None:
    v = _load(path)
    with pytest.raises(gg.PacketError):
        gg.admit(
            v["document"], v["schema"], v["candidates"], v["policy"], None, v.get("judgments"),
            **_extra(v),
        )  # fmt: skip


@pytest.mark.parametrize(
    "path", sorted((ROOT / "vectors").glob("export-*.json")), ids=lambda p: p.stem
)
def test_export_vector(path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    v = _load(path)
    source = tmp_path / "source.txt"
    source.write_bytes(v["document"].encode("utf-8"))
    folder = tmp_path / "store"
    with FolderStore(folder) as store:
        reading, _ = put_reading(store, source)
        packet, receipt = admit_packet(
            store,
            v["document"],
            v["schema"],
            v["candidates"],
            v["policy"],
            reading=reading,
            references=v.get("references"),
        )
    assert main(["export", "--store", str(folder), packet]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert main(["verify", "--store", str(folder), exported["packet_sha256"]]) == 0
    assert capsys.readouterr().out == "receipt verified\n"

    saved = receipt.to_dict()
    order = [d["field"] for d in saved["decisions"] if d["outcome"] == "admitted"]
    refs = {r["id"]: r for r in v.get("references", [])}
    expected = []
    for fact in sorted(v["expected"]["export"], key=lambda f: order.index(f["field"])):
        origin = fact["source"]
        source_sha256 = text_sha256 = None
        if origin == "document":
            source_sha256 = store_key("source@1", source.read_bytes())
            text_sha256 = gg.digest("document", {"text": v["document"]})
        elif origin == "reference":
            text_sha256 = gg.digest("reference", {"text": refs[fact["ref"]]["text"]})
        expected.append(
            {k: fact[k] for k in ("field", "key", "value", "unit")}
            | {
                "citation": {
                    "source": origin,
                    "ref": fact.get("ref"),
                    "url": fact.get("url"),
                    "source_sha256": source_sha256,
                    "text_sha256": text_sha256,
                    "span": fact["span"],
                    "receipt_sha256": saved["receipt_sha256"],
                }
            }
        )
    assert exported == {"format": "facts@1", "packet_sha256": packet, "facts": expected}


def test_export_refuses_a_receipt_that_does_not_rederive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    v = _load(ROOT / "vectors" / "export-invoice.json")
    with FolderStore(tmp_path) as store:
        packet, receipt = admit_packet(store, v["document"], v["schema"], v["candidates"])
        body = receipt.to_dict()
        body["decisions"][0]["value"] = "999"
        body.pop("receipt_sha256")
        body["receipt_sha256"] = gg.digest("receipt", body)
        forged = json.loads(store.get("packet@1", packet))
        forged["receipt"] = store.put("receipt@1", gg.jcs(body).encode("utf-8"))
        forged_key = store.put("packet@1", gg.jcs(forged).encode("utf-8"))
    assert main(["export", "--store", str(tmp_path), forged_key]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "differs" in captured.err


def test_description_changes_digest_only() -> None:
    v = _load(ROOT / "vectors" / "21-field-description.json")
    without = {
        "fields": {
            name: {key: value for key, value in field.items() if key != "description"}
            for name, field in v["schema"]["fields"].items()
        }
    }
    described = gg.admit(v["document"], v["schema"], v["candidates"]).to_dict()
    baseline = gg.admit(v["document"], without, v["candidates"]).to_dict()
    assert described["schema_sha256"] == gg.digest(
        "schema", gg.Schema.from_dict(v["schema"]).to_dict()
    )
    for key in ("schema_sha256", "receipt_sha256"):
        assert described.pop(key) != baseline.pop(key)
    assert described == baseline


def test_every_code_has_two_vectors() -> None:
    files: dict[str, set[str]] = defaultdict(set)
    for path in VECTORS:
        v = _load(path)
        for want in v["expected"]["decisions"]:
            for code in want["codes"]:
                files[code].add(path.stem)
        for cov in v["expected"]["coverage"]:
            files[cov["code"]].add(path.stem)
        for line in v["expected"].get("records", []):
            for code in line["codes"]:
                files[code].add(path.stem)
    every = REJECT_CODES | FLAG_CODES | RECORD_CODES | {"REQUIRED_FIELD_MISSING"}
    for code in every:
        assert len(files[code]) >= 2, f"{code} appears in {sorted(files[code])}"
    assert set(files) <= every
