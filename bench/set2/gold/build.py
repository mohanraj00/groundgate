"""Build the set-2 gold drafts (#10) into bench/set2/gold/<id>.json.

A model (Claude) drafts every fact from reading bench/set2/docs, after spec 0.2 was frozen. The
drafts are not ground truth: a person checks each one in the labeling app before it counts.

    uv run python bench/set2/gold/build.py                        # write new gold files
    uv run python bench/set2/gold/build.py --check drafts_fda1.py  # check one file, write nothing

The drafts live in ``drafts_*.py`` next to this file, one or more per kind, so they can be
written in parallel. Each defines ``DRAFTS`` and may define ``FIELDS``, ``UNITS`` and
``DOSE_UNIT``:

- ``FIELDS[doc_id]``: ``{name: (schema, description)}``, the document's own fields. FDA labels
  and NTSB reports get the common fields below, and ``FIELDS`` adds to or overrides them. IRS
  and Federal Register documents have only their own fields.
- ``UNITS[doc_id]``: extra unit surfaces for the document's schema.
- ``DOSE_UNIT[doc_id]``: the unit of an FDA label's common mg fields when it doses in another
  unit, such as ``"mcg"``.
- ``DRAFTS[doc_id]``: one entry per field.
  - ``["7000", context, ...]``: the value and the places that state it.
  - ``[["10", context], ["20", context]]``: a ``multiple`` field, one entry per value.
  - ``{key: ["10", context, ...]}``: a keyed field, at most one value per key.
  - ``[None]``: the document does not state the field.

A context is text copied from the document with the evidence in ``[[...]]``. Spaces match any
whitespace run, and the context must occur exactly once.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
SET = HERE.parent
DOCS = SET / "docs"
SOURCES = SET / "sources.json"


def f(type_: str = "integer", unit: str | None = "USD", comparator: str = "eq", **kw: Any) -> dict:
    return {"type": type_, "unit": unit, "comparator": comparator, "minimum": "0", **kw}


# ------------------------------------------------------------------------- common fields

# SELECTION.md "Fields". Keyed by indication when the label's section 1 has titled subsections.
FDA_FIELDS = {
    "starting_dose": (
        f("number", "mg"),
        "Usual recommended starting dose for adults. If the label gives a range, its lower bound.",
    ),
    "max_daily_dose": (
        f("number", "mg", "le"),
        "Maximum recommended daily dose for adults. Doses that were only studied or used are "
        "not a recommendation.",
    ),
    "pediatric_min_age": (
        f("integer", "years", "ge"),
        "Youngest age, in years, for which section 2 gives pediatric dosing.",
    ),
    "hepatic_starting_dose": (
        f("number", "mg"),
        "Recommended starting dose for adults with hepatic impairment, when the label gives a "
        "number.",
    ),
    "strengths": (
        f("number", "mg", multiple=True),
        "Every tablet or capsule strength listed in section 3 (one extraction per strength).",
    ),
}
FDA_KEYED = {"starting_dose", "max_daily_dose"}
FDA_UNKEYED_SCOPE = " For the first indication in section 2."
FDA_KEYED_SCOPE = " One per indication, with the indication's key."
FDA_UNITS = {"years": {"suffix": ["years", "year", "Years", "Year", "-year"]}}

# the twelve v0.1 fields, unchanged
NTSB_FIELDS = {
    "pilot_age": (f("integer", None), "Age of the pilot in command (the flight instructor on "
                  "instructional flights)."),
    "pilot_total_hours": (f("number", "hours"), "Pilot in command's total flight time, all "
                          "aircraft."),
    "pilot_make_model_hours": (f("number", "hours"), "Pilot in command's total flight time in "
                               "this make and model."),
    "pilot_last_90_days_hours": (f("number", "hours"), "Pilot in command's flight time in the "
                                 "last 90 days, all aircraft."),
    "aircraft_year": (f("integer", None), "Aircraft year of manufacture."),
    "airframe_total_hours": (f("number", "hours"), "Airframe total time."),
    "airport_elevation": (f("integer", "ft"), "Elevation of the airport in the Airport "
                          "Information table (not the weather station's elevation)."),
    "runway_length": (f("integer", "ft"), "Length of the runway used."),
    "visibility": (f("number", "miles"), "Visibility in the weather observation."),
    "wind_speed": (f("integer", "knots"), "Wind speed in the weather observation (not gusts)."),
    "temperature": (f("number", "C", minimum=None), "Temperature in the weather observation "
                    "(not dew point), in degrees Celsius."),
    "altimeter_setting": (f("number", "inHg"), "Altimeter setting, in inches of mercury."),
}  # fmt: skip
NTSB_UNITS = {
    "hours": {"suffix": ["hours", "hour", "Hrs", "hrs"]},
    "ft": {"suffix": ["ft", "feet", "-ft", "-foot"]},
    "miles": {"suffix": ["miles", "mile"]},
    "knots": {"suffix": ["knots", "knot", "kts"]},
    "C": {"suffix": ["°C", "° C"]},
    "inHg": {"suffix": ["inches Hg", "in Hg", "inHg"]},
}
IRS_UNITS = {"cents": {"suffix": ["cents"]}}


# --------------------------------------------------------------------------------- builder

_NUMBER = re.compile(r"[-\u2212]?\d[\d,]*(?:\.\d+)?")
_SCALE = re.compile(r"\s{0,2}(thousand|million|billion|trillion)\b", re.I)
_EXP = {"thousand": 3, "million": 6, "billion": 9, "trillion": 12}


def stated(value: str, quote: str) -> bool:
    """Whether ``quote`` writes ``value``, as written or scaled ("$1.2 million")."""
    want = Decimal(value.replace(",", ""))
    for m in _NUMBER.finditer(quote):
        try:
            got = Decimal(m.group().replace(",", "").replace("\u2212", "-"))
        except InvalidOperation:  # pragma: no cover - the regex admits only decimals
            continue
        scale = _SCALE.match(quote, m.end())
        if got == want or (scale and got.scaleb(_EXP[scale.group(1).lower()]) == want):
            return True
    return False


def locate(text: str, context: str) -> tuple[dict[str, int], str]:
    """Byte span and text of the [[...]] part of a context that occurs exactly once."""
    pre, rest = context.split("[[", 1)
    mid, post = rest.split("]]", 1)
    ws = r"\s+"
    pieces = [re.escape(p) for p in pre.split()]
    pat = (ws.join(pieces) + (ws if pre[-1:].isspace() else "")) if pieces else ""
    pat += "(" + ws.join(re.escape(p) for p in mid.split()) + ")"
    if post.strip():
        pat += (ws if post[:1].isspace() else "") + ws.join(re.escape(p) for p in post.split())
    hits = list(re.finditer(pat, text))
    if len(hits) != 1:
        raise ValueError(f"context matches {len(hits)} times: {context!r}")
    s, e = hits[0].span(1)
    return {"start": len(text[:s].encode()), "end": len(text[:e].encode())}, text[s:e]


def load_drafts(paths: list[Path]) -> tuple[dict, dict, dict, dict]:
    drafts: dict[str, Any] = {}
    fields: dict[str, Any] = {}
    units: dict[str, Any] = {}
    dose_unit: dict[str, Any] = {}
    sys.path.insert(0, str(HERE))  # drafts import f from here
    for path in paths:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        parts = (("DRAFTS", drafts), ("FIELDS", fields), ("UNITS", units), ("DOSE_UNIT", dose_unit))
        for name, target in parts:
            part = getattr(mod, name, {})
            if overlap := set(part) & set(target):
                raise SystemExit(f"{path.name}: {name} repeats {sorted(overlap)}")
            target.update(part)
    return drafts, fields, units, dose_unit


def schema_for(src: dict, own: dict, own_units: dict, dose_unit: str) -> tuple[dict, dict]:
    kind = src["kind"]
    if kind == "fda":
        keys = src.get("keys") or []
        table = {}
        for name, (schema, desc) in FDA_FIELDS.items():
            if name in FDA_KEYED:
                if keys:
                    schema, desc = {**schema, "keys": keys}, desc + FDA_KEYED_SCOPE
                else:
                    desc += FDA_UNKEYED_SCOPE
            if schema["unit"] == "mg":
                schema = {**schema, "unit": dose_unit}
            table[name] = (schema, desc)
        units = dict(FDA_UNITS)
    elif kind == "ntsb":
        table, units = dict(NTSB_FIELDS), dict(NTSB_UNITS)
    else:
        table, units = {}, dict(IRS_UNITS)
    table.update(own)
    units.update(own_units)
    return table, units


def build(
    src: dict, draft: dict, own: dict, own_units: dict, dose_unit: str, errors: list[str]
) -> dict:
    doc_id = src["id"]
    text = (DOCS / f"{doc_id}.txt").read_text(encoding="utf-8")
    table, units = schema_for(src, own, own_units, dose_unit)
    fields = {}
    for name, (schema, desc) in table.items():
        schema = {k: v for k, v in schema.items() if v is not None or k == "unit"}
        fields[name] = {"schema": schema, "description": desc}
    if missing := set(fields) - set(draft):
        errors.append(f"{doc_id}: no draft for {sorted(missing)}")
    facts: list[dict] = []
    absent = {}
    for name, spec in draft.items():
        if name not in fields:
            errors.append(f"{doc_id}: draft for unknown field {name}")
            continue
        schema = fields[name]["schema"]
        if spec == [None]:
            absent[name] = "draft"
            continue
        if schema.get("keys"):
            if not isinstance(spec, dict):
                errors.append(f"{doc_id}: {name} is keyed; give {{key: [value, context]}}")
                continue
            entries = [(key, entry) for key, entry in spec.items()]
        elif isinstance(spec, dict):
            errors.append(f"{doc_id}: {name} has no keys")
            continue
        else:
            entries = [(None, e) for e in (spec if schema.get("multiple") else [spec])]
        for key, entry in entries:
            if key is not None and key not in schema["keys"]:
                errors.append(f"{doc_id}: {name} key {key!r} is not in the key list")
                continue
            value, *contexts = entry
            if not isinstance(value, str) or not contexts:
                errors.append(f"{doc_id}: {name} needs a string value and a context")
                continue
            evidence = []
            for c in contexts:
                try:
                    span, quote = locate(text, c)
                except ValueError as e:
                    errors.append(f"{doc_id}: {e}")
                    continue
                if not stated(value, quote):
                    errors.append(f"{doc_id}: {name} {value} is not written in [[{quote}]]")
                evidence.append(span)
            fact = {"id": f"f{len(facts) + 1}", "field": name}
            if key is not None:
                fact["key"] = key
            facts.append({**fact, "value": value, "unit": schema["unit"], "evidence": evidence,
                          "status": "draft"})  # fmt: skip
    return {"doc": doc_id, "kind": src["kind"], "groups": src["groups"], "fields": fields,
            "units": units, "facts": facts, "absent": absent, "excluded": {},
            "prelabeled_by": "Claude (model draft)", "checked": None}  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", type=Path, help="check one drafts file and write nothing")
    args = ap.parse_args()
    paths = [HERE / args.check.name] if args.check else sorted(HERE.glob("drafts_*.py"))
    sources = {s["id"]: s for s in json.loads(SOURCES.read_text(encoding="utf-8"))["sources"]}
    drafts, own_fields, own_units, dose_unit = load_drafts(paths)
    errors = [f"{d}: not a set-2 document" for d in drafts if d not in sources]
    built = {
        d: build(
            sources[d],
            drafts[d],
            own_fields.get(d, {}),
            own_units.get(d, {}),
            dose_unit.get(d, "mg"),
            errors,
        )
        for d in drafts
        if d in sources
    }
    if errors:
        raise SystemExit("\n".join(errors))
    if args.check:
        facts = sum(len(g["facts"]) for g in built.values())
        print(f"{len(built)} documents valid: {facts} facts, "
              f"{sum(len(g['absent']) for g in built.values())} absent fields")  # fmt: skip
        return
    wrote = 0
    for doc_id, gold in built.items():
        path = HERE / f"{doc_id}.json"
        if path.exists():
            continue  # never overwrite labels a person may have edited
        path.write_text(json.dumps(gold, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        wrote += 1
    left = sorted(set(sources) - set(drafts))
    print(f"{len(built)} drafts valid; wrote {wrote} new gold files; {len(left)} not drafted yet")


if __name__ == "__main__":
    sys.exit(main())
