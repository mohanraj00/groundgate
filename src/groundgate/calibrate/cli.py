"""groundgate calibrate (experimental): measure a judge's thresholds on your own documents (§9).

    groundgate calibrate sample --work W --docs D --candidates C --schema S --question key \
        [--store DIR]                           # with a store: a packet and a task for each item
    groundgate calibrate split  --work W [--store DIR --set NAME]  # before any model run
    groundgate calibrate label  --work W [--store DIR --reviewer NAME]  # blind, before ask
    groundgate calibrate ask    --work W --judge jev [--store DIR --reviewer NAME]
    groundgate calibrate report --work W [--store DIR]  # REPORT.md, report.json
    groundgate calibrate judge  --docs D --candidates C --schema S --policy P \
        --calibration W [W2] --out J            # recorded judgments (spec 0.4 and later)

D holds <doc>.txt files, C holds <doc>.json files with each document's candidates in the
candidate format of the installed groundgate's spec, and S is a schema of that spec. W keeps
everything that a later step needs, so a step never asks for an earlier input again.

Without --store, the labels are in W/labels.json, as in 0.10. With --store, label opens the
review page on the tasks of W, each label is an answer in the answer log of the reviewer, and
ask and report read the labels from those logs (docs/design/review.md §11).
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

from . import judges, label
from . import questions as q
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
    found_by_doc: list[tuple[str, str, list[Any], list[dict[str, Any]]]] = []
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
        given = json.loads(cpath.read_text(encoding="utf-8"))
        found = q.sample(args.question, doc, text, schema, given)
        if found:
            (w.path / "docs" / f"{doc}.txt").write_text(text, encoding="utf-8")
            items += found
            found_by_doc.append((doc, text, given, found))
    config = {
        "spec": SPEC_VERSION,
        "question": args.question,
        "context": args.context,
        "descriptions": q.descriptions(schema) | descriptions,
        "schema": schema,
    }
    if not items:
        raise SystemExit(f"no {args.question} items in these documents; there is nothing to label")
    if args.store is not None:
        # the packet schema holds each description, so a stored task asks what the page asks
        described = {**schema, "fields": {
            name: {**f, "description": config["descriptions"][name]}
            if config["descriptions"].get(name) else f
            for name, f in schema["fields"].items()
        }}  # fmt: skip
        w.write("tasks.json", put_tasks(args.store, described, found_by_doc, args.question))
    w.write("config.json", config)
    w.write("items.json", items)
    print(f"{len(items)} items in {len({it['doc'] for it in items})} documents")
    print("With no failure, the calibration part needs this many right items for each ceiling:")
    for c in CEILINGS:
        print(f"  {c}: {needed(c)}")
    print("A split by document puts about half of the items in the calibration part.")


def put_tasks(
    store: Path,
    schema: dict[str, Any],
    found: list[tuple[str, str, list[Any], list[dict[str, Any]]]],
    question: str,
) -> dict[str, dict[str, str]]:
    """Write a packet for each document and a blind task for each item to ``store``, and give
    the map of tasks.json: item id to packet and task."""
    from groundgate.model import PacketError
    from groundgate.store import FolderStore, StoreError

    from .stored import put_items

    out: dict[str, dict[str, str]] = {}
    try:
        with FolderStore(store) as s:
            for doc, text, cands, items in found:
                out |= put_items(s, doc, text, schema, cands, items, question)
    except (StoreError, PacketError, ValueError, OSError) as exc:
        raise SystemExit(f"{store}: {exc}") from exc
    return out


def stored_labels(
    w: Work, store: Path, reviewer: str, heads: dict[str, str | None] | None = None
) -> tuple[dict[str, Any], dict[str, str | None]]:
    """The labels of ``reviewer`` from the answer logs in ``store``, and the head of each log."""
    from .stored import labels

    return labels(store, w.read("tasks.json"), w.read("items.json"), reviewer, heads)


def part(doc: str) -> str:
    """The calibration part holds a document whose sha256 starts with 0 to 7, the test part the
    rest, so one document is never on both sides."""
    return "calibration" if hashlib.sha256(doc.encode()).hexdigest()[0] in "01234567" else "test"


def split(w: Work, store: Path | None = None, set_name: str | None = None) -> None:
    """Write split.json. With a store and a set name, also write the part of each document to
    the splits log of that set (store.md §10), before split.json."""
    if (store is None) != (set_name is None):
        raise SystemExit("give --store and --set together")
    if (w.path / "split.json").exists():
        raise SystemExit("split.json is there already; a split is written once")
    if list(w.path.glob("answers-*.json")):
        raise SystemExit("a model has answered already; a split comes before any model run")
    items = w.read("items.json")
    out = {it["id"]: part(it["doc"]) for it in items}
    if store is not None and set_name is not None:
        log_split(w, items, store, set_name)
    w.write("split.json", out)
    # the prompts that the split is for: ask asks only these, and report scores only their answers
    w.write("prompts.json", {"prompts_sha256": prompts_sha256(w)})
    n = sum(v == "calibration" for v in out.values())
    print(f"wrote split.json: {n} calibration, {len(out) - n} test")


# The split name in the splits log for each part (store.md §10): the calibration part chooses
# the thresholds, as the development split of #383 does, and the test part only measures.
LOG_SPLIT = {"calibration": "development", "test": "held-out"}


def log_split(w: Work, items: list[dict[str, Any]], store: Path, set_name: str) -> None:
    """Write the split of each document to the splits log of ``set_name`` in ``store``: the
    calibration part is ``development`` and the test part is ``held-out``. The document key is
    the text key, because calibrate has no source. The log comes before any label, and a
    document that the log puts in another split stops the split."""
    from groundgate.store import FolderStore, StoreError, key
    from groundgate.store.splits import write_split

    if w.read("labels.json", {}):
        raise SystemExit("labels.json has labels; the splits log comes before any label")
    if (w.path / "tasks.json").exists():
        tasks = w.read("tasks.json").values()
        packets, task_keys = {t["packet"] for t in tasks}, {t["task"] for t in tasks}
        try:
            with FolderStore(store) as s:
                logs, _ = s.log_names()
                # only an answer to a task of tasks.json is a label; a review answer is not
                labeled = any(
                    r.get("task") in task_keys
                    for log in logs
                    if log[0] == "answers" and log[1] in packets
                    for r in s.read(log)
                    if isinstance(r.get("task"), str)
                )
        except (StoreError, OSError) as exc:
            raise SystemExit(f"{store}: {exc}") from exc
        if labeled:
            raise SystemExit("the store has answers to these items; the splits log comes first")
    parts: dict[str, str] = {}
    names: dict[str, str] = {}
    for doc in sorted({it["doc"] for it in items}):
        k = key("text@1", w.text(doc).encode("utf-8"))
        if parts.setdefault(k, LOG_SPLIT[part(doc)]) != LOG_SPLIT[part(doc)]:
            raise SystemExit(f"{names[k]} and {doc} have the same text but not the same part")
        names.setdefault(k, doc)
    try:
        with FolderStore(store) as s:
            added = write_split(s, set_name, parts)
    except (StoreError, ValueError, OSError) as exc:
        raise SystemExit(f"{store}: {exc}") from exc
    print(
        f"the splits log of {set_name}: {added} new documents, {len(parts) - added} there already"
    )


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


def ask(w: Work, judge: str, store: Path | None = None, reviewer: str | None = None) -> None:
    """Ask every prompt once. A stopped run goes on where it stopped, but only with the same
    judge, model and prompts: a resume never mixes the answers of two runs. With ``store``, the
    labels come from the answer logs of ``reviewer``, and the meta keeps the head of each log."""
    if (store is None) != (reviewer is None):
        raise SystemExit("give --store and --reviewer together")
    w.read("split.json")
    target = w.path / f"answers-{judge}.json"
    if target.exists():
        raise SystemExit(f"{target.name} is there already")
    ps = prompts(w)
    digest = hashlib.sha256(json.dumps(ps).encode()).hexdigest()
    if digest != w.read("prompts.json")["prompts_sha256"]:
        raise SystemExit("the documents, items or config changed after the split")
    # the partial file freezes the labels (label and label --store refuse each write while it is
    # there), so it is written before the label snapshot and stays until the run ends
    partial = w.path / f".answers-{judge}.partial.json"
    with label.labels_lock(w.path):
        fresh = not partial.exists()
        if fresh:
            partial.write_text(json.dumps({"meta": {"pending": True}, "answers": {}}), "utf-8")
        try:
            jd, record, answers = _ask_start(w, judge, ps, digest, partial, fresh, store, reviewer)
        except BaseException:
            if fresh:
                partial.unlink(missing_ok=True)  # no judge was asked: the labels are open again
            raise
    question = w.config["question"]
    for n, (iid, st, qs) in enumerate(ps, 1):
        if iid in answers:
            continue
        answers[iid] = q.keep(question, call(jd, st, qs, iid))
        partial.write_text(json.dumps({"meta": record, "answers": answers}), encoding="utf-8")
        print(f"{n}/{len(ps)}", end="\r", flush=True)
    w.write(target.name, {"meta": {**record, "run": datetime.date.today().isoformat()},
                          "answers": answers})  # fmt: skip
    partial.unlink(missing_ok=True)
    print(f"\nwrote {target.name}")


def _ask_start(
    w: Work,
    judge: str,
    ps: list[tuple[str, str, dict[str, Any]]],
    digest: str,
    partial: Path,
    fresh: bool,
    store: Path | None,
    reviewer: str | None,
) -> tuple[judges.Judge, dict[str, Any], dict[str, Any]]:
    """Take the label snapshot while the partial file freezes the labels, check it, and write
    the meta of the run to the partial file before the first judge call."""
    # every item is labeled before any judge answers, and those labels are the ones scored
    labels = w.read("labels.json", {})
    source: dict[str, Any] = {}
    if store is not None and reviewer is not None:
        labels, heads = stored_labels(w, store, reviewer)
        source = {"labels_from": {"reviewer": reviewer, "heads": heads}}
    # every judge of the folder scores the same labels from the same source: a run without a
    # store has no labels_from, and a run with a store keeps the reviewer and the log heads
    for path in sorted([*w.path.glob("answers-*.json"), *w.path.glob(".answers-*.partial.json")]):
        if fresh and path == partial:
            continue
        given = json.loads(path.read_text(encoding="utf-8"))["meta"].get("labels_from")
        if given != source.get("labels_from"):
            raise SystemExit(
                f"{path.name} has its labels from another source, or the answer logs changed "
                "after it; the labels are frozen once a judge has answered"
            )
    missing = [iid for iid, _, _ in ps if iid not in labels]
    if missing:
        raise SystemExit(f"{len(missing)} items are not labeled yet; label before a judge answers")
    jd = judges.load(judge)
    record = {
        "judge": jd.id,
        "model": jd.digest,
        "prompts_sha256": digest,
        "labels_sha256": labels_sha256(labels),
        "scoring_sha256": scoring_sha256(w),
        **source,
    }
    answers: dict[str, Any] = {}
    if not fresh:
        saved = json.loads(partial.read_text(encoding="utf-8"))
        if saved["meta"] != record:
            raise SystemExit(f"{partial.name} is from another run; delete it")
        answers = saved["answers"]
    partial.write_text(json.dumps({"meta": record, "answers": answers}), encoding="utf-8")
    return jd, record, answers


def call(jd: judges.Judge, st: str, qs: dict[str, Any], what: str) -> dict[str, Any]:
    """Ask one prompt, with three retries on a network failure."""
    for attempt in range(4):
        try:
            return jd.ask(st, qs)
        except (TimeoutError, urllib.error.URLError) as e:
            if attempt == 3:
                raise SystemExit(f"{what}: {e}; run again to go on") from e
            time.sleep(5 * (attempt + 1))
    raise AssertionError("unreachable")


def judge_packets(args: argparse.Namespace) -> None:
    """Answer the questions that the policy names, for every document, and write the recorded
    judgments (SPEC 0.4 §2.6) to --out/<doc>.json. A question is asked as its calibration asked
    it, and only of the candidates where its answer can change the decision."""
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    block = policy.get("judge") if isinstance(policy, dict) else None
    if not isinstance(block, dict):
        raise SystemExit("the policy has no judge block; groundgate calibrate report writes one")
    jd = judges.load(str(block.get("id")))
    if jd.digest != block.get("digest"):
        raise SystemExit(f"the policy names {block.get('digest')}, the judge is {jd.digest}")
    wanted = {
        "key": block.get("clear", {}).get("KEY_NOT_AT_VALUE") is not None,
        "field": block.get("doubt", {}).get("field_match") is not None,
    }
    cals: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    for path in args.calibration:
        w = Work(path)
        cfg = w.config  # refuses a calibration of another spec
        rec = w.read(f"answers-{jd.id}.json")
        if rec["meta"]["model"] != jd.digest:
            raise SystemExit(f"{path} calibrated {rec['meta']['model']}, not {jd.digest}")
        # the thresholds hold for the prompts that set them, so the wording, context,
        # descriptions and items must be those of the calibration run
        if prompts_sha256(w) != rec["meta"]["prompts_sha256"]:
            raise SystemExit(f"{path} changed after its judge answered; calibrate again")
        if cfg["question"] in cals:
            raise SystemExit(f"two calibrations for the {cfg['question']} question; give one")
        cals[cfg["question"]] = cfg
        paths[cfg["question"]] = path
    for question, on in wanted.items():
        if on and question not in cals:
            raise SystemExit(f"the policy has a {question} threshold; give its calibration")
    # groundgate reads the judge block itself; here only the other policy keys decide the items
    rest = {k: v for k, v in policy.items() if k != "judge"}
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    if wanted["field"]:
        # the field question states the description that was calibrated; a schema that gives the
        # field another meaning needs its own calibration
        then = q.descriptions(cals["field"]["schema"])
        calibrated = cals["field"]["schema"]["fields"]
        for name, description in q.descriptions(schema, all_fields=True).items():
            if name in calibrated and description != then.get(name):
                raise SystemExit(
                    f"the description of {name} differs from the one that {paths['field']} "
                    "calibrated; calibrate again"
                )
    args.out.mkdir(parents=True, exist_ok=True)
    for path in sorted(args.docs.glob("*.txt")):
        doc, text = path.stem, path.read_text(encoding="utf-8")
        cands = json.loads((args.candidates / f"{doc}.json").read_text(encoding="utf-8"))
        out = []
        for question, cfg in sorted(cals.items()):
            if not wanted[question]:
                continue
            for it in q.sample(question, doc, text, schema, cands, rest, wanted["key"]):
                cid = cands[int(it["id"].rsplit(":", 1)[1])].get("id")
                ids = [c.get("id") for c in cands if isinstance(c, dict)]
                same = [x for x in ids if type(x) is type(cid)]
                if type(cid) not in (str, int) or same.count(cid) != 1:
                    # spec 0.4 names a judgment's candidate by a string or integer id
                    raise SystemExit(f"{doc}: a judged candidate needs a unique string or int id")
                st, qs = q.prompt(question, text, it, cfg["context"], cfg["descriptions"])
                a = q.keep(question, call(jd, st, qs, it["id"]))
                j: dict[str, Any] = {
                    "candidate_id": cid,
                    "judge": {"id": jd.id, "digest": jd.digest},
                }
                if question == "key":
                    j |= {
                        "question": "key",
                        "answer": q.chosen(it, a["choice"]),
                        "p": a["confidence"],
                    }
                else:
                    j |= {"question": "field_match", "p": a["p"]}
                out.append(j)
        (args.out / f"{doc}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
        print(f"{doc}: {len(out)} judgments")


def report(w: Work, check: bool, store: Path | None = None) -> None:
    cfg, items = w.config, w.read("items.json")
    labels, parts = w.read("labels.json", {}), w.read("split.json")
    if store is None and not labels and (w.path / "tasks.json").exists():
        raise SystemExit("the labels of this work folder are answers in a store; give --store")
    if store is None:
        missing = [it["id"] for it in items if it["id"] not in labels]
        if missing:
            raise SystemExit(f"{len(missing)} items are not labeled yet")
    results: dict[str, Any] = {"question": cfg["question"], "judges": {}}
    for path in sorted(w.path.glob("answers-*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        given = rec["meta"].get("labels_from")
        if given is not None:
            # the labels as they were when the judge answered, from the answer logs
            if store is None:
                raise SystemExit(f"{path.name} took its labels from a store; give --store")
            labels, _ = stored_labels(w, store, given["reviewer"], given["heads"])
        else:
            labels = w.read("labels.json", {})
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
        "Generated by `groundgate calibrate report`. The threshold for each ceiling comes from "
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


def main(argv: list[str] | None = None, prog: str = "groundgate calibrate") -> None:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sample", help="take the items for one question from your documents")
    p.add_argument("--docs", type=Path, required=True)
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--schema", type=Path, required=True)
    p.add_argument("--question", choices=("key", "field"), required=True)
    p.add_argument(
        "--descriptions",
        type=Path,
        help="JSON: field name to a meaning; overrides schema descriptions",
    )
    p.add_argument("--context", default="", help='for example "The text is from a 10-K filing."')
    p.add_argument(
        "--store", type=Path, metavar="DIR", help="also write a packet and a task for each item"
    )
    p = sub.add_parser("label", help="label the items in the browser")
    p.add_argument("--port", type=int, default=8780)
    p.add_argument("--store", type=Path, metavar="DIR", help="answer on the review page")
    p.add_argument("--reviewer", metavar="NAME", help="the reviewer name of the answer log")
    p = sub.add_parser("split", help="split the items, before any model run")
    p.add_argument(
        "--store",
        type=Path,
        metavar="DIR",
        help="also write the part of each document to the splits log of --set in this store",
    )
    p.add_argument("--set", dest="set_name", metavar="NAME", help="the set of the splits log")
    p = sub.add_parser("ask", help="ask a judge every question")
    p.add_argument(
        "--judge", required=True, help="a judge name: chat, jev, or an installed plug-in"
    )
    p.add_argument("--store", type=Path, metavar="DIR", help="read the labels from this store")
    p.add_argument("--reviewer", metavar="NAME", help="the reviewer whose answers are labels")
    p = sub.add_parser("report", help="write REPORT.md and report.json")
    p.add_argument("--check", action="store_true", help="fail if the written files differ")
    p.add_argument("--store", type=Path, metavar="DIR", help="the store of the labels")
    for s in sub.choices.values():
        s.add_argument("--work", type=Path, required=True, help="the work directory")
    p = sub.add_parser("judge", help="write recorded judgments for your documents")
    p.add_argument("--docs", type=Path, required=True)
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--schema", type=Path, required=True)
    p.add_argument("--policy", type=Path, required=True, help="a policy with a judge block")
    p.add_argument("--calibration", type=Path, nargs="+", required=True, help="work directories")
    p.add_argument("--out", type=Path, required=True, help="a directory for <doc>.json")
    args = ap.parse_args(argv)
    if args.cmd == "judge":
        judge_packets(args)
        return
    w = Work(args.work)
    if args.cmd == "sample":
        sample(w, args.docs, args.candidates, args.schema, args)
    elif args.cmd == "label":
        if args.store is not None or args.reviewer is not None:
            review_serve(w, args.store, args.reviewer, args.port)
        else:
            from .label import serve

            serve(w, args.port)
    elif args.cmd == "split":
        split(w, args.store, args.set_name)
    elif args.cmd == "ask":
        ask(w, args.judge, args.store, args.reviewer)
    else:
        report(w, args.check, args.store)


def judged(w: Work) -> bool:
    """True once a judge run starts in the work folder: the labels are frozen then."""
    return label.judged(w.path)


def label_review(w: Work, store: Any, reviewer: str) -> Any:
    """The review of the tasks of the work folder. Like the label page, it refuses each answer
    once a judge run starts, also while the server runs."""
    from collections.abc import Mapping

    from groundgate.review.serve import Refused, Review

    class Frozen(Review):
        def answer(self, body: Mapping[str, Any]) -> dict[str, Any]:
            with label.labels_lock(w.path):
                if judged(w):
                    raise Refused(409, "the labels are frozen once a judge has answered")
                return super().answer(body)

    return Frozen(store, reviewer, only={t["task"] for t in w.read("tasks.json").values()})


def review_serve(w: Work, store: Path | None, reviewer: str | None, port: int) -> None:
    """Open the review page on the tasks of the work folder (docs/design/review.md §9, §11)."""
    from groundgate.review.serve import server
    from groundgate.store import FolderStore, StoreError

    if store is None or reviewer is None:
        raise SystemExit("give --store and --reviewer together")
    if judged(w):
        raise SystemExit("a judge has answered already; the labels are frozen")
    try:
        with FolderStore(store) as s:
            review = label_review(w, s, reviewer)
            for line in review.skipped:
                print(f"skipped: {line}")
            httpd, url = server(review, port)
            print(f"Open {url} and press Ctrl-C here when you finish.")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                httpd.server_close()
    except (StoreError, ValueError, OSError) as exc:
        raise SystemExit(f"{store}: {exc}") from exc
