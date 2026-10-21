"""Review items of the held-out runner arm, and their score against the sealed labels (#234).

#234 asks: if a person sees an item for the first time, together with groundgate's reading, are
the answers as good as blind labels? This module makes the items and scores the answers. The
person answers in ``groundgate review serve``. No model runs here, and the core does not change.

    PYTHONPATH=bench uv run python -m requested.review_items build --set bench/requested4 \\
        --store bench/requested4/.cache/review/store
    PYTHONPATH=bench uv run python -m requested.review_items score --set bench/requested4 \\
        --store bench/requested4/.cache/review/store --reviewer maintainer [--checks FILE]
    PYTHONPATH=bench uv run python -m requested.review_items report --set bench/requested4

``build`` reads the frozen held-out run of the ``runner`` arm and its sources. It never reads
``labels.json``. For each held-out document it writes a reading of the PDF and a packet to the
store, and it stops if the packet receipt is not the recorded receipt of the run. Then it writes
a ``splits`` record for each document and the tasks of the review policy ``review/policy.json``:
a task for each review slot, and an audit task for a sample of the admitted slots. The sample
is the slots with the smallest audit hash for a fixed seed, so the policy audit rate gives the
same sample. ``review/items.json`` lists each packet and task key. A second build must give the
same keys.

``score`` reads the latest answer of the reviewer to each task, and the sealed labels. It stops
before it reads a label if a task has no answer. An answer agrees with its label when it gives
the labeled value and unit, or ``not_in_document`` for an absent label. ``unsure`` and an
``unclear`` label are not scored. An independent blind check of the original document decides
each disagreement: ``review/checks-needed.json`` names each item to check with no answer and no
label, and ``--checks`` reads the result in the same form as a label. Then the wrong answers are
the disagreements where the check does not give the answer. The bar of #234: the 95% upper
bound of the rate of wrong answers is below 0.05. ``report`` writes ``review/RESULTS.md`` from
``review/results.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import groundgate as gg
from groundgate import jcs
from groundgate.review.resolve import CORRECTIONS, resolve
from groundgate.review.tasks import (
    audit_hash,
    check_policy,
    checked_packet,
    make_tasks,
    write_tasks,
)
from groundgate.store import FolderStore, key, reviewer_key, set_key
from groundgate.store.packets import admit_packet, load_reading, put_reading

from .metrics import signature, upper95
from .run_set import FrozenSet, _settings

Json = dict[str, Any]
ITEMS = "requested-review-items/1"
RESULTS = "requested-review-results/1"
ARM = "runner"
SPLIT = "heldout"
SEED = "requested4-234-audit"
AUDIT = 30
BAR = 0.05
OUTCOMES = ("agree", "wrong", "label_wrong", "pending", "unsure", "unclear")


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


# The held-out run


def heldout(set_dir: Path, cache: Path) -> Iterator[tuple[Json, Json, Json]]:
    """Each held-out document of the runner arm in id order: the manifest entry, the cached
    result and the schema of the run. The cached result must give the published projection."""
    manifest = _load(set_dir / "manifest.json")
    run = _load(set_dir / "runs" / f"{ARM}.json")
    if run.get("arm") != ARM or run.get("split") != SPLIT:
        raise ValueError(f"runs/{ARM}.json is not the {SPLIT} run of the {ARM} arm")
    binding = run["binding_sha256"]
    config = run["provenance"]["configuration"]
    frozen = SimpleNamespace(manifest=manifest, settings=_settings(config["run_policy"]))
    docs = {d["id"]: d for d in manifest["documents"]}
    folder = cache / binding.removeprefix("sha256:") / ARM / SPLIT
    for out in sorted(run["documents"], key=lambda d: str(d["id"])):
        doc = docs[out["id"]]
        if doc["split"] != SPLIT:
            raise ValueError(f"{out['id']} is not a {SPLIT} document")
        result = _load(folder / out["id"] / "result.json")
        if result["binding_sha256"] != binding:
            raise ValueError(f"the cached result of {out['id']} has another binding")
        if result["output"]["decisions"] != out["decisions"]:
            raise ValueError(f"the cached result of {out['id']} is not the published projection")
        schema = FrozenSet.schema(frozen, doc)  # type: ignore[arg-type]
        if _sha(jcs(schema).encode()) != result["schema_sha256"]:
            raise ValueError(f"the schema of {out['id']} is not the schema of the run")
        yield doc, result, schema


def _policy(set_dir: Path) -> Json:
    config = _load(set_dir / "runs" / f"{ARM}.json")["provenance"]["configuration"]
    return gg.Policy.from_dict(config["policy"]).to_dict()


# The audit sample


def audit_rate(hashes: list[int], n: int) -> str:
    """The shortest decimal rate that picks exactly the ``n`` smallest of ``hashes``: H is
    picked when H * 10^d < rate digits * 2^64 (docs/design/review.md section 6.3 point 2)."""
    ordered = sorted(hashes)
    if n >= len(ordered):
        return "1"
    if n == 0:
        return "0"
    last, first_out = ordered[n - 1], ordered[n]
    if last == first_out:
        raise ValueError("two audit slots have the same hash")
    for d in range(1, 19):
        top = last * 10**d // 2**64 + 1  # the smallest numerator that picks ``last``
        if top * 2**64 <= first_out * 10**d:
            digits = str(top).rjust(d, "0").rstrip("0")
            return "0." + digits if digits else "0"
    raise ValueError("no rate of 18 digits separates the sample")


def build(
    set_dir: Path, sources: Path, cache: Path, store_dir: Path, *, audit: int = AUDIT
) -> Json:
    """Write the packets, the splits records and the tasks, and give the items."""
    name = set_dir.name
    policy = _policy(set_dir)
    packets: list[tuple[str, str]] = []
    with FolderStore(store_dir) as store:
        splits = {r["document"]: r["split"] for r in store.read(("splits", set_key(name)))}
        for doc, result, schema in heldout(set_dir, cache):
            ident = doc["id"]
            pdf, txt = sources / f"{ident}.pdf", sources / f"{ident}.txt"
            if _sha(pdf.read_bytes()) != doc["source_sha256"]:
                raise ValueError(f"the source of {ident} is not the frozen source")
            text = txt.read_text(encoding="utf-8")
            if _sha(text.encode("utf-8")) != doc["text_sha256"]:
                raise ValueError(f"the text of {ident} is not the frozen text")
            reading, _ = put_reading(store, pdf)
            if load_reading(store, reading)["text"] != key("text@1", text.encode("utf-8")):
                raise ValueError(f"the reader now gives another text for {ident}")
            pk, receipt = admit_packet(
                store,
                text,
                schema,
                result["candidates"],
                policy,
                ident,
                document_source=doc["source"],
                reading=reading,
            )
            if receipt.to_dict() != result["receipt"]:
                raise ValueError(f"the packet of {ident} does not give the recorded receipt")
            source = load_reading(store, reading)["source"]
            if splits.get(source) not in (None, SPLIT):
                raise ValueError(f"the splits log gives {ident} another split")
            if source not in splits:
                store.append(
                    ("splits", set_key(name)), {"set": name, "document": source, "split": SPLIT}
                )
                splits[source] = SPLIT
            packets.append((ident, pk))
        every = {
            "format": "review-policy@1",
            "audit": {"rate": "1", "seed": SEED},
            "agree": 1,
            "leads": [],
            "rejected": False,
        }
        hashes = []
        for _, pk in packets:
            packet, schema_, layout, problems = checked_packet(store, pk)
            if problems or schema_ is None:
                raise ValueError(f"the packet {pk} does not match its receipt")
            for t in make_tasks(
                pk,
                packet.receipt,
                packet.text,
                schema_,
                every,
                references=packet.references,
                layout=layout,
            ):
                if t["mode"] == "audit":
                    s = t["slot"]
                    multiple = schema_.fields[s["field"]].multiple
                    first = s["decisions"][0] if multiple else None
                    hashes.append(audit_hash(SEED, pk, s["field"], s["key"], first))
        review = {**every, "audit": {"rate": audit_rate(hashes, audit), "seed": SEED}}
        check_policy(review)
        documents = []
        counts = {"review": 0, "audit": 0}
        for ident, pk in packets:
            written = write_tasks(store, pk, review)
            if written.problems:
                raise ValueError(f"the packet {pk} does not match its receipt")
            for _, t in written.tasks:
                counts[t["mode"]] += 1
            documents.append(
                {"id": ident, "packet": pk, "tasks": sorted(k for k, _ in written.tasks)}
            )
    if counts["audit"] != min(audit, len(hashes)):
        raise ValueError("the audit rate does not give the audit sample")
    manifest_sha = _sha((set_dir / "manifest.json").read_bytes())
    runner_sha = _sha((set_dir / "runs" / f"{ARM}.json").read_bytes())
    items = {
        "format": ITEMS,
        "set": name,
        "arm": ARM,
        "split": SPLIT,
        "manifest_sha256": manifest_sha,
        "run_sha256": runner_sha,
        "groundgate": gg.__version__,
        "policy": review,
        "counts": counts,
        "documents": documents,
    }
    out = set_dir / "review"
    if (out / "items.json").exists():
        if _load(out / "items.json") != items:
            raise ValueError("this build gives other items than review/items.json")
    else:
        _dump(out / "items.json", items)
        _dump(out / "policy.json", review)
    return items


# The score


def _answer_value(task: Mapping[str, Any], answer: Mapping[str, Any]) -> Json | None:
    """The value and unit that the answer gives, or None for ``not_in_document``."""
    verdict = answer["verdict"]
    if verdict == "confirm":
        c = task["choices"][0]
    elif verdict == "choose":
        c = next(c for c in task["choices"] if c["decision"] == answer["decision"])
    elif verdict in CORRECTIONS:
        c = answer["candidate"]
    else:
        return None
    return {"value": c["value"], "unit": c.get("unit")}


def _same(given: Json | None, status: str, values: list[Json], kind: str) -> bool:
    """True when the answer value (None: not in the document) is the labeled state."""
    if given is None:
        return status == "absent"
    if status != "present":
        return False
    return signature(given, kind) in {signature(v, kind) for v in values}


def _summary(rows: list[Json]) -> Json:
    counts = {o: sum(r["outcome"] == o for r in rows) for o in OUTCOMES}
    scored = counts["agree"] + counts["wrong"] + counts["label_wrong"]
    pending = counts["pending"]
    followed = [r for r in rows if r["followed"] and r["label"] != "unclear"]
    ms = [r["ms"] for r in rows if isinstance(r["ms"], int)]
    bound = None if pending else upper95(counts["wrong"], scored)
    return {
        "items": len(rows),
        **counts,
        "scored": scored,
        "followed": {
            "n": len(followed),
            "not_label": sum(r["outcome"] != "agree" for r in followed),
        },
        "median_ms": statistics.median(ms) if ms else None,
        "one_key": sum(r["keys"] == 1 for r in rows),
        "wrong_upper95": bound,
        "passes": None if pending or bound is None else bound < BAR,
    }


def score(set_dir: Path, store_dir: Path, reviewer: str, checks: Path | None = None) -> Json:
    """Score the latest answer of ``reviewer`` to each item against the sealed labels."""
    out = set_dir / "review"
    items = _load(out / "items.json")
    if _sha((set_dir / "manifest.json").read_bytes()) != items["manifest_sha256"]:
        raise ValueError("the manifest changed after the items were built")
    policy = check_policy(items["policy"])
    found: list[tuple[str, str, Json, Json, str]] = []
    heads = {}
    missing = 0
    with FolderStore(store_dir) as store:
        for doc in items["documents"]:
            pk = doc["packet"]
            packet, schema, layout, problems = checked_packet(store, pk)
            if problems or schema is None:
                raise ValueError(f"the packet of {doc['id']} does not match its receipt")
            records = store.read(("answers", pk, reviewer_key(reviewer)))
            if any(r.get("reviewer") != reviewer for r in records):
                raise ValueError(f"the answer log of {doc['id']} names another reviewer")
            resolve(pk, packet, schema, policy, {reviewer: records}, layout=layout)  # checks
            heads[doc["id"]] = records[-1]["entry_sha256"] if records else None
            latest = {r["task"]: r for r in records}
            for tk in doc["tasks"]:
                task = json.loads(store.get("task@1", tk))
                if tk not in latest:
                    missing += 1
                    continue
                kind = schema.fields[task["slot"]["field"]].type
                found.append((doc["id"], tk, task, latest[tk], kind))
    if missing:
        raise SystemExit(f"{missing} items have no answer yet: score after the last answer")
    labels = _load(set_dir / "labels.json")  # read only after every item has an answer
    if labels.get("status") != "sealed":
        raise ValueError("the labels are not sealed")
    gold = {
        (d["id"], s["field"], s.get("key")): s for d in labels["documents"] for s in d["fields"]
    }
    checked: dict[str, Json] = {}
    if checks is not None:
        for c in _load(checks)["checks"]:
            checked[c["task"]] = c
    rows, needed = [], []
    for ident, tk, task, answer, kind in found:
        slot = task["slot"]
        label = gold[(ident, slot["field"], slot["key"])]
        given = _answer_value(task, answer)
        if answer["verdict"] == "unsure":
            outcome = "unsure"
        elif label["status"] == "unclear":
            outcome = "unclear"
        elif _same(given, label["status"], label.get("values", []), kind):
            outcome = "agree"
        else:
            page = task["places"][0].get("page") if task["places"] else None
            needed.append(
                {
                    "task": tk,
                    "document": ident,
                    "field": slot["field"],
                    "key": slot["key"],
                    "page": page,
                }
            )
            c = checked.get(tk)
            if c is None:
                outcome = "pending"
            elif c["status"] == "unclear":
                outcome = "unclear"
            elif _same(given, c["status"], c.get("values", []), kind):
                outcome = "label_wrong"
            else:
                outcome = "wrong"
        rows.append(
            {
                "task": tk,
                "document": ident,
                "item": task["item"],
                "mode": task["mode"],
                "field": slot["field"],
                "key": slot["key"],
                "verdict": answer["verdict"],
                "followed": answer["verdict"] in ("confirm", "choose"),
                "reason_seen": answer["reason_seen"],
                "keys": answer["keys"],
                "ms": answer["ms"],
                "label": label["status"],
                "outcome": outcome,
            }
        )
    groups: dict[str, list[Json]] = {}
    for r in rows:
        for g in (r["mode"], r["item"], f"{r['mode']} {r['item']}"):
            groups.setdefault(g, []).append(r)
    results = {
        "format": RESULTS,
        "items_sha256": _sha((out / "items.json").read_bytes()),
        "labels_sha256": _sha((set_dir / "labels.json").read_bytes()),
        "checks_sha256": None if checks is None else _sha(checks.read_bytes()),
        "reviewer": reviewer,
        "heads": heads,
        "bar": {"wrong_upper95_below": BAR},
        "total": _summary(rows),
        "groups": {g: _summary(groups[g]) for g in sorted(groups)},
        "rows": rows,
    }
    _dump(out / "results.json", results)
    _dump(out / "checks-needed.json", {"checks_needed": needed})
    return results


# The report


def report(set_dir: Path) -> str:
    """``review/RESULTS.md`` from ``review/results.json``: each number comes from the file."""
    results = _load(set_dir / "review" / "results.json")

    def line(name: str, s: Json) -> str:
        bound = "pending" if s["wrong_upper95"] is None else f"{s['wrong_upper95']:.4f}"
        ms = "none" if s["median_ms"] is None else f"{s['median_ms']:g}"
        return (
            f"| {name} | {s['items']} | {s['scored']} | {s['agree']} | {s['label_wrong']} | "
            f"{s['wrong']} | {s['pending']} | {s['unsure']} | {s['unclear']} | "
            f"{s['followed']['not_label']} of {s['followed']['n']} | {ms} | {bound} |"
        )

    total = results["total"]
    verdict = {True: "passes", False: "does not pass", None: "waits for the checks"}
    out = [
        "# Review answers against blind labels (#234)",
        "",
        "`bench/requested/review_items.py report` wrote this file from `results.json`, for the",
        f"reviewer `{results['reviewer']}`.",
        f"The bar is a 95% upper bound below {results['bar']['wrong_upper95_below']} for the "
        f"rate of wrong answers. The result {verdict[total['passes']]}.",
        "",
        "| Group | Items | Scored | Agree | Label wrong | Wrong | Pending | Unsure | Unclear "
        "| Followed, not the label | Median ms | Upper 95% |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        line("total", total),
        *(line(g, s) for g, s in results["groups"].items()),
        "",
    ]
    text = "\n".join(out)
    (set_dir / "review" / "RESULTS.md").write_text(text, encoding="utf-8")
    return text


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="write the packets and tasks to a store")
    s = sub.add_parser("score", help="score the answers against the sealed labels")
    r = sub.add_parser("report", help="write review/RESULTS.md from review/results.json")
    for p in (b, s, r):
        p.add_argument("--set", type=Path, required=True, help="the set folder")
    for p in (b, s):
        p.add_argument("--store", type=Path, required=True, help="the store folder")
    b.add_argument("--sources", type=Path, help="the PDF and text files (.cache/run_sources)")
    b.add_argument("--cache", type=Path, help="the run cache (.cache/runs/heldout)")
    s.add_argument("--reviewer", required=True, help="the name of the reviewer")
    s.add_argument("--checks", type=Path, help="the blind checks of the disagreements")
    args = ap.parse_args(argv)
    if args.command == "build":
        sources = args.sources or args.set / ".cache" / "run_sources"
        cache = args.cache or args.set / ".cache" / "runs" / SPLIT
        items = build(args.set, sources, cache, args.store)
        print(f"{len(items['documents'])} packets; tasks: {items['counts']}")
    elif args.command == "score":
        results = score(args.set, args.store, args.reviewer, args.checks)
        pending = results["total"]["pending"]
        print(f"wrote review/results.json; {pending} disagreements wait for a blind check")
    else:
        sys.stdout.write(report(args.set))


if __name__ == "__main__":
    main()
