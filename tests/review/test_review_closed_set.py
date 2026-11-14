"""The closed_set item kind of review (docs/design/review.md §7, SPEC §2.3, #530)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from groundgate.review import format_schema
from groundgate.review.measures import lines as measure_lines
from groundgate.review.measures import measures
from groundgate.review.resolve import AnswerError, write_resolution
from groundgate.review.serve import Refused, Review
from groundgate.review.tasks import write_tasks
from groundgate.store import FolderStore, reviewer_key
from groundgate.store.packets import admit_packet

CLOCK = datetime(2026, 11, 13, 9, 30, tzinfo=timezone.utc)
TEXT = "Billing is monthly. Billing was annual before 2020.\nThe term is 12 months.\n"
OPTIONS = ["monthly", "quarterly", "annual"]
SCHEMA = {"fields": {"billing": {"type": "string", "options": OPTIONS},
                     "term": {"type": "string"}}}  # fmt: skip
CANDS = [
    {
        "id": "a",
        "field": "billing",
        "value": "monthly",
        "evidence": [{"text": "Billing is monthly"}],
    },
    {
        "id": "b",
        "field": "billing",
        "value": "annual",
        "evidence": [{"text": "Billing was annual"}],
    },
    {"id": "c", "field": "term", "value": "12 months", "evidence": [{"text": "12 months"}]},
]


def stored(root: Path) -> tuple[FolderStore, str, str, dict[str, Any]]:
    """A store with a packet whose closed field has two candidates, and its tasks."""
    store = FolderStore(root)
    k, receipt = admit_packet(store, TEXT, SCHEMA, CANDS)
    codes = {d["candidate_id"]: d["codes"] for d in receipt.to_dict()["decisions"]}
    assert codes["a"] == codes["b"] == ["CONFLICTING_CANDIDATES"]
    written = write_tasks(store, k)
    tk, task = next((tk, t) for tk, t in written.tasks if t["slot"]["field"] == "billing")
    return store, k, tk, task


def body(tk: str, verdict: str, **more: Any) -> dict[str, Any]:
    return {"task": tk, "verdict": verdict, "decision": None, "codes_kept": [],
            "reason_seen": False, "keys": 1, "ms": 1500, **more}  # fmt: skip


def test_a_field_with_options_gives_a_closed_set_task(tmp_path: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    store, _k, _, task = stored(tmp_path / "s")
    with store:
        jsonschema.Draft202012Validator(format_schema("task@1")).validate(task)
        assert (task["item"], task["template"]) == ("closed_set", "closed_set@1")
        assert task["options"] == OPTIONS
        assert task["question"] == "Which option is the billing?"
        assert task["parts"] == ["option", "field"]
        assert [c["shown"] for c in task["choices"]] == ['"monthly"', '"annual"'] or [
            c["shown"] for c in task["choices"]
        ] == ['"annual"', '"monthly"']


def test_a_task_of_another_string_field_has_no_options(tmp_path: Path) -> None:
    store = FolderStore(tmp_path / "s")
    with store:
        doubt = [{"start": 64, "end": 66, "confidence": 0.1}]
        k, _ = admit_packet(store, TEXT, SCHEMA, CANDS[2:], {"min_read_confidence": 0.5},
                            doubt=doubt)  # fmt: skip
        (task,) = [t for _, t in write_tasks(store, k).tasks if t["slot"]["field"] == "term"]
        assert task["item"] == "text" and "options" not in task


def test_one_choice_asks_if_no_other_option_fits(tmp_path: Path) -> None:
    store = FolderStore(tmp_path / "s")
    with store:
        doubt = [{"start": 11, "end": 18, "confidence": 0.1}]
        k, _ = admit_packet(store, TEXT, SCHEMA, CANDS[:1], {"min_read_confidence": 0.5},
                            doubt=doubt)  # fmt: skip
        (task,) = [t for _, t in write_tasks(store, k).tasks if t["slot"]["field"] == "billing"]
        assert task["question"] == 'Is "monthly" the billing, and does no other option fit?'


def test_the_page_shows_the_options_and_takes_no_correction(tmp_path: Path) -> None:
    store, k, tk, task = stored(tmp_path / "s")
    with store:
        review = Review(store, "ana", clock=lambda: CLOCK)
        view = review.view(tk)
        assert view["item"] == "closed_set" and view["options"] == OPTIONS
        other = next(t for t in review.tasks if t != tk) if len(review.tasks) > 1 else None
        if other is not None:
            assert review.view(other)["options"] is None
        for verdict in ("correct", "adjust_span", "wrong"):
            with pytest.raises(Refused, match="closed_set task takes only"):
                review.answer(body(tk, verdict))
        with pytest.raises(Refused, match="takes no correction"):
            review.check({"task": tk, "verdict": "correct"})
        assert store.read(("answers", k, reviewer_key("ana"))) == []
        second = task["choices"][1]["decision"]
        review.answer(body(tk, "choose", decision=second))
        (record,) = store.read(("answers", k, reviewer_key("ana")))
        assert record["format"] == "answer@1" and record["decision"] == second
        resolved = write_resolution(store, k, None, ["ana"])
        assert resolved.resolution is not None
        slot = next(s for s in resolved.resolution["slots"] if s["field"] == "billing")
        assert slot["status"] == "chosen"
        assert slot["value"] == task["choices"][1]["value"]
        found = measures(store).kinds["closed_set"]
        assert found["answers"] == 1 and found["other_option"] == [1, 1]
        line = next(x for x in measure_lines(measures(store)) if x.startswith("closed_set:"))
        assert "another option 1 of 1" in line


def test_resolve_refuses_a_correction_record_of_a_closed_set_task(tmp_path: Path) -> None:
    store, k, tk, task = stored(tmp_path / "s")
    with store:
        review = Review(store, "ana", clock=lambda: CLOCK)
        review.answer(body(tk, "choose", decision=task["choices"][0]["decision"]))
        (record,) = store.read(("answers", k, reviewer_key("ana")))
        log = ("answers", k, reviewer_key("ben"))
        kept = {m: v for m, v in record.items()
                if m not in ("sequence", "previous", "entry_sha256")}  # fmt: skip
        store.append(log, {**kept, "reviewer": "ben", "verdict": "wrong", "decision": None,
                           "format": "answer@2", "field_keys": None})  # fmt: skip
        with pytest.raises(AnswerError, match="closed_set task takes only"):
            write_resolution(store, k, None, ["ben"])


def test_the_same_option_from_another_candidate_is_not_another_option(tmp_path: Path) -> None:
    text = "Billing is monthly. Each invoice is monthly.\n"
    cands = [
        {"id": "a", "field": "billing", "value": "monthly", "evidence": [{"text": "is monthly."}]},
        {
            "id": "b",
            "field": "billing",
            "value": "monthly",
            "evidence": [{"text": "is monthly.\n"}],
        },
    ]
    store = FolderStore(tmp_path / "s")
    with store:
        doubt = [{"start": 0, "end": len(text), "confidence": 0.1}]
        k, _ = admit_packet(store, text, SCHEMA, cands, {"min_read_confidence": 0.5},
                            doubt=doubt)  # fmt: skip
        (found,) = [(tk, t) for tk, t in write_tasks(store, k).tasks
                    if t["slot"]["field"] == "billing"]  # fmt: skip
        tk, task = found
        assert [c["value"] for c in task["choices"]] == ["monthly", "monthly"]
        review = Review(store, "ana", clock=lambda: CLOCK)
        review.answer(body(tk, "choose", decision=task["choices"][1]["decision"]))
        assert measures(store).kinds["closed_set"]["other_option"] == [0, 1]
