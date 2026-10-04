"""Can a typed-decision model sort the change-or-range reviews (#65)? Asks one fixed question
about each labeled pair, twice, and compares the answers with the labels and spec 0.3.

    LAYA_REVISION=7b928d828b7b0e022f929d9bd2e44165aa270148 \\
    uv run --isolated --no-project --python 3.12 --with laya==0.3.26 \\
        python bench/patterns/triage.py run laya         # local, on the CPU
    TYPESAFE_API_KEY=... uv run python bench/patterns/triage.py run jev   # TypeSafe API
    uv run python bench/patterns/triage.py recheck       # recheck.json: pairs to label again
    uv run python bench/patterns/pairs.py label --recheck  # blind: no first label, no answer
    uv run python bench/patterns/triage.py recheck --apply  # the new labels replace the first
    uv run python bench/patterns/triage.py report        # TRIAGE.md from triage-*.json

This is a bench experiment. The core never calls a model. The question was written once, before
the first run, and is not tuned on these pairs: they are the test.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import urllib.request
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
THRESHOLDS = (0.5, 0.7, 0.8, 0.9, 0.95, 0.99)
CHOICES = ("change", "range", "neither")
LAYA_MODEL = "english"
JEV_MODEL = "jev-1.13.0"
JEV_URL = "https://api.typesafe.ai/v1/systemone"
ENGINES = {"laya": "Laya", "jev": "Jev"}
RECHECK_SEED = 65

Ask = Callable[[str, dict[str, Any]], dict[str, Any]]


def state(text: str, p: dict[str, Any]) -> str:
    """What the label tool showed: up to 300 code points before X and 200 after Y, with X and Y
    in brackets instead of bold."""
    (x0, x1), (y0, y1) = p["x"], p["y"]
    a, b = max(0, x0 - 300), min(len(text), y1 + 200)
    parts = [text[a:x0], f"[{text[x0:x1]}]", text[x1:y0], f"[{text[y0:y1]}]", text[y1:b]]
    return " ".join("".join(parts).split())


def question(x: str, y: str) -> dict[str, Any]:
    return {
        "pair": {
            "type": "choice",
            "instructions": (
                f"The text marks two numbers in brackets, [{x}] and [{y}], in a phrase like "
                f"'from {x} to {y}'. Is {y} the new value that replaces {x}, the end of a range "
                f"that starts at {x}, or neither?"
            ),
            "criteria": {
                "change": f"a change: one quantity was {x} and is now {y}",
                "range": (
                    f"a range: {x} and {y} are the two ends of a span, and any value between "
                    "them applies"
                ),
                "neither": (
                    f"neither: {x} and {y} are not two values of one quantity, such as a form "
                    "number, a phone number, or the minutes of one clock time and the hour of "
                    "another"
                ),
            },
        }
    }


def laya_engine(meta: dict[str, Any]) -> Ask:
    import laya
    from laya import Router

    revision = os.environ.get("LAYA_REVISION")
    if not revision:
        raise SystemExit("set LAYA_REVISION to the checkpoint commit, as the docstring shows")
    router = Router(device="cpu")
    meta.update(
        engine=f"Laya {laya.__version__}",
        model=f"convaiinnovations/laya at {revision}, on the CPU",
    )

    def ask(st: str, qs: dict[str, Any]) -> dict[str, Any]:
        a = router.predict(st, qs, model=LAYA_MODEL)["answers"]["pair"]
        return {
            "choice": a["choice"],
            "confidence": a["answer_confidence"],
            "p": a["probabilities"],
        }

    return ask


def jev_engine(meta: dict[str, Any]) -> Ask:
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise SystemExit("set TYPESAFE_API_KEY")
    meta.update(engine="Jev (TypeSafe API)", model=JEV_MODEL)

    def ask(st: str, qs: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"state": st, "model": JEV_MODEL, "questions": qs}).encode()
        req = urllib.request.Request(
            JEV_URL,
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.load(r)
        if res["model"] != JEV_MODEL:
            raise SystemExit(f"answered by {res['model']}, not {JEV_MODEL}")
        a = res["answers"]["pair"]
        return {"choice": a["choice"], "confidence": a["confidence"], "p": a["probabilities"]}

    return ask


def run(engine: str) -> None:
    pairs = json.loads((HERE / "pairs.json").read_text())
    texts = {
        p["doc"]: (HERE / "docs" / f"{p['doc']}.txt").read_text(encoding="utf-8") for p in pairs
    }
    meta: dict[str, Any] = {}
    answers: list[dict[str, Any]] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ask = (laya_engine if engine == "laya" else jev_engine)(meta)
        for _ in range(2):
            out = {}
            for p in pairs:
                text = texts[p["doc"]]
                x, y = text[p["x"][0] : p["x"][1]], text[p["y"][0] : p["y"][1]]
                out[p["id"]] = ask(state(text, p), question(x, y))
            answers.append(out)
    first, second = answers
    meta.update(
        same_on_rerun=first == second,
        choices_changed_on_rerun=sum(first[k]["choice"] != second[k]["choice"] for k in first),
        largest_confidence_change_on_rerun=round(
            max(abs(first[k]["confidence"] - second[k]["confidence"]) for k in first), 4
        ),
        warnings=sorted({str(w.message) for w in caught if w.category is RuntimeWarning}),
        question=question("X", "Y"),
    )
    path = HERE / f"triage-{engine}.json"
    path.write_text(json.dumps({"meta": meta, "answers": answers[0]}, indent=1) + "\n")
    print(f"wrote {path.name}")


def section(engine: str, rows: list[dict[str, Any]], meta: dict[str, Any]) -> list[str]:
    name = ENGINES[engine]
    md = [
        f"## {name}",
        "",
        f"{meta['engine']}, model `{meta['model']}`. Same answers on a second run: "
        f"{'yes' if meta['same_on_rerun'] else 'no'}.",
    ]
    if not meta["same_on_rerun"]:
        md[-1] += (
            f" On the second run {meta['choices_changed_on_rerun']} choices changed, and the "
            f"largest change in confidence was {meta['largest_confidence_change_on_rerun']}. "
            "The tables use the first run."
        )
    if meta["warnings"]:
        md += ["", f"{name} warned:", ""] + [f"- {w}" for w in meta["warnings"]]
    md += [
        "",
        "| Label | " + " | ".join(f"{name}: {c}" for c in CHOICES) + " |",
        "|---|" + "---:|" * len(CHOICES),
    ]
    for lab in CHOICES:
        row = [sum(r["label"] == lab and r[engine] == c for r in rows) for c in CHOICES]
        md.append(f"| {lab} | " + " | ".join(str(n) for n in row) + " |")
    right = sum(r["label"] == r[engine] for r in rows)
    md += ["", f"{right} of {len(rows)} answers match the label."]
    review = [r for r in rows if r["spec_0.3"] == "range"]
    changes = sum(r["label"] == "change" for r in review)
    md += [
        "",
        f"As a review aid, on the {len(review)} Y values that spec 0.3 sends to review "
        f"({changes} of them changes):",
        "",
        "| Threshold | Changes marked (right) | Other pairs marked (wrong) |",
        "|---:|---:|---:|",
    ]
    for t in THRESHOLDS:
        marked = [r for r in review if r[engine] == "change" and r[f"{engine}_c"] >= t]
        ok = sum(r["label"] == "change" for r in marked)
        md.append(f"| {t} | {ok} of {changes} | {len(marked) - ok} |")
    wrong = [
        r
        for r in review
        if r[engine] == "change" and r["label"] != "change" and r[f"{engine}_c"] >= 0.9
    ]
    md += ["", "Marked as a change with confidence 0.9 or more, but labeled otherwise:", ""]
    if not wrong:
        md.append("None.")
    else:
        md += ["| Pair | Label | Confidence |", "|---|---|---:|"]
        md += [f"| `{r['id']}` | {r['label']} | {r[f'{engine}_c']:.3f} |" for r in wrong]
    return md


def report(check: bool) -> None:
    pairs = json.loads((HERE / "pairs.json").read_text())
    labels = json.loads((HERE / "labels.json").read_text())
    read = {r["id"]: r for r in json.loads((HERE / "results.json").read_text())["pairs_read"]}
    rows = [{**p, "label": labels[p["id"]], "spec_0.3": read[p["id"]]["spec_0.3"]} for p in pairs]
    md = [
        "# Pattern set: typed-decision models on the change-or-range question",
        "",
        "Generated by `bench/patterns/triage.py report` (#65). A bench experiment: the core never "
        "calls a model. The labels and the spec 0.3 readings come from "
        "[RESULTS.md](RESULTS.md). Each model gets the text the label tool showed, with X and Y "
        "in brackets, and one Choice question: change, range or neither. The question was "
        "written once, before the first run, and these pairs are the test, so it was not tuned "
        "on them. It is in each `triage-*.json`.",
        "",
        'A review aid would mark a Y that spec 0.3 sends to review as "likely a change" when '
        "the model says change with at least the threshold confidence. It is right when the "
        "label is change, and wrong otherwise.",
    ]
    for engine in ENGINES:
        path = HERE / f"triage-{engine}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for r in rows:
            a = data["answers"][r["id"]]
            r[engine], r[f"{engine}_c"] = a["choice"], a["confidence"]
        md += ["", *section(engine, rows, data["meta"])]
    body = "\n".join(md) + "\n"
    out = HERE / "TRIAGE.md"
    if check:
        if not out.exists() or out.read_text() != body:
            raise SystemExit("TRIAGE.md is out of date; run triage.py report")
        print("TRIAGE.md is up to date")
        return
    out.write_text(body)
    print("wrote TRIAGE.md")


def recheck(apply: bool) -> None:
    """recheck.json: the pairs where Jev's first run and the label differ, and as many pairs
    where they agree, drawn with a fixed seed, in a shuffled order. With ``apply``, the labels
    from recheck-labels.json replace the first ones, and recheck.json records each change."""
    path = HERE / "recheck.json"
    labels = json.loads((HERE / "labels.json").read_text())
    if apply:
        rc = json.loads(path.read_text())
        new = json.loads((HERE / "recheck-labels.json").read_text())
        if set(new) != set(rc["ids"]):
            raise SystemExit("recheck-labels.json does not cover every pair in recheck.json")
        rc["changes"] = [
            {"id": i, "before": labels[i], "after": new[i]}
            for i in rc["ids"]
            if labels[i] != new[i]
        ]
        for c in rc["changes"]:
            labels[c["id"]] = c["after"]
        path.write_text(json.dumps(rc, indent=1) + "\n")
        (HERE / "labels.json").write_text(json.dumps(dict(sorted(labels.items())), indent=1) + "\n")
        print(f"{len(rc['changes'])} labels changed")
        return
    jev = json.loads((HERE / "triage-jev.json").read_text())["answers"]
    differ = sorted(i for i, a in jev.items() if a["choice"] != labels[i])
    agree = sorted(i for i, a in jev.items() if a["choice"] == labels[i])
    rng = random.Random(RECHECK_SEED)
    ids = differ + rng.sample(agree, len(differ))
    rng.shuffle(ids)
    rc = {"seed": RECHECK_SEED, "disagree": differ, "ids": ids}
    path.write_text(json.dumps(rc, indent=1) + "\n")
    print(f"wrote recheck.json: {len(ids)} pairs, {len(differ)} where Jev and the label differ")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("engine", choices=list(ENGINES))
    p = sub.add_parser("recheck")
    p.add_argument("--apply", action="store_true", help="apply recheck-labels.json")
    p = sub.add_parser("report")
    p.add_argument("--check", action="store_true", help="fail if TRIAGE.md differs")
    args = ap.parse_args()
    if args.cmd == "run":
        run(args.engine)
    elif args.cmd == "recheck":
        recheck(args.apply)
    else:
        report(args.check)


if __name__ == "__main__":
    main()
