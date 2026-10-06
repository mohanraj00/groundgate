"""Can a typed-decision model clear the QUALIFIED_VALUE flags that spec 0.3 raises (#67)? Asks
one fixed question about each labeled value of the relations set, and scores the answers against
the labels and the qualifiers that spec 0.3 finds. The plan is on #67.

    uv run python bench/judges/relations/judge.py split    # split.json, before any model run
    TYPESAFE_API_KEY=... uv run python bench/judges/relations/judge.py run jev
    JEFF_MODEL="..." uv run python bench/judges/relations/judge.py run jeff
    uv run python bench/judges/relations/judge.py report   # REPORT.md, report.json
    uv run python bench/judges/relations/judge.py report --check

This is the key judge (bench/judges/keys/judge.py) with its own gold, question and report. The
question was written once, before the first run, and is not tuned on these values.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
BENCH = HERE.parent.parent
sys.path[:0] = [str(HERE.parent / "keys"), str(BENCH / "relations")]

import judge as kj  # noqa: E402  (bench/judges/keys/judge.py)

RELATIONS = {
    "eq": "exactly this value",
    "le": "at most this value: up to, no more than, a maximum",
    "lt": "less than this value: below, under",
    "ge": "at least this value: no less than, a minimum",
    "gt": "more than this value: over, above, exceeds",
    "approx": "about this value: approximately, around",
    "range": "one end of a range: from this value to another, or between two values",
}
ENGINES = {"jev": "Jev", "jeff": "Jeff"}


def gold() -> list[dict[str, Any]]:
    """Each labeled value of the relations set, with its label and the comparators of the
    qualifiers that spec 0.3 finds at it. Values labeled not sure or not a fact are left out."""
    from groundgate.text import qualifiers, tokens

    labels = json.loads((BENCH / "relations" / "labels.json").read_text())
    texts: dict[str, str] = {}
    out = []
    for it in json.loads((BENCH / "relations" / "items.json").read_text()):
        if labels[it["id"]] not in RELATIONS:
            continue
        if it["doc"] not in texts:
            path = BENCH / "relations" / "docs" / f"{it['doc']}.txt"
            texts[it["doc"]] = path.read_text(encoding="utf-8")
        text = texts[it["doc"]]
        (tok,) = [t for t in tokens(text) if [t.start, t.end] == it["span"]]
        out.append(
            {
                "id": it["id"],
                "set": "relations",
                "doc": it["doc"],
                "span": it["span"],
                "label": labels[it["id"]],
                "spec_0.3": sorted(qualifiers(text, tok)),
            }
        )
    return out


def question() -> dict[str, Any]:
    return {
        "relation": {
            "type": "choice",
            "instructions": (
                "The text is from the dosage section of a drug label and marks one number in "
                "brackets. What does the text say about that number?"
            ),
            "criteria": dict(RELATIONS),
        }
    }


def prompt(it: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return kj.state(it), question()


def clear(it: dict[str, Any], a: dict[str, Any], t: float, c: str) -> str | None:
    """What the answer does at threshold t for a field with comparator c. Spec 0.3 flags the
    value when its qualifiers hold another comparator. The answer clears that flag when it is c
    with confidence t or more: "right" when the label is c, "escape" when it is not."""
    if not set(it["spec_0.3"]) - {c} or a["choice"] != c or a["confidence"] < t:
        return None
    return "right" if it["label"] == c else "escape"


def score(items: list[dict[str, Any]], answers: dict[str, Any]) -> dict[str, Any]:
    """Accuracy, calibration and clears for one engine, by part and by comparator."""
    out: dict[str, Any] = {}
    for p in ("calibration", "test"):
        rows = [(it, answers[it["id"]]) for it in items if it["part"] == p]
        by_label = {
            r: {
                "values": sum(it["label"] == r for it, _ in rows),
                "correct": sum(it["label"] == r == a["choice"] for it, a in rows),
            }
            for r in RELATIONS
        }
        calibration = {}
        for t in kj.THRESHOLDS:
            sure = [(it, a) for it, a in rows if a["confidence"] >= t]
            calibration[str(t)] = {
                "answered": len(sure),
                "correct": sum(it["label"] == a["choice"] for it, a in sure),
            }
        clears: dict[str, Any] = {}
        for c in RELATIONS:
            right = sum(bool(set(it["spec_0.3"]) - {c}) and it["label"] == c for it, _ in rows)
            by_t = {}
            for t in kj.THRESHOLDS:
                done = [clear(it, a, t, c) for it, a in rows]
                k, n = done.count("escape"), done.count("right") + done.count("escape")
                by_t[str(t)] = {
                    "clears_right": done.count("right"),
                    "escapes": k,
                    "escape_rate_upper_95": kj.upper_95(k, n),
                }
            clears[c] = {"right_flags": right, "by_threshold": by_t}
        out[p] = {
            "values": len(rows),
            "correct": sum(it["label"] == a["choice"] for it, a in rows),
            "by_label": by_label,
            "by_threshold": calibration,
            "clears": clears,
        }
    # for each comparator and ceiling, the lowest threshold whose calibration bound is below the
    # ceiling (hybrid design §9), and the test part at that threshold
    out["by_ceiling"] = {}
    for c in RELATIONS:
        cal = out["calibration"]["clears"][c]["by_threshold"]
        for ceiling in kj.CEILINGS:
            ok = [t for t in kj.THRESHOLDS if cal[str(t)]["escape_rate_upper_95"] < ceiling]
            t = min(ok) if ok else None
            out["by_ceiling"][f"{c} {ceiling}"] = {
                "threshold": t,
                "test": out["test"]["clears"][c]["by_threshold"][str(t)] if t is not None else None,
            }
    return out


def report(check: bool) -> None:
    items = gold()
    digest = kj.prompts_sha256(items)
    parts = json.loads((HERE / "split.json").read_text())
    for it in items:
        it["part"] = parts[it["id"]]
    names = ("calibration", "test")
    results: dict[str, Any] = {
        "values": {p: sum(it["part"] == p for it in items) for p in names},
        "labels": {p: len({it["doc"] for it in items if it["part"] == p}) for p in names},
        "spec_holds_the_label": {
            p: sum(it["label"] in it["spec_0.3"] for it in items if it["part"] == p) for p in names
        },
        "engines": {},
    }
    md = [
        "# Clearing qualifier flags with a typed-decision model",
        "",
        "Generated by `bench/judges/relations/judge.py report` from `split.json` and the "
        "`answers-*.json` files. The plan is on #67. The gold is the labeled values of the "
        "relations set, split by label into a calibration part and a test part.",
        "",
        f"Calibration: {results['values']['calibration']} values in "
        f"{results['labels']['calibration']} labels. Test: {results['values']['test']} values "
        f"in {results['labels']['test']} labels. The comparators that spec 0.3 finds hold the "
        f"labeled relation for {results['spec_holds_the_label']['calibration']} calibration "
        f"values and {results['spec_holds_the_label']['test']} test values.",
        "",
        "| Label | " + " | ".join(RELATIONS) + " |",
        "|---|" + "---:|" * len(RELATIONS),
    ]
    for p in names:
        n = [sum(it["label"] == r and it["part"] == p for it in items) for r in RELATIONS]
        md.append(f"| {p.capitalize()} | " + " | ".join(map(str, n)) + " |")
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
                f"**{p.capitalize()} part.** {r['correct']} of {r['values']} answers match the "
                "label.",
                "",
                "| Label | " + " | ".join(RELATIONS) + " |",
                "|---|" + "---:|" * len(RELATIONS),
                "| Values | "
                + " | ".join(str(r["by_label"][x]["values"]) for x in RELATIONS)
                + " |",
                "| Correct | "
                + " | ".join(str(r["by_label"][x]["correct"]) for x in RELATIONS)
                + " |",
                "",
                "| Confidence at least | " + " | ".join(map(str, kj.THRESHOLDS)) + " |",
                "|---|" + "---:|" * len(kj.THRESHOLDS),
                "| Answered | "
                + " | ".join(str(r["by_threshold"][str(t)]["answered"]) for t in kj.THRESHOLDS)
                + " |",
                "| Correct | "
                + " | ".join(str(r["by_threshold"][str(t)]["correct"]) for t in kj.THRESHOLDS)
                + " |",
                "",
            ]
        md += [
            "**Clears.** For a field with comparator c, the right flags are the values labeled c "
            "that spec 0.3 flags. For each ceiling, the lowest threshold whose 95% upper bound "
            "of the escape rate on the calibration part is below it, and the test part at that "
            "threshold. A comparator with no threshold at any ceiling is not in the table.",
            "",
            "| c | Right flags, calibration | Right flags, test | Ceiling | Threshold "
            "| Test: right cleared | Test: escapes | Test: bound |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        none = []
        for c in RELATIONS:
            rows = [(x, s["by_ceiling"][f"{c} {x}"]) for x in kj.CEILINGS]
            rows = [(x, b) for x, b in rows if b["threshold"] is not None]
            if not rows:
                none.append(f"`{c}`")
            for x, b in rows:
                md.append(
                    f"| {c} | {s['calibration']['clears'][c]['right_flags']} "
                    f"| {s['test']['clears'][c]['right_flags']} | {x} | {b['threshold']} "
                    f"| {b['test']['clears_right']} | {b['test']['escapes']} "
                    f"| {b['test']['escape_rate_upper_95']} |"
                )
        md += ["", f"No threshold at any ceiling: {', '.join(none) or 'none'}."]
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


kj.HERE, kj.gold, kj.prompt, kj.ENGINES = HERE, gold, prompt, ENGINES


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("split")
    p = sub.add_parser("run")
    p.add_argument("engine", choices=sorted(ENGINES))
    p.add_argument("--repeat", type=int, default=1, help="the number of this run, 2 or more")
    p = sub.add_parser("report")
    p.add_argument("--check", action="store_true", help="fail if the committed files differ")
    args = ap.parse_args()
    if args.cmd == "split":
        kj.split()
    elif args.cmd == "run":
        kj.run(args.engine, args.repeat)
    else:
        report(args.check)


if __name__ == "__main__":
    main()
