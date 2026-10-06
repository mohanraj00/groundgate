"""Can a typed-decision model choose the right value when spec 0.3 admits more than one (#67)?
Asks one choice for each labeled field of the conflicts set at which spec 0.3 admits two values
or more, and scores the answers against the labels. The plan is on #67.

    uv run python bench/judges/conflicts/judge.py split    # split.json, before any model run
    TYPESAFE_API_KEY=... uv run python bench/judges/conflicts/judge.py run jev
    uv run python bench/judges/conflicts/judge.py report   # REPORT.md, report.json
    uv run python bench/judges/conflicts/judge.py report --check

This is the key judge (bench/judges/keys/judge.py) with its own gold, question and report. The
question was written once, before the first run, and is not tuned on these labels.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
BENCH = HERE.parent.parent
sys.path[:0] = [str(HERE.parent / "keys"), str(BENCH / "conflicts")]

import judge as kj  # noqa: E402  (bench/judges/keys/judge.py)
from conflicts import FIELDS  # noqa: E402  (bench/conflicts/conflicts.py)

ENGINES = {"jev": "Jev"}
NONE = "none"
# the unit of a dose: right after it, or after the range or list that it starts
UNIT = re.compile(r"(?:mg|mcg)(?![A-Za-z])")


def value(text: str, span: list[int]) -> str:
    """The canonical value of the number token at span: "1,000" and "1000.0" are "1000"."""
    v = Decimal(text[span[0] : span[1]].replace(",", "")).normalize()
    return format(v, "f")


def candidate(text: str, span: list[int], field: str) -> dict[str, Any]:
    """The dose as an extraction of the field: the number, in mg, with evidence from the number
    to the end of its unit, in UTF-8 bytes."""
    a, b = span
    m = UNIT.search(text, b)
    if m is None:
        raise SystemExit(f"no unit after the dose at {a}")

    def byte(i: int) -> int:
        return len(text[:i].encode())

    return {
        "field": field,
        "value": text[a:b],
        "unit": "mg",
        "evidence": {"start": byte(a), "end": byte(m.end())},
    }


def admitted(text: str, doses: list[dict[str, Any]], field: str) -> list[str]:
    """The values, in order of first dose, that spec 0.3 admits for the field when each dose is
    decided alone."""
    from groundgate import admit

    schema = {"fields": {field: FIELDS[field]["schema"]}, "units": {}}
    out: list[str] = []
    for it in doses:
        (decision,) = admit(text, schema, [candidate(text, it["span"], field)]).decisions
        v = value(text, it["span"])
        if decision.outcome == "admitted" and v not in out:
            out.append(v)
    return out


def gold() -> list[dict[str, Any]]:
    """Each labeled field of the conflicts set at which spec 0.3 admits two values or more, with
    the labeled value (None when the text states none) and those values. Fields labeled not sure
    are left out."""
    labels = json.loads((BENCH / "conflicts" / "labels.json").read_text())
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for it in json.loads((BENCH / "conflicts" / "items.json").read_text()):
        by_doc.setdefault(it["doc"], []).append(it)
    spans = {it["id"]: it["span"] for doses in by_doc.values() for it in doses}
    out = []
    for doc, doses in by_doc.items():
        text = (BENCH / "conflicts" / "docs" / f"{doc}.txt").read_text(encoding="utf-8")
        for field in FIELDS:
            label = labels[f"{doc}|{field}"]
            if label is None:
                continue
            values = admitted(text, doses, field)
            if len(values) < 2:
                continue
            out.append(
                {
                    "id": f"{doc}|{field}",
                    "set": "conflicts",
                    "doc": doc,
                    "field": field,
                    "label": None if label == NONE else value(text, spans[label]),
                    "spec_0.3": values,
                }
            )
    return out


def question(field: str, values: list[str]) -> dict[str, Any]:
    criteria: dict[str, str] = {f"{v} mg": f"the dose of {v} mg" for v in values}
    criteria[NONE] = "the text states none of these doses as this value"
    return {
        "value": {
            "type": "choice",
            "instructions": (
                "The text is sections 2 and 3 of a drug label. Which dose does the text state "
                "as this value? " + FIELDS[field]["description"]
            ),
            "criteria": criteria,
        }
    }


def prompt(it: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    path = BENCH / "conflicts" / "docs" / f"{it['doc']}.txt"
    return path.read_text(encoding="utf-8"), question(it["field"], it["spec_0.3"])


def chosen(a: dict[str, Any]) -> str | None:
    """The value an answer chooses, or None for "none"."""
    c = str(a["choice"])
    return c.removesuffix(" mg") if c != NONE else None


def clear(it: dict[str, Any], a: dict[str, Any], t: float) -> str | None:
    """What the answer does to the conflict at threshold t: it admits the value it chooses when
    its confidence is t or more. "right" when that is the labeled value, "escape" when it is not,
    and None when it admits nothing."""
    v = chosen(a)
    if v is None or a["confidence"] < t:
        return None
    return "right" if v == it["label"] else "escape"


def correct(it: dict[str, Any], a: dict[str, Any]) -> bool:
    """The answer is the labeled value, or none when no admitted value is the labeled one."""
    right = it["label"] if it["label"] in it["spec_0.3"] else None
    return chosen(a) == right


def score(items: list[dict[str, Any]], answers: dict[str, Any]) -> dict[str, Any]:
    """Accuracy, calibration and clears for one engine, by part."""
    out: dict[str, Any] = {}
    for p in ("calibration", "test"):
        rows = [(it, answers[it["id"]]) for it in items if it["part"] == p]
        by_t = {}
        for t in kj.THRESHOLDS:
            done = [clear(it, a, t) for it, a in rows]
            sure = [(it, a) for it, a in rows if a["confidence"] >= t]
            k, n = done.count("escape"), done.count("right") + done.count("escape")
            by_t[str(t)] = {
                "answered": len(sure),
                "answered_correct": sum(correct(it, a) for it, a in sure),
                "clears_right": done.count("right"),
                "escapes": k,
                "escape_rate_upper_95": kj.upper_95(k, n),
            }
        out[p] = {
            "conflicts": len(rows),
            "correct": sum(correct(it, a) for it, a in rows),
            "with_the_right_value": sum(it["label"] in it["spec_0.3"] for it, _ in rows),
            "by_threshold": by_t,
        }
    # for each ceiling, the lowest threshold whose calibration bound is below it (§9)
    out["by_ceiling"] = {}
    for c in kj.CEILINGS:
        cal = out["calibration"]["by_threshold"]
        ok = [t for t in kj.THRESHOLDS if cal[str(t)]["escape_rate_upper_95"] < c]
        t = min(ok) if ok else None
        out["by_ceiling"][str(c)] = {
            "threshold": t,
            "test": out["test"]["by_threshold"][str(t)] if t is not None else None,
        }
    return out


def report(check: bool) -> None:
    items = gold()
    digest = kj.prompts_sha256(items)
    parts = json.loads((HERE / "split.json").read_text())
    for it in items:
        it["part"] = parts[it["id"]]
    names = ("calibration", "test")

    def count(p: str, test: Any) -> int:
        return sum(1 for it in items if it["part"] == p and test(it))

    results: dict[str, Any] = {
        "conflicts": {p: count(p, lambda it: True) for p in names},
        "labels": {p: len({it["doc"] for it in items if it["part"] == p}) for p in names},
        "with_the_right_value": {
            p: count(p, lambda it: it["label"] in it["spec_0.3"]) for p in names
        },
        "labeled_none": {p: count(p, lambda it: it["label"] is None) for p in names},
        "engines": {},
    }
    md = [
        "# Choosing among conflicting values with a typed-decision model",
        "",
        "Generated by `bench/judges/conflicts/judge.py report` from `split.json` and the "
        "`answers-*.json` files. The plan is on #67. The gold is the labeled fields of the "
        "conflicts set at which spec 0.3 admits two values or more, split by label into a "
        "calibration part and a test part. A model clears a conflict when it chooses a value "
        "with confidence t or more. The clear is right when the value is the labeled one, and "
        "an escape when it is not.",
        "",
        "| Part | Conflicts | Labels | The labeled value is a candidate | Labeled none |",
        "|---|---:|---:|---:|---:|",
    ]
    for p in names:
        md.append(
            f"| {p.capitalize()} | {results['conflicts'][p]} | {results['labels'][p]} "
            f"| {results['with_the_right_value'][p]} | {results['labeled_none'][p]} |"
        )
    for engine, name in ENGINES.items():
        path = HERE / f"answers-{engine}.json"
        if not path.exists():
            continue
        run_ = json.loads(path.read_text())
        if run_["meta"].get("prompts_sha256") != digest:
            raise SystemExit(f"{path.name} answers other prompts than the gold; run it again")
        s = score(items, run_["answers"])
        results["engines"][engine] = {"meta": run_["meta"], **s}
        m = run_["meta"]
        md += ["", f"## {name}", "", f"{m['engine']}, {m['model']}, run {m['run']}.", ""]
        for p in names:
            r = s[p]
            md += [
                f"**{p.capitalize()} part.** {r['correct']} of {r['conflicts']} answers are "
                "right: the labeled value, or none when no candidate is the labeled value.",
                "",
                "| Confidence at least | Answered | Right | Conflicts cleared, right | Escapes |",
                "|---:|---:|---:|---:|---:|",
            ]
            for t in kj.THRESHOLDS:
                b = r["by_threshold"][str(t)]
                md.append(
                    f"| {t} | {b['answered']} | {b['answered_correct']} | {b['clears_right']} "
                    f"| {b['escapes']} |"
                )
            md.append("")
        md += [
            "**Thresholds.** For each ceiling on the escape rate among cleared conflicts, the "
            "lowest threshold whose 95% upper bound on the calibration part is below it, and the "
            "test part at that threshold.",
            "",
            "| Ceiling | Threshold | Test: cleared right | Test: escapes | Test: bound |",
            "|---:|---:|---:|---:|---:|",
        ]
        for c in kj.CEILINGS:
            b = s["by_ceiling"][str(c)]
            if b["threshold"] is None:
                md.append(f"| {c} | none | 0 | 0 | |")
            else:
                t_ = b["test"]
                md.append(
                    f"| {c} | {b['threshold']} | {t_['clears_right']} | {t_['escapes']} "
                    f"| {t_['escape_rate_upper_95']} |"
                )
    out = {
        HERE / "report.json": json.dumps(results, indent=1, sort_keys=True) + "\n",
        HERE / "REPORT.md": "\n".join(md) + "\n",
    }
    if check:
        stale = [p.name for p, body in out.items() if not p.exists() or p.read_text() != body]
        if stale:
            raise SystemExit(f"out of date: {', '.join(stale)}; run judge.py report")
        print("REPORT.md is up to date")
        return
    for path, body in out.items():
        path.write_text(body)
    print("wrote REPORT.md, report.json")


def main() -> None:
    # the key judge runs and splits with this judge's files, gold and prompts
    kj.HERE, kj.gold, kj.prompt, kj.ENGINES = HERE, gold, prompt, ENGINES
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("split")
    p = sub.add_parser("run")
    p.add_argument("engine", choices=sorted(ENGINES))
    p = sub.add_parser("report")
    p.add_argument("--check", action="store_true", help="fail if the committed files differ")
    args = ap.parse_args()
    if args.cmd == "split":
        kj.split()
    elif args.cmd == "run":
        kj.run(args.engine)
    else:
        report(args.check)


if __name__ == "__main__":
    main()
