"""groundgate-calibrate: measure a judge's thresholds on your own documents (hybrid design §9).

    groundgate-calibrate sample --work W --docs D --candidates C --schema S --question key
    groundgate-calibrate split  --work W        # before any model run
    groundgate-calibrate label  --work W        # label in the browser, blind, before ask
    groundgate-calibrate ask    --work W --judge jev
    groundgate-calibrate report --work W        # REPORT.md, report.json

D holds <doc>.txt files, C holds <doc>.json files with each document's candidates in the
spec 0.3 candidate format, and S is a spec 0.3 schema. W keeps everything that a later step
needs, so a step never asks for an earlier input again.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import time
import unicodedata
import urllib.error
from pathlib import Path
from typing import Any

from groundgate.canonical import SPEC_VERSION

from . import questions as q
from .judges import JUDGES
from .stats import CEILINGS, needed


class Work:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self, name: str, default: Any = None) -> Any:
        p = self.path / name
        if not p.exists():
            if default is None:
                raise SystemExit(f"{p} is not there; run the step that writes it first")
            return default
        return json.loads(p.read_text(encoding="utf-8"))

    def write(self, name: str, obj: Any) -> None:
        body = json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        (self.path / name).write_text(body, encoding="utf-8")

    def text(self, doc: str) -> str:
        return (self.path / "docs" / f"{doc}.txt").read_text(encoding="utf-8")

    @property
    def config(self) -> dict[str, Any]:
        cfg = dict(self.read("config.json"))
        if cfg.get("spec") != SPEC_VERSION:
            # another spec can admit and flag other candidates, so the items would differ
            raise SystemExit(
                f"{self.path} was sampled under spec {cfg.get('spec')}; this groundgate "
                f"implements {SPEC_VERSION}. Sample again in a new work directory."
            )
        return cfg


def sample(w: Work, docs: Path, cands: Path, schema_path: Path, args: argparse.Namespace) -> None:
    if (w.path / "items.json").exists():
        raise SystemExit(f"{w.path} has items already; use a new work directory")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    descriptions = (
        json.loads(args.descriptions.read_text(encoding="utf-8")) if args.descriptions else {}
    )
    (w.path / "docs").mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for path in sorted(docs.glob("*.txt")):
        doc = path.stem
        if any(ch.isspace() for ch in doc):
            raise SystemExit(f"{path.name}: a document name has no spaces")
        text = path.read_text(encoding="utf-8")
        if not unicodedata.is_normalized("NFC", text):
            # the candidates' byte offsets point into this text, so it is never changed here
            raise SystemExit(f"{path.name} is not NFC; normalise it before you extract")
        cpath = cands / f"{doc}.json"
        if not cpath.exists():
            # a document without its candidates would leave the sample quietly; an empty list
            # says that the extractor found nothing
            raise SystemExit(f"{cpath} is not there; write [] for a document with no candidates")
        found = q.sample(
            args.question, doc, text, schema, json.loads(cpath.read_text(encoding="utf-8"))
        )
        if found:
            (w.path / "docs" / f"{doc}.txt").write_text(text, encoding="utf-8")
            items += found
    config = {
        "spec": SPEC_VERSION,
        "question": args.question,
        "context": args.context,
        "descriptions": descriptions,
        "schema": schema,
    }
    if not items:
        raise SystemExit(f"no {args.question} items in these documents; there is nothing to label")
    w.write("config.json", config)
    w.write("items.json", items)
    print(f"{len(items)} items in {len({it['doc'] for it in items})} documents")
    print("With no failure, the calibration part needs this many right items for each ceiling:")
    for c in CEILINGS:
        print(f"  {c}: {needed(c)}")
    print("A split by document puts about half of the items in the calibration part.")


def part(doc: str) -> str:
    """The calibration part holds a document whose sha256 starts with 0 to 7, the test part the
    rest, so one document is never on both sides."""
    return "calibration" if hashlib.sha256(doc.encode()).hexdigest()[0] in "01234567" else "test"


def split(w: Work) -> None:
    if (w.path / "split.json").exists():
        raise SystemExit("split.json is there already; a split is written once")
    if list(w.path.glob("answers-*.json")):
        raise SystemExit("a model has answered already; a split comes before any model run")
    out = {it["id"]: part(it["doc"]) for it in w.read("items.json")}
    w.write("split.json", out)
    # the prompts that the split is for: ask asks only these, and report scores only their answers
    w.write("prompts.json", {"prompts_sha256": prompts_sha256(w)})
    n = sum(v == "calibration" for v in out.values())
    print(f"wrote split.json: {n} calibration, {len(out) - n} test")


def prompts(w: Work) -> list[tuple[str, str, dict[str, Any]]]:
    cfg = w.config
    out = []
    for it in w.read("items.json"):
        st, qs = q.prompt(
            cfg["question"], w.text(it["doc"]), it, cfg["context"], cfg["descriptions"]
        )
        out.append((it["id"], st, qs))
    return out


def labels_sha256(labels: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(labels, sort_keys=True).encode()).hexdigest()


def scoring_sha256(w: Work) -> str:
    """A digest of what report scores besides the labels and answers: the items, with the
    candidates' keys that the prompts do not show, and the split."""
    both = {"items": w.read("items.json"), "split": w.read("split.json")}
    return hashlib.sha256(json.dumps(both, sort_keys=True).encode()).hexdigest()


def prompts_sha256(w: Work) -> str:
    return hashlib.sha256(json.dumps(prompts(w)).encode()).hexdigest()


def ask(w: Work, judge: str) -> None:
    """Ask every prompt once. A stopped run goes on where it stopped, but only with the same
    judge, model and prompts: a resume never mixes the answers of two runs."""
    w.read("split.json")
    target = w.path / f"answers-{judge}.json"
    if target.exists():
        raise SystemExit(f"{target.name} is there already")
    ps = prompts(w)
    digest = hashlib.sha256(json.dumps(ps).encode()).hexdigest()
    if digest != w.read("prompts.json")["prompts_sha256"]:
        raise SystemExit("the documents, items or config changed after the split")
    # every item is labeled before any judge answers, and those labels are the ones scored
    labels = w.read("labels.json", {})
    missing = [iid for iid, _, _ in ps if iid not in labels]
    if missing:
        raise SystemExit(f"{len(missing)} items are not labeled yet; label before a judge answers")
    meta, call = JUDGES[judge]()
    record = {
        **meta,
        "prompts_sha256": digest,
        "labels_sha256": labels_sha256(labels),
        "scoring_sha256": scoring_sha256(w),
    }
    partial = w.path / f".answers-{judge}.partial.json"
    answers: dict[str, Any] = {}
    if partial.exists():
        saved = json.loads(partial.read_text(encoding="utf-8"))
        if saved["meta"] != record:
            raise SystemExit(f"{partial.name} is from another run; delete it")
        answers = saved["answers"]
    question = w.config["question"]
    for n, (iid, st, qs) in enumerate(ps, 1):
        if iid in answers:
            continue
        for attempt in range(4):
            try:
                a = call(st, qs)
                break
            except (TimeoutError, urllib.error.URLError) as e:
                if attempt == 3:
                    raise SystemExit(f"{iid}: {e}; run again to go on") from e
                time.sleep(5 * (attempt + 1))
        answers[iid] = q.keep(question, a)
        partial.write_text(json.dumps({"meta": record, "answers": answers}), encoding="utf-8")
        print(f"{n}/{len(ps)}", end="\r", flush=True)
    w.write(target.name, {"meta": {**record, "run": datetime.date.today().isoformat()},
                          "answers": answers})  # fmt: skip
    partial.unlink(missing_ok=True)
    print(f"\nwrote {target.name}")


def report(w: Work, check: bool) -> None:
    cfg, items = w.config, w.read("items.json")
    labels, parts = w.read("labels.json", {}), w.read("split.json")
    missing = [it["id"] for it in items if it["id"] not in labels]
    if missing:
        raise SystemExit(f"{len(missing)} items are not labeled yet")
    results: dict[str, Any] = {"question": cfg["question"], "judges": {}}
    for path in sorted(w.path.glob("answers-*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec["meta"]["prompts_sha256"] != w.read("prompts.json")["prompts_sha256"]:
            raise SystemExit(f"{path.name} answers other prompts than the split's")
        if rec["meta"]["scoring_sha256"] != scoring_sha256(w):
            raise SystemExit(f"the items or the split changed after {path.name}")
        if rec["meta"]["labels_sha256"] != labels_sha256(labels):
            raise SystemExit(f"the labels changed after {path.name}; a judge's answers are scored "
                             "only against the labels made before it answered")  # fmt: skip
        s = q.score(cfg["question"], items, labels, parts, rec["answers"])
        results["judges"][path.stem[8:]] = {"meta": rec["meta"], **s}
    if not results["judges"]:
        raise SystemExit("no answers yet; run ask first")
    out = {
        "report.json": json.dumps(results, indent=1, sort_keys=True) + "\n",
        "REPORT.md": markdown(results),
    }
    if check:
        stale = [n for n, body in out.items() if (w.path / n).read_text(encoding="utf-8") != body]
        if stale:
            raise SystemExit(f"out of date: {', '.join(stale)}; run report")
        print("REPORT.md is up to date")
        return
    for name, body in out.items():
        (w.path / name).write_text(body, encoding="utf-8")
    print("wrote REPORT.md, report.json")


def policy(question: str, meta: dict[str, Any], t: float) -> dict[str, Any]:
    """The judge block of a policy (hybrid design §7) for one threshold."""
    rule = (
        {"clear": {"KEY_NOT_AT_VALUE": t}} if question == "key" else {"doubt": {"field_match": t}}
    )
    return {"judge": {"id": meta["judge"], "digest": meta["model"], **rule}}


def markdown(results: dict[str, Any]) -> str:
    question = results["question"]
    md = [
        "# Calibration report",
        "",
        "Generated by `groundgate-calibrate report`. The threshold for each ceiling comes from "
        "the calibration part (hybrid design §9). The test part shows what that threshold does "
        "on documents that did not choose it.",
    ]
    for r in results["judges"].values():
        meta = r["meta"]
        md += ["", f"## {meta['judge']} ({meta['model']})", ""]
        if question == "key":
            md += [
                "A clear is right when the label holds the candidate's key, and an escape when "
                "it does not. The ceiling is on the escape rate among clears.",
                "",
                "| Ceiling | Threshold | Test: right clears | Test: escapes | Test: right flags |",
                "|---:|---:|---:|---:|---:|",
            ]
            for c, v in r["by_ceiling"].items():
                t, test = v["threshold"], v["test"]
                cells = (
                    [str(t), str(test["clears_right"]), str(test["escapes"])]
                    if t is not None
                    else ["none", "", ""]
                )
                md.append(f"| {c} | " + " | ".join(cells) + f" | {r['test']['right_flags']} |")
        else:
            md += [
                "A doubt catches a wrong value, and it sends a right one to review. The ceiling is "
                "on the share of right values doubted.",
                "",
                "| Ceiling | Threshold | Test: wrong caught | Test: right doubted | Test: wrong "
                "| Test: right |",
                "|---:|---:|---:|---:|---:|---:|",
            ]
            for c, v in r["by_ceiling"].items():
                t, test = v["threshold"], v["test"]
                cells = (
                    [str(t), str(test["wrong_caught"]), str(test["right_doubted"])]
                    if t is not None
                    else ["none", "", ""]
                )
                md.append(
                    f"| {c} | " + " | ".join(cells) + f" | {r['test']['wrong']} | "
                    f"{r['test']['right']} |"
                )
        md += ["", "Policy blocks, one for each ceiling that has a threshold:", ""]
        for c, v in r["by_ceiling"].items():
            if v["threshold"] is not None:
                block = json.dumps(policy(question, meta, v["threshold"]))
                md.append(f"- {c}: `{block}`")
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="groundgate-calibrate", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sample", help="take the items for one question from your documents")
    p.add_argument("--docs", type=Path, required=True)
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--schema", type=Path, required=True)
    p.add_argument("--question", choices=("key", "field"), required=True)
    p.add_argument("--descriptions", type=Path, help="JSON: field name to a one-line meaning")
    p.add_argument("--context", default="", help='for example "The text is from a 10-K filing."')
    p = sub.add_parser("label", help="label the items in the browser")
    p.add_argument("--port", type=int, default=8780)
    sub.add_parser("split", help="split the items, before any model run")
    p = sub.add_parser("ask", help="ask a judge every question")
    p.add_argument("--judge", choices=sorted(JUDGES), required=True)
    p = sub.add_parser("report", help="write REPORT.md and report.json")
    p.add_argument("--check", action="store_true", help="fail if the written files differ")
    for s in sub.choices.values():
        s.add_argument("--work", type=Path, required=True, help="the work directory")
    args = ap.parse_args(argv)
    w = Work(args.work)
    if args.cmd == "sample":
        sample(w, args.docs, args.candidates, args.schema, args)
    elif args.cmd == "label":
        from .label import serve

        serve(w, args.port)
    elif args.cmd == "split":
        split(w)
    elif args.cmd == "ask":
        ask(w, args.judge)
    else:
        report(w, args.check)
