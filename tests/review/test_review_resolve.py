"""`groundgate review resolve` (docs/design/review.md §5.4, §6).

The cases in ``cases/`` are written by hand (#408). Each case gives its expected resolution, and
this module builds the full ``resolution@1`` bytes from it: the keys come from the store and
from ``admit``, never from the resolution code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from groundgate import admit
from groundgate.canonical import jcs
from groundgate.cli import main
from groundgate.model import PacketError
from groundgate.review import format_schema
from groundgate.review.resolve import AnswerError, lines, resolve, write_resolution
from groundgate.review.tasks import checked_packet, write_tasks
from groundgate.store import FolderStore, NotFound, key, reviewer_key
from groundgate.store.maintain import check, forget_packet
from groundgate.store.packets import admit_packet, load_packet

HERE = Path(__file__).parent
FILES = {path.stem: json.loads(path.read_text("utf-8")) for path in HERE.glob("cases/*.json")}
CASES = [(stem, case) for stem, data in sorted(FILES.items()) for case in data["cases"]]
CASE_IDS = [f"{stem}/{case['name']}" for stem, case in CASES]
CORRECTIONS = {"correct", "adjust_span"}
EVERY = {
    "format": "review-policy@1",
    "audit": {"rate": "1", "seed": "s"},
    "agree": 1,
    "leads": [],
    "rejected": True,
}


def policy(**members: Any) -> dict[str, Any]:
    out = {**EVERY, "audit": {"rate": "0", "seed": "s"}, "rejected": False}
    return {**out, **members}


def _key(kind: str, value: Any) -> str:
    return key(kind, jcs(value).encode("utf-8"))


def stored(store: FolderStore, packet: dict[str, Any]) -> str:
    k, _ = admit_packet(
        store, packet["text"], packet["schema"], packet["candidates"], packet["policy"],
        None, packet["judgments"],
    )  # fmt: skip
    return k


def task_keys(store: FolderStore, k: str) -> dict[tuple[str, Any], tuple[str, dict[str, Any]]]:
    """The task of each slot, by field and key, with the policy that makes each task."""
    written = write_tasks(store, k, EVERY)
    return {(t["slot"]["field"], t["slot"]["key"]): (tk, t) for tk, t in written.tasks}


def record(
    task: str, reviewer: str, verdict: str, *, decision: int | None = None, **more: Any
) -> dict[str, Any]:
    return {
        "format": "answer@1",
        "task": task,
        "reviewer": reviewer,
        "verdict": verdict,
        "decision": decision,
        "candidate": more.get("candidate"),
        "codes_kept": more.get("codes_kept", []),
        "statements": None,
        "nodes": None,
        "reason_seen": False,
        "keys": 1,
        "ms": 1000,
        "time": "2026-10-20T10:00:00Z",
    }


def index(receipt: dict[str, Any], cid: str) -> int:
    (i,) = [i for i, d in enumerate(receipt["decisions"]) if d["candidate_id"] == cid]
    return i


def write_answers(store: FolderStore, k: str, answers: list[dict[str, Any]]) -> list[str]:
    """Append each answer of a case to the log of its reviewer, in case order. Return the
    reviewer names."""
    tasks = task_keys(store, k)
    receipt = load_packet(store, k).receipt
    for a in answers:
        slot = (a["slot"]["field"], a["slot"]["key"])
        decision = index(receipt, a["choice"]) if "choice" in a else None
        given = record(
            tasks[slot][0],
            a["reviewer"],
            a["verdict"],
            decision=decision,
            candidate=a.get("candidate"),
            codes_kept=a.get("codes_kept", []),
        )
        store.append(("answers", k, reviewer_key(a["reviewer"])), given)
    return sorted({a["reviewer"] for a in answers})


def correction_receipt(packet: dict[str, Any], candidate: dict[str, Any]) -> str:
    """The key of a correction receipt, from admit with the inputs of §6.2."""
    schema = packet["schema"]
    field = candidate["field"]
    keyed = schema["fields"][field].get("keys") is not None
    slot = (field, candidate.get("key") if keyed else None)
    kept = [
        c for c in packet["candidates"]
        if (c["field"], c.get("key") if schema["fields"][c["field"]].get("keys") else None) != slot
    ]  # fmt: skip
    removed = {c["id"] for c in packet["candidates"]} - {c["id"] for c in kept}
    judgments = packet["judgments"]
    if judgments is not None:
        judgments = [j for j in judgments if j["candidate_id"] not in removed]
    got = admit(packet["text"], schema, [*kept, candidate], packet["policy"], None, judgments)
    return _key("receipt@1", got.to_dict())


def expected(
    store: FolderStore, k: str, data: dict[str, Any], case: dict[str, Any], reviewers: list[str]
) -> dict[str, Any]:
    receipt = load_packet(store, k).receipt
    tasks = task_keys(store, k)
    heads = []
    for name in reviewers:
        log = store.read(("answers", k, reviewer_key(name)))
        heads.append({"reviewer": name, "head": log[-1]["entry_sha256"]})
    slots = []
    for s in case["expected"]["slots"]:
        if s["receipt"] == "packet":
            rkey = _key("receipt@1", receipt)
        else:
            who = s["receipt"].removeprefix("correction ")
            mine = [a for a in case["answers"] if a["reviewer"] == who]
            rkey = correction_receipt(data["packet"], mine[-1]["candidate"])
        tkey = None
        if s["task"] is not None:
            tkey, task = tasks[s["field"], s["key"]]
            assert task["mode"] == s["task"]
        slots.append(
            {"field": s["field"], "key": s["key"],
             "decisions": sorted(index(receipt, c) for c in s["candidates"]),
             "status": s["status"], "value": s["value"], "unit": s["unit"],
             "evidence": s["evidence"], "receipt": rkey, "task": tkey,
             "statements": None, "nodes": None}
        )  # fmt: skip
    return {
        "format": "resolution@1",
        "packet": k,
        "policy": _key("review-policy@1", case["policy"]),
        "answers": heads,
        "slots": slots,
    }


# The cases (#408)


@pytest.mark.parametrize(("stem", "case"), CASES, ids=CASE_IDS)
def test_cases_give_their_resolution(tmp_path: Path, stem: str, case: dict[str, Any]) -> None:
    data = FILES[stem]
    with FolderStore(tmp_path / "s") as store:
        k = stored(store, data["packet"])
        reviewers = write_answers(store, k, case["answers"])
        if "error" in case["expected"]:
            with pytest.raises(AnswerError) as info:
                write_resolution(store, k, case["policy"], reviewers)
            assert info.value.reviewer == case["expected"]["error"]["reviewer"]
            assert info.value.sequence == case["expected"]["error"]["sequence"]
            return
        got = write_resolution(store, k, case["policy"], reviewers)
        want = expected(store, k, data, case, reviewers)
        assert got.problems == ()
        assert got.resolution == want
        assert got.key is not None
        assert store.get("resolution@1", got.key) == jcs(want).encode("utf-8")
        for slot in want["slots"]:  # each receipt and task that the resolution names is stored
            store.get("receipt@1", slot["receipt"])
            if slot["task"] is not None:
                store.get("task@1", slot["task"])
        store.get("review-policy@1", want["policy"])
    jsonschema = pytest.importorskip("jsonschema")
    check = jsonschema.Draft202012Validator(format_schema("resolution@1"))
    assert check.is_valid(want), list(check.iter_errors(want))


def test_the_same_inputs_give_the_same_bytes(tmp_path: Path) -> None:
    (case,) = [c for c in FILES["one-choice"]["cases"] if c["name"] == "kept-code-counts"]
    data = FILES["one-choice"]
    outs = []
    for n in (1, 2):
        with FolderStore(tmp_path / f"s{n}") as store:
            k = stored(store, data["packet"])
            reviewers = write_answers(store, k, case["answers"])
            first = write_resolution(store, k, case["policy"], reviewers)
            again = write_resolution(store, k, case["policy"], [*reviewers, *reviewers])
            assert first == again
            packet, schema, _, _ = checked_packet(store, k)
            assert schema is not None
            logs = {r: store.read(("answers", k, reviewer_key(r))) for r in reviewers}
            pure, _ = resolve(k, packet, schema, case["policy"], logs)
            assert jcs(pure) == jcs(first.resolution)
            outs.append(jcs(first.resolution))
    assert outs[0] == outs[1]


# Corrections (§6.2)


def one_choice(tmp_path: Path) -> tuple[FolderStore, str, str, dict[str, Any]]:
    store = FolderStore(tmp_path / "s")
    data = FILES["one-choice"]
    k = stored(store, data["packet"])
    tk, _ = task_keys(store, k)["revenue", None]
    return store, k, tk, data


def correction(value: str, cid: str = "ana-1", **more: Any) -> dict[str, Any]:
    return {
        "id": cid,
        "field": "revenue",
        "value": value,
        "proposer": "person:ana",
        "evidence": {"start": 12, "end": 26, "text": "4,200 thousand"},
        **more,
    }


def test_a_rejected_correction_never_counts(tmp_path: Path) -> None:
    store, k, tk, data = one_choice(tmp_path)
    log = ("answers", k, reviewer_key("ana"))
    with store:
        store.append(log, record(tk, "ana", "correct", candidate=correction("4300000")))
        got = write_resolution(store, k, policy(), ["ana"])
        assert got.resolution is not None
        (slot,) = got.resolution["slots"]
        assert (slot["status"], slot["value"]) == ("open", None)
        # Ana keeps the code of the rejection: a rejected correction still does not count.
        store.append(
            log,
            record(
                tk, "ana", "correct", candidate=correction("4300000"),
                codes_kept=["VALUE_NOT_IN_EVIDENCE"],
            ),
        )  # fmt: skip
        got = write_resolution(store, k, policy(), ["ana"])
        assert got.resolution is not None
        assert got.resolution["slots"][0]["status"] == "open"
        # The receipt of the rejected correction is in the store.
        rkey = correction_receipt(data["packet"], correction("4300000"))
        rejected = json.loads(store.get("receipt@1", rkey))
        assert [d["outcome"] for d in rejected["decisions"] if d["candidate_id"] == "ana-1"] == [
            "rejected"
        ]


def test_the_id_of_a_correction_differs_from_each_candidate_id(tmp_path: Path) -> None:
    """#410 open point: a person's candidate with the id of a candidate of the packet makes the
    correction call to admit invalid, so the resolution stops."""
    store, k, tk, _ = one_choice(tmp_path)
    with store:
        store.append(
            ("answers", k, reviewer_key("ana")),
            record(tk, "ana", "correct", candidate=correction("4200000", "c1")),
        )
        with pytest.raises(AnswerError, match="id of a candidate of the packet") as info:
            write_resolution(store, k, policy(), ["ana"])
    assert (info.value.reviewer, info.value.sequence) == ("ana", 1)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"task": "sha256:" + "0" * 64}, "not a task of a slot of this packet"),
        ({"task": ["a list"]}, "not a task of a slot of this packet"),
        ({"reviewer": "ben"}, "another reviewer than its log"),
        ({"format": "answer@3"}, "not answer@1 or answer@2"),
        ({"format": "answer@2"}, "members of answer@2"),
        ({"verdict": "wrong"}, "wrong needs answer@2"),
        ({"format": "answer@2", "field_keys": []}, "only a calibrate key task"),
        ({"verdict": "maybe"}, "not an answer@1 verdict"),
        ({"decision": 0}, "a confirm answer has no decision"),
        ({"codes_kept": ["SCALE_WORD"]}, "only a correction keeps codes"),
        ({"nodes": []}, "null in format 1"),
        ({"ms": -1}, "ms is not an integer"),
        ({"extra": 1}, "members of answer@1"),
    ],
)
def test_an_answer_that_breaks_its_task_stops(
    tmp_path: Path, change: dict[str, Any], message: str
) -> None:
    store, k, tk, _ = one_choice(tmp_path)
    with store:
        log = ("answers", k, reviewer_key("ana"))
        store.append(log, record(tk, "ana", "confirm"))
        store.append(log, {**record(tk, "ana", "confirm"), **change})
        with pytest.raises(AnswerError, match=message) as info:
            write_resolution(store, k, policy(), ["ana"])
    assert (info.value.reviewer, info.value.sequence) == ("ana", 2)


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (correction("4200000", field="net_income"), "another field or key"),
        (correction("4200000", key="2025"), "has a key"),
        (correction("4200000", proposer="model:x"), "proposer"),
        (correction("4200000", id=7), "id is not a string"),
    ],
)
def test_a_bad_candidate_stops(tmp_path: Path, candidate: dict[str, Any], message: str) -> None:
    store, k, tk, _ = one_choice(tmp_path)
    with store:
        store.append(
            ("answers", k, reviewer_key("ana")), record(tk, "ana", "correct", candidate=candidate)
        )
        with pytest.raises(AnswerError, match=message):
            write_resolution(store, k, policy(), ["ana"])


def test_a_log_with_no_record_adds_nothing(tmp_path: Path) -> None:
    store, k, _, _ = one_choice(tmp_path)
    with store:
        got = write_resolution(store, k, policy(), ["ana", "ben"])
    assert got.resolution is not None
    assert got.resolution["answers"] == []
    assert got.resolution["slots"][0]["status"] == "open"


def test_lines() -> None:
    slot = {"field": "rent", "key": None, "decisions": [0], "status": "chosen",
            "value": "1200", "unit": "USD"}  # fmt: skip
    resolution = {
        "slots": [
            slot,
            {**slot, "key": "2025\x1b[2J", "status": "open", "value": None, "unit": None},
            {**slot, "field": "tenant", "decisions": [1], "unit": None, "value": "A\nB"},
            {**slot, "field": "tenant", "decisions": [2], "status": "disputed", "value": None},
            {**slot, "field": "note", "value": "\U000e0001\u200b1", "unit": None},
        ]
    }
    assert lines(resolution) == [
        "rent: 1200 USD (chosen)",
        "rent [2025\\u001b[2J]: no value (open: no answer settles the task yet)",
        "tenant #1: A\\u000aB (chosen)",
        "tenant #2: no value (disputed: the reviewers do not agree)",
        "note: \\U000e0001\\u200b1 (chosen)",  # one fixed length on each side of U+FFFF (#448)
    ]


def test_command_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "s"
    data = FILES["conflict"]
    (case,) = [c for c in data["cases"] if c["name"] == "lead-settles-a-dispute"]
    with FolderStore(root) as store:
        k = stored(store, data["packet"])
        reviewers = write_answers(store, k, case["answers"])
    given = tmp_path / "policy.json"
    given.write_text(json.dumps(case["policy"]), encoding="utf-8")
    named = [arg for r in reviewers for arg in ("--reviewer", r)]
    args = ["review", "resolve", "--store", str(root), k, "--policy", str(given)]
    assert main([*args, *named]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[1:] == ["net_income: 310000 (admitted)", "revenue: 4200 (chosen)"]
    with FolderStore(root) as store:
        assert json.loads(store.get("resolution@1", out[0]))["packet"] == k

    assert main([*args, "--reviewer", "ana"]) == 0  # Ana alone: no dispute
    assert capsys.readouterr().out.splitlines()[2] == "revenue: 4200000 (chosen)"
    assert main(["review", "resolve", "--store", str(root), k]) == 0  # no log: open
    assert capsys.readouterr().out.splitlines()[2] == (
        "revenue: no value (open: no answer settles the task yet)"
    )

    with FolderStore(root) as store:
        log = ("answers", k, reviewer_key("cy"))
        tk = task_keys(store, k)["revenue", None][0]
        store.append(log, record(tk, "cy", "confirm"))
    assert main([*args, *named]) == 2
    err = capsys.readouterr().err
    assert "answer 2 of the reviewer cy" in err and "exactly one choice" in err
    assert main([*args, "--reviewer", " "]) == 2
    assert "reviewer name" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["review", "resolve", k])  # --store is required


def test_an_error_of_admit_shows_no_control_character(tmp_path: Path) -> None:
    """A message of admit can quote the candidate, so the message of AnswerError escapes each
    control character (security review of #443, finding 1)."""
    store, k, tk, _ = one_choice(tmp_path)
    with store:
        log = ("answers", k, reviewer_key("ana"))
        store.append(log, record(tk, "ana", "correct", candidate=correction("4200000")))
        packet, schema, _, _ = checked_packet(store, k)
        assert schema is not None
        logs = {"ana": store.read(log)}

    def run(candidates: list[Any], judgments: list[Any] | None) -> Any:
        raise PacketError("candidate key '\x1b[2J\U0010ffff' is invalid")

    with pytest.raises(AnswerError) as info:
        resolve(k, packet, schema, policy(), logs, correct=run)
    assert "\x1b" not in str(info.value) and "\\u001b[2J\\U0010ffff'" in str(info.value)
    assert "\n" not in str(AnswerError("a\nb", 1, "line\none"))


def test_a_broken_answer_runs_no_correction_and_writes_nothing(tmp_path: Path) -> None:
    """Each record is checked before the first correction runs, and the corrections go to the
    store only after the resolution succeeds (security review of #443, finding 2)."""
    store, k, tk, data = one_choice(tmp_path)
    with store:
        log = ("answers", k, reviewer_key("ana"))
        store.append(log, record(tk, "ana", "correct", candidate=correction("4200000")))
        store.append(log, record(tk, "ana", "choose", decision=99))
        packet, schema, _, _ = checked_packet(store, k)
        assert schema is not None
        calls: list[Any] = []

        def run(candidates: list[Any], judgments: list[Any] | None) -> Any:
            calls.append(candidates)
            raise AssertionError("no correction runs")

        with pytest.raises(AnswerError, match="not a choice"):
            resolve(k, packet, schema, policy(), {"ana": store.read(log)}, correct=run)
        assert calls == []
        with pytest.raises(AnswerError, match="not a choice"):
            write_resolution(store, k, policy(), ["ana"])
        rkey = correction_receipt(data["packet"], correction("4200000"))
        with pytest.raises(NotFound):
            store.get("receipt@1", rkey)


# store forget --all (#516)


def _naming(store: FolderStore, kind: str, packet: str) -> list[str]:
    keys, _ = store.object_keys()
    out = []
    for k in keys:
        data = store.object_bytes(k)
        if key(kind, data) == k and json.loads(data).get("packet") == packet:
            out.append(k)
    return out


def test_forget_all_removes_the_review_objects_of_the_packet(tmp_path: Path) -> None:
    store, k, tk, data = one_choice(tmp_path)
    root = tmp_path / "s"
    outside = tmp_path / "outside.json"
    outside.write_text("{}", "utf-8")
    packet = data["packet"]
    with store:
        # The other packet: the same inputs, another document id, and its own review.
        other, _ = admit_packet(
            store, packet["text"], packet["schema"], packet["candidates"], packet["policy"],
            "other", packet["judgments"],
        )  # fmt: skip
        (otk,) = [t for t, _ in write_tasks(store, other, EVERY).tasks]
        store.append(
            ("answers", other, reviewer_key("ana")),
            record(otk, "ana", "correct", candidate=correction("4200000")),
        )
        kept = write_resolution(store, other, policy(), ["ana"])
        # Ana's correction counts. Ben's correction is rejected, and no resolution names its
        # receipt. A record of Cy names a path outside the store.
        store.append(
            ("answers", k, reviewer_key("ana")),
            record(tk, "ana", "correct", candidate=correction("4200000")),
        )
        first = write_resolution(store, k, policy(), ["ana"])
        assert first.resolution is not None
        assert first.resolution["slots"][0]["status"] == "corrected"
        bad = {**record(tk, "cy", "correct", candidate={"id": "../../outside.json"}),
               "task": "../../outside.json"}  # fmt: skip
        store.append(("answers", k, reviewer_key("cy")), bad)
        store.append(
            ("answers", k, reviewer_key("ben")),
            record(tk, "ben", "correct", candidate=correction("4300000", "ben-1")),
        )
        second = write_resolution(store, k, policy(), ["ana", "ben"])
        assert second.resolution is not None
        receipts = [
            correction_receipt(packet, correction("4200000")),
            correction_receipt(packet, correction("4300000", "ben-1")),
        ]
        assert [s["receipt"] for s in second.resolution["slots"]] == receipts[:1]
        keys, _ = store.object_keys()
        corrections = [
            p for p in keys
            if key("packet@1", store.object_bytes(p)) == p
            and json.loads(store.object_bytes(p))["receipt"] in receipts
        ]  # fmt: skip
        assert len(corrections) == 2
        policies = [p for p in keys if key("review-policy@1", store.object_bytes(p)) == p]
        other_review = [*_naming(store, "task@1", other), *_naming(store, "resolution@1", other)]
        assert len(other_review) == 2
        # The other packet and its correction packet, with the objects that they name. Their
        # candidates are the same bytes as the candidates of this packet, so they go for both.
        mine = []
        for p in keys:
            data = store.object_bytes(p)
            if key("packet@1", data) == p and json.loads(data)["document"]["id"] == "other":
                obj = json.loads(data)
                mine += [p, obj["schema"], obj["policy"], obj["receipt"]]
        assert len(mine) == 8
    with FolderStore(root) as store:
        done = forget_packet(store, k, "all", everything=True)
        assert {(kind, state) for kind, _, state, _ in done if kind == "task@1"} == {
            ("task@1", "deleted")
        }
        assert _naming(store, "task@1", k) == [] and _naming(store, "resolution@1", k) == []
        left, _ = store.object_keys()
        assert not set(corrections) & set(left)
        assert not set(receipts) & set(left)
        # The policies, the other packet and its review objects stay.
        assert set(policies) <= set(left)
        assert {kept.key, *other_review, *mine} <= set(left)
        assert all(store.read(("answers", other, reviewer_key("ana"))))
    assert outside.read_text("utf-8") == "{}"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["outside.json", "s"]


def test_forget_all_keeps_a_packet_that_only_holds_the_candidate_of_a_correction(
    tmp_path: Path,
) -> None:
    # Another packet of the same inputs holds the original candidate and the candidate of a
    # correction answer. review resolve never gives these candidates to admit, because it
    # removes the candidates of the slot. A packet with a receipt list is also not a
    # correction, and it does not stop forget.
    store, k, tk, data = one_choice(tmp_path)
    packet = data["packet"]
    with store:
        store.append(
            ("answers", k, reviewer_key("ana")),
            record(tk, "ana", "correct", candidate=correction("4200000")),
        )
        both, _ = admit_packet(
            store, packet["text"], packet["schema"],
            [*packet["candidates"], correction("4200000")], packet["policy"], None,
            packet["judgments"],
        )  # fmt: skip
        odd = {**json.loads(store.get("packet@1", k)), "receipt": []}
        odd_key = store.put("packet@1", jcs(odd).encode("utf-8"))
    with FolderStore(tmp_path / "s") as store:
        done = forget_packet(store, k, "all", everything=True)
        left, _ = store.object_keys()
    assert {both, odd_key} <= set(left)
    assert ("packet@1", k, "deleted", 0) in done


def test_forget_all_keeps_a_correction_that_another_packet_shares(tmp_path: Path) -> None:
    # Two packets differ only in the candidate of the slot. The same correction of each gives
    # one correction packet, and the resolution of the other packet names its receipt.
    store, k, tk, data = one_choice(tmp_path)
    packet = data["packet"]
    changed = [{**packet["candidates"][0], "value": "4200001"}]
    with store:
        other, _ = admit_packet(
            store, packet["text"], packet["schema"], changed, packet["policy"], None,
            packet["judgments"],
        )  # fmt: skip
        (otk,) = [t for t, _ in write_tasks(store, other, EVERY).tasks]
        for pk, t in ((k, tk), (other, otk)):
            store.append(
                ("answers", pk, reviewer_key("ana")),
                record(t, "ana", "correct", candidate=correction("4200000")),
            )
        first = write_resolution(store, k, policy(), ["ana"])
        second = write_resolution(store, other, policy(), ["ana"])
        assert first.resolution is not None and second.resolution is not None
        (receipt,) = {s["receipt"] for s in second.resolution["slots"]}
        assert {s["receipt"] for s in first.resolution["slots"]} == {receipt}
    with FolderStore(tmp_path / "s") as store:
        done = forget_packet(store, k, "all", everything=True)
        left, _ = store.object_keys()
    assert ("receipt@1", receipt, "kept", 1) in done
    assert {receipt, other, second.key} <= set(left)
    assert _naming(FolderStore(tmp_path / "s"), "resolution@1", k) == []


def test_forget_all_keeps_the_packet_when_an_answer_log_cannot_be_read(tmp_path: Path) -> None:
    # A torn answer log can name a correction. forget --all keeps the packet and its review
    # objects, and after the repair a second forget --all finishes.
    store, k, tk, data = one_choice(tmp_path)
    root = tmp_path / "s"
    log = ("answers", k, reviewer_key("ana"))
    with store:
        store.append(log, record(tk, "ana", "correct", candidate=correction("4200000")))
        got = write_resolution(store, k, policy(), ["ana"])
    receipt = correction_receipt(data["packet"], correction("4200000"))
    path = root / "logs" / "answers" / k[7:] / f"{reviewer_key('ana')[7:]}.jsonl"
    with path.open("ab") as f:
        f.write(b"{")
    with FolderStore(root) as store:
        done = forget_packet(store, k, "all", everything=True)
        left, _ = store.object_keys()
    rel = f"logs/answers/{k[7:]}/{reviewer_key('ana')[7:]}.jsonl"
    assert ("log", rel, "unchecked", 0) in done
    assert ("packet@1", k, "kept", 0) in done
    assert {k, got.key, tk, receipt} <= set(left)
    with FolderStore(root) as store:
        assert check(store, repair=True).cut
    with FolderStore(root) as store:
        done = forget_packet(store, k, "all", everything=True)
        left, _ = store.object_keys()
    assert not {k, got.key, tk, receipt} & set(left)
    assert not any(state == "unchecked" for _, _, state, _ in done)
    assert not path.exists()
