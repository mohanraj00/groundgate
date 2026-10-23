"""The items of the Codex judge for one split of bench/requested4 (#67).

An item is one field of the `runner` arm that ends in review with at least one candidate: the
field has no admitted value, and at least one decision for it is `needs_verification`. Each
review decision is a candidate. Its value already holds the printed scale, so the candidate has
no scale. Its spans are the evidence span and the cited parts of the decision receipt.

    uv run python bench/judges/codex/items.py \\
        --run bench/requested4/loop/04/runs/runner.json \\
        --results CACHE/runs/loop04/BINDING/runner/development \\
        --texts CACHE/run_sources --out CACHE/judge/items-development.json

The committed run file selects the items. The run cache gives the receipt spans, and its
decisions must be the same as the committed ones. The reader texts must have the manifest
`text_sha256`. The items file holds the whole reader text, so it stays in the ignored cache.
A held-out run file is refused unless `--allow-heldout` is given: the held-out run needs the
maintainer's approval.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

Json = dict[str, Any]
ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "bench" / "requested4" / "manifest.json"
KINDS = {
    "annual": "an annual report",
    "component": "a component datasheet",
    "sbc": "a Summary of Benefits and Coverage",
    "sds": "a safety data sheet",
}
DECISION = ("candidate_id", "field", "key", "value", "unit", "outcome")

_spec = importlib.util.spec_from_file_location("codex_judge", Path(__file__).with_name("judge.py"))
assert _spec and _spec.loader
judge = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("codex_judge", judge)
_spec.loader.exec_module(judge)


class ItemsError(Exception):
    """An input that the item builder refuses."""


def review_fields(decisions: list[Json]) -> dict[str, list[Json]]:
    """The review decisions of each field that has no admitted value and at least one review
    decision, by field, in the run order."""
    admitted = {d["field"] for d in decisions if d["outcome"] == "admitted"}
    out: dict[str, list[Json]] = {}
    for d in decisions:
        if d["outcome"] == "needs_verification" and d["field"] not in admitted:
            out.setdefault(d["field"], []).append(d)
    return out


def item_id(doc: str, field: str) -> str:
    return f"{doc}/{field}"


def spans(text: str, receipt: Json) -> list[list[int]]:
    """The code point spans of the evidence and the cited parts of one receipt decision."""
    if receipt.get("source") != "document":
        raise ItemsError(f"{receipt.get('candidate_id')}: the evidence is not in the document")
    raw = [receipt.get("evidence"), *receipt.get("parts", [])]
    got: list[list[int]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        a, b = judge.code_point_span(text, r["start"], r["end"])
        if [a, b] not in got:
            got.append([a, b])
    if not got:
        raise ItemsError(f"{receipt.get('candidate_id')}: the decision cites no span")
    return sorted(got)


def description(field: Json, context: Json | None) -> str:
    """The field description, then the request of the document, as the runner got it."""
    text = field["description"]
    if context:
        text += f" The request: {context['subject']}. {context['scope']}"
    return text


def build(
    run: Json, manifest: Json, results: Path, texts: Path, allow_heldout: bool = False
) -> list[Json]:
    split = run.get("split")
    if split not in judge.SPLITS:
        raise ItemsError("the run file has no known split")
    if split != "development" and not allow_heldout:
        raise ItemsError("a held-out run; the held-out run needs approval")
    docs = {d["id"]: d for d in manifest["documents"]}
    items: list[Json] = []
    for out in sorted(run["documents"], key=lambda d: d["id"]):
        doc = docs[out["id"]]
        if doc["split"] != split:
            raise ItemsError(f"{out['id']}: the manifest puts it in {doc['split']}")
        fields = review_fields(out["decisions"])
        if not fields:
            continue
        cached = judge._load_json(results / out["id"] / "result.json")
        if [[d.get(k) for k in DECISION] for d in cached["output"]["decisions"]] != [
            [d.get(k) for k in DECISION] for d in out["decisions"]
        ]:
            raise ItemsError(f"{out['id']}: the cached decisions differ from the run file")
        receipts = cached["receipt"]["decisions"]
        if len(receipts) != len(out["decisions"]):
            raise ItemsError(f"{out['id']}: the receipt has another number of decisions")
        raw = (texts / f"{out['id']}.txt").read_bytes()
        if "sha256:" + hashlib.sha256(raw).hexdigest() != doc["text_sha256"]:
            raise ItemsError(f"{out['id']}: the reader text is not the manifest text")
        text = raw.decode("utf-8")
        schema = doc.get("schema", manifest["schemas"][doc["kind"]])
        by_candidate = {
            (r["candidate_id"], r["field"], r["value"]): r
            for r in receipts
            if r["outcome"] == "needs_verification"
        }
        for name, decisions in fields.items():
            candidates = []
            for d in decisions:
                receipt = by_candidate[(d["candidate_id"], d["field"], d["value"])]
                candidates.append(
                    {
                        "value": d["value"],
                        "scale": None,
                        "unit": d["unit"],
                        "spans": spans(text, receipt),
                    }
                )
            items.append(
                judge.check_item(
                    {
                        "id": item_id(out["id"], name),
                        "doc": out["id"],
                        "split": split,
                        "document": KINDS[doc["kind"]],
                        "field": name,
                        "description": description(
                            schema["fields"][name], doc.get("request_context")
                        ),
                        "text": text,
                        "candidates": candidates,
                    }
                )
            )
    return items


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", type=Path, required=True, help="a committed runs/runner.json")
    ap.add_argument("--results", type=Path, required=True, help="the run cache of that split")
    ap.add_argument("--texts", type=Path, required=True, help="the folder of reader texts")
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-heldout", action="store_true")
    args = ap.parse_args(argv)
    try:
        run = judge._load_json(args.run)
        manifest = judge._load_json(args.manifest)
        items = build(run, manifest, args.results, args.texts, args.allow_heldout)
        body = json.dumps(
            {"format": judge.ITEMS_FORMAT, "items": items}, ensure_ascii=False, sort_keys=True
        )
        judge._write(args.out, body)
    except (ItemsError, judge.JudgeError, OSError, KeyError) as e:
        raise SystemExit(f"items: {e}") from e
    print(f"wrote {args.out}: {len(items)} items")


if __name__ == "__main__":
    main(sys.argv[1:])
