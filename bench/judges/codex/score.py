"""Score the Codex judge answers on one split of bench/requested4 against the sealed labels (#67).

    uv run python bench/judges/codex/score.py --answers bench/requested4/judge/answers/*.json \\
        --out bench/requested4/judge [--check]

The items come again from the committed run file (`review_fields` of items.py), so the scores
need no cache. A clear is a candidate choice at confidence t or more. The clear is right when the
label holds the chosen (value, unit) by the `score.py` match rule of bench/requested
(`metrics.signature`), and an escape when it does not. A slot labeled unclear is left out.

For each ceiling, the threshold is the lowest t whose one-sided 95% upper bound on escapes among
clears is below the ceiling (hybrid design §9). The thresholds and the ceilings are fixed here
before the first model call. One threshold is pooled over the kinds, and the split gives its
counts for each kind.

The script writes `results.json` and `RESULTS.md`. `--check` compares them with the files in
`--out` and writes nothing. Labels of the other split are not read: only the documents of the
split of the run file are taken from the label file.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import sys
from pathlib import Path
from typing import Any

from groundgate.calibrate.stats import CEILINGS, pick, upper_95

Json = dict[str, Any]
ROOT = Path(__file__).resolve().parents[3]
SET = ROOT / "bench" / "requested4"
FORMAT = "codex-judge-scores/1"
THRESHOLDS = (0.5, 0.7, 0.8, 0.9, 0.95, 0.99)
BINS = (0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.01)


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


items_mod = _load("codex_judge_items", Path(__file__).with_name("items.py"))
metrics = _load("requested_metrics", ROOT / "bench" / "requested" / "metrics.py")


class ScoreError(Exception):
    """An input that the scorer refuses."""


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def sig(value: Any, unit: Any, field_type: str) -> tuple[str, Any]:
    return tuple(metrics.signature({"value": value, "unit": unit}, field_type))  # type: ignore[no-any-return]


def slots(run: Json, manifest: Json, labels: Json) -> dict[str, Json]:
    """Each review item of the run file, with its kind, its options as (value, unit)
    signatures, and its label: a set of signatures, or None for an unclear slot."""
    if labels.get("status") != "sealed":
        raise ScoreError("the labels are not sealed")
    split = run["split"]
    docs = {d["id"]: d for d in manifest["documents"]}
    wanted = {d["id"] for d in run["documents"]}
    if any(docs[i]["split"] != split for i in wanted):
        raise ScoreError("the run file has a document of another split")
    gold = {d["id"]: d for d in labels["documents"] if d["id"] in wanted}
    out: dict[str, Json] = {}
    for doc in sorted(run["documents"], key=lambda d: d["id"]):
        m = docs[doc["id"]]
        schema = m.get("schema", manifest["schemas"][m["kind"]])
        for field, decisions in items_mod.review_fields(doc["decisions"]).items():
            ftype = schema["fields"][field].get("type", "number")
            slot = [s for s in gold[doc["id"]]["fields"] if s["field"] == field]
            if len(slot) != 1:
                raise ScoreError(f"{doc['id']}/{field}: no single label slot")
            label = None
            if slot[0]["status"] != "unclear":
                label = {sig(v["value"], v.get("unit"), ftype) for v in slot[0].get("values", [])}
            out[items_mod.item_id(doc["id"], field)] = {
                "kind": m["kind"],
                "type": ftype,
                "options": {sig(d["value"], d["unit"], ftype) for d in decisions},
                "label": label,
            }
    return out


def chosen(item: Json, answer: Json) -> tuple[str, Any] | None:
    """The signature of the chosen candidate, or None for "none"."""
    c = answer["choice"]
    if c is None:
        return None
    got = sig(c["value"], c["unit"], item["type"])
    if got not in item["options"]:
        raise ScoreError("an answer chose a value that is not a candidate of its item")
    return got


def correct(item: Json, answer: Json) -> bool:
    got = chosen(item, answer)
    if got is None:
        return not (item["options"] & item["label"])
    return got in item["label"]


def counts(rows: list[tuple[Json, Json]]) -> Json:
    """The counts of one group of scored items (no unclear slot)."""
    by_t = {}
    for t in THRESHOLDS:
        right = escapes = 0
        for it, a in rows:
            got = chosen(it, a)
            if got is not None and a["confidence"] >= t:
                right += got in it["label"]
                escapes += got not in it["label"]
        by_t[str(t)] = {
            "clears_right": right,
            "escapes": escapes,
            "escape_rate_upper_95": upper_95(escapes, right + escapes),
        }
    bins = []
    for lo, hi in itertools.pairwise(BINS):
        inside = [(it, a) for it, a in rows if lo <= a["confidence"] < hi]
        good = sum(correct(it, a) for it, a in inside)
        bins.append({"from": lo, "to": min(hi, 1), "items": len(inside), "correct": good})
    picks = [(it, chosen(it, a)) for it, a in rows]
    return {
        "items": len(rows),
        "right_candidate": sum(bool(it["options"] & it["label"]) for it, _ in rows),
        "choices": {
            "right": sum(g is not None and g in it["label"] for it, g in picks),
            "wrong": sum(g is not None and g not in it["label"] for it, g in picks),
            "none_right": sum(g is None and not (it["options"] & it["label"]) for it, g in picks),
            "none_wrong": sum(g is None and bool(it["options"] & it["label"]) for it, g in picks),
        },
        "by_threshold": by_t,
        "bins": bins,
    }


def check_answers(answers: Json, items: dict[str, Json], name: str) -> None:
    if answers.get("format") != "codex-judge-answers/1":
        raise ScoreError(f"{name} is not a codex-judge-answers/1 file")
    if set(answers["answers"]) != set(items):
        raise ScoreError(f"{name} does not answer exactly the items of the run file")


def judge_scores(answers: Json, items: dict[str, Json], loop: Json) -> Json:
    scored = {i: it for i, it in items.items() if it["label"] is not None}
    kinds = sorted({it["kind"] for it in items.values()})

    def group(kind: str | None) -> list[tuple[Json, Json]]:
        return [
            (it, answers["answers"][i])
            for i, it in sorted(scored.items())
            if kind is None or it["kind"] == kind
        ]

    total = counts(group(None))
    by_kind = {k: counts(group(k)) for k in kinds}
    runner = loop["runs"]["runner"]
    by_t = total["by_threshold"]
    by_ceiling = {}
    for c in CEILINGS:
        t = pick(THRESHOLDS, lambda t: by_t[str(t)]["escape_rate_upper_95"], c, "lowest")
        row: Json = {"threshold": t}
        if t is not None:
            for k, part in [
                ("total", runner["total"]),
                *[(k, runner["by_kind"][k]) for k in kinds],
            ]:
                at = (total if k == "total" else by_kind[k])["by_threshold"][str(t)]
                miss = part["miss_rate"]
                row[k] = {
                    "clears_right": at["clears_right"],
                    "escapes": at["escapes"],
                    "escape_rate_upper_95": at["escape_rate_upper_95"],
                    "runner_miss": {"k": miss["k"], "n": miss["n"]},
                    "miss_with_clears": {"k": miss["k"] - at["clears_right"], "n": miss["n"]},
                    "runner_escapes": part["escapes"],
                    "escapes_with_clears": part["escapes"] + at["escapes"],
                }
        by_ceiling[str(c)] = row
    meta = answers["meta"]
    return {
        "model": meta["model"],
        "effort": meta["effort"],
        "run": meta["run"],
        "calls": answers["calls"],
        "codex_versions": meta["codex_versions"],
        "prompts_sha256": meta["prompts_sha256"],
        "template_sha256": meta["template_sha256"],
        "manifest_sha256": meta["manifest_sha256"],
        "unclear": len(items) - len(scored),
        "total": total,
        "by_kind": by_kind,
        "by_ceiling": by_ceiling,
    }


def label(meta: Json) -> str:
    return f"{meta['model']} {meta['effort'] or 'default'} run {meta['run']}"


def compare(a: Json, b: Json, items: dict[str, Json]) -> Json:
    """Two answer files on the same items: the same option, and the wrong choices of each."""
    scored = [i for i, it in items.items() if it["label"] is not None]
    wa = {
        i for i in scored if (g := chosen(items[i], a["answers"][i])) and g not in items[i]["label"]
    }
    wb = {
        i for i in scored if (g := chosen(items[i], b["answers"][i])) and g not in items[i]["label"]
    }
    same_wrong = {
        i for i in wa & wb if chosen(items[i], a["answers"][i]) == chosen(items[i], b["answers"][i])
    }
    clears = {}
    for t in THRESHOLDS:
        ca = {
            i
            for i in scored
            if chosen(items[i], a["answers"][i]) and a["answers"][i]["confidence"] >= t
        }
        cb = {
            i
            for i in scored
            if chosen(items[i], b["answers"][i]) and b["answers"][i]["confidence"] >= t
        }
        clears[str(t)] = {
            "both": len(ca & cb),
            "first_only": len(ca - cb),
            "second_only": len(cb - ca),
        }
    return {
        "first": label(a["meta"]),
        "second": label(b["meta"]),
        "items": len(scored),
        "same_option": sum(
            chosen(items[i], a["answers"][i]) == chosen(items[i], b["answers"][i]) for i in scored
        ),
        "wrong_first": len(wa),
        "wrong_second": len(wb),
        "wrong_both": len(wa & wb),
        "same_wrong": len(same_wrong),
        "clears": clears,
    }


def score(
    run_path: Path,
    loop_path: Path,
    labels_path: Path,
    manifest_path: Path,
    answer_paths: list[Path],
) -> Json:
    run, manifest, loop = read(run_path), read(manifest_path), read(loop_path)
    if loop["labels_sha256"] != run["labels_sha256"]:
        raise ScoreError("the run file and the loop results name other labels")
    if digest(labels_path) != run["labels_sha256"]:
        raise ScoreError("the label file is not the one of the run file")
    items = slots(run, manifest, read(labels_path))
    answers = []
    for p in answer_paths:
        a = read(p)
        check_answers(a, items, p.name)
        if a["meta"]["manifest_sha256"] != digest(manifest_path):
            raise ScoreError(f"{p.name} names another manifest")
        answers.append(a)
    judges = {label(a["meta"]): judge_scores(a, items, loop) for a in answers}
    if len(judges) != len(answers):
        raise ScoreError("two answer files have the same model, effort and run")
    pairs = []
    for a, b in itertools.combinations(answers, 2):
        same_model = a["meta"]["model"] == b["meta"]["model"]
        if same_model or (a["meta"]["run"] == 1 and b["meta"]["run"] == 1):
            pairs.append(compare(a, b, items))
    kinds = sorted({it["kind"] for it in items.values()})
    return {
        "format": FORMAT,
        "split": run["split"],
        "inputs": {
            "run": rel(run_path),
            "run_binding_sha256": run["binding_sha256"],
            "loop_results": rel(loop_path),
            "loop_results_sha256": digest(loop_path),
            "labels_sha256": digest(labels_path),
            "manifest_sha256": digest(manifest_path),
            "answers": {rel(p): digest(p) for p in answer_paths},
        },
        "thresholds": list(THRESHOLDS),
        "ceilings": list(CEILINGS),
        "items": {
            "total": len(items),
            "by_kind": {k: sum(it["kind"] == k for it in items.values()) for k in kinds},
            "unclear": sum(it["label"] is None for it in items.values()),
        },
        "judges": judges,
        "pairs": pairs,
    }


def pct(k: int, n: int) -> str:
    return f"{100 * k / n:.2f}% ({k} of {n})" if n else "none"


def bound(x: float) -> str:
    return f"{x:.4f}"


def markdown(r: Json) -> str:
    """RESULTS.md, from results.json only."""
    kinds = sorted(r["items"]["by_kind"])
    per_kind = ", ".join(f"{k} {r['items']['by_kind'][k]}" for k in kinds)
    lines = [
        "# Codex judge on the review fields: development split",
        "",
        "This file comes from `results.json` through `bench/judges/codex/score.py`.",
        "",
        f"Items: {r['items']['total']} fields of the `runner` arm that end in review with at least "
        f"one candidate ({per_kind}). "
        f"{r['items']['unclear']} of them have an unclear label and are left out of the scores.",
        "",
        "## Judges",
        "",
        "| Judge | Calls | Scored items | Right candidate | Right choices | Wrong choices "
        "| None, right | None, wrong |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, j in r["judges"].items():
        t, ch = j["total"], j["total"]["choices"]
        lines.append(
            f"| {name} | {j['calls']} | {t['items']} | {t['right_candidate']} | {ch['right']} "
            f"| {ch['wrong']} | {ch['none_right']} | {ch['none_wrong']} |"
        )
    lines += [
        "",
        '"Right candidate" counts the items where a candidate matches the label. "None, right" '
        "is a none choice on an item with no right candidate.",
        "",
        "## Threshold at each ceiling",
        "",
        "The threshold is the lowest t whose one-sided 95% upper bound on escapes among clears "
        "is below the ceiling, pooled over the kinds.",
        "",
        "| Judge | Ceiling | t | Right values cleared | Escapes | Upper 95% "
        "| Runner miss rate | Miss rate with the clears | Escapes with the clears |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, j in r["judges"].items():
        for c, row in j["by_ceiling"].items():
            if row["threshold"] is None:
                lines.append(f"| {name} | {c} | none | | | | | | |")
                continue
            tot = row["total"]
            lines.append(
                f"| {name} | {c} | {row['threshold']} | {tot['clears_right']} | {tot['escapes']} "
                f"| {bound(tot['escape_rate_upper_95'])} "
                f"| {pct(tot['runner_miss']['k'], tot['runner_miss']['n'])} "
                f"| {pct(tot['miss_with_clears']['k'], tot['miss_with_clears']['n'])} "
                f"| {tot['escapes_with_clears']} |"
            )
    lines += [
        "",
        "## Each kind at the threshold",
        "",
        "| Judge | Ceiling | t | Kind | Items | Right values cleared | Escapes "
        "| Runner miss rate | Miss rate with the clears |",
        "|---|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    for name, j in r["judges"].items():
        for c, row in j["by_ceiling"].items():
            if row["threshold"] is None:
                continue
            for k in kinds:
                x = row[k]
                lines.append(
                    f"| {name} | {c} | {row['threshold']} | {k} | {j['by_kind'][k]['items']} "
                    f"| {x['clears_right']} | {x['escapes']} "
                    f"| {pct(x['runner_miss']['k'], x['runner_miss']['n'])} "
                    f"| {pct(x['miss_with_clears']['k'], x['miss_with_clears']['n'])} |"
                )
    lines += [
        "",
        "## All thresholds",
        "",
        "| Judge | t | Right values cleared | Escapes | Upper 95% |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, j in r["judges"].items():
        for t, x in j["total"]["by_threshold"].items():
            lines.append(
                f"| {name} | {t} | {x['clears_right']} | {x['escapes']} "
                f"| {bound(x['escape_rate_upper_95'])} |"
            )
    lines += [
        "",
        "## Calibration bins",
        "",
        "A choice is correct when it names a right candidate, or none on an item with no right "
        "candidate.",
        "",
        "| Judge | Confidence | Items | Correct |",
        "|---|---|---:|---:|",
    ]
    for name, j in r["judges"].items():
        for b in j["total"]["bins"]:
            if b["items"]:
                lines.append(
                    f"| {name} | {b['from']} to {b['to']} | {b['items']} | {b['correct']} |"
                )
    if r["pairs"]:
        lines += [
            "",
            "## Pairs",
            "",
            "Two runs of one model show the repeatability. Two models show the shared wrong "
            "choices. A wrong choice names a candidate that the label does not hold.",
            "",
            "| First | Second | Items | Same option | Wrong, first | Wrong, second "
            "| Wrong, both | Same wrong candidate |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
        for p in r["pairs"]:
            lines.append(
                f"| {p['first']} | {p['second']} | {p['items']} | {p['same_option']} "
                f"| {p['wrong_first']} | {p['wrong_second']} | {p['wrong_both']} "
                f"| {p['same_wrong']} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--answers", type=Path, nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True, help="the folder of results.json")
    ap.add_argument("--run", type=Path, default=SET / "loop" / "04" / "runs" / "runner.json")
    ap.add_argument("--loop-results", type=Path, default=SET / "loop" / "04" / "results.json")
    ap.add_argument("--labels", type=Path, default=SET / "labels.json")
    ap.add_argument("--manifest", type=Path, default=SET / "manifest.json")
    ap.add_argument("--check", action="store_true", help="compare with the files in --out")
    args = ap.parse_args(argv)
    try:
        result = score(args.run, args.loop_results, args.labels, args.manifest, args.answers)
    except (ScoreError, KeyError, ValueError, OSError) as e:
        raise SystemExit(f"score: {e}") from e
    body = json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    report = markdown(result)
    files = {args.out / "results.json": body, args.out / "RESULTS.md": report}
    if args.check:
        stale = [p.name for p, b in files.items() if not p.exists() or p.read_text() != b]
        if stale:
            raise SystemExit(f"score: {', '.join(stale)} differ from the answers; run score again")
        print("results.json and RESULTS.md match the answers")
        return
    for p, b in files.items():
        p.write_text(b, encoding="utf-8")
    print(f"wrote {args.out / 'results.json'} and RESULTS.md")


if __name__ == "__main__":
    main(sys.argv[1:])
