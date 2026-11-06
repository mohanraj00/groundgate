"""The proposer and agreement beyond the vectors (SPEC §2.4, §3.3 and §5, spec 0.12, #509)."""

from __future__ import annotations

import time
from typing import Any

import pytest

import groundgate as gg

TEXT = "Supply current Typ 1 mA Max 2 mA. Standby 2 mA."
SCHEMA: dict[str, Any] = {"fields": {"current": {"type": "number", "unit": "mA"}}}
STRUCTURE = {"proposers": {"structure": "corroborate"}}


def cand(cid: str, proposer: object = None, quote: str = "1 mA", **extra: Any) -> dict[str, Any]:
    item = {"source": "document", "role": "value", "text": quote}
    out = {"id": cid, "field": "current", "value": quote.split()[0], "unit": "mA", **extra}
    out["evidence"] = [item]
    if proposer is not None:
        out["proposer"] = proposer
    return out


def codes(receipt: gg.Receipt) -> dict[object, tuple[str, ...]]:
    return {d.candidate_id: d.codes for d in receipt.decisions}


def test_null_proposer_is_no_proposer() -> None:
    receipt = gg.admit(TEXT, SCHEMA, [{**cand("a"), "proposer": None}])
    assert receipt.decisions[0].outcome == "admitted"
    assert receipt.decisions[0].proposer is None


def test_two_candidates_with_no_proposer_are_one_proposer() -> None:
    both = [cand("a", quote="1 mA"), cand("b", quote="Typ 1 mA", value="1")]
    policy = {"proposers": {"structure": "corroborate", "other": "admit"}}
    assert codes(gg.admit(TEXT, SCHEMA, both, policy)) == {"a": (), "b": ()}


def test_an_admit_proposer_is_not_flagged_and_can_agree() -> None:
    policy = {"proposers": {"structure": "corroborate", "model": "admit"}}
    both = [cand("s", "structure"), cand("m", "model")]
    assert codes(gg.admit(TEXT, SCHEMA, both, policy)) == {"s": (), "m": ()}
    alone = [cand("m", "model")]
    assert codes(gg.admit(TEXT, SCHEMA, alone, policy)) == {"m": ()}


def test_no_corroborate_proposer_means_no_flag() -> None:
    policy = {"proposers": {"a": "admit", "b": "admit"}}
    both = [cand("a", "a", "2 mA"), {**cand("b", "b", "Standby 2 mA"), "value": "2"}]
    assert codes(gg.admit(TEXT, SCHEMA, both, policy)) == {"a": (), "b": ()}


def test_an_agreement_does_not_hide_another_span() -> None:
    text = "Supply current Typ 1 mA and Standby 1 mA."
    three = [
        cand("s", "structure", "Typ 1 mA", value="1"),
        cand("m", "model", "Typ 1 mA", value="1"),
        cand("o", "other", "Standby 1 mA", value="1"),
    ]
    assert codes(gg.admit(text, SCHEMA, three, STRUCTURE)) == {
        "s": ("OTHER_SPAN",),
        "m": (),
        "o": ("OTHER_SPAN",),
    }


def test_multiple_field_has_no_other_span() -> None:
    schema = {"fields": {"current": {"type": "number", "unit": "mA", "multiple": True}}}
    text = "Supply current Typ 1 mA and Standby 1 mA."
    both = [
        cand("s", "structure", "Typ 1 mA", value="1"),
        cand("m", "model", "Standby 1 mA", value="1"),
    ]
    assert codes(gg.admit(text, schema, both, STRUCTURE)) == {"s": ("NOT_CORROBORATED",), "m": ()}


def test_outside_path_has_neither_flag() -> None:
    item = {"source": "knowledge", "text": "It is 1 mA."}
    outside = {**cand("o", "structure"), "evidence": [item]}
    decision = gg.admit(TEXT, SCHEMA, [outside], STRUCTURE).decisions[0]
    assert decision.codes == ("EVIDENCE_STATED",)
    assert decision.proposer == "structure"
    other = gg.admit(TEXT, SCHEMA, [outside, cand("m", "model")], STRUCTURE)
    assert codes(other) == {"o": ("EVIDENCE_STATED",), "m": ()}


def test_receipt_order_and_verify() -> None:
    both = [cand("s", "structure"), cand("m", "model", "2 mA")]
    receipt = gg.admit(TEXT, SCHEMA, both, STRUCTURE).to_dict()
    first = list(receipt["decisions"][0])
    assert first.index("proposer") == first.index("key") + 1
    assert gg.verify(receipt, TEXT, SCHEMA, both, STRUCTURE).ok
    changed = {**STRUCTURE, "proposers": {"structure": "admit"}}
    assert not gg.verify(receipt, TEXT, SCHEMA, both, changed).ok


def test_policy_digest_covers_proposers() -> None:
    plain = gg.admit(TEXT, SCHEMA, [cand("a")], {}).to_dict()
    named = gg.admit(TEXT, SCHEMA, [cand("a")], {"proposers": {"x": "admit"}}).to_dict()
    assert plain["policy_sha256"] != named["policy_sha256"]
    policy = gg.Policy.from_dict({"proposers": {"x": "admit"}})
    assert policy.to_dict()["proposers"] == {"x": "admit"}


@pytest.mark.parametrize("bad", [[], "x", None, {"": "admit"}, {"\n": "admit"}, {"x": []}])
def test_invalid_proposers_make_the_packet_invalid(bad: object) -> None:
    with pytest.raises(gg.PacketError):
        gg.admit(TEXT, SCHEMA, [cand("a")], {"proposers": bad})


def test_candidate_schema_names_proposer() -> None:
    member = gg.candidate_schema()["properties"]["proposer"]
    assert member["type"] == ["string", "null"]
    assert member["pattern"] == "\\S"


def test_many_candidates_of_many_proposers_stay_fast() -> None:
    many = [cand(str(n), f"p{n}") for n in range(20000)]
    policy = {"proposers": {f"p{n}": "corroborate" for n in range(20000)}}
    begin = time.perf_counter()
    receipt = gg.admit(TEXT, SCHEMA, many, policy)
    assert time.perf_counter() - begin < 20
    assert all(d.outcome == "admitted" for d in receipt.decisions)
