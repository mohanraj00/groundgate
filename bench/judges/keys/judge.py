"""Can a typed-decision model clear the KEY_NOT_AT_VALUE flags that spec 0.3 raises (#67)? Asks
one fixed question about each labeled dose of the keys and tables sets, and scores the answers
against the labels and the spec 0.3 readings. The plan is on #67.

    uv run python bench/judges/keys/judge.py split       # split.json, before any model run
    TYPESAFE_API_KEY=... uv run python bench/judges/keys/judge.py run jev      # TypeSafe API
    JEFF_MODEL="..." uv run python bench/judges/keys/judge.py run jeff   # a local jeff-serve
    LAYA_REVISION=7b928d828b7b0e022f929d9bd2e44165aa270148 \\
    uv run --isolated --no-project --python 3.12 --with laya==0.3.26 \\
        python bench/judges/keys/judge.py run laya       # local, on the CPU
    uv run python bench/judges/keys/judge.py report      # REPORT.md, report.json
    uv run python bench/judges/keys/judge.py report --check

This is a bench experiment. The core never calls a model. The question was written once, before
the first run, and is not tuned on these doses.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
BENCH = HERE.parent.parent
SETS = ("keys", "tables")
THRESHOLDS = (0.5, 0.7, 0.8, 0.9, 0.95, 0.99)
# a user sets the ceiling on the escape rate among cleared flags (docs/design/hybrid-decisions.md
# §9), so the report shows three
CEILINGS = (0.05, 0.1, 0.2)
LAYA_MODEL = "english"
JEV_MODEL = "jev-1.13.0"
JEV_URL = "https://api.typesafe.ai/v1/systemone"
ENGINES = {"jev": "Jev", "jeff": "Jeff", "laya": "Laya"}
JEFF_URL = os.environ.get("JEFF_URL", "http://localhost:8790/v1/systemone")
NONE = "none"
# doses whose label changed after a model answered them: a model-led change can't score a model
# in either direction, so these doses are left out of the gold (README)
RELABELED_AFTER_A_RUN = {"keys:fda-lansoprazole:801"}

Ask = Callable[[str, dict[str, Any]], dict[str, Any]]


def load(name: str, file: str) -> Any:
    return json.loads((BENCH / name / file).read_text())


def gold() -> list[dict[str, Any]]:
    """Each labeled dose of the keys and tables sets, with its label, its label's keys and the
    keys that spec 0.3 puts at it. Doses labeled not sure are left out."""
    out = []
    for name in SETS:
        keys = {s["id"]: s["keys"] for s in load(name, "sources.json")["sources"]}
        labels = load(name, "labels.json")
        read = {r["id"]: r["spec_0.3"] for r in load(name, "results.json")["doses_read"]}
        for it in load(name, "items.json"):
            if labels[it["id"]] is None or f"{name}:{it['id']}" in RELABELED_AFTER_A_RUN:
                continue
            out.append(
                {
                    "id": f"{name}:{it['id']}",
                    "set": name,
                    "doc": it["doc"],
                    "span": it["span"],
                    "keys": keys[it["doc"]],
                    "label": labels[it["id"]],
                    "spec_0.3": read[it["id"]],
                }
            )
    return out


def part(doc: str) -> str:
    """The calibration part holds a label whose sha256 starts with 0 to 7, the test part the
    rest, so one label's text is never on both sides."""
    return "calibration" if hashlib.sha256(doc.encode()).hexdigest()[0] in "01234567" else "test"


def split() -> None:
    items = gold()
    out = {it["id"]: part(it["doc"]) for it in items}
    (HERE / "split.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    n = sum(v == "calibration" for v in out.values())
    print(f"wrote split.json: {n} calibration, {len(out) - n} test")


def state(it: dict[str, Any]) -> str:
    """What the label tool showed: 400 code points before the dose and 150 after, line breaks
    kept, the dose in brackets instead of bold."""
    text = (BENCH / it["set"] / "docs" / f"{it['doc']}.txt").read_text(encoding="utf-8")
    a, b = it["span"]
    return text[max(0, a - 400) : a] + f"[{text[a:b]}]" + text[b : b + 150]


def question(keys: list[str]) -> dict[str, Any]:
    criteria = {f"k{n}": k for n, k in enumerate(keys, 1)}
    criteria[NONE] = "none of these conditions: the dose belongs to another use, or to none"
    return {
        "key": {
            "type": "choice",
            "instructions": (
                "The text is from the dosage section of a drug label and marks one dose in "
                "brackets. Which of the drug's conditions does that dose belong to?"
            ),
            "criteria": criteria,
        }
    }


def laya_engine(meta: dict[str, Any]) -> Ask:
    import laya  # type: ignore[import-not-found]
    from laya import Router

    revision = os.environ.get("LAYA_REVISION")
    if not revision:
        raise SystemExit("set LAYA_REVISION to the checkpoint commit, as the docstring shows")
    router = Router(device="cpu")
    meta.update(
        engine=f"Laya {laya.__version__}", model=f"convaiinnovations/laya at {revision}, CPU"
    )

    def ask(st: str, qs: dict[str, Any]) -> dict[str, Any]:
        a = router.predict(st, qs, model=LAYA_MODEL)["answers"]["key"]
        return {"choice": a["choice"], "confidence": a["answer_confidence"]}

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
        a = res["answers"]["key"]
        return {"choice": a["choice"], "confidence": a["confidence"]}

    return ask


def jeff_engine(meta: dict[str, Any]) -> Ask:
    """A local jeff-serve, which takes the request format of Jev. JEFF_MODEL names the code commit
    and the weights it serves, for the run record."""
    served = os.environ.get("JEFF_MODEL")
    if not served:
        raise SystemExit("set JEFF_MODEL to the jeff commit and the weights it serves")
    health = JEFF_URL.removesuffix("/v1/systemone") + "/health"
    with urllib.request.urlopen(health, timeout=30) as r:
        name = json.load(r)["model"]
    # the name the server reports goes in the record too, so a resume can't change the model
    meta.update(engine="Jeff (local jeff-serve)", model=served, served_model=name)

    def ask(st: str, qs: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"state": st, "model": name, "questions": qs}).encode()
        req = urllib.request.Request(
            JEFF_URL, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            a = json.load(r)["answers"]["key"]
        return {"choice": a["choice"], "confidence": a["confidence"]}

    return ask


def prompts_sha256(items: list[dict[str, Any]]) -> str:
    """A digest of every prompt, in order: the dose id, the state and the question."""
    prompts = [(it["id"], state(it), question(it["keys"])) for it in items]
    return hashlib.sha256(json.dumps(prompts, sort_keys=True).encode()).hexdigest()


def run(engine: str) -> None:
    if not (HERE / "split.json").exists():
        raise SystemExit("run judge.py split first, before any model run")
    meta: dict[str, Any] = {"run": datetime.date.today().isoformat()}
    engines = {"laya": laya_engine, "jev": jev_engine, "jeff": jeff_engine}
    ask = engines[engine](meta)
    # answers so far, so that a stopped run goes on where it stopped, but only with the same
    # engine, model and prompts: a resume never mixes the answers of two runs
    partial = HERE / f".answers-{engine}.partial.json"
    items = gold()
    # the engine, the model and the prompts: a resume needs all three
    meta["prompts_sha256"] = prompts_sha256(items)
    record = {k: v for k, v in meta.items() if k != "run"}
    answers: dict[str, Any] = {}
    if partial.exists():
        saved = json.loads(partial.read_text())
        if saved["meta"] != record:
            raise SystemExit(f"{partial.name} is from {saved['meta']}, not {record}; delete it")
        answers = saved["answers"]
    for n, it in enumerate(items, 1):
        if it["id"] in answers:
            continue
        for attempt in range(4):
            try:
                a = ask(state(it), question(it["keys"]))
                break
            except (TimeoutError, urllib.error.URLError) as e:
                if attempt == 3:
                    raise SystemExit(f"{it['id']}: {e}; run again to go on") from e
                time.sleep(5 * (attempt + 1))
        answers[it["id"]] = {"choice": a["choice"], "confidence": round(a["confidence"], 4)}
        partial.write_text(json.dumps({"meta": record, "answers": answers}))
        print(f"{n}/{len(items)}", end="\r", flush=True)
    out = {"meta": meta, "answers": answers}
    (HERE / f"answers-{engine}.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    partial.unlink()
    print(f"\nwrote answers-{engine}.json")


def chosen_key(it: dict[str, Any], choice: str) -> str | None:
    """The key a choice names, or None for "none" or an unknown name."""
    if choice.startswith("k") and choice[1:].isdigit() and 1 <= int(choice[1:]) <= len(it["keys"]):
        return str(it["keys"][int(choice[1:]) - 1])
    return None


def clear(it: dict[str, Any], a: dict[str, Any], t: float) -> str | None:
    """What the answer does to a flag at threshold t: "right" when it clears the flag of a
    labeled key that spec 0.3 does not put at the dose, "escape" when it clears one of a key that
    is not labeled, and None when it clears nothing."""
    k = chosen_key(it, a["choice"])
    if k is None or a["confidence"] < t or k in it["spec_0.3"]:
        return None
    return "right" if k in it["label"] else "escape"


def correct(it: dict[str, Any], a: dict[str, Any]) -> bool:
    k = chosen_key(it, a["choice"])
    return (k in it["label"]) if k is not None else not it["label"]


def upper_95(k: int, n: int) -> float:
    """The one-sided 95% upper bound of a binomial rate, k of n (Clopper-Pearson), by bisection
    on the binomial CDF."""
    if n == 0 or k >= n:
        return 1.0

    def cdf(p: float) -> float:
        total, term = 0.0, (1 - p) ** n
        for i in range(k + 1):
            total += term
            term *= (n - i) / (i + 1) * p / (1 - p) if p < 1 else 0
        return total

    lo, hi = k / n, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) > 0.05 else (lo, mid)
    return round(hi, 4)


def score(items: list[dict[str, Any]], answers: dict[str, Any]) -> dict[str, Any]:
    """Accuracy, calibration and clears for one engine, by part."""
    out: dict[str, Any] = {}
    for p in ("calibration", "test"):
        rows = [(it, answers[it["id"]]) for it in items if it["part"] == p]
        right = [set(it["label"]) - set(it["spec_0.3"]) for it, _ in rows]
        by_t = {}
        for t in THRESHOLDS:
            done = [clear(it, a, t) for it, a in rows]
            sure = [(it, a) for it, a in rows if a["confidence"] >= t]
            by_t[str(t)] = {
                "answered": len(sure),
                "answered_correct": sum(correct(it, a) for it, a in sure),
                "clears_right": done.count("right"),
                "escapes": done.count("escape"),
            }
        out[p] = {
            "doses": len(rows),
            "correct": sum(correct(it, a) for it, a in rows),
            "doses_with_a_right_key_in_review": sum(map(bool, right)),
            # one answer clears at most one flag, so a dose with two right keys keeps one
            "right_flags_in_review": sum(map(len, right)),
            "by_threshold": by_t,
        }
    for p in ("calibration", "test"):
        for b in out[p]["by_threshold"].values():
            b["escape_rate_upper_95"] = upper_95(b["escapes"], b["clears_right"] + b["escapes"])
    # for each ceiling, the lowest threshold whose calibration bound is below it (§9)
    out["by_ceiling"] = {}
    for c in CEILINGS:
        ok = [
            t
            for t in THRESHOLDS
            if out["calibration"]["by_threshold"][str(t)]["escape_rate_upper_95"] < c
        ]
        t = min(ok) if ok else None
        out["by_ceiling"][str(c)] = {
            "threshold": t,
            "test": out["test"]["by_threshold"][str(t)] if t is not None else None,
        }
    return out


def report(check: bool) -> None:
    items = gold()
    digest = prompts_sha256(items)
    parts = json.loads((HERE / "split.json").read_text())
    for it in items:
        it["part"] = parts[it["id"]]
    results: dict[str, Any] = {
        "doses": {p: sum(it["part"] == p for it in items) for p in ("calibration", "test")},
        "labels": {
            p: len({it["doc"] for it in items if it["part"] == p}) for p in ("calibration", "test")
        },
        "engines": {},
    }
    md = [
        "# Clearing key flags with a typed-decision model",
        "",
        "Generated by `bench/judges/keys/judge.py report` from `split.json` and the "
        "`answers-*.json` files. The plan is on #67. The gold is the labeled doses of the keys "
        "and tables sets, split by label into a calibration part and a test part.",
        "",
        f"Calibration: {results['doses']['calibration']} doses in "
        f"{results['labels']['calibration']} labels. Test: {results['doses']['test']} doses in "
        f"{results['labels']['test']} labels. Left out: {len(RELABELED_AFTER_A_RUN)} dose whose "
        "label changed after a model answered it ([README.md](README.md)).",
    ]
    for engine, name in ENGINES.items():
        path = HERE / f"answers-{engine}.json"
        if not path.exists():
            continue
        run_ = json.loads(path.read_text())
        if run_["meta"].get("prompts_sha256") != digest:
            raise SystemExit(f"{path.name} answers other prompts than the gold; run it again")
        s = score(items, run_["answers"])
        results["engines"][engine] = {"meta": run_["meta"], **s}
        md += [
            "",
            f"## {name}",
            "",
            f"{run_['meta']['engine']}, {run_['meta']['model']}, run {run_['meta']['run']}.",
            "",
        ]
        for p in ("calibration", "test"):
            r = s[p]
            md += [
                f"**{p.capitalize()} part.** {r['correct']} of {r['doses']} answers match the "
                f"label. {r['doses_with_a_right_key_in_review']} doses have a right key that "
                f"spec 0.3 sends to review, with {r['right_flags_in_review']} right flags in all. "
                "One answer clears at most one flag.",
                "",
                "| Confidence at least | Answered | Correct | Flags cleared, right | Escapes |",
                "|---:|---:|---:|---:|---:|",
            ]
            for t in THRESHOLDS:
                b = r["by_threshold"][str(t)]
                md.append(
                    f"| {t} | {b['answered']} | {b['answered_correct']} | {b['clears_right']} "
                    f"| {b['escapes']} |"
                )
            md.append("")
        md += [
            "**Thresholds.** For each ceiling on the escape rate among cleared flags, the lowest "
            "threshold whose 95% upper bound on the calibration part is below it, and the test "
            "part at that threshold.",
            "",
            "| Ceiling | Threshold | Test: right flags cleared | Test: escapes | Test: bound |",
            "|---:|---:|---:|---:|---:|",
        ]
        for c in CEILINGS:
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
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("split")
    p = sub.add_parser("run")
    p.add_argument("engine", choices=sorted(ENGINES))
    p = sub.add_parser("report")
    p.add_argument("--check", action="store_true", help="fail if the committed files differ")
    args = ap.parse_args()
    if args.cmd == "split":
        split()
    elif args.cmd == "run":
        run(args.engine)
    else:
        report(args.check)


if __name__ == "__main__":
    main()
