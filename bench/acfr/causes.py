"""Why most proposals on bench/acfr are not admitted (#244): for each proposal that the 0.8 draft
does not admit, the part that fails or is missing, and why. The plan is on #244.

    uv run python bench/acfr/causes.py causes             # causes/causes.json
    uv run python bench/acfr/causes.py web                # blind labels, http://127.0.0.1:8779
    uv run python bench/acfr/causes.py results [--check]  # causes/results.json, RESULTS.md

causes decides the replies of run.py again in process, under the groundgate that runs it. A script
finds each cause from the decision's parts, the candidate and the text, never a person. A proposal
can have more than one cause, so it can count once for each.

- key item, field has no keys: the candidate has a key item, and its field has no keys, so the
  item cannot hold a key mention of the candidate's key (SPEC 4.6).
- key item fails: the candidate has a key item that fails, on a field with keys.
- field item, no alias: the field item holds no mention of an alias of the field.
- field item, another line: a line break stands between the field item and the value.
- field item, other: the field item fails for another reason.
- unit item fails: the candidate has a unit item that fails.
- unit missing, no unit form on the page: the value's page (from the page break before it to the
  page break after it) holds no form of the field's unit.
- unit missing, a unit form above the value: the page holds a form of the unit before the value,
  but not at a unit place of the value (SPEC 4.6).
- unit missing, a unit form only below the value: the page holds forms of the unit only after
  the value, as on a total row at the foot of the statement.

web labels each fact of a proposal that has no label in bench/acfr/labels.json yet, with the page
of measure.py: the same ids, so a fact has one label.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
OUT = HERE / "causes"
sys.path.insert(0, str(HERE))
import measure  # noqa: E402  (bench/acfr/measure.py)


def _str(text: str, span: tuple[int, int]) -> tuple[int, int]:
    """A UTF-8 byte span as a code point span."""
    raw = text.encode("utf-8")
    return len(raw[: span[0]].decode()), len(raw[: span[1]].decode())


def _forms(unit: str) -> re.Pattern[str]:
    """The forms of a currency unit, each as a whole (SPEC 4.3)."""
    from groundgate.text import _CURRENCY

    prefixes, suffixes = _CURRENCY[unit]
    words = [re.escape(x) for x in (*prefixes, *suffixes)]
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(words) + r")(?![A-Za-z0-9])")


def field_cause(text: str, part: Any, pos: int, aliases: tuple[str, ...]) -> str:
    from groundgate.text import key_mentions

    if part.span is None:
        return "field item, other"
    a, b = _str(text, part.span)
    if not any(a <= x and y <= b for x, y, _ in key_mentions(text, aliases)):
        return "field item, no alias"
    if b <= pos and "\n" in text[b:pos]:
        return "field item, another line"
    return "field item, other"


def unit_cause(text: str, pos: int, unit: str) -> str:
    start = text.rfind("\f", 0, pos) + 1
    end = text.find("\f", pos)
    page = text[start : len(text) if end < 0 else end]
    forms = _forms(unit)
    if forms.search(text, start, pos) is not None:
        return "unit missing, a unit form above the value"
    if forms.search(page) is not None:
        return "unit missing, a unit form only below the value"
    return "unit missing, no unit form on the page"


def _proposals(
    runs: tuple[str, ...] = measure.RUNS, docs: Path = HERE / "docs"
) -> list[tuple[str, str, str, dict[str, Any], Any]]:
    """Each proposal of each run, with its decision under the groundgate that runs this."""
    import groundgate as gg

    schema = measure._read(HERE / "schema.json")
    out = []
    for run in runs:
        for doc_path in sorted(docs.glob("*.txt")):
            doc = doc_path.stem
            reply = measure._read(HERE / "runs" / run / f"{doc}.json")["reply"]
            cands = [] if reply is None else reply["candidates"]
            cands = [{"id": f"c{i}", **c} for i, c in enumerate(cands)]
            text = doc_path.read_text(encoding="utf-8")
            by_sha = {d.candidate_sha256: d for d in gg.admit(text, schema, cands).decisions}
            for c in cands:
                out.append((run, doc, text, c, by_sha[gg.digest("candidate", c)]))
    return out


def causes() -> None:
    from groundgate.canonical import SPEC_VERSION

    if SPEC_VERSION != "0.8":
        raise SystemExit(f"these causes are decided with the 0.8 draft, not {SPEC_VERSION}")
    schema = measure._read(HERE / "schema.json")
    out = []
    for run, doc, text, c, d in _proposals():
        row: dict[str, Any] = {"run": run, "doc": doc, "id": c["id"], "field": d.field}
        row["outcome"] = d.outcome
        row["fact"] = None if d.value is None else measure.item_id(doc, d.field, d.key, d.value)
        found: list[str] = []
        if d.outcome != "admitted" and d.evidence is not None:
            f = schema["fields"][d.field]
            pos = _str(text, d.evidence)[0]
            failed = {p.role: p for p in d.parts if not p.passed}
            if "key" in failed:
                found.append("key item, field has no keys" if "keys" not in f else "key item fails")
            if "field" in failed:
                found.append(field_cause(text, failed["field"], pos, tuple(f.get("aliases", ()))))
            if "unit" in failed:
                found.append("unit item fails")
            if "unit" in d.missing:
                found.append(unit_cause(text, pos, f["unit"]))
            found += [f"other: {code}" for code in d.codes if code == "VALUE_NOT_IN_EVIDENCE"]
        elif d.outcome != "admitted":
            found.append("other: no evidence")
        row["causes"] = found
        out.append(row)
    OUT.mkdir(exist_ok=True)
    measure._dump(OUT / "causes.json", out)
    print(f"wrote {len(out)} proposals")


def facts() -> dict[str, dict[str, Any]]:
    """Each fact of a proposal under the 0.8 draft that has no label yet, once."""
    given = measure.labels()
    out: dict[str, dict[str, Any]] = {}
    for _, doc, _, _, d in _proposals():
        if d.value is None:
            continue
        fid = measure.item_id(doc, d.field, d.key, d.value)
        if fid in given or (fid in out and out[fid]["evidence"] is not None):
            continue
        evidence = None if d.evidence is None else list(d.evidence)
        out[fid] = {"field": d.field, "key": d.key, "value": d.value, "evidence": evidence}
        out[fid]["doc"] = doc
    return out


def score() -> dict[str, Any]:
    """For each run: the outcomes, the right values admitted and the escapes, and the proposals
    that are not admitted by cause, with how many of them hold a value that a label calls right."""
    given = measure.labels()
    rows = measure._read(OUT / "causes.json")
    res: dict[str, Any] = {"runs": {}, "causes": {}}
    for run in measure.RUNS:
        mine = [r for r in rows if r["run"] == run]
        count = collections.Counter(r["outcome"] for r in mine)
        admitted = {r["fact"] for r in mine if r["outcome"] == "admitted"}
        verdicts = collections.Counter(
            given.get(f, {}).get("verdict", "unlabeled") for f in admitted
        )
        res["runs"][run] = {
            "proposals": len(mine),
            "admitted": count["admitted"],
            "right admitted": verdicts["right"],
            "escapes": verdicts["wrong"],
            "admitted not sure or unlabeled": verdicts["not sure"] + verdicts["unlabeled"],
            "not admitted": len(mine) - count["admitted"],
            "not admitted, right": sum(
                given.get(r["fact"], {}).get("verdict") == "right"
                for r in mine
                if r["outcome"] != "admitted"
            ),
        }
    by: dict[str, dict[str, collections.Counter[str]]] = {}
    for r in rows:
        for cause in r["causes"]:
            c = by.setdefault(cause, {}).setdefault(r["run"], collections.Counter())
            c["proposals"] += 1
            c["right"] += given.get(r["fact"], {}).get("verdict") == "right"
            c["only cause"] += len(r["causes"]) == 1
    res["causes"] = {
        cause: {run: dict(sorted(c.items())) for run, c in sorted(runs.items())}
        for cause, runs in sorted(by.items())
    }
    return res


def render(res: dict[str, Any]) -> str:
    runs = measure.RUNS
    out = [
        "# Why most proposals on bench/acfr are not admitted (#244)",
        "",
        "Generated by `bench/acfr/causes.py results` from `results.json`. Do not edit.",
        "",
        "The replies of `run.py`, decided again under the 0.8 draft. A script finds the cause of "
        "each proposal that is not admitted from the decision's parts; the causes are defined in "
        "`causes.py`. A value counts once per document, field, key and value. An escape is a "
        "wrong value that a decision admits.",
        "",
        "| Run | Proposals | Admitted | Right admitted | Escapes | Admitted, not sure or "
        "not labeled | Not admitted | Not admitted, right |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run in runs:
        c = res["runs"][run]
        out.append(
            f"| {run} | {c['proposals']} | {c['admitted']} | {c['right admitted']} | "
            f"{c['escapes']} | {c['admitted not sure or unlabeled']} | {c['not admitted']} | "
            f"{c['not admitted, right']} |"
        )
    out += [
        "",
        "Each cell is the proposals that are not admitted with the cause, then in brackets those "
        "whose value a label calls right, then those that have no other cause.",
        "",
        "| Cause | " + " | ".join(runs) + " |",
        "|---|" + "---:|" * len(runs),
    ]
    for cause, by in res["causes"].items():
        cells = [
            f"{by[r]['proposals']} ({by[r]['right']}, {by[r]['only cause']} only)"
            if r in by
            else "0"
            for r in runs
        ]
        out.append(f"| {cause} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def results(check: bool) -> None:
    res = score()
    body = json.dumps(res, indent=1) + "\n"
    md = render(res) + "\n"
    if check:
        old = (OUT / "results.json").read_text(), (OUT / "RESULTS.md").read_text()
        same = old == (body, md)
        print("results are up to date" if same else "out of date: run results")
        sys.exit(0 if same else 1)
    (OUT / "results.json").write_text(body)
    (OUT / "RESULTS.md").write_text(md)
    print(md)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("causes")
    sub.add_parser("web")
    r = sub.add_parser("results")
    r.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.cmd == "causes":
        causes()
    elif args.cmd == "web":
        measure.facts = facts  # the page of measure.py, with the facts that have no label
        measure.serve(measure.PORT)
    else:
        results(args.check)


if __name__ == "__main__":
    main()
