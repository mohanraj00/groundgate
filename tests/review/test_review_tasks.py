"""`groundgate review tasks` (docs/design/review.md §5.2, §6.3 point 2, §7).

The audit vectors in ``audit-picks.json`` and the cases in ``cases/`` are written by hand (#408).
The tasks code must agree with them.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from groundgate.canonical import digest, jcs
from groundgate.cli import main
from groundgate.model import PacketError
from groundgate.review import format_schema
from groundgate.review.tasks import (
    DEFAULT_POLICY,
    _number,
    _Source,
    audit_hash,
    audit_picked,
    check_policy,
    write_tasks,
)
from groundgate.store import FolderStore, key
from groundgate.store.packets import admit_packet

HERE = Path(__file__).parent
FILES = {path.stem: json.loads(path.read_text("utf-8")) for path in HERE.glob("cases/*.json")}
CASES = [(stem, case) for stem, data in sorted(FILES.items()) for case in data["cases"]]
CASE_IDS = [f"{stem}/{case['name']}" for stem, case in CASES]


def policy(rate: str = "0", seed: str = "s", *, rejected: bool = False) -> dict[str, Any]:
    return {
        "format": "review-policy@1",
        "audit": {"rate": rate, "seed": seed},
        "agree": 1,
        "leads": [],
        "rejected": rejected,
    }


EVERY = policy("1", rejected=True)  # each slot that a rule can select gets a task


def ev(quote: str, text: str, nth: int = 0) -> dict[str, Any]:
    data, at = text.encode(), -1
    for _ in range(nth + 1):
        at = data.index(quote.encode(), at + 1)
    return {"start": at, "end": at + len(quote.encode()), "text": quote}


def stored(store: FolderStore, packet: dict[str, Any]) -> str:
    k, _ = admit_packet(
        store, packet["text"], packet["schema"], packet["candidates"], packet["policy"],
        None, packet["judgments"],
    )  # fmt: skip
    return k


def tasks_of(store: FolderStore, k: str, given: dict[str, Any] | None) -> list[dict[str, Any]]:
    written = write_tasks(store, k, given)
    assert written.problems == ()
    return [t for _, t in written.tasks]


def _validator() -> Any:
    jsonschema = pytest.importorskip("jsonschema")
    return jsonschema.Draft202012Validator(format_schema("task@1"))


# The audit pick (§6.3, point 2)


def test_audit_pick_agrees_with_the_vectors() -> None:
    rows = json.loads((HERE / "audit-picks.json").read_text("utf-8"))["vectors"]
    for row in rows:
        h = audit_hash(row["seed"], row["packet"], row["field"], row["key"], row["decision"])
        assert f"{h:016x}" == row["first_8_bytes"]
        for pick in row["picks"]:
            assert audit_picked(h, pick["rate"]) == pick["picked"], pick["rate"]


def test_audit_pick_edges() -> None:
    assert audit_picked(0, "0.000000000000000001")
    assert not audit_picked(0, "0")
    assert audit_picked(2**64 - 1, "1")
    assert not audit_picked(2**63, "0.5")  # H / 2^64 = 0.5 is not less than 0.5
    assert audit_picked(2**63 - 1, "0.5")
    for bad in ("0.50", "1.0", ".5", "0.1234567890123456789", "2", "-0.1", "0.5e1"):
        with pytest.raises(ValueError):
            audit_picked(0, bad)


# The review policy (§5.1)


def test_check_policy() -> None:
    assert check_policy(DEFAULT_POLICY) == DEFAULT_POLICY
    jsonschema = pytest.importorskip("jsonschema")
    schema = jsonschema.Draft202012Validator(format_schema("review-policy@1"))
    assert schema.is_valid(DEFAULT_POLICY)
    bad = [
        None,
        {**policy(), "extra": 1},
        {**policy(), "format": "review-policy@2"},
        {**policy(), "audit": {"rate": 0.5, "seed": "s"}},
        {**policy(), "audit": {"rate": "0.50", "seed": "s"}},
        {**policy(), "audit": {"rate": "0.5"}},
        {**policy(), "audit": {"rate": "0.5", "seed": 1}},
        {**policy(), "agree": 0},
        {**policy(), "agree": True},
        {**policy(), "leads": ["ana", "ana"]},
        {**policy(), "leads": [" "]},
        {**policy(), "rejected": "no"},
    ]
    for value in bad:
        with pytest.raises(ValueError):
            check_policy(value)
        assert value is None or not schema.is_valid(value), value


# The cases of #408


def _slot_ids(receipt_ids: list[str], task: dict[str, Any]) -> Any:
    slot = task["slot"]
    return slot["field"], slot["key"], tuple(sorted(receipt_ids[i] for i in slot["decisions"]))


@pytest.mark.parametrize(("stem", "case"), CASES, ids=CASE_IDS)
def test_cases_give_their_tasks(tmp_path: Path, stem: str, case: dict[str, Any]) -> None:
    """Each slot of a case that has a task in the expected resolution gets a task with that mode.
    Under the policy of the case, the other slots get no task. A case of §6.3 point 1 has an
    answer to a task that its policy no longer makes, so only the mode is checked there."""
    data = FILES[stem]
    if "error" in case["expected"]:
        return
    with FolderStore(tmp_path / "s") as store:
        k = stored(store, data["packet"])
        packet = json.loads(store.get("packet@1", k))
        receipt = json.loads(store.get("receipt@1", packet["receipt"]))
        ids = [d["candidate_id"] for d in receipt["decisions"]]
        every = {_slot_ids(ids, t): t for t in tasks_of(store, k, EVERY)}
        made = {_slot_ids(ids, t): t for t in tasks_of(store, k, case["policy"])}
    expected = {
        (s["field"], s["key"], tuple(sorted(s["candidates"]))): s["task"]
        for s in case["expected"]["slots"]
    }
    for slot, mode in expected.items():
        if mode is not None:
            assert every[slot]["mode"] == mode, slot
        if mode is not None and "6.3.1" not in case["rules"]:
            assert slot in made, slot
    for slot, task in made.items():
        assert expected[slot] == task["mode"], slot
        assert task == every[slot]  # a policy never changes the bytes of a task (§6.3 point 1)


def test_tasks_are_valid_and_the_same_each_time(tmp_path: Path) -> None:
    check = _validator()
    with FolderStore(tmp_path / "s") as store:
        for data in FILES.values():
            k = stored(store, data["packet"])
            first = write_tasks(store, k, EVERY).tasks
            again = write_tasks(store, k, EVERY).tasks
            assert first == again and first
            for task_key, task in first:
                assert check.is_valid(task), list(check.iter_errors(task))
                assert task["packet"] == k
                assert set(task["parts"]) <= {"amount", "scale", "sign", "unit", "field", "key"} | {
                    "text",
                    "start",
                    "end",
                }
                assert store.get("task@1", task_key) == jcs(task).encode()
                assert key("task@1", jcs(task).encode()) == task_key


def test_the_example_of_a_conflict(tmp_path: Path) -> None:
    with FolderStore(tmp_path / "s") as store:
        (task,) = tasks_of(store, stored(store, FILES["conflict"]["packet"]), None)
    assert task["question"] == "Which amount is revenue?"
    assert task["mode"] == "review" and task["item"] == "number" and task["template"] == "number@1"
    assert task["parts"] == ["amount", "scale", "sign", "unit", "field"]
    assert task["codes"] == ["CONFLICTING_CANDIDATES", "SCALE_WORD"]
    assert [c["shown"] for c in task["choices"]] == [
        "4,200,000 with no unit (written 4,200, in thousands, positive)",
        "4,200 with no unit (written 4,200, not scaled, positive)",
    ]
    assert task["places"] == [{"start": 12, "end": 26, "page": None, "box": None}]


# Kinds, keys and multiple fields (§7)

LONG = "The tenant shall keep the premises in good repair. " * 7


def test_kinds_keys_and_questions(tmp_path: Path) -> None:
    text = (
        "Lessor: Example Holdings Ltd. Clause: " + LONG + "\nNotes: first line\nsecond line.\n"
        "Fees in 2024 were (1,250) million dollars. Staff: 12.\n"
    )
    schema = {
        "fields": {
            "clause": {"type": "string"},
            "fee": {"type": "number", "unit": "USD", "keys": ["2024", "2025"]},
            "lessor": {"type": "string"},
            "notes": {"type": "string"},
            "staff": {"type": "integer"},
        }
    }
    low = 0.1
    candidates = [
        {"id": "c", "field": "clause", "value": LONG.strip(), "evidence": ev(LONG.strip(), text),
         "confidence": low},
        {"id": "f", "field": "fee", "key": "2024", "value": "-1250000000", "unit": "USD",
         "evidence": ev("(1,250) million dollars", text), "confidence": low},
        {"id": "l", "field": "lessor", "value": "Example Holdings Ltd",
         "evidence": ev("Example Holdings Ltd", text), "confidence": low},
        {"id": "n", "field": "notes", "value": "first line\nsecond line",
         "evidence": ev("first line\nsecond line", text), "confidence": low},
        {"id": "s", "field": "staff", "value": 12, "evidence": ev("12", text), "confidence": low},
    ]  # fmt: skip
    with FolderStore(tmp_path / "s") as store:
        k, receipt = admit_packet(store, text, schema, candidates, {"min_confidence": 0.5})
        assert {d.outcome for d in receipt.decisions} == {"needs_verification"}
        tasks = {t["slot"]["field"]: t for t in tasks_of(store, k, None)}
    assert [t["item"] for t in tasks.values()] == ["span", "number", "text", "span", "number"]
    fee = tasks["fee"]
    assert fee["slot"]["key"] == "2024"
    assert fee["question"] == (
        "Is fee for 2024 -1,250,000,000 USD (written 1,250, in millions, negative)?"
    )
    assert fee["parts"] == ["amount", "scale", "sign", "unit", "field", "key"]
    staff = "Is staff 12 with no unit (written 12, not scaled, positive)?"
    assert tasks["staff"]["question"] == staff
    assert tasks["lessor"]["question"] == 'Is "Example Holdings Ltd" the lessor?'
    assert tasks["lessor"]["parts"] == ["text", "field"]
    clause = tasks["clause"]
    assert clause["template"] == "span@1" and clause["parts"] == ["start", "end", "field"]
    assert clause["question"] == (
        'Is the clause the text from "The tenant shall keep the premises in good" to '
        f'"tenant shall keep the premises in good repair." ({len(LONG.strip())} characters)?'
    )
    # the receipt value has no line break, so the line break comes from the text (§7)
    assert tasks["notes"]["choices"][0]["value"] == "first line second line"


def test_a_multiple_field_has_a_slot_for_each_decision(tmp_path: Path) -> None:
    text = "Risks: fire 10 and flood 20.\n"
    schema = {"fields": {"risk": {"type": "number", "multiple": True}}}
    candidates = [
        {"id": "a", "field": "risk", "value": "10", "evidence": ev("10", text)},
        {"id": "b", "field": "risk", "value": "20", "evidence": ev("20", text)},
    ]
    with FolderStore(tmp_path / "s") as store:
        k, _ = admit_packet(store, text, schema, candidates)
        tasks = tasks_of(store, k, policy("1"))
        assert tasks_of(store, k, policy("0")) == []
    assert [t["slot"]["decisions"] for t in tasks] == [[0], [1]]
    assert {t["mode"] for t in tasks} == {"audit"}
    # each decision has its own pick: the hash names the decision index
    hashes = {audit_hash("s", k, "risk", None, i) for i in (0, 1)}
    assert len(hashes) == 2
    assert audit_hash("s", k, "risk", None, None) not in hashes


def test_the_audit_rate_picks_by_the_hash(tmp_path: Path) -> None:
    data = FILES["audit"]
    with FolderStore(tmp_path / "s") as store:
        k = stored(store, data["packet"])
        h = audit_hash("seed-x", k, "revenue", None, None)
        n = h * 10**18 // 2**64  # H / 2^64 rounded down to 18 digits, calculated by hand
        below = f"0.{n:018d}".rstrip("0")  # n / 10^18 <= H / 2^64: no pick
        above = f"0.{n + 1:018d}".rstrip("0")  # (n + 1) / 10^18 > H / 2^64: a pick
        assert tasks_of(store, k, policy(below, "seed-x")) == []
        (task,) = tasks_of(store, k, policy(above, "seed-x"))
    assert task["mode"] == "audit"
    assert task["question"] == (
        "Is revenue 3,900,000 with no unit (written 3,900, in thousands, positive)?"
    )


def test_the_scale_is_exact_for_long_numbers() -> None:
    text = "Total 12345678901234567890123456789 here"
    assert _number("12345678901234567890123456789000", "USD", (6, 35), _Source(text)) == (
        "12,345,678,901,234,567,890,123,456,789,000 USD "
        "(written 12345678901234567890123456789, in thousands, positive)"
    )
    # Decimal arithmetic with 28 digits rounds the token to 12345678901234567890123456790
    assert _number("12345678901234567890123456790", "USD", (6, 35), _Source(text)).endswith(
        "(written form not found, positive)"
    )


def test_a_long_number_takes_linear_time() -> None:
    digits = "7" * 200_000
    text = f"Revenue {digits} here."
    times = []
    for _ in range(3):  # the best of three runs, so a pause of a shared runner does not count
        start = time.perf_counter()
        shown = _number(digits + "000", None, (8, 8 + len(digits)), _Source(text))
        times.append(time.perf_counter() - start)
    assert min(times) < 0.5
    assert shown.endswith(f"(written {digits}, in thousands, positive)")


def test_source_spans_in_code_points() -> None:
    source = _Source("€ 1,5 ü x")
    assert source.chars((0, 3)) == (0, 1)
    assert source.chars((4, 7)) == (2, 5)
    assert source.chars((8, 10)) == (6, 7)
    assert source.chars((1, 3)) is None  # inside the euro sign
    assert source.chars((0, 99)) is None
    assert _Source("abc").chars((1, 2)) == (1, 2)


# No document text (§5.2)


def test_no_task_holds_document_text(tmp_path: Path) -> None:
    secret = "Zebrafish quartzite lantern"
    text = f"{secret} Revenue 4,200 thousands. {secret} Lessor: Acme Ltd. {secret}\n"
    schema = {
        "fields": {
            "lessor": {"type": "string"},
            "net": {"type": "number", "required": True},
            "revenue": {"type": "number"},
        }
    }
    candidates = [
        {"id": "r", "field": "revenue", "value": "4200000", "confidence": 0.1,
         "evidence": [ev("4,200 thousands", text), {"role": "scale", "text": "thousands"}]},
        {"id": "x", "field": "revenue", "value": "999", "evidence": ev(secret, text)},
        {"id": "l", "field": "lessor", "value": "Acme Ltd", "evidence": ev("Acme Ltd", text)},
    ]  # fmt: skip
    with FolderStore(tmp_path / "s") as store:
        k, _ = admit_packet(store, text, schema, candidates, {"min_confidence": 0.5})
        tasks = tasks_of(store, k, EVERY)
    assert len(tasks) == 3
    dumped = jcs(tasks)
    for word in ("Zebrafish", "quartzite", "lantern", "Lessor:"):
        assert word not in dumped
    revenue = next(t for t in tasks if t["slot"]["field"] == "revenue")
    assert [p["start"] for p in revenue["places"]] == sorted(p["start"] for p in revenue["places"])
    assert len(revenue["places"]) == 3  # the value, the scale item and the rejected value


# The store and the command line


def test_page_and_box_come_from_the_layout(tmp_path: Path) -> None:
    text = "Intro\n\fRevenue was 4,200 in 2025.\n"
    data = text.encode()
    at = data.index(b"4,200")
    layout = {
        "groundgate_layout": "0.1",
        "document_sha256": digest("document", {"text": text}),
        "pages": [
            {"page": 1, "width": 612, "height": 792, "start": 0, "end": 7},
            {"page": 2, "width": 612, "height": 792, "start": 7, "end": len(data)},
        ],
        "words": [
            [0, 5, 1, 72, 80, 100, 92],
            [7, 14, 2, 72, 80, 120, 92],
            [at, at + 5, 2, 150.5, 80, 180.25, 92],
            [at + 9, at + 13, 2, 200, 80, 230, 92],
        ],
    }
    with FolderStore(tmp_path / "s") as store:
        reading = {
            "format": "reading@1",
            "source": store.put("source@1", data),
            "reader": {"name": "groundgate.read", "version": "0"},
            "options": {"pages": None},
            "text": store.put("text@1", data),
            "layout": store.put("layout@1", jcs(layout).encode()),
            "document": None,
        }
        reading_key = store.put("reading@1", jcs(reading).encode())
        candidates = [{"field": "revenue", "value": "4200", "evidence": ev("4,200", text)}]
        schema = {"fields": {"revenue": {"type": "number"}}}
        k, _ = admit_packet(store, text, schema, candidates, reading=reading_key)
        (task,) = tasks_of(store, k, policy("1"))
    assert task["places"] == [
        {"start": at, "end": at + 5, "page": 2, "box": [150.5, 80, 180.25, 92]}
    ]


def test_a_box_that_is_not_finite_writes_no_task(tmp_path: Path) -> None:
    text = "Revenue 10 and 20.\n"
    layout = {
        "groundgate_layout": "0.1",
        "document_sha256": digest("document", {"text": text}),
        "pages": [{"page": 1, "width": 612, "height": 792, "start": 0, "end": len(text)}],
        "words": [[8, 10, 1, 72, 80, 90, 92], [15, 17, 1, "nan", 80, 120, 92]],
    }
    with FolderStore(tmp_path / "s") as store:
        reading = {
            "format": "reading@1",
            "source": store.put("source@1", text.encode()),
            "reader": {"name": "groundgate.read", "version": "0"},
            "options": {"pages": None},
            "text": store.put("text@1", text.encode()),
            "layout": store.put("layout@1", jcs(layout).encode()),
            "document": None,
        }
        schema = {"fields": {"a": {"type": "number"}, "b": {"type": "number"}}}
        candidates = [
            {"field": "a", "value": "10", "evidence": ev("10", text)},
            {"field": "b", "value": "20", "evidence": ev("20", text)},
        ]
        k, _ = admit_packet(
            store, text, schema, candidates, reading=store.put("reading@1", jcs(reading).encode())
        )
        with pytest.raises(PacketError, match="not a finite number"):
            write_tasks(store, k, policy("1"))
    objects = [p for p in (tmp_path / "s" / "objects").rglob("*") if p.is_file()]
    names = {"sha256:" + p.parent.name + p.name: p.read_bytes() for p in objects}
    kinds = {"task@1" for name, data in names.items() if key("task@1", data) == name}
    assert kinds == set()  # the task of field a is not in the store either


class _Small:
    """A store that reads as ``inner`` reads, with a smaller ``max_bytes`` for a write."""

    def __init__(self, inner: FolderStore, max_bytes: int) -> None:
        self.inner, self.max_bytes = inner, max_bytes

    def get(self, kind: str, k: str) -> bytes:
        return self.inner.get(kind, k)

    def read(self, log: tuple[str, ...]) -> list[Any]:
        return self.inner.read(log)

    def put(self, kind: str, data: bytes) -> str:
        if len(data) > self.max_bytes:
            raise ValueError(f"the {kind} object is larger than max_bytes")
        return self.inner.put(kind, data)


def test_a_task_over_max_bytes_writes_no_task(tmp_path: Path) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        k = stored(store, FILES["missing"]["packet"])
        sizes = [len(jcs(t).encode()) for t in make(store, k)]
        before = sorted(p for p in root.rglob("*") if p.is_file())
        # the first task fits, and a later one does not
        small = _Small(store, sizes[0])
        assert max(sizes) > sizes[0]
        with pytest.raises(ValueError, match="larger than max_bytes"):
            write_tasks(small, k, EVERY)
    assert sorted(p for p in root.rglob("*") if p.is_file()) == before


def make(store: FolderStore, k: str) -> list[dict[str, Any]]:
    """The tasks of ``k`` under EVERY, with no write."""
    from groundgate.model import Schema
    from groundgate.review.tasks import make_tasks
    from groundgate.store.packets import load_packet

    packet = load_packet(store, k)
    schema = Schema.from_dict(packet.schema, packet.packs)
    return make_tasks(k, packet.receipt, packet.text, schema, EVERY)


def _tampered(store: FolderStore, k: str) -> str:
    packet = json.loads(store.get("packet@1", k))
    receipt = json.loads(store.get("receipt@1", packet["receipt"]))
    receipt["decisions"][0]["outcome"] = "needs_verification"
    packet["receipt"] = store.put("receipt@1", jcs(receipt).encode())
    return store.put("packet@1", jcs(packet).encode())


def test_command_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        k = stored(store, FILES["missing"]["packet"])
        bad = _tampered(store, k)
    given = tmp_path / "policy.json"
    given.write_text(json.dumps(EVERY), encoding="utf-8")
    assert main(["review", "tasks", "--store", str(root), k, "--policy", str(given)]) == 0
    keys = capsys.readouterr().out.split()
    assert len(keys) == 3
    with FolderStore(root) as store:
        assert [json.loads(store.get("task@1", t))["slot"]["field"] for t in keys] == [
            "net_income", "revenue", "staff"
        ]  # fmt: skip
    assert main(["review", "tasks", "--store", str(root), k]) == 0
    assert capsys.readouterr().out.split() == [keys[0]]  # the default policy: no audit

    assert main(["review", "tasks", "--store", str(root), bad]) == 1
    err = capsys.readouterr().err
    assert err.startswith("mismatch: ") and "no task for a receipt that does not match" in err

    given.write_text(json.dumps({**EVERY, "agree": 0}), encoding="utf-8")
    assert main(["review", "tasks", "--store", str(root), k, "--policy", str(given)]) == 2
    assert "agree must be an integer" in capsys.readouterr().err
    assert main(["review", "tasks", "--store", str(root), "../objects"]) == 2
    assert "is not a store key" in capsys.readouterr().err
    assert main(["review", "tasks", "--store", str(tmp_path / "none"), k]) == 2
    assert "store folder is not there" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["review", "tasks", k])  # --store is required
