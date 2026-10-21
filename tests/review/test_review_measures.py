"""`groundgate review measures` (docs/design/review.md §10).

The store is made by hand: three packets of tests/review/cases, their tasks under a policy that
makes each task, and answers with known times and keys. Each expected number is counted by hand
in the comments of ``store``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from groundgate.cli import main
from groundgate.review.measures import lines, measures
from groundgate.review.tasks import write_tasks
from groundgate.store import FolderStore, key, reviewer_key, set_key
from groundgate.store.packets import admit_packet

HERE = Path(__file__).parent
EVERY = {
    "format": "review-policy@1",
    "audit": {"rate": "1", "seed": "s"},
    "agree": 1,
    "leads": [],
    "rejected": True,
}


def _packet(store: FolderStore, case: str) -> tuple[str, dict[str, str]]:
    p = json.loads((HERE / "cases" / f"{case}.json").read_text("utf-8"))["packet"]
    k, _ = admit_packet(
        store, p["text"], p["schema"], p["candidates"], p["policy"], None, p["judgments"]
    )
    return k, {t["slot"]["field"]: tk for tk, t in write_tasks(store, k, EVERY).tasks}


def _answer(
    store: FolderStore, pk: str, name: str, task: str, verdict: str, ms: int, keys: int,
    *, seen: bool = False, decision: int | None = None, candidate: Any = None,
) -> None:  # fmt: skip
    store.append(
        ("answers", pk, reviewer_key(name)),
        {"format": "answer@1", "task": task, "reviewer": name, "verdict": verdict,
         "decision": decision, "candidate": candidate, "codes_kept": [], "statements": None,
         "nodes": None, "reason_seen": seen, "keys": keys, "ms": ms,
         "time": "2026-10-21T10:00:00Z"},
    )  # fmt: skip


def store(root: Path) -> tuple[FolderStore, dict[str, str]]:
    """The hand-made store.

    conflict: revenue is a review task with choices 0 and 1, net_income an audit task.
      revenue     ana choose 0 (2000 ms, 1 key), ben choose 0 (4000 ms, 2 keys)
      net_income  ana confirm, blind (1000 ms, 1 key); ben confirm, reason seen (3000 ms, 1
                  key); cara unsure (700 ms, 1 key)
      Pairs: ben with the blind label of ana agrees. ana has no blind label of another
      reviewer, and cara is unsure. net_income resolves admitted: 1 audit slot, no escape.
    audit: revenue is an audit task with one choice, 3900000.
      ana not_in_document, blind (5000 ms, 1 key); ben confirm, blind (1500 ms, 3 keys). ben
      first answered unsure (9000 ms); only the latest answer counts.
      Pairs: ana with ben and ben with ana disagree. With no lead the slot is disputed, so it
      is not an audit slot that an answer settles. With ana as lead it is not_in_document: an
      escape.
    text: lessor is a review task with one choice at 13 to 41.
      ana adjust_span to 21 to 41 (8000 ms, 3 keys): the start moves 8 characters.

    number: 7 answers, times 2000 4000 1000 3000 700 5000 1500, median 2000; one key: 5 of 7
    (ben revenue 2 keys, ben audit 3 keys); agreement 1 of 3.
    """
    s = FolderStore(root)
    conflict, ct = _packet(s, "conflict")
    _answer(s, conflict, "ana", ct["revenue"], "choose", 2000, 1, decision=0)
    _answer(s, conflict, "ben", ct["revenue"], "choose", 4000, 2, decision=0)
    _answer(s, conflict, "ana", ct["net_income"], "confirm", 1000, 1)
    _answer(s, conflict, "ben", ct["net_income"], "confirm", 3000, 1, seen=True)
    _answer(s, conflict, "cara", ct["net_income"], "unsure", 700, 1)
    audit, at = _packet(s, "audit")
    _answer(s, audit, "ana", at["revenue"], "not_in_document", 5000, 1)
    _answer(s, audit, "ben", at["revenue"], "unsure", 9000, 1)
    _answer(s, audit, "ben", at["revenue"], "confirm", 1500, 3)
    text, tt = _packet(s, "text")
    moved = {"id": "review-1", "field": "lessor", "value": "Example Holdings Ltd",
             "proposer": "person:ana", "evidence": {"start": 21, "end": 41}}  # fmt: skip
    _answer(s, text, "ana", tt["lessor"], "adjust_span", 8000, 3, candidate=moved)
    return s, {"conflict": conflict, "audit": audit, "text": text}


def _m(n: int, ms: Any, one: list[int], agree: list[int], esc: list[int]) -> dict[str, Any]:
    return {"answers": n, "ms_median": ms, "one_key": one, "agreement": agree, "escapes": esc}


def test_the_numbers_of_a_store_made_by_hand(tmp_path: Path) -> None:
    s, _ = store(tmp_path)
    got = measures(s)
    assert got.skipped == () and got.packets == 3
    number = got.kinds["number"]
    assert {k: v for k, v in number.items() if k != "fields"} == _m(7, 2000, [5, 7], [1, 3], [0, 1])
    assert number["fields"] == {
        # 1000 3000 700 2000 4000 5000 1500 -> net_income 700 1000 3000, revenue 1500 to 5000
        "net_income": _m(3, 1000, [3, 3], [1, 1], [0, 1]),
        "revenue": _m(4, 3000, [2, 4], [0, 2], [0, 0]),
    }
    text = got.kinds["text"]
    assert {k: v for k, v in text.items() if k != "fields"} == {
        **_m(1, 8000, [0, 1], [0, 0], [0, 0]), "span_moved": [1, 1], "span_move_median": 8,
    }  # fmt: skip
    assert set(got.kinds) == {"number", "text"}


def test_a_lead_settles_the_audit_slot_and_finds_an_escape(tmp_path: Path) -> None:
    s, _ = store(tmp_path)
    got = measures(s, {**EVERY, "leads": ["ana"]})
    assert got.kinds["number"]["escapes"] == [1, 2]
    assert got.kinds["number"]["fields"]["revenue"]["escapes"] == [1, 1]
    assert got.kinds["number"]["fields"]["net_income"]["escapes"] == [0, 1]


def test_a_split_measures_only_its_documents(tmp_path: Path) -> None:
    s, _ = store(tmp_path)
    texts = {}
    for name in ("conflict", "audit"):
        p = json.loads((HERE / "cases" / f"{name}.json").read_text("utf-8"))["packet"]
        texts[name] = key("text@1", p["text"].encode("utf-8"))
    log = ("splits", set_key("set-a"))
    s.append(log, {"set": "set-a", "document": texts["conflict"], "split": "development"})
    s.append(log, {"set": "set-a", "document": texts["audit"], "split": "held-out"})
    got = measures(s, set_name="set-a", split="development")
    assert got.packets == 1 and set(got.kinds) == {"number"}
    assert got.kinds["number"]["answers"] == 5
    with pytest.raises(ValueError, match="together"):
        measures(s, set_name="set-a")
    s.append(log, {"set": "set-a", "document": texts["conflict"], "split": "held-out"})
    with pytest.raises(ValueError, match="two splits"):
        measures(s, set_name="set-a", split="development")


def test_a_bad_answer_leaves_its_packet_out(tmp_path: Path) -> None:
    s, keys = store(tmp_path)
    _answer(s, keys["text"], "ben", "sha256:" + "0" * 64, "confirm", 10, 1)
    got = measures(s)
    assert got.packets == 2 and "text" not in got.kinds
    (line,) = got.skipped
    assert line.startswith(f"packet {keys['text']}: answer 1 of the reviewer ben: the task is not")


def test_the_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    s, keys = store(tmp_path / "s")
    s.close()
    assert main(["review", "measures", "--store", str(tmp_path / "s")]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "packets: 3"
    assert out[1] == (
        "number: answers 7, median time 2000 ms, one key 5 of 7, agreement with blind labels "
        "1 of 3, escapes 0 of 1 audit slots"
    )
    assert out[-1] == (
        "  text lessor: answers 1, median time 8000 ms, one key 0 of 1, agreement with blind "
        "labels 0 of 0, escapes 0 of 0 audit slots, span moved 1 of 1, median move 8 characters"
    )
    assert main(["review", "measures", "--store", str(tmp_path / "s"), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    with FolderStore(tmp_path / "s") as again:
        assert data == measures(again).to_dict()
        _answer(again, keys["text"], "ben", "sha256:" + "0" * 64, "confirm", 10, 1)
    assert main(["review", "measures", "--store", str(tmp_path / "s")]) == 1
    assert capsys.readouterr().err.startswith(f"skipped: packet {keys['text']}")
    assert lines(measures(FolderStore(tmp_path / "s")))[0] == "packets: 2"
