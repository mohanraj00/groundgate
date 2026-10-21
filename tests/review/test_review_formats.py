"""The four review formats (docs/design/review.md §5) and the resolution cases (§6).

The cases in ``cases/`` are written by hand. No case comes from a run of groundgate: the
resolution code (#410) must agree with them. These tests check the shape of each case, check each
case against the four schemas, and check the premises of each case with ``admit``: the outcome of
each candidate of the packet and of each correction. A premise that fails is a mistake in the
case, so correct the packet, never the expected resolution.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from groundgate import admit
from groundgate.canonical import jcs
from groundgate.codes import INFO
from groundgate.review import FORMATS, format_schema

HERE = Path(__file__).parent
CASE_FILES = sorted((HERE / "cases").glob("*.json"))
PICKS = HERE / "audit-picks.json"
KEY = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64

# Each rule of §6.1 and §6.2 needs a case (#408). 6.3 holds the points that the cases settle.
REQUIRED_RULES = {f"6.1.{n}" for n in range(1, 8)} | {"6.2", "6.2.1", "6.2.2", "6.2.3"}
RULES = REQUIRED_RULES | {"5.1", "5.2"} | {f"6.3.{n}" for n in range(1, 10)}
STATUSES = {
    "admitted",
    "confirmed",
    "chosen",
    "corrected",
    "not_in_document",
    "rejected",
    "open",
    "disputed",
}
CORRECTIONS = {"correct", "adjust_span"}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


FILES = {path.stem: _load(path) for path in CASE_FILES}
CASES = [(stem, case) for stem, data in FILES.items() for case in data["cases"]]
CASE_IDS = [f"{stem}/{case['name']}" for stem, case in CASES]


def _validator(name: str) -> Any:
    jsonschema = pytest.importorskip("jsonschema")
    schema = format_schema(name)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


# The schemas


@pytest.mark.parametrize("name", FORMATS)
def test_each_schema_ships_with_the_package(name: str) -> None:
    schema = format_schema(name)
    assert schema["properties"]["format"] == {"const": name}
    assert schema["title"].endswith(f"format {name}")
    _validator(name)


def test_an_unknown_format_is_refused() -> None:
    with pytest.raises(ValueError, match="not a review format"):
        format_schema("task@2")
    with pytest.raises(ValueError, match="not a review format"):
        format_schema("../candidate")


def test_format_1_reserves_the_later_kinds_and_members() -> None:
    task = format_schema("task@1")
    assert {"closed_set", "model_text", "structure"} <= set(task["properties"]["item"]["enum"])
    answer = format_schema("answer@1")["properties"]
    assert {"statements", "nodes"} <= set(answer)
    slot = format_schema("resolution@1")["$defs"]["slot"]["properties"]
    assert {"statements", "nodes"} <= set(slot)


def _policy() -> dict[str, Any]:
    return {
        "format": "review-policy@1",
        "audit": {"rate": "0.02", "seed": "2026-10-lease"},
        "agree": 1,
        "leads": ["ana"],
        "rejected": False,
    }


def _task() -> dict[str, Any]:
    return {
        "format": "task@1",
        "packet": KEY,
        "slot": {"field": "total_revenue", "key": "2025", "decisions": [3, 7]},
        "item": "number",
        "mode": "review",
        "template": "number@1",
        "question": "Which amount is total revenue for 2025?",
        "parts": ["amount", "scale", "sign", "unit", "field", "key"],
        "codes": ["CONFLICTING_CANDIDATES"],
        "choices": [
            {
                "decision": 3,
                "value": "4200000",
                "unit": "USD",
                "shown": "$4,200,000 (written 4,200, in thousands)",
                "evidence": {"start": 18120, "end": 18125},
            },
            {
                "decision": 7,
                "value": "4200",
                "unit": "USD",
                "shown": "$4,200",
                "evidence": {"start": 18120, "end": 18125},
            },
        ],
        "places": [{"start": 18120, "end": 18125, "page": 41, "box": [72.0, 310.5, 101.2, 321.0]}],
    }


def _answer(verdict: str = "correct") -> dict[str, Any]:
    candidate = {
        "id": "review-1",
        "field": "total_revenue",
        "key": "2025",
        "value": "4200000",
        "unit": "USD",
        "proposer": "person:ana",
        "evidence": [
            {"start": 18120, "end": 18125},
            {"role": "scale", "start": 17002, "end": 17025},
        ],
    }
    return {
        "format": "answer@1",
        "task": KEY,
        "reviewer": "ana",
        "verdict": verdict,
        "decision": 3 if verdict == "choose" else None,
        "candidate": candidate if verdict in CORRECTIONS else None,
        "codes_kept": [],
        "statements": None,
        "nodes": None,
        "reason_seen": False,
        "keys": 3,
        "ms": 8400,
        "time": "2026-10-20T10:31:07Z",
    }


def _slot(**members: Any) -> dict[str, Any]:
    slot = {
        "field": "total_revenue",
        "key": "2025",
        "decisions": [3, 7],
        "status": "corrected",
        "value": "4200000",
        "unit": "USD",
        "evidence": {"start": 18120, "end": 18125},
        "receipt": KEY,
        "task": OTHER,
        "statements": None,
        "nodes": None,
    }
    slot.update(members)
    return slot


def _resolution(*slots: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": "resolution@1",
        "packet": KEY,
        "policy": OTHER,
        "answers": [{"reviewer": "ana", "head": KEY}],
        "slots": list(slots) or [_slot()],
    }


def test_the_examples_of_the_note_are_valid() -> None:
    assert _validator("review-policy@1").is_valid(_policy())
    assert _validator("task@1").is_valid(_task())
    check = _validator("answer@1")
    for verdict in ("confirm", "choose", "correct", "adjust_span", "not_in_document", "unsure"):
        assert check.is_valid(_answer(verdict)), verdict
    stored = {**_answer(), "sequence": 1, "previous": None, "entry_sha256": OTHER}
    assert check.is_valid(stored)
    assert _validator("resolution@1").is_valid(_resolution())


def _change(obj: dict[str, Any], path: tuple[Any, ...], value: Any) -> dict[str, Any]:
    out = copy.deepcopy(obj)
    target = out
    for step in path[:-1]:
        target = target[step]
    if value is _DROP:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return out


_DROP = object()

BAD = [
    ("review-policy@1", _policy, ("audit", "rate"), "0.020"),
    ("review-policy@1", _policy, ("audit", "rate"), "1.5"),
    ("review-policy@1", _policy, ("audit", "rate"), 0.02),
    ("review-policy@1", _policy, ("agree",), 0),
    ("review-policy@1", _policy, ("leads",), ["ana", "ana"]),
    ("review-policy@1", _policy, ("rejected",), _DROP),
    ("task@1", _task, ("policy",), KEY),
    ("task@1", _task, ("packet",), "sha256:ABC"),
    ("task@1", _task, ("item",), "table"),
    ("task@1", _task, ("mode",), "blind"),
    ("task@1", _task, ("slot", "field"), "Total revenue"),
    ("task@1", _task, ("places", 0, "box"), [1, 2, 3]),
    ("answer@1", _answer, ("verdict",), "maybe"),
    ("answer@1", _answer, ("candidate",), None),
    ("answer@1", _answer, ("candidate", "proposer"), "model:x"),
    ("answer@1", _answer, ("statements",), _DROP),
    ("answer@1", _answer, ("time",), "2026-10-20 10:31:07"),
    ("resolution@1", _resolution, ("slots", 0, "status"), "pending"),
    ("resolution@1", _resolution, ("slots", 0, "task"), None),
    ("resolution@1", _resolution, ("slots", 0, "nodes"), _DROP),
    (
        "resolution@1",
        _resolution,
        ("slots", 0, "nodes"),
        [{"node": "n1", "verdict": "accepted", "box": [0, 0, 1, 1]}],
    ),
]


@pytest.mark.parametrize(("name", "make", "path", "value"), BAD, ids=lambda x: repr(x)[:40])
def test_a_bad_member_is_invalid(name: str, make: Any, path: tuple[Any, ...], value: Any) -> None:
    assert not _validator(name).is_valid(_change(make(), path, value))


def test_the_verdict_sets_the_other_members() -> None:
    check = _validator("answer@1")
    assert not check.is_valid({**_answer("choose"), "decision": None})
    assert not check.is_valid({**_answer("confirm"), "decision": 3})
    assert not check.is_valid({**_answer("unsure"), "codes_kept": ["SCALE_WORD"]})
    assert check.is_valid({**_answer("correct"), "codes_kept": ["SCALE_WORD"]})


def test_a_slot_with_no_value_has_no_value() -> None:
    check = _validator("resolution@1")
    assert check.is_valid(_resolution(_slot(status="open", value=None, unit=None, evidence=None)))
    assert not check.is_valid(_resolution(_slot(status="open")))
    assert not check.is_valid(_resolution(_slot(status="chosen", value=None)))
    assert check.is_valid(_resolution(_slot(status="admitted", task=None)))


# The cases


def test_every_rule_and_status_has_a_case() -> None:
    rules = {rule for _, case in CASES for rule in case["rules"]}
    assert rules >= REQUIRED_RULES, sorted(REQUIRED_RULES - rules)
    statuses = {slot["status"] for _, case in CASES for slot in case["expected"].get("slots", [])}
    assert statuses == STATUSES


def test_case_names_are_unique() -> None:
    assert len(set(CASE_IDS)) == len(CASE_IDS)


@pytest.mark.parametrize(("stem", "case"), CASES, ids=CASE_IDS)
def test_case_shape(stem: str, case: dict[str, Any]) -> None:
    data = FILES[stem]
    assert set(data) == {"about", "packet", "decisions", "coverage", "cases"}
    ids = [c["id"] for c in data["packet"]["candidates"]]
    assert sorted(ids) == sorted(data["decisions"])
    assert set(case) == {"name", "rules", "about", "policy", "answers", "expected"}
    assert case["rules"] and set(case["rules"]) <= RULES
    reviewers = []
    for answer in case["answers"]:
        assert set(answer) <= {
            "reviewer",
            "slot",
            "verdict",
            "choice",
            "candidate",
            "codes_kept",
            "admit",
        }
        assert set(answer["slot"]) == {"field", "key"}
        assert ("choice" in answer) == (answer["verdict"] == "choose")
        if "choice" in answer:
            assert answer["choice"] in ids
        correction = answer["verdict"] in CORRECTIONS
        assert ("candidate" in answer) == correction == ("admit" in answer)
        if correction:
            assert answer["candidate"]["id"] not in ids
            assert answer["candidate"]["field"] == answer["slot"]["field"]
        reviewers.append(answer["reviewer"])
    expected = case["expected"]
    if "error" in expected:
        assert set(expected) == {"error"}
        error = expected["error"]
        assert 1 <= error["sequence"] <= reviewers.count(error["reviewer"])
        return
    assert set(expected) == {"slots"}
    fields = [(s["field"], s["key"] or "") for s in expected["slots"]]
    assert fields == sorted(fields), "the slots are in field order"
    covered = []
    for slot in expected["slots"]:
        assert slot["status"] in STATUSES
        covered += slot["candidates"]
        if slot["status"] == "corrected":
            who = slot["receipt"].removeprefix("correction ")
            assert slot["receipt"] == f"correction {who}"
            assert any(
                a["reviewer"] == who and a["verdict"] in CORRECTIONS for a in case["answers"]
            )
        else:
            assert slot["receipt"] == "packet"
        assert slot["task"] in (None, "review", "audit")
    assert sorted(covered) == sorted(ids)


@pytest.mark.parametrize(("stem", "case"), CASES, ids=CASE_IDS)
def test_case_policy_is_a_review_policy(stem: str, case: dict[str, Any]) -> None:
    check = _validator("review-policy@1")
    assert check.is_valid(case["policy"]), list(check.iter_errors(case["policy"]))


@pytest.mark.parametrize(("stem", "case"), CASES, ids=CASE_IDS)
def test_case_answers_are_answers(stem: str, case: dict[str, Any]) -> None:
    check = _validator("answer@1")
    ids = [c["id"] for c in FILES[stem]["packet"]["candidates"]]
    for answer in case["answers"]:
        record = {
            "format": "answer@1",
            "task": KEY,
            "reviewer": answer["reviewer"],
            "verdict": answer["verdict"],
            "decision": ids.index(answer["choice"]) if "choice" in answer else None,
            "candidate": answer.get("candidate"),
            "codes_kept": answer.get("codes_kept", []),
            "statements": None,
            "nodes": None,
            "reason_seen": False,
            "keys": 1,
            "ms": 1000,
            "time": "2026-10-20T10:00:00Z",
        }
        assert check.is_valid(record), list(check.iter_errors(record))


@pytest.mark.parametrize(("stem", "case"), CASES, ids=CASE_IDS)
def test_case_expected_is_a_resolution(stem: str, case: dict[str, Any]) -> None:
    if "error" in case["expected"]:
        return
    ids = [c["id"] for c in FILES[stem]["packet"]["candidates"]]
    slots = []
    for slot in case["expected"]["slots"]:
        slots.append(
            _slot(
                field=slot["field"],
                key=slot["key"],
                decisions=[ids.index(c) for c in slot["candidates"]],
                status=slot["status"],
                value=slot["value"],
                unit=slot["unit"],
                evidence=slot["evidence"],
                task=None if slot["task"] is None else OTHER,
            )
        )
    check = _validator("resolution@1")
    resolution = _resolution(*slots)
    assert check.is_valid(resolution), list(check.iter_errors(resolution))


# The premises: what admit gives for the packet and for each correction


def _admit(packet: dict[str, Any], candidates: list[Any], judgments: Any) -> dict[str, Any]:
    receipt = admit(packet["text"], packet["schema"], candidates, packet["policy"], None, judgments)
    return receipt.to_dict()


def _outcomes(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        d["candidate_id"]: {"outcome": d["outcome"], "codes": d["codes"]}
        for d in receipt["decisions"]
    }


@pytest.mark.parametrize("stem", sorted(FILES))
def test_packet_premise(stem: str) -> None:
    data = FILES[stem]
    packet = data["packet"]
    receipt = _admit(packet, packet["candidates"], packet["judgments"])
    assert _outcomes(receipt) == data["decisions"]
    assert [c["field"] for c in receipt["coverage"]] == data["coverage"]


def _slot_key(schema: dict[str, Any], candidate: dict[str, Any]) -> tuple[str, Any]:
    keyed = schema["fields"][candidate["field"]].get("keys") is not None
    return candidate["field"], candidate.get("key") if keyed else None


@pytest.mark.parametrize(("stem", "case"), CASES, ids=CASE_IDS)
def test_correction_premise(stem: str, case: dict[str, Any]) -> None:
    """§6.2: the candidates of the packet without those of the slot, with the candidate of the
    person, and the judgments without those of the removed candidates."""
    packet = FILES[stem]["packet"]
    schema = packet["schema"]
    for answer in case["answers"]:
        if answer["verdict"] not in CORRECTIONS:
            continue
        slot = (answer["slot"]["field"], answer["slot"]["key"])
        kept = [c for c in packet["candidates"] if _slot_key(schema, c) != slot]
        removed = {c["id"] for c in packet["candidates"]} - {c["id"] for c in kept}
        judgments = packet["judgments"]
        if judgments is not None:
            judgments = [j for j in judgments if j["candidate_id"] not in removed]
        receipt = _admit(packet, [*kept, answer["candidate"]], judgments)
        assert _outcomes(receipt)[answer["candidate"]["id"]] == answer["admit"]


@pytest.mark.parametrize(("stem", "case"), CASES, ids=CASE_IDS)
def test_kept_codes_are_codes_of_the_correction(stem: str, case: dict[str, Any]) -> None:
    for answer in case["answers"]:
        kept = answer.get("codes_kept", [])
        if kept:
            flags = [c for c in answer["admit"]["codes"] if c not in INFO]
            assert set(kept) <= set(flags)


# The audit pick (§6.3, point 2)


def _picked(h: int, rate: str) -> bool:
    whole, _, digits = rate.partition(".")
    n = int(whole + digits)
    return h * 10 ** len(digits) < n * 2**64


def test_audit_pick_vectors() -> None:
    check = _validator("review-policy@1")
    for row in _load(PICKS)["vectors"]:
        parts = [row["seed"], row["packet"], row["field"], row["key"], row["decision"]]
        hashed = "groundgate-audit/1:" + jcs(parts)
        assert hashed == row["hashed"]
        h = int.from_bytes(hashlib.sha256(hashed.encode("utf-8")).digest()[:8], "big")
        assert f"{h:016x}" == row["first_8_bytes"]
        for pick in row["picks"]:
            policy = _change(_policy(), ("audit", "rate"), pick["rate"])
            assert check.is_valid(policy), pick["rate"]
            assert _picked(h, pick["rate"]) == pick["picked"], pick["rate"]
