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
    "UNIT_INVALID", "NO_EVIDENCE", "SPAN_INVALID", "VALUE_NOT_IN_EVIDENCE", "UNIT_NOT_IN_EVIDENCE",
}  # fmt: skip
FLAG_CODES = {
    "NON_VERBATIM_EVIDENCE", "QUALIFIED_VALUE", "SCALE_WORD", "LOW_CONFIDENCE",
    "CONFLICTING_CANDIDATES", "EVIDENCE_REANCHORED",
}  # fmt: skip


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.mark.parametrize("path", VECTORS, ids=lambda p: p.stem)
def test_vector(path: Path) -> None:
    v = _load(path)
    receipt = gg.admit(v["document"], v["schema"], v["candidates"], v["policy"]).to_dict()
    by_sha = {d["candidate_sha256"]: d for d in receipt["decisions"]}
    for cand, want in zip(v["candidates"], v["expected"]["decisions"], strict=True):
        got = by_sha[gg.digest("candidate", cand)]
        label = cand.get("id") if isinstance(cand, dict) else repr(cand)
        assert (got["outcome"], got["codes"]) == (want["outcome"], want["codes"]), label
    assert receipt["coverage"] == v["expected"]["coverage"]
    assert gg.verify(receipt, v["document"], v["schema"], v["candidates"], v["policy"]).ok


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.stem)
def test_invalid_packet(path: Path) -> None:
    v = _load(path)
    with pytest.raises(gg.PacketError):
        gg.admit(v["document"], v["schema"], v["candidates"], v["policy"])


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
