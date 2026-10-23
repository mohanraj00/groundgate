"""The review items of #234 on a synthetic set with two held-out PDF documents.

doc-a gives two readings of ``max_v`` (a review task with two choices), one admitted ``min_v``
and one admitted ``code``. doc-b gives one admitted ``max_v``. So the build finds 1 review slot
and 3 admitted slots. With an audit sample of 3, it writes 4 tasks.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "tests"))
sys.path.insert(0, str(Path(__file__).parents[1]))
from requested import review_items

import groundgate as gg
from groundgate import jcs
from groundgate.read import read
from groundgate.review.serve import Review
from groundgate.store import FolderStore, set_key

from pdfgen import make_pdf

RUN_POLICY = {
    "chunk_chars": 60000,
    "overlap_chars": 2000,
    "max_repair_rounds": 2,
    "targeted": True,
    "search_context_chars": 4000,
    "max_target_regions": 8,
    "max_calls": 256,
    "max_prompt_chars": 131072,
    "max_reply_bytes": 1048576,
    "max_candidates_per_reply": 256,
    "max_total_candidates": 2048,
    "max_admission_bytes": 33554432,
}
SCHEMA = {
    "fields": {
        "max_v": {"type": "number", "unit": "V"},
        "min_v": {"type": "number", "unit": "V"},
        "code": {"type": "string"},
    }
}
PAGES = {
    "doc-a": [
        (72, 700, "Supply voltage max 5.5 V"),
        (72, 680, "Absolute max 6.0 V"),
        (72, 660, "Supply voltage min 1.8 V"),
        (72, 640, "Code AB-12"),
    ],
    "doc-b": [(72, 700, "Supply voltage max 3.6 V")],
}
CANDIDATES = {
    "doc-a": [
        {
            "id": "a1",
            "field": "max_v",
            "value": "5.5",
            "unit": "V",
            "evidence": [{"text": "5.5 V"}],
        },
        {
            "id": "a2",
            "field": "max_v",
            "value": "6.0",
            "unit": "V",
            "evidence": [{"text": "6.0 V"}],
        },
        {
            "id": "a3",
            "field": "min_v",
            "value": "1.8",
            "unit": "V",
            "evidence": [{"text": "1.8 V"}],
        },
        {"id": "a4", "field": "code", "value": "AB-12", "evidence": [{"text": "AB-12"}]},
    ],
    "doc-b": [
        {
            "id": "b1",
            "field": "max_v",
            "value": "3.6",
            "unit": "V",
            "evidence": [{"text": "3.6 V"}],
        },
    ],
}
BINDING = "sha256:" + "c" * 64


def sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def make_set(root: Path, split: str = "heldout") -> tuple[Path, Path, Path]:
    set_dir, sources = root / "requested9", root / "sources"
    cache = root / "cache"
    sources.mkdir()
    documents, outputs = [], []
    policy = gg.Policy.from_dict({}).to_dict()
    for ident, lines in PAGES.items():
        pdf = sources / f"{ident}.pdf"
        pdf.write_bytes(make_pdf([lines]))
        text = read(pdf).text
        (sources / f"{ident}.txt").write_text(text, encoding="utf-8")
        doc = {
            "id": ident,
            "kind": "part",
            "split": split,
            "source": f"https://x.test/{ident}",
            "source_sha256": sha(pdf.read_bytes()),
            "text_sha256": sha(text.encode()),
        }
        documents.append(doc)
        receipt = gg.admit(
            text, SCHEMA, CANDIDATES[ident], policy, ident, document_source=doc["source"]
        ).to_dict()
        decisions = [{"field": d["field"], "outcome": d["outcome"]} for d in receipt["decisions"]]
        result = {
            "binding_sha256": BINDING,
            "candidates": CANDIDATES[ident],
            "receipt": receipt,
            "output": {"decisions": decisions},
            "schema_sha256": sha(jcs(gg.Schema.from_dict(SCHEMA).to_dict()).encode()),
        }
        folder = cache / BINDING.removeprefix("sha256:") / "runner" / split / ident
        folder.mkdir(parents=True)
        (folder / "result.json").write_text(json.dumps(result), encoding="utf-8")
        outputs.append({"id": ident, "decisions": decisions})
    runs = set_dir / "runs" if split == "heldout" else set_dir / split / "runs"
    runs.mkdir(parents=True)
    manifest = {"schemas": {"part": SCHEMA}, "documents": documents}
    (set_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    run = {
        "arm": "runner",
        "split": split,
        "binding_sha256": BINDING,
        "documents": outputs,
        "provenance": {"configuration": {"policy": {}, "run_policy": RUN_POLICY}},
    }
    (runs / "runner.json").write_text(json.dumps(run), encoding="utf-8")
    return set_dir, sources, cache


def labels(set_dir: Path, max_a: str) -> None:
    def present(field: str, value: str, unit: str | None) -> dict[str, Any]:
        return {
            "field": field,
            "key": None,
            "status": "present",
            "values": [{"value": value, "unit": unit}],
        }

    docs = [
        {
            "id": "doc-a",
            "fields": [
                present("max_v", max_a, "V"),
                present("min_v", "1.8", "V"),
                present("code", "AB-12", None),
            ],
        },
        {
            "id": "doc-b",
            "fields": [
                {"field": "max_v", "key": None, "status": "unclear"},
                {"field": "min_v", "key": None, "status": "absent"},
                {"field": "code", "key": None, "status": "absent"},
            ],
        },
    ]
    body = {"status": "sealed", "documents": docs}
    (set_dir / "labels.json").write_text(json.dumps(body), encoding="utf-8")


def test_build_score_and_report(tmp_path: Path) -> None:
    set_dir, sources, cache = make_set(tmp_path)
    store_dir = tmp_path / "store"
    items = review_items.build(set_dir, sources, cache, store_dir, audit=3)
    assert items["counts"] == {"review": 1, "audit": 3}
    assert [d["id"] for d in items["documents"]] == ["doc-a", "doc-b"]
    assert items["policy"]["audit"]["seed"] == review_items.SEED
    assert review_items.build(set_dir, sources, cache, store_dir, audit=3) == items  # same keys
    policy = set_dir / "review" / "policy.json"
    policy.write_text(policy.read_text().replace(review_items.SEED, "other"), encoding="utf-8")
    with pytest.raises(ValueError, match="other items"):
        review_items.build(set_dir, sources, cache, store_dir, audit=3)
    policy.write_text(json.dumps(items["policy"]), encoding="utf-8")
    with FolderStore(store_dir) as store:
        splits = store.read(("splits", set_key("requested9")))
    assert sorted(r["split"] for r in splits) == ["heldout", "heldout"]

    # No label is read before each item has an answer: labels.json does not exist yet.
    with pytest.raises(SystemExit, match="4 items have no answer yet"):
        review_items.score(set_dir, store_dir, "ana")

    with FolderStore(store_dir) as store:
        review = Review(store, "ana")
        base = {"codes_kept": [], "reason_seen": False, "keys": 1, "ms": 1000}
        for entry in review.queue()["tasks"]:
            view = review.view(entry["task"])
            if len(view["choices"]) > 1:  # max_v of doc-a: choose 6.0
                six = next(c for c in view["choices"] if c["shown"].startswith("6"))
                body = {
                    **base,
                    "task": entry["task"],
                    "verdict": "choose",
                    "decision": six["decision"],
                    "ms": 3000,
                }
            else:
                body = {**base, "task": entry["task"], "verdict": "confirm", "decision": None}
            review.answer(body)
    labels(set_dir, "5.5")
    results = review_items.score(set_dir, store_dir, "ana")
    total = results["total"]
    assert (total["items"], total["agree"], total["unclear"]) == (4, 2, 1)
    assert total["pending"] == 1 and total["passes"] is None and total["wrong_upper95"] is None
    needed = json.loads((set_dir / "review" / "checks-needed.json").read_text())["checks_needed"]
    assert [(c["document"], c["field"]) for c in needed] == [("doc-a", "max_v")]
    assert set(needed[0]) == {"task", "document", "field", "key", "page"}  # blind: no values
    assert total["followed"] == {"n": 3, "not_label": 1}

    checks = tmp_path / "checks.json"
    check = {
        "task": needed[0]["task"],
        "status": "present",
        "values": [{"value": "5.5", "unit": "V"}],
    }
    checks.write_text(json.dumps({"checks": [check]}), encoding="utf-8")
    total = review_items.score(set_dir, store_dir, "ana", checks)["total"]
    assert (total["wrong"], total["pending"], total["label_wrong"]) == (1, 0, 0)
    assert total["passes"] is False and total["wrong_upper95"] is not None

    other = {"task": "sha256:" + "d" * 64, "status": "absent"}  # not a disagreement
    for bad, why in (
        ({"checks": [{**check, "status": "maybe"}]}, "needs a status"),
        ({"checks": [{**check, "values": []}]}, "needs values only when it is present"),
        ({"checks": [{**check, "values": [{"val": "85"}]}]}, "needs value and unit"),
        ({"checks": [check, other]}, "1 tasks that are not a disagreement"),
    ):
        checks.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match=why):
            review_items.score(set_dir, store_dir, "ana", checks)

    check["values"] = [{"value": "6", "unit": "V"}]  # the check gives the answer: label wrong
    checks.write_text(json.dumps({"checks": [check]}), encoding="utf-8")
    total = review_items.score(set_dir, store_dir, "ana", checks)["total"]
    assert (total["wrong"], total["label_wrong"]) == (0, 1)
    text = review_items.report(set_dir)
    assert "| total | 4 |" in text and (set_dir / "review" / "RESULTS.md").exists()
    notes = review_items.MARKER + " I wrote them.\n\n## The result\n\nBy hand.\n"
    results_md = set_dir / "review" / "RESULTS.md"
    results_md.write_text(text + notes, encoding="utf-8")
    assert review_items.report(set_dir) == text + notes  # the hand-written sections stay
    assert results_md.read_text(encoding="utf-8") == text + notes


def test_development_split(tmp_path: Path) -> None:
    set_dir, sources, cache = make_set(tmp_path, "development")
    store_dir = tmp_path / "store"
    with pytest.raises(FileNotFoundError):  # the held-out run is not there
        review_items.build(set_dir, sources, cache, store_dir, audit=3)
    items = review_items.build(set_dir, sources, cache, store_dir, audit=3, split="development")
    assert items["split"] == "development" and items["counts"] == {"review": 1, "audit": 3}
    seed = review_items.SPLITS["development"]["seed"]
    assert items["policy"]["audit"]["seed"] == seed != review_items.SEED
    out = set_dir / "review" / "development"
    assert (out / "items.json").exists() and not (set_dir / "review" / "items.json").exists()
    with FolderStore(store_dir) as store:
        splits = store.read(("splits", set_key("requested9")))
    assert sorted(r["split"] for r in splits) == ["development", "development"]
    with pytest.raises(FileNotFoundError):  # no held-out items
        review_items.score(set_dir, store_dir, "ana")
    with FolderStore(store_dir) as store:
        review = Review(store, "ana")
        for entry in review.queue()["tasks"]:
            view = review.view(entry["task"])
            body = {
                "task": entry["task"],
                "verdict": "unsure",
                "decision": None,
                "codes_kept": [],
                "reason_seen": False,
                "keys": 1,
                "ms": 1000,
            }
            if len(view["choices"]) == 1:  # max_v of doc-a has two choices: unsure
                body["verdict"] = "confirm"
            review.answer(body)
    labels(set_dir, "5.5")
    total = review_items.score(set_dir, store_dir, "ana", split="development")["total"]
    assert (total["items"], total["unsure"]) == (4, 1)
    text = review_items.report(set_dir, "development")
    assert text.startswith("# Review answers against blind labels (#463)")
    assert "of the development split" in text and (out / "RESULTS.md").exists()


def test_build_refuses_another_receipt(tmp_path: Path) -> None:
    set_dir, sources, cache = make_set(tmp_path)
    path = cache / BINDING.removeprefix("sha256:") / "runner" / "heldout" / "doc-b" / "result.json"
    result = json.loads(path.read_text())
    result["candidates"][0]["value"] = "3.7"
    path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="does not give the recorded receipt"):
        review_items.build(set_dir, sources, cache, tmp_path / "store", audit=1)


def test_audit_rate_picks_the_smallest() -> None:
    hashes = [5 * 2**60, 2**62, 3 * 2**61, 2**63]
    for n in range(5):
        rate = review_items.audit_rate(hashes, n)
        whole, _, digits = rate.partition(".")
        picked = [h for h in hashes if h * 10 ** len(digits) < int(whole + digits) * 2**64]
        assert sorted(picked) == sorted(hashes)[:n]
