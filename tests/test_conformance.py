"""Run every conformance vector (SPEC §3) against the reference implementation."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg

ROOT = Path(__file__).parent.parent / "conformance"
VECTORS = sorted((ROOT / "vectors").glob("*.json"))
INVALID = sorted((ROOT / "invalid").glob("*.json"))

REJECT_CODES = {
    "CANDIDATE_INVALID", "FIELD_UNKNOWN", "NULL_STRING_LITERAL", "TYPE_INVALID", "RANGE_INVALID",
    "UNIT_INVALID", "KEY_INVALID", "NO_EVIDENCE", "SPAN_INVALID", "VALUE_NOT_IN_EVIDENCE",
    "UNIT_NOT_IN_EVIDENCE", "QUOTE_NOT_FOUND", "SOURCE_REJECTED",
}  # fmt: skip
FLAG_CODES = {
    "NON_VERBATIM_EVIDENCE", "QUALIFIED_VALUE", "SCALE_WORD", "KEY_NOT_AT_VALUE",
    "LOW_CONFIDENCE", "CONFLICTING_CANDIDATES", "EVIDENCE_REANCHORED", "MODEL_DOUBT",
    "MODEL_CLEARED", "KEY_CITED", "KEY_CITATION_INVALID", "PART_MISSING", "SIGN_CITATION_INVALID",
    "SCALE_CITATION_INVALID", "UNIT_CITATION_INVALID", "FIELD_CITATION_INVALID", "EVIDENCE_QUOTED",
    "EVIDENCE_STATED", "VALUE_DERIVED", "ADMITTED_BY_POLICY",
}  # fmt: skip


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _extra(v: dict[str, Any]) -> dict[str, Any]:
    """The optional packet members of a vector (SPEC §2.1)."""
    return {"references": v.get("references"), "document_source": v.get("document_source")}


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
    assert receipt["coverage"] == v["expected"]["coverage"]
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
    for code in REJECT_CODES | FLAG_CODES | {"REQUIRED_FIELD_MISSING"}:
        assert len(files[code]) >= 2, f"{code} appears in {sorted(files[code])}"
    assert set(files) <= REJECT_CODES | FLAG_CODES | {"REQUIRED_FIELD_MISSING"}
