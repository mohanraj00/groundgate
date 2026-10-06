"""Can a typed-decision model find a dose that spec 0.3 admits as the wrong field (#67)? Asks
one yes-or-no question for each field that spec 0.3 admits at a labeled dose of the fields set,
and scores the answers against the labels. The plan is on #67.

    uv run python bench/judges/fields/judge.py split    # split.json, before any model run
    TYPESAFE_API_KEY=... uv run python bench/judges/fields/judge.py run jev
    uv run python bench/judges/fields/judge.py report   # REPORT.md, report.json
    uv run python bench/judges/fields/judge.py report --check

This is the key judge (bench/judges/keys/judge.py) with its own gold, question and report. The
question was written once, before the first run, and is not tuned on these doses.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
BENCH = HERE.parent.parent
sys.path[:0] = [str(HERE.parent / "keys"), str(BENCH / "fields"), str(BENCH / "keys")]

import judge as kj  # noqa: E402  (bench/judges/keys/judge.py)
from fields import FIELDS  # noqa: E402  (bench/fields/fields.py)

ENGINES = {"jev": "Jev"}
# a pair is doubted when the model gives it a probability below t
THRESHOLDS = (0.01, 0.05, 0.1, 0.2, 0.3, 0.5)
UNIT = re.compile(r"\s*(mg|mcg)\b")


def candidate(text: str, span: list[int], field: str) -> dict[str, Any]:
    """The dose as an extraction of the field: the number, in mg, with the number and its unit
    as evidence, in UTF-8 bytes."""
    a, b = span
    m = UNIT.match(text, b)
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


def admitted(text: str, span: list[int]) -> list[str]:
    """The fields that spec 0.3 admits the dose as, each decided alone."""
    from groundgate import admit

    out = []
    for f, d in FIELDS.items():
        schema = {"fields": {f: d["schema"]}, "units": {}}
        (decision,) = admit(text, schema, [candidate(text, span, f)]).decisions
        if decision.outcome == "admitted":
            out.append(f)
    return out


def gold() -> list[dict[str, Any]]:
    """Each labeled dose of the fields set at which spec 0.3 admits one field or more, with its
    label and those fields. Doses labeled not sure are left out."""
    labels = json.loads((BENCH / "fields" / "labels.json").read_text())
    texts: dict[str, str] = {}
    out = []
    for it in json.loads((BENCH / "fields" / "items.json").read_text()):
        if labels[it["id"]] is None:
            continue
        if it["doc"] not in texts:
            path = BENCH / "fields" / "docs" / f"{it['doc']}.txt"
            texts[it["doc"]] = path.read_text(encoding="utf-8")
        fields = admitted(texts[it["doc"]], it["span"])
        if fields:
            out.append(
                {
                    "id": it["id"],
                    "set": "fields",
                    "doc": it["doc"],
                    "span": it["span"],
                    "label": labels[it["id"]],
                    "spec_0.3": fields,
                }
            )
    return out


def question(fields: list[str]) -> dict[str, Any]:
    return {
        f: {
            "type": "noul",
            "instructions": (
                "The text is from sections 2 and 3 of a drug label and marks one dose in "
                "brackets. Does the text state that dose as this value? " + FIELDS[f]["description"]
            ),
        }
        for f in fields
    }


def prompt(it: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return kj.state(it), question(it["spec_0.3"])


def keep(answers: dict[str, Any]) -> dict[str, Any]:
    """The probability that the model gives each field."""
    return {f: round(a["noul"], 4) for f, a in sorted(answers.items())}


def pairs(items: list[dict[str, Any]], answers: dict[str, Any]) -> list[tuple[bool, float]]:
    """(right, probability) for each admitted field of each dose. A pair is right when the
    label holds the field."""
    out = []
    for it in items:
        got = answers[it["id"]]
        if sorted(got) != sorted(it["spec_0.3"]):
            raise SystemExit(f"{it['id']}: the answers are for {sorted(got)}")
        out += [(f in it["label"], got[f]) for f in it["spec_0.3"]]
    return out


def score(items: list[dict[str, Any]], answers: dict[str, Any]) -> dict[str, Any]:
    """For each part: the pairs, how many wrong pairs each threshold catches and how many right
    pairs it doubts, and the right share in bins of probability."""
    out: dict[str, Any] = {}
    for p in ("calibration", "test"):
        rows = pairs([it for it in items if it["part"] == p], answers)
        right = sum(r for r, _ in rows)
        by_t = {}
        for t in THRESHOLDS:
            caught = sum(not r and q < t for r, q in rows)
            doubted = sum(r and q < t for r, q in rows)
            by_t[str(t)] = {
                "wrong_caught": caught,
                "right_doubted": doubted,
                "right_doubted_upper_95": kj.upper_95(doubted, right),
            }
        edges = (0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.01)
        bins = []
        for lo, hi in itertools.pairwise(edges):
            inside = [r for r, q in rows if lo <= q < hi]
            bins.append({"from": lo, "to": min(hi, 1), "pairs": len(inside), "right": sum(inside)})
        out[p] = {
            "pairs": len(rows),
            "right": right,
            "wrong": len(rows) - right,
            "by_threshold": by_t,
            "bins": bins,
        }
    # for each ceiling on the share of right pairs doubted, the highest threshold whose 95%
    # upper bound on the calibration part is below it (hybrid design §9), and the test part there
    out["by_ceiling"] = {}
    for c in kj.CEILINGS:
        cal = out["calibration"]["by_threshold"]
        ok = [t for t in THRESHOLDS if cal[str(t)]["right_doubted_upper_95"] < c]
        t = max(ok) if ok else None
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
    pairs_in = {
        p: [(f in it["label"]) for it in items if it["part"] == p for f in it["spec_0.3"]]
        for p in names
    }
    results: dict[str, Any] = {
        "doses": {p: sum(it["part"] == p for it in items) for p in names},
        "labels": {p: len({it["doc"] for it in items if it["part"] == p}) for p in names},
        "pairs": {p: len(pairs_in[p]) for p in names},
        "right_pairs": {p: sum(pairs_in[p]) for p in names},
        "engines": {},
    }
    md = [
        "# Finding wrong fields with a typed-decision model",
        "",
        "Generated by `bench/judges/fields/judge.py report` from `split.json` and the "
        "`answers-*.json` files. The plan is on #67. The gold is the labeled doses of the "
        "fields set at which spec 0.3 admits a field, split by label into a calibration part "
        "and a test part. A pair is a dose and a field that spec 0.3 admits it as. It is right "
        "when the label holds the field, and wrong when it does not.",
        "",
        "| Part | Doses | Labels | Pairs | Right pairs | Wrong pairs |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for p in names:
        n, r = results["pairs"][p], results["right_pairs"][p]
        md.append(
            f"| {p.capitalize()} | {results['doses'][p]} | {results['labels'][p]} | {n} | {r} "
            f"| {n - r} |"
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
                f"**{p.capitalize()} part.** The model doubts a pair when it gives the pair a "
                f"probability below the threshold. {r['wrong']} wrong pairs and {r['right']} "
                "right pairs.",
                "",
                "| Doubt below | " + " | ".join(map(str, THRESHOLDS)) + " |",
                "|---|" + "---:|" * len(THRESHOLDS),
                "| Wrong pairs caught | "
                + " | ".join(str(r["by_threshold"][str(t)]["wrong_caught"]) for t in THRESHOLDS)
                + " |",
                "| Right pairs doubted | "
                + " | ".join(str(r["by_threshold"][str(t)]["right_doubted"]) for t in THRESHOLDS)
                + " |",
                "",
                "| Probability | "
                + " | ".join(f"{b['from']} to {b['to']}" for b in r["bins"])
                + " |",
                "|---|" + "---:|" * len(r["bins"]),
                "| Pairs | " + " | ".join(str(b["pairs"]) for b in r["bins"]) + " |",
                "| Right | " + " | ".join(str(b["right"]) for b in r["bins"]) + " |",
                "",
            ]
        md += [
            "**Thresholds.** For each ceiling on the share of right pairs doubted, the highest "
            "threshold whose 95% upper bound on the calibration part is below it, and the test "
            "part at that threshold.",
            "",
            "| Ceiling | Threshold | Test: wrong caught | Test: right doubted | Test: bound |",
            "|---:|---:|---:|---:|---:|",
        ]
        for c in kj.CEILINGS:
            b = s["by_ceiling"][str(c)]
            if b["threshold"] is None:
                md.append(f"| {c} | none | 0 | 0 | |")
            else:
                t_ = b["test"]
                md.append(
                    f"| {c} | {b['threshold']} | {t_['wrong_caught']} | {t_['right_doubted']} "
                    f"| {t_['right_doubted_upper_95']} |"
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
    # the key judge runs and splits with this judge's files, gold, prompts and answers
    kj.HERE, kj.gold, kj.prompt, kj.keep, kj.ENGINES = HERE, gold, prompt, keep, ENGINES
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
