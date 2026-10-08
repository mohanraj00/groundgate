"""candidate.schema.json against step 1 of SPEC §3, on every conformance vector."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate.canonical import SPEC_VERSION

VECTORS = sorted((Path(__file__).parent.parent / "conformance" / "vectors").glob("*.json"))

# step 1 rules that the schema does not express (its description lists them)
NOT_IN_SCHEMA = {
    ("05-non-ascii", "n5"),  # an offset written 2.0: JSON Schema counts it as an integer
    ("19-evidence-list", "bad5"),  # two items with the role value
    ("19-evidence-list", "bad9"),  # a ref that names no reference in the packet
}


def _validator() -> Any:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(gg.candidate_schema())
    return jsonschema.Draft202012Validator(gg.candidate_schema())


def test_schema_ships_with_the_package() -> None:
    s = gg.candidate_schema()
    assert s["required"] == ["field", "value"]
    assert s["title"].endswith(f"spec {SPEC_VERSION}")


@pytest.mark.parametrize("path", VECTORS, ids=lambda p: p.stem)
def test_schema_agrees_with_step_1(path: Path) -> None:
    v = json.loads(path.read_text(encoding="utf-8"))
    check = _validator()
    for cand, want in zip(v["candidates"], v["expected"]["decisions"], strict=True):
        label = cand.get("id") if isinstance(cand, dict) else repr(cand)
        step_1 = "CANDIDATE_INVALID" not in want["codes"] or (path.stem, label) in NOT_IN_SCHEMA
        assert check.is_valid(cand) == step_1, label


def test_every_exception_is_used() -> None:
    seen = set()
    for path in VECTORS:
        for cand in json.loads(path.read_text(encoding="utf-8"))["candidates"]:
            if isinstance(cand, dict):
                seen.add((path.stem, cand.get("id")))
    assert seen >= NOT_IN_SCHEMA
