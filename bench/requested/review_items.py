"""Review items of the runner arm, and their score against the sealed labels (#234, #463).

#234 asks: if a person sees an item for the first time, together with groundgate's reading, are
the answers as good as blind labels? This module makes the items and scores the answers. The
person answers in ``groundgate review serve``. No model runs here, and the core does not change.

    PYTHONPATH=bench uv run python -m requested.review_items build --set bench/requested4 \\
        --store bench/requested4/.cache/review/store
    PYTHONPATH=bench uv run python -m requested.review_items score --set bench/requested4 \\
        --store bench/requested4/.cache/review/store --reviewer maintainer [--checks FILE]
    PYTHONPATH=bench uv run python -m requested.review_items report --set bench/requested4

Each command takes ``--split heldout`` (the default, #234) or ``--split development`` (#463).
The held-out split reads ``runs/runner.json`` and writes to ``review/``. The development split
reads ``development/runs/runner.json`` and writes to ``review/development/``, with its own audit
seed. The splits log of the store records the split of each document.

``build`` reads the cached run of the ``runner`` arm on the split and its sources. It never reads
``labels.json``. For each document of the split it writes a reading of the PDF and a packet to the
store, and it stops if the packet receipt is not the recorded receipt of the run. Then it writes
a ``splits`` record for each document and the tasks of the review policy ``review/policy.json``:
a task for each review slot, and an audit task for a sample of the admitted slots. The sample
is the slots with the smallest audit hash for a fixed seed, so the policy audit rate gives the
same sample. ``review/items.json`` lists each packet and task key. A second build must give the
same keys.

``score`` reads the latest answer of the reviewer to each task, and the sealed labels. It stops
before it reads a label if a task has no answer. An answer agrees with its label when it gives
the labeled value and unit, or ``not_in_document`` for an absent label. ``unsure`` and an
``unclear`` label are not scored. For a field with more than one value, an answer agrees when
its value is one of the labeled values. An independent blind check of the original document decides
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
# The audit seed and the issue of each split. A new seed for the development split gives a
# sample that no held-out choice made.
SPLITS = {
    "heldout": {"seed": SEED, "issue": "#234"},
    "development": {"seed": "requested4-463-audit", "issue": "#463"},
}
AUDIT = 30
BAR = 0.05
# ``report`` keeps the lines of RESULTS.md from this marker on: the sections written by hand.
MARKER = "`report` does not write the sections below."
OUTCOMES = ("agree", "wrong", "label_wrong", "pending", "unsure", "unclear")


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


# The run of the split


def _split(split: str) -> Json:
    if split not in SPLITS:
        raise ValueError(f"unknown split: {split}")
    return SPLITS[split]


def run_path(set_dir: Path, split: str) -> Path:
    """The projection of the runner arm on ``split``."""
    _split(split)
    folder = set_dir if split == "heldout" else set_dir / split
    return folder / "runs" / f"{ARM}.json"


def out_dir(set_dir: Path, split: str) -> Path:
    """The folder of the items, the policy, the results and the report of ``split``."""
    _split(split)
    return set_dir / "review" if split == "heldout" else set_dir / "review" / split


def run_documents(
    set_dir: Path, cache: Path, split: str = SPLIT
) -> Iterator[tuple[Json, Json, Json]]:
    """Each document of the runner arm on ``split`` in id order: the manifest entry, the cached
    result and the schema of the run. The cached result must give the published projection."""
    manifest = _load(set_dir / "manifest.json")
    run = _load(run_path(set_dir, split))
    if run.get("arm") != ARM or run.get("split") != split:
        raise ValueError(f"{run_path(set_dir, split).name} is not the {split} run of {ARM}")
    binding = run["binding_sha256"]
    config = run["provenance"]["configuration"]
    frozen = SimpleNamespace(manifest=manifest, settings=_settings(config["run_policy"]), terms={})
    docs = {d["id"]: d for d in manifest["documents"]}
    folder = cache / binding.removeprefix("sha256:") / ARM / split
    for out in sorted(run["documents"], key=lambda d: str(d["id"])):
        doc = docs[out["id"]]
        if doc["split"] != split:
            raise ValueError(f"{out['id']} is not a {split} document")
        result = _load(folder / out["id"] / "result.json")
        if result["binding_sha256"] != binding:
            raise ValueError(f"the cached result of {out['id']} has another binding")
        if result["output"]["decisions"] != out["decisions"]:
            raise ValueError(f"the cached result of {out['id']} is not the published projection")
        schema = FrozenSet.schema(frozen, doc)  # type: ignore[arg-type]
        if _sha(jcs(schema).encode()) != result["schema_sha256"]:
            raise ValueError(f"the schema of {out['id']} is not the schema of the run")
        yield doc, result, schema


def _policy(set_dir: Path, split: str) -> Json:
    config = _load(run_path(set_dir, split))["provenance"]["configuration"]
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
    set_dir: Path,
    sources: Path,
    cache: Path,
    store_dir: Path,
    *,
    audit: int = AUDIT,
    split: str = SPLIT,
) -> Json:
    """Write the packets, the splits records and the tasks, and give the items."""
    name = set_dir.name
    seed = _split(split)["seed"]
    policy = _policy(set_dir, split)
    packets: list[tuple[str, str]] = []
    with FolderStore(store_dir) as store:
        splits = {r["document"]: r["split"] for r in store.read(("splits", set_key(name)))}
        for doc, result, schema in run_documents(set_dir, cache, split):
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
            if splits.get(source) not in (None, split):
                raise ValueError(f"the splits log gives {ident} another split")
            if source not in splits:
                store.append(
                    ("splits", set_key(name)), {"set": name, "document": source, "split": split}
                )
                splits[source] = split
            packets.append((ident, pk))
        every = {
            "format": "review-policy@1",
            "audit": {"rate": "1", "seed": seed},
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
                    hashes.append(audit_hash(seed, pk, s["field"], s["key"], first))
        review = {**every, "audit": {"rate": audit_rate(hashes, audit), "seed": seed}}
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
    runner_sha = _sha(run_path(set_dir, split).read_bytes())
    items = {
        "format": ITEMS,
        "set": name,
        "arm": ARM,
        "split": split,
        "manifest_sha256": manifest_sha,
        "run_sha256": runner_sha,
        "groundgate": gg.__version__,
        "policy": review,
        "counts": counts,
        "documents": documents,
    }
    out = out_dir(set_dir, split)
    if (out / "items.json").exists():
        if _load(out / "items.json") != items or _load(out / "policy.json") != review:
            raise ValueError("this build gives other items than its items.json and policy.json")
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


def _checks(raw: Any) -> dict[str, Json]:
    """The blind check of each task, from a ``{"checks": [...]}`` file. Each check has the
    form of a label: ``task``, ``status``, and ``values`` for a present value."""
    if not isinstance(raw, dict) or not isinstance(raw.get("checks"), list):
        raise ValueError('the checks file must be {"checks": [...]}')
    out: dict[str, Json] = {}
    for c in raw["checks"]:
        if not isinstance(c, dict) or not isinstance(c.get("task"), str):
            raise ValueError("each check needs a task key")
        if c.get("status") not in ("present", "absent", "unclear"):
            raise ValueError(f"the check of {c['task']} needs a status: present, absent, unclear")
        values = c.get("values", [])
        if (c["status"] == "present") != bool(values) or not isinstance(values, list):
            raise ValueError(f"the check of {c['task']} needs values only when it is present")
        for v in values:
            if not isinstance(v, dict) or set(v) != {"value", "unit"}:
                raise ValueError(f"each value of the check of {c['task']} needs value and unit")
        if c["task"] in out:
            raise ValueError(f"two checks name the task {c['task']}")
        out[c["task"]] = c
    return out


def score(
    set_dir: Path,
    store_dir: Path,
    reviewer: str,
    checks: Path | None = None,
    split: str = SPLIT,
) -> Json:
    """Score the latest answer of ``reviewer`` to each item against the sealed labels."""
    out = out_dir(set_dir, split)
    items = _load(out / "items.json")
    if items.get("split") != split:
        raise ValueError(f"the items of {out} are not of the {split} split")
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
    checked = {} if checks is None else _checks(_load(checks))
    rows, needed = [], []
    for ident, tk, task, answer, kind in found:
        slot = task["slot"]
        label = gold.get((ident, slot["field"], slot["key"]))
        if label is None:
            raise ValueError(f"labels.json has no label for {ident} {slot['field']}")
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
    extra = sorted(set(checked) - {c["task"] for c in needed})
    if extra:
        raise ValueError(f"the checks name {len(extra)} tasks that are not a disagreement")
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


def report(set_dir: Path, split: str = SPLIT) -> str:
    """``RESULTS.md`` from ``results.json`` in the folder of ``split``: each number comes from
    the file. A line that starts with ``MARKER`` in the old file, and each line after it, stay
    as they are."""
    out_folder = out_dir(set_dir, split)
    results = _load(out_folder / "results.json")
    issue = _split(split)["issue"]

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
        f"# Review answers against blind labels ({issue})",
        "",
        "`bench/requested/review_items.py report` wrote this file from `results.json`, for the",
        f"reviewer `{results['reviewer']}`."
        + ("" if split == SPLIT else f" The items are of the {split} split."),
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
    target = out_folder / "RESULTS.md"
    if target.exists():
        # Keep the hand-written sections: each line from the marker to the end of the file.
        # The blank lines before the marker stay too. The table ends with one newline.
        old = target.read_text(encoding="utf-8")
        at = old.find("\n" + MARKER)
        if at >= 0:
            start = len(old[: at + 1].rstrip("\n")) + 1
            text += old[start:]
    target.write_text(text, encoding="utf-8")
    return text


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="write the packets and tasks to a store")
    s = sub.add_parser("score", help="score the answers against the sealed labels")
    r = sub.add_parser("report", help="write RESULTS.md from results.json")
    for p in (b, s, r):
        p.add_argument("--set", type=Path, required=True, help="the set folder")
        p.add_argument(
            "--split", choices=sorted(SPLITS), default=SPLIT, help="the split (default heldout)"
        )
    for p in (b, s):
        p.add_argument("--store", type=Path, required=True, help="the store folder")
    b.add_argument("--sources", type=Path, help="the PDF and text files (.cache/run_sources)")
    b.add_argument("--cache", type=Path, help="the run cache (default .cache/runs/heldout)")
    s.add_argument("--reviewer", required=True, help="the name of the reviewer")
    s.add_argument("--checks", type=Path, help="the blind checks of the disagreements")
    args = ap.parse_args(argv)
    if args.command == "build":
        sources = args.sources or args.set / ".cache" / "run_sources"
        if args.cache is None and args.split != SPLIT:
            ap.error("a development build needs --cache")
        cache = args.cache or args.set / ".cache" / "runs" / SPLIT
        items = build(args.set, sources, cache, args.store, split=args.split)
        print(f"{len(items['documents'])} packets; tasks: {items['counts']}")
    elif args.command == "score":
        results = score(args.set, args.store, args.reviewer, args.checks, args.split)
        pending = results["total"]["pending"]
        where = out_dir(args.set, args.split) / "results.json"
        print(f"wrote {where}; {pending} disagreements wait for a blind check")
    else:
        sys.stdout.write(report(args.set, args.split))


if __name__ == "__main__":
    main()
