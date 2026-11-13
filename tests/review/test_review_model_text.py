"""The model text input of review and its item kind (docs/design/review.md §7, #531)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from groundgate.cli import main
from groundgate.model import PacketError
from groundgate.review import format_schema
from groundgate.review.measures import lines as measure_lines
from groundgate.review.measures import measures
from groundgate.review.model_text import differing
from groundgate.review.resolve import lines, write_resolution
from groundgate.review.serve import Refused, Review
from groundgate.review.tasks import write_tasks
from groundgate.store import FolderStore, key, reviewer_key
from groundgate.store.maintain import check, forget_packet
from groundgate.store.packets import admit_packet

HERE = Path(__file__).parent
PACKET = json.loads((HERE / "cases" / "conflict.json").read_text("utf-8"))["packet"]
CLOCK = datetime(2026, 11, 13, 9, 30, tzinfo=timezone.utc)
# The document is "Revenue was 4,200 thousand in 2025.\nNet income was 310 thousand in 2025.\n"
TEXT = "Revenue was 4,300 thousand. Net income rose."
FIRST = {"start": 0, "end": 27, "cites": [{"start": 0, "end": 35}]}
SECOND = {"start": 28, "end": 44, "cites": []}


def model_text(packet_key: str, /, **over: Any) -> dict[str, Any]:
    out = {"format": "model-text@1", "packet": packet_key, "name": "summary", "text": TEXT,
           "statements": [FIRST, SECOND]}  # fmt: skip
    return out | over


def stored(root: Path) -> tuple[FolderStore, str, str, dict[str, Any]]:
    """A store with the conflict packet, a model text and its task."""
    store = FolderStore(root)
    k, _ = admit_packet(
        store, PACKET["text"], PACKET["schema"], PACKET["candidates"], PACKET["policy"],
        None, PACKET["judgments"],
    )  # fmt: skip
    written = write_tasks(store, k, None, model_text(k))
    tk, task = next((tk, t) for tk, t in written.tasks if t["item"] == "model_text")
    return store, k, tk, task


def body(tk: str, verdicts: list[str], **more: Any) -> dict[str, Any]:
    return {"task": tk, "verdict": "confirm", "decision": None, "codes_kept": [],
            "reason_seen": False, "keys": 3, "ms": 4000,
            "statements": [{"statement": n, "verdict": v} for n, v in enumerate(verdicts)],
            **more}  # fmt: skip


def test_the_task_holds_offsets_and_no_model_text(tmp_path: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    store, k, tk, task = stored(tmp_path / "t")
    with store:
        jsonschema.Draft202012Validator(format_schema("task@1")).validate(task)
        given = json.loads(store.get("model-text@1", task["model_text"]["key"]))
        jsonschema.Draft202012Validator(format_schema("model-text@1")).validate(given)
        assert given == model_text(k)
        assert task["slot"] == {"field": "summary", "key": None, "decisions": []}
        assert (task["item"], task["template"], task["mode"]) == (
            "model_text", "model_text@1", "review")  # fmt: skip
        assert task["places"] == [{"start": 0, "end": 35, "page": None, "box": None}]
        assert task["model_text"]["statements"] == 2
        assert "4,300" not in json.dumps(task)
        # the same packet and input give the same task, also with no input argument
        again = [tk2 for tk2, t in write_tasks(store, k).tasks if t["item"] == "model_text"]
        assert again == [tk]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"name": "revenue"}, "is a field of the schema"),
        ({"name": "Summary"}, "form of a field name"),
        ({"packet": "sha256:" + "0" * 64}, "another packet"),
        ({"text": "Café text that is long enough to hold both statements."}, "NFC"),
        ({"statements": []}, "1 to 200"),
        ({"statements": [SECOND, FIRST]}, "before the end"),
        ({"statements": [{"start": 0, "end": 99, "cites": []}]}, "not a span"),
        ({"statements": [{"start": 0, "end": 5, "cites": [{"start": 0, "end": 999}]}]}, "cite"),
        ({"statements": [{"start": 0, "end": 5, "cites": [], "value": "1"}]}, "members"),
        ({"extra": 1}, "must have the members"),
    ],
)
def test_a_bad_model_text_is_refused(tmp_path: Path, change: dict[str, Any], message: str) -> None:
    store, k, _, _ = stored(tmp_path / "s")
    with store:
        before = set(store.object_keys()[0])
        with pytest.raises(PacketError, match=message):
            write_tasks(store, k, None, model_text(k, **change))
        assert set(store.object_keys()[0]) == before


def test_a_span_inside_a_character_is_refused(tmp_path: Path) -> None:
    store, k, _, _ = stored(tmp_path / "s")
    with store, pytest.raises(PacketError, match="inside a character"):
        bad = model_text(k, text="Révenue rose.", statements=[{"start": 0, "end": 2, "cites": []}])
        write_tasks(store, k, None, bad)


def test_the_marked_words_are_not_in_the_cited_text() -> None:
    cited = ["Revenue was 4,200 thousand in 2025."]
    said = "Revenue was 4,300 thousand."
    assert [said[a:b] for a, b in differing(said, cited)] == ["300"]
    assert differing(said, []) == []


def test_the_page_shows_each_statement_and_takes_its_verdicts(tmp_path: Path) -> None:
    store, k, tk, _ = stored(tmp_path / "s")
    with store:
        review = Review(store, "ana", clock=lambda: CLOCK)
        assert tk in [t["task"] for t in review.queue()["tasks"]]
        view = review.view(tk)
        assert view["item"] == "model_text" and view["definition"] is None
        first, second = view["statements"]
        assert first["text"] == "Revenue was 4,300 thousand."
        assert first["cites"] == ["Revenue was 4,200 thousand in 2025."]
        assert [first["text"][a:b] for a, b in first["marks"]] == ["300"]
        assert second == {"n": 1, "text": "Net income rose.", "marks": [], "cites": []}
        for bad, message in [
            (body(tk, ["supported"]), "one verdict for each"),
            (body(tk, ["supported", "true"]), "supported, unsupported or unsure"),
            (body(tk, ["supported", "unsure"], verdict="unsure"), "verdict confirm"),
            (body(tk, ["supported", "unsure"], decision=0), "no decision"),
        ]:
            with pytest.raises(Refused, match=message):
                review.answer(bad)
        with pytest.raises(Refused, match="no correction"):
            review.check({"task": tk, "verdict": "correct"})
        assert store.read(("answers", k, reviewer_key("ana"))) == []
        left = review.answer(body(tk, ["unsupported", "unsure"]))
        assert tk not in [t["task"] for t in left["tasks"]]
        (record,) = store.read(("answers", k, reviewer_key("ana")))
        assert record["format"] == "answer@1" and record["verdict"] == "confirm"
        assert record["statements"] == [
            {"statement": 0, "verdict": "unsupported"},
            {"statement": 1, "verdict": "unsure"},
        ]
        jsonschema = pytest.importorskip("jsonschema")
        plain = {m: v for m, v in record.items()
                 if m in format_schema("answer@1")["properties"]}  # fmt: skip
        jsonschema.Draft202012Validator(format_schema("answer@1")).validate(plain)


def test_another_task_takes_no_statements(tmp_path: Path) -> None:
    store, k, _, _ = stored(tmp_path / "s")
    with store:
        review = Review(store, "ana", clock=lambda: CLOCK)
        other = next(t for t in review.tasks if t not in review.docs[k].texts)
        review.answer(body(other, ["supported"], verdict="unsure"))
        (record,) = store.read(("answers", k, reviewer_key("ana")))
        assert record["statements"] is None


def _answer(store: FolderStore, k: str, tk: str, name: str, verdicts: list[str]) -> None:
    Review(store, name, clock=lambda: CLOCK).answer(body(tk, verdicts))


def _slot(store: FolderStore, k: str, names: list[str], policy: Any = None) -> dict[str, Any]:
    resolved = write_resolution(store, k, policy, names)
    assert resolved.resolution is not None
    return next(s for s in resolved.resolution["slots"] if s["field"] == "summary")


def test_the_resolution_gives_the_verdict_of_each_statement(tmp_path: Path) -> None:
    store, k, tk, _ = stored(tmp_path / "s")
    with store:
        assert _slot(store, k, [])["status"] == "open"
        _answer(store, k, tk, "ana", ["unsure", "unsure"])
        assert _slot(store, k, ["ana"])["status"] == "open"  # only unsure: it does not count
        _answer(store, k, tk, "ana", ["unsupported", "supported"])
        slot = _slot(store, k, ["ana"])
        assert slot == {
            "field": "summary", "key": None, "decisions": [], "status": "confirmed",
            "value": None, "unit": None, "evidence": None, "receipt": slot["receipt"],
            "task": tk, "nodes": None,
            "statements": [{"statement": 0, "verdict": "unsupported"},
                           {"statement": 1, "verdict": "supported"}],
        }  # fmt: skip
        resolved = write_resolution(store, k, None, ["ana"])
        assert resolved.resolution is not None
        assert resolved.resolution["slots"][-1] == slot  # after the slots of the receipt
        jsonschema = pytest.importorskip("jsonschema")
        jsonschema.Draft202012Validator(format_schema("resolution@1")).validate(resolved.resolution)
        assert "summary: 1 of 2 statements supported, 1 unsupported (confirmed)" in lines(
            resolved.resolution
        )


def test_two_reviewers_must_agree_on_each_statement(tmp_path: Path) -> None:
    store, k, tk, _ = stored(tmp_path / "s")
    two = {"format": "review-policy@1", "audit": {"rate": "0", "seed": ""}, "agree": 2,
           "leads": ["bo"], "rejected": False}  # fmt: skip
    with store:
        _answer(store, k, tk, "ana", ["unsupported", "supported"])
        assert _slot(store, k, ["ana"], two)["status"] == "open"
        _answer(store, k, tk, "bo", ["unsupported", "unsupported"])
        no_lead = two | {"leads": []}
        assert _slot(store, k, ["ana", "bo"], no_lead)["status"] == "disputed"
        slot = _slot(store, k, ["ana", "bo"], two)  # the lead settles the dispute
        assert [s["verdict"] for s in slot["statements"]] == ["unsupported", "unsupported"]


def test_the_measures_count_the_statements(tmp_path: Path) -> None:
    store, k, tk, _ = stored(tmp_path / "s")
    with store:
        _answer(store, k, tk, "ana", ["unsupported", "supported"])
        found = measures(store).kinds["model_text"]
        assert found["answers"] == 1
        assert found["statement_ms_median"] == 2000  # 4000 ms for 2 statements
        assert found["unsupported"] == [1, 2]
        line = next(x for x in measure_lines(measures(store)) if x.startswith("model_text:"))
        assert "median time for a statement 2000 ms" in line
        assert "unsupported 1 of 2 statements" in line


def test_forget_removes_the_model_text_and_keeps_the_task(tmp_path: Path) -> None:
    store, k, tk, task = stored(tmp_path / "s")
    with store:
        assert check(store).findings == []
        _answer(store, k, tk, "ana", ["unsupported", "supported"])
        mk = task["model_text"]["key"]
        done = forget_packet(store, k, "test")
        assert ("model-text@1", mk, "deleted", 0) in done
        keys = set(store.object_keys()[0])
        assert mk not in keys and tk in keys
        assert len(store.read(("answers", k, reviewer_key("ana")))) == 1


def test_the_model_text_of_another_packet_stays(tmp_path: Path) -> None:
    store, k, _, _ = stored(tmp_path / "s")
    with store:
        other = "sha256:" + "1" * 64
        data = json.dumps(model_text(other), sort_keys=True, separators=(",", ":")).encode()
        ok = store.put("model-text@1", data)
        assert ok == key("model-text@1", data)
        forget_packet(store, k, "test")
        assert ok in set(store.object_keys()[0])


def test_the_command_writes_the_model_text_task(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, k, tk, _ = stored(tmp_path / "s")
    store.close()
    path = tmp_path / "mt.json"
    path.write_text(json.dumps(model_text(k)), encoding="utf-8")
    assert main(["review", "tasks", "--store", str(tmp_path / "s"), k,
                 "--model-text", str(path)]) == 0  # fmt: skip
    assert tk in capsys.readouterr().out.split()
    path.write_text(json.dumps(model_text(k, name="revenue")), encoding="utf-8")
    assert main(["review", "tasks", "--store", str(tmp_path / "s"), k,
                 "--model-text", str(path)]) == 2  # fmt: skip
    assert "is a field of the schema" in capsys.readouterr().err
