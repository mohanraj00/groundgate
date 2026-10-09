"""extractor_schema() against steps 1, 2, 6 and 7 of SPEC §3, on every vector's schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate.cli import main

VECTORS = sorted((Path(__file__).parent.parent / "conformance" / "vectors").glob("*.json"))

# the subset of JSON Schema that the strict structured-output modes take
KEYWORDS = {
    "type", "properties", "required", "additionalProperties", "items", "const", "enum", "anyOf",
    "$defs", "$ref", "description",
}  # fmt: skip
BEFORE_STEP_8 = {
    "CANDIDATE_INVALID", "FIELD_UNKNOWN", "NULL_STRING_LITERAL", "TYPE_INVALID", "RANGE_INVALID",
    "UNIT_INVALID", "KEY_INVALID",
}  # fmt: skip


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _ids(v: dict[str, Any]) -> list[str] | None:
    refs = v.get("references")
    return [r["id"] for r in refs] if refs else None


def _validator(schema: dict[str, Any]) -> Any:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _keywords(node: object, out: set[str]) -> set[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(k)
            if k in ("properties", "$defs"):
                for sub in v.values():
                    _keywords(sub, out)
            elif k not in ("const", "enum", "required", "description"):
                _keywords(v, out)
    elif isinstance(node, list):
        for sub in node:
            _keywords(sub, out)
    return out


def _value(f: gg.Field) -> str:
    if f.type == "string":
        return "x"
    return str(f.minimum if f.minimum is not None else f.maximum if f.maximum is not None else 1)


def _samples(f: gg.Field, ids: list[str] | None) -> list[dict[str, Any]]:
    """Candidates for one field, one for each item kind and one with every kind."""
    items: list[dict[str, Any]] = [{"source": "document", "role": "value", "text": "1"}]
    if ids:
        items.append({"source": "reference", "ref": ids[0], "role": "sign", "text": "("})
    items.append(
        {"source": "external", "url": "https://a.test/", "retrieved": "2026-10-07", "text": "1"}
    )
    items.append({"source": "knowledge", "text": "It is 1."})
    head = {
        "field": f.name,
        "value": _value(f),
        "unit": f.unit,
        "key": f.keys[0] if f.keys else None,
    }
    return [{**head, "evidence": [it]} for it in items] + [{**head, "evidence": items}]


@pytest.mark.parametrize("path", VECTORS, ids=lambda p: p.stem)
def test_only_strict_keywords(path: Path) -> None:
    v = _load(path)
    s = gg.extractor_schema(v["schema"], _ids(v))
    _validator(s)
    assert _keywords(s, set()) <= KEYWORDS


@pytest.mark.parametrize("path", VECTORS, ids=lambda p: p.stem)
def test_accepted_candidates_pass_steps_1_to_7(path: Path) -> None:
    v = _load(path)
    check = _validator(gg.extractor_schema(v["schema"], _ids(v)))
    schema = gg.Schema.from_dict(v["schema"])
    cands = [c for f in schema.fields.values() for c in _samples(f, _ids(v))]
    assert check.is_valid({"candidates": cands})
    receipt = gg.admit(
        v["document"], v["schema"], cands, v["policy"], references=v.get("references")
    )
    for d in receipt.to_dict()["decisions"]:
        assert not BEFORE_STEP_8 & set(d["codes"]), d


@pytest.mark.parametrize("path", VECTORS, ids=lambda p: p.stem)
def test_rejected_candidates_fail(path: Path) -> None:
    v = _load(path)
    check = _validator(gg.extractor_schema(v["schema"], _ids(v)))
    for cand, want in zip(v["candidates"], v["expected"]["decisions"], strict=True):
        if {"CANDIDATE_INVALID", "FIELD_UNKNOWN", "UNIT_INVALID", "KEY_INVALID"} & set(
            want["codes"]
        ):
            assert not check.is_valid({"candidates": [cand]}), cand


def test_reference_ids() -> None:
    schema = {"fields": {"fee": {"type": "number", "unit": "USD"}}}
    assert "reference" not in gg.extractor_schema(schema)["$defs"]
    s = gg.extractor_schema(schema, ["tax-table"])
    assert s["$defs"]["reference"]["properties"]["ref"] == {"enum": ["tax-table"]}
    for bad in ([], ["a", "a"], [" "], [[]], [{}]):
        with pytest.raises(gg.PacketError):
            gg.extractor_schema(schema, bad)


def test_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = {"fields": {"fee": {"type": "number", "unit": "USD"}}}
    (tmp_path / "s.json").write_text(json.dumps(schema), encoding="utf-8")
    (tmp_path / "r.json").write_text(json.dumps([{"id": "t", "text": "x"}]), encoding="utf-8")
    assert main(["schema", str(tmp_path / "s.json"), "--references", str(tmp_path / "r.json")]) == 0
    assert json.loads(capsys.readouterr().out) == gg.extractor_schema(schema, ["t"])
    (tmp_path / "r.json").write_text('{"id": "t"}', encoding="utf-8")
    assert main(["schema", str(tmp_path / "s.json"), "--references", str(tmp_path / "r.json")]) == 2


def test_guide_example() -> None:
    doc = (
        "CONSOLIDATED STATEMENTS OF OPERATIONS\n(in thousands)\n\n\t2025\t2024\n"
        "Revenue\t$ 412,300\t$ 388,950\nLoss from operations\t(12,040)\t(9,775)\n"
    )
    schema = {
        "fields": {
            "operating_income": {
                "type": "number",
                "unit": "USD",
                "keys": ["2025", "2024"],
                "aliases": ["Income from operations", "Loss from operations"],
            }
        }
    }

    def cand(value: str, quote: str, key: str) -> dict[str, Any]:
        parts = [("value", quote), ("scale", "(in thousands)"), ("unit", "$")]
        parts += [("field", "Loss from operations"), ("key", key)]
        return {
            "field": "operating_income",
            "value": value,
            "unit": "USD",
            "key": key,
            "evidence": [{"source": "document", "role": r, "text": q} for r, q in parts],
        }

    out = {
        "candidates": [cand("-12040000", "(12,040)", "2025"), cand("-9775000", "(9,775)", "2024")]
    }
    assert _validator(gg.extractor_schema(schema)).is_valid(out)
    for d in gg.admit(doc, schema, out["candidates"]).decisions:
        assert (d.outcome, list(d.codes)) == ("admitted", ["VALUE_DERIVED", "KEY_CITED"])


def test_field_descriptions_and_aliases() -> None:
    description = " \nThe fee in dollars.\t "
    schema = {
        "fields": {
            "plain": {},
            "described": {"description": description},
            "aliased": {"aliases": ["late fee", "filing fee"]},
            "both": {"description": description, "aliases": ["late fee", "filing fee"]},
        }
    }
    parsed = gg.Schema.from_dict(schema)
    generated = gg.extractor_schema(parsed)
    assert generated == gg.extractor_schema(schema)
    shapes = generated["properties"]["candidates"]["items"]["anyOf"]
    descriptions = {s["properties"]["field"]["const"]: s.get("description") for s in shapes}
    names = "Names in the document: late fee, filing fee."
    assert descriptions == {
        "plain": None,
        "described": description,
        "aliased": names,
        "both": description + "\n" + names,
    }


def test_edge_schemas() -> None:
    with pytest.raises(gg.PacketError):
        gg.extractor_schema({"fields": {}})
    s = gg.extractor_schema({"fields": {"ratio": {"type": "number", "unit": ""}}})
    assert s["properties"]["candidates"]["items"]["properties"]["unit"] == {"const": ""}
