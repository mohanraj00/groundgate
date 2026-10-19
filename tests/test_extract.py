"""Runner invariants with fixed replies, no network or model."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import itertools
import json

import pytest

import groundgate as gg
from groundgate.extract import (
    ExtractError,
    ExtractInputError,
    RunPolicy,
    RunResult,
    extract,
    replay,
)
from groundgate.extract.runner import _chunks, _queries


class Client:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("unexpected call")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)


def item(text, role="value", ref=None):
    return {
        "source": "document" if ref is None else "reference",
        "role": role,
        "text": text,
        **({"ref": ref} if ref is not None else {}),
    }


def candidate(value="5", field="amount", unit=None, evidence=None, key=None):
    return {
        "field": field,
        "value": value,
        "unit": unit,
        "key": key,
        "evidence": [item(value)] if evidence is None else evidence,
    }


def envelope(*candidates, missing=()):
    return {"candidates": list(candidates), "not_found": list(missing)}


SCHEMA = {"fields": {"amount": {"type": "integer"}}}


def execute(text, client, schema=SCHEMA, **kwargs):
    return extract(text, schema, client=client, model_id="fixed-1", **kwargs)


def assert_replays(result, text, schema=SCHEMA, **kwargs):
    assert replay(result.record, result.artifacts, text, schema, **kwargs).ok
    assert gg.verify(result.receipt.to_dict(), text, schema, result.candidates, **kwargs).ok


def test_one_pass_and_byte_identical_replay():
    result = execute("Amount 5.", Client(envelope(candidate())))
    assert result.complete
    assert result.receipt.decisions[0].outcome == "admitted"
    assert_replays(result, "Amount 5.")
    again = execute("Amount 5.", Client(envelope(candidate())))
    assert gg.jcs(result.record) == gg.jcs(again.record)


@pytest.mark.parametrize(
    "bad",
    [
        '{"candidates":[],"candidates":[],"not_found":["amount"]}',
        '{"candidates":[],"not_found":["amount"]} trailing',
        '{"candidates":[],"not_found":["amount"],"x":NaN}',
        '{"candidates":[],"not_found":[],"x":9007199254740992}',
        envelope(missing=()),
        envelope(candidate(), missing=("amount",)),
        envelope(candidate(field="other")),
        envelope({**candidate(), "id": "untrusted"}),
        envelope(candidate(evidence=[{"source": "knowledge", "text": "5"}])),
        envelope(candidate(evidence=[{**item("5"), "start": 0, "end": 1}])),
    ],
)
def test_invalid_reply_is_incomplete_without_partial_admission(bad):
    client = Client(bad)
    result = execute("Amount 5.", client)
    assert not result.complete and not result.candidates and len(client.prompts) == 1
    assert result.record[2]["status"] == "invalid_reply"
    assert_replays(result, "Amount 5.")


def test_chunk_stop_utf8_and_degenerate_overlap_bound():
    settings = RunPolicy(chunk_chars=6, overlap_chars=2)
    assert _chunks("éé\néééé", settings) == [(0, 6), (4, 7)]
    assert _chunks("éé", settings) == [(0, 2)]
    client = Client(envelope(candidate()), envelope(candidate()))
    result = execute("éé\néé5é", client, run_policy=settings)
    plan = result.record[1]["chunks"]
    assert plan[0]["end"] == len("éé\néé5".encode())
    assert_replays(result, "éé\néé5é")
    with pytest.raises(ExtractInputError, match="chunks"):
        execute("x" * 50000, Client(), run_policy=RunPolicy(overlap_chars=11999))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_calls": True},
        {"max_calls": 0},
        {"targeted": 1},
        {"overlap_chars": 12000},
        {"max_repair_rounds": -1},
    ],
)
def test_invalid_policy_fails_before_call(kwargs):
    with pytest.raises(ExtractInputError):
        RunPolicy(**kwargs)


def test_inputs_are_validated_before_model_call():
    client = Client()
    with pytest.raises(gg.PacketError):
        execute("e\u0301", client)
    with pytest.raises(gg.PacketError):
        execute("5", client, references=[{"id": 3, "text": "5"}])
    for empty in ("", b"", {}):
        with pytest.raises(gg.PacketError):
            execute("5", client, references=empty)
    with pytest.raises(ExtractInputError):
        execute("5", client, run_policy=RunPolicy(max_prompt_chars=1))
    with pytest.raises(ExtractInputError, match="UTF-8"):
        execute("x\udcff", client)
    with pytest.raises(ExtractInputError, match="UTF-8"):
        execute("5", client, references=[{"id": "r", "text": "x\udcff"}])
    assert client.prompts == []


def test_missing_scale_evidence_repair_value_locked():
    text = "Amount 5."
    first = candidate("5000", evidence=[item("5")])
    new = candidate("5000", evidence=[item("5"), item("in thousands", "scale")])
    client = Client(envelope(first), new, {"not_found": True})
    result = execute(text, client)
    assert len(client.prompts) == 3
    assert result.candidates[0]["value"] == "5000"
    assert result.receipt.decisions[0].outcome == "needs_verification"
    assert any(e.get("status") == "evidence_repair" for e in result.record)
    assert_replays(result, text)


def test_quote_repair_admits_same_value():
    first = candidate(evidence=[item("5x")])
    client = Client(envelope(first), candidate())
    result = execute("Amount 5.", client)
    assert len(client.prompts) == 2
    assert result.receipt.decisions[0].outcome == "admitted"
    assert_replays(result, "Amount 5.")


@pytest.mark.parametrize(
    "change",
    [
        {"unit": "USD"},
        {"key": "new"},
        {"evidence": [item("5"), item("Amount", "field")]},
    ],
)
def test_forbidden_repair_changes_keep_old_tip(change):
    first = candidate(evidence=[item("absent")])
    reply = {**candidate(), **change}
    result = execute("Amount 5.", Client(envelope(first), reply))
    assert result.candidates[0]["evidence"][0]["text"] == "absent"
    assert any(e.get("status") == "protocol_failure" for e in result.record)
    assert_replays(result, "Amount 5.")


def test_changed_value_is_one_shot_and_keeps_original():
    first = candidate("5", evidence=[item("missing")])
    new = candidate("6", evidence=[item("also missing")])
    client = Client(envelope(first), new)
    result = execute("Amount 5. Other 6.", client)
    assert len(client.prompts) == 2 and len(result.candidates) == 2
    assert {c["value"] for c in result.candidates} == {"5", "6"}
    assert_replays(result, "Amount 5. Other 6.")


def test_changed_value_can_admit_once_after_original_rejected():
    client = Client(envelope(candidate(evidence=[item("missing")])), candidate("6"))
    result = execute("Other 6.", client)
    assert [d.outcome for d in result.receipt.decisions].count("admitted") == 1
    assert len(client.prompts) == 2
    assert_replays(result, "Other 6.")


def test_scale_word_with_role_repair_can_change_value_terminally():
    text = "Amount 5 million. Other 6 million."
    schema = {"fields": {"amount": {"type": "integer"}}}
    first = candidate("5", evidence=[item("5 million"), item("missing", "sign")])
    new = candidate("5000000", evidence=[item("5 million")])
    client = Client(envelope(first), new)
    result = execute(text, client, schema)
    assert len(client.prompts) == 2
    assert len(result.candidates) == 2
    assert all(d.outcome == "needs_verification" for d in result.receipt.decisions)
    assert all("CONFLICTING_CANDIDATES" in d.codes for d in result.receipt.decisions)
    assert_replays(result, text, schema)


def test_terminal_code_does_not_get_retry_or_target():
    client = Client(envelope(candidate("6", evidence=[item("5")])))
    result = execute("Amount 5.", client)
    assert len(client.prompts) == 1
    assert result.receipt.decisions[0].codes == ("VALUE_NOT_IN_EVIDENCE",)


def test_no_op_and_not_found_preserve_previous_candidate():
    first = candidate(evidence=[item("missing")])
    for reply, status in [(first, "no_op"), ({"not_found": True}, "repair_not_found")]:
        client = Client(envelope(first), reply)
        result = execute("Amount 5.", client)
        assert len(client.prompts) == 2
        assert result.candidates[0]["evidence"] == first["evidence"]
        assert any(e.get("status") == status for e in result.record)


def test_targeted_missing_field_only_and_field_terms():
    schema = {
        "fields": {
            "amount": {"type": "integer", "description": "Total count"},
            "known": {"type": "integer"},
        }
    }
    client = Client(envelope(candidate("2", "known"), missing=("amount",)), envelope(candidate()))
    result = execute("Known 2. Amount 5.", client, schema)
    assert len(client.prompts) == 2
    targeted = json.loads(client.prompts[1].split("\n", 1)[1])
    assert targeted["fields"] == ["amount"]
    assert {d.field for d in result.receipt.decisions} == {"amount", "known"}
    assert_replays(result, "Known 2. Amount 5.", schema)
    assert _queries(
        "total_amount", {"aliases": ["Total Amount", "Amount"], "description": "Net amount"}
    )[0] == ["total amount", "Amount", "total", "Net"]


def test_targeted_reference_pins_first_occurrence_accepting_review_cost():
    reference = {"id": "r", "text": "Other 5,000.\nRevenue 5,000."}
    schema = {"fields": {"amount": {"type": "integer", "aliases": ["Revenue", "Other"]}}}
    raw = candidate("5000", evidence=[item("5,000", ref="r"), item("Revenue", "field", "r")])
    # In the initial pass the quote resolves at the later field's occurrence.
    initial = execute("Nothing here.", Client(envelope(raw)), schema, references=[reference])
    assert initial.receipt.decisions[0].outcome == "admitted"
    # The approved targeted adapter pins the first occurrence and accepts the field review.
    targeted = execute(
        "Nothing here.",
        Client(envelope(missing=("amount",)), envelope(raw), {"not_found": True}),
        schema,
        references=[reference],
    )
    value_item = targeted.candidates[0]["evidence"][0]
    assert value_item == {"source": "reference", "ref": "r", "role": "value", "start": 6, "end": 11}
    assert targeted.receipt.decisions[0].outcome == "needs_verification"
    assert_replays(targeted, "Nothing here.", schema, references=[reference])


def test_target_no_terms_no_match_and_explicit_not_found():
    cases = [
        ("___", "Anything 5.", "search_no_terms"),
        ("amount", "Anything 5.", "search_no_match"),
        ("amount", "Amount absent.", "targeted_not_found"),
    ]
    for field, text, expected in cases:
        schema = {"fields": {field: {}}}
        client = Client(envelope(missing=(field,)), envelope(missing=(field,)))
        result = execute(text, client, schema)
        assert expected in result.record[-1]["fields"][field]
        assert len(client.prompts) == (2 if expected == "targeted_not_found" else 1)
        assert_replays(result, text, schema)


def test_target_source_escape_is_not_absence():
    client = Client(envelope(missing=("amount",)), envelope(candidate(evidence=[item("absent")])))
    result = execute("Amount 5.", client)
    assert result.complete and not result.candidates
    assert result.record[-1]["fields"]["amount"] == ["model_not_found", "protocol_failure"]
    assert_replays(result, "Amount 5.")


def test_bad_targeted_quote_fails_only_its_field():
    schema = {"fields": {"a": {"type": "integer"}, "b": {"type": "integer"}}}
    client = Client(
        envelope(missing=("a", "b")),
        envelope(candidate("5", "a", evidence=[item("9")])),
        envelope(candidate("7", "b")),
    )
    result = execute("A 5. B 7.", client, schema)
    fields = result.record[-1]["fields"]
    assert fields["a"] == ["model_not_found", "protocol_failure"]
    assert fields["b"][:2] == ["model_not_found", "proposed"]
    assert [c["field"] for c in result.candidates] == ["b"] and len(client.prompts) == 3
    assert result.receipt.decisions[0].outcome == "admitted" and result.complete
    failure = next(e for e in result.record if e["kind"] == "protocol_failure")
    assert failure["field"] == "a" and failure["phase"] == "targeted"
    assert_replays(result, "A 5. B 7.", schema)


def test_targeted_trim_drops_the_worst_ranked_region_first():
    schema = {"fields": {"net_income": {"type": "integer", "description": "the yearly profit"}}}
    text = "".join(f"profit line {i} y\n" for i in range(6)) + "Net income 42."
    for limit in (2750, 3050, 3350):
        client = Client(envelope(missing=("net_income",)), envelope(missing=("net_income",)))
        settings = RunPolicy(search_context_chars=1, max_prompt_chars=limit)
        result = execute(text, client, schema, run_policy=settings)
        sent = json.loads(client.prompts[1].split("\n", 1)[1])["sources"]
        # The title match has rank 0. It stays, and it stays last in location order.
        assert sent[-1]["text"] == "\nNet income "
        assert [s["start"] for s in sent] == sorted(s["start"] for s in sent)
        search = next(e for e in result.record if e["kind"] == "search")
        assert search["status"] == "search_truncated" and search["trimmed_regions"] > 0
        assert search["regions"] == [
            {k: s[k] for k in ("source", "start", "end", "text")} for s in sent
        ]
        assert result.complete and "targeted_not_found" in result.record[-1]["fields"]["net_income"]
        assert_replays(result, text, schema)


def test_repair_without_value_item_may_cite_a_reference_of_its_call():
    references = [{"id": "r", "text": "Amount 5."}]
    new = candidate(evidence=[item("5", ref="r")])
    result = execute(
        "Nothing.", Client(envelope(candidate(evidence=[])), new), references=references
    )
    assert result.receipt.decisions[0].outcome == "admitted"
    assert result.candidates[0]["evidence"] == [item("5", ref="r")]
    assert_replays(result, "Nothing.", references=references)
    # A reference outside the call's context is still a protocol failure.
    # An empty document gives a call with no document region. A document quote is outside it.
    outside = candidate(evidence=[item("5")])
    client = Client(envelope(candidate(evidence=[])), outside)
    escape = execute("", client, references=references)
    assert escape.receipt.decisions[0].outcome == "rejected"
    assert any(e.get("status") == "protocol_failure" for e in escape.record)
    assert_replays(escape, "", references=references)


def test_repair_keeps_a_reference_unit_and_adds_a_document_value():
    schema = {"fields": {"amount": {"type": "integer", "unit": "USD"}}}
    references = [{"id": "r", "text": "Currency $"}]
    first = candidate(unit="USD", evidence=[item("$", "unit", "r")])
    new = candidate(unit="USD", evidence=[item("$", "unit", "r"), item("5")])
    result = execute(
        "Amount 5.",
        Client(envelope(first), new, {"not_found": True}),
        schema,
        references=references,
    )
    assert any(e.get("status") == "evidence_repair" for e in result.record)
    assert result.candidates[0]["evidence"][1] == item("5")
    assert_replays(result, "Amount 5.", schema, references=references)


def test_call_budget_never_records_skipped_target_as_not_found():
    client = Client(envelope(missing=("amount",)))
    result = execute("Amount 5.", client, run_policy=RunPolicy(max_calls=1))
    assert not result.complete and len(client.prompts) == 1
    assert result.record[-1]["fields"]["amount"] == ["model_not_found", "unsearched"]
    assert_replays(result, "Amount 5.")


def test_reply_size_and_candidate_count_limits():
    for settings, reply, status in [
        (RunPolicy(max_reply_bytes=1), envelope(candidate()), "reply_limit"),
        (
            RunPolicy(max_candidates_per_reply=1),
            envelope(candidate(), candidate()),
            "invalid_reply",
        ),
    ]:
        result = execute("Amount 5.", Client(reply), run_policy=settings)
        assert not result.complete and not result.candidates
        assert any(e.get("status") == status for e in result.record)
        assert_replays(result, "Amount 5.")


def test_client_error_keeps_record_without_exception_secret():
    result = execute("Amount 5.", Client(RuntimeError("secret")))
    assert not result.complete
    assert "secret" not in gg.jcs(result.record)
    assert_replays(result, "Amount 5.")


def test_empty_source_records_absence_without_a_call():
    client = Client()
    result = execute("", client)
    assert result.complete and not client.prompts
    assert result.record[-1]["fields"]["amount"] == ["empty_source"]
    assert_replays(result, "")


def test_replay_detects_modified_artifacts_settings_and_record():
    result = execute("Amount 5.", Client(envelope(candidate())))
    for mutate in [
        lambda r: r[0]["settings"].update(max_calls=2),
        lambda r: r.pop(-2),
        lambda r: r[-1].update(complete=False),
    ]:
        record = copy.deepcopy(result.record)
        mutate(record)
        assert not replay(record, result.artifacts, "Amount 5.", SCHEMA).ok
    assert not replay(result.record, {}, "Amount 5.", SCHEMA).ok
    assert not replay(result.record, result.artifacts, "Amount 6.", SCHEMA).ok


def test_runtime_error_has_partial_record(monkeypatch):
    import groundgate.extract.runner as module

    def fail(self, *args):
        raise RuntimeError("failure")

    monkeypatch.setattr(module._Engine, "decide", fail)
    with pytest.raises(ExtractError) as error:
        execute("Amount 5.", Client(envelope(candidate())))
    assert error.value.record[1]["kind"] == "plan"


@pytest.mark.parametrize(
    "text,schema,first,new,code",
    [
        (
            "Loss 5.",
            SCHEMA,
            candidate("-5", evidence=[item("5"), item("wrong", "sign")]),
            candidate("-5", evidence=[item("5"), item("Loss", "sign")]),
            "SIGN_CITATION_INVALID",
        ),
        (
            "Amounts (in thousands)\nAmount 5.",
            SCHEMA,
            candidate("5000", evidence=[item("5"), item("in thousands missing", "scale")]),
            candidate("5000", evidence=[item("5"), item("in thousands", "scale")]),
            "SCALE_CITATION_INVALID",
        ),
        (
            "Amount $ 5.",
            {"fields": {"amount": {"unit": "USD", "aliases": ["Amount"]}}},
            candidate(unit="USD", evidence=[item("5"), item("missing", "unit")]),
            candidate(unit="USD", evidence=[item("5"), item("$", "unit")]),
            "UNIT_CITATION_INVALID",
        ),
        (
            "Amount 5.",
            {"fields": {"amount": {"aliases": ["Amount"]}}},
            candidate(evidence=[item("5"), item("wrong", "field")]),
            candidate(evidence=[item("5"), item("Amount", "field")]),
            "FIELD_CITATION_INVALID",
        ),
        (
            "2026 Amount 5.",
            {"fields": {"amount": {"keys": ["2026"]}}},
            candidate(key="2026", evidence=[item("5"), item("wrong", "key")]),
            candidate(key="2026", evidence=[item("5"), item("2026", "key")]),
            "KEY_CITATION_INVALID",
        ),
        ("Amount 5.", SCHEMA, candidate(evidence=[]), candidate(), "NO_EVIDENCE"),
        (
            "Loss 5.",
            SCHEMA,
            candidate("-5", evidence=[item("5")]),
            candidate("-5", evidence=[item("5"), item("Loss", "sign")]),
            "PART_MISSING",
        ),
        (
            "$\nAmount\t5",
            {"fields": {"amount": {"unit": "USD", "aliases": ["Amount"]}}},
            candidate(unit="USD"),
            candidate(unit="USD", evidence=[item("5"), item("$", "unit"), item("Amount", "field")]),
            "PART_MISSING",
        ),
        (
            "2025\t2026\nAmount\t3\t5\nCount\t7\t8\nLast\t9\t10",
            {"fields": {"amount": {"keys": ["2025", "2026"], "aliases": ["Amount"]}}},
            candidate(key="2026"),
            candidate(
                key="2026", evidence=[item("5"), item("2026", "key"), item("Amount", "field")]
            ),
            "KEY_NOT_AT_VALUE",
        ),
    ],
)
def test_each_repairable_evidence_role(text, schema, first, new, code):
    initial = gg.admit(text, schema, [{"id": "first", **first}])
    assert code in initial.decisions[0].codes
    client = Client(envelope(first), new)
    result = execute(text, client, schema)
    assert len(client.prompts) == 2
    assert result.receipt.decisions[0].outcome == "admitted"
    assert_replays(result, text, schema)


def test_repair_round_limit_and_duplicate_budget():
    first = candidate(evidence=[item("missing-a")])
    client = Client(
        envelope(first, first),
        candidate(evidence=[item("missing-b")]),
        candidate(evidence=[item("missing-c")]),
    )
    result = execute("Amount 5.", client)
    assert len(client.prompts) == 3
    assert "repair_limit" in result.record[-1]["fields"]["amount"]
    assert_replays(result, "Amount 5.")


def test_no_op_duplicate_stops_group_not_just_one_candidate():
    first = candidate(evidence=[item("missing")])
    client = Client(envelope(first, first), first)
    result = execute("Amount 5.", client)
    assert len(client.prompts) == 2
    assert_replays(result, "Amount 5.")


def test_conflicts_from_different_chunks_are_in_final_receipt():
    text = "Amount 5.\nAmount 6."
    client = Client(envelope(candidate()), envelope(candidate("6")))
    result = execute(text, client, run_policy=RunPolicy(chunk_chars=10, overlap_chars=0))
    assert len(client.prompts) == 2
    assert all("CONFLICTING_CANDIDATES" in d.codes for d in result.receipt.decisions)
    assert_replays(result, text)


def test_target_match_casefold_expansion_and_truncation():
    schema = {"fields": {"strasse": {}}}
    text = "Straße 5.\n" + "x" * 20 + "\nStraße 6."
    client = Client(envelope(missing=("strasse",)), envelope(missing=("strasse",)))
    result = execute(
        text, client, schema, run_policy=RunPolicy(search_context_chars=1, max_target_regions=1)
    )
    search = next(e for e in result.record if e["kind"] == "search")
    assert search["status"] == "search_truncated" and search["omitted_regions"] == 1
    assert search["matches"][0]["end"] == len("Straße".encode())
    assert_replays(result, text, schema)


def test_client_cannot_mutate_pinned_inputs():
    schema = copy.deepcopy(SCHEMA)
    policy = {"reanchor": False}
    references = [{"id": "r", "text": "Amount 5."}]

    def client(prompt):
        schema["fields"]["amount"]["type"] = "string"
        policy["reanchor"] = True
        references[0]["text"] = "Amount 6."
        return json.dumps(envelope(candidate()))

    result = execute("Amount 5.", client, schema, policy=policy, references=references)
    assert_replays(
        result,
        "Amount 5.",
        SCHEMA,
        policy={"reanchor": False},
        references=[{"id": "r", "text": "Amount 5."}],
    )


@pytest.mark.parametrize("reply", [False, "\ud800", '{"candidates":[],"not_found":["\\ud800"]}'])
def test_nonstring_and_surrogate_replies_are_recorded_incomplete(reply):
    result = execute("Amount 5.", lambda prompt: reply)
    assert not result.complete and not result.candidates
    assert_replays(result, "Amount 5.")


def test_repair_cannot_change_a_role_reference_even_to_value_source():
    text = "Amount $ 5."
    schema = {"fields": {"amount": {"unit": "USD"}}}
    references = [{"id": "r", "text": "$"}]
    first = candidate(unit="USD", evidence=[item("5"), item("$", "unit", "r")])
    new = candidate(unit="USD", evidence=[item("5"), item("$", "unit")])
    result = execute(text, Client(envelope(first), new), schema, references=references)
    assert result.candidates[0]["evidence"][1]["source"] == "reference"
    assert any(e.get("status") == "protocol_failure" for e in result.record)
    assert_replays(result, text, schema, references=references)


def test_targeted_document_repair_cannot_move_to_another_retained_region():
    text = "Amount 5. " + "x" * 50 + " Amount 5000."
    # Missing scale is repairable, but changing the quote to a different selected region is not.
    first = candidate("5000", evidence=[item("5")])
    new = candidate("5000", evidence=[item("5000")])
    result = execute(
        text,
        Client(envelope(missing=("amount",)), envelope(first), new),
        run_policy=RunPolicy(search_context_chars=10),
    )
    assert result.candidates[0]["search_region"]["start"] == 0
    assert result.receipt.decisions[0].outcome == "needs_verification"
    assert any(e.get("status") == "protocol_failure" for e in result.record)
    assert_replays(result, text)


FIELDS_SCHEMA = {"fields": {"amount": {"aliases": ["Amount", "Total"]}}}
FIELDS_TEXT = "Total\nAmount\t5"


def test_repair_reply_with_two_field_items_is_kept():
    # A row label and a column header both cite the field (spec 0.10, #300).
    first = candidate(evidence=[item("5"), item("wrong", "field")])
    new = candidate(evidence=[item("5"), item("Amount", "field"), item("Total", "field")])
    client = Client(envelope(first), new)
    result = execute(FIELDS_TEXT, client, FIELDS_SCHEMA)
    assert len(client.prompts) == 2
    assert any(e.get("status") == "evidence_repair" for e in result.record)
    assert result.candidates[0]["evidence"] == new["evidence"]
    assert result.receipt.decisions[0].outcome == "admitted"
    assert_replays(result, FIELDS_TEXT, FIELDS_SCHEMA)


@pytest.mark.parametrize(
    "fields",
    [
        [item("Amount", "field")],
        [item("Amount", "field"), item("Total", "field"), item("Amount", "field")],
    ],
)
def test_repair_can_remove_or_add_field_items(fields):
    first = candidate(evidence=[item("5"), item("wrong", "field"), item("other", "field")])
    new = candidate(evidence=[item("5"), *fields])
    client = Client(envelope(first), new)
    result = execute(FIELDS_TEXT, client, FIELDS_SCHEMA)
    assert result.candidates[0]["evidence"] == new["evidence"]
    assert result.receipt.decisions[0].outcome == "admitted"
    assert_replays(result, FIELDS_TEXT, FIELDS_SCHEMA)


def test_evidence_repair_keeps_two_field_items():
    text = "Amounts (in thousands)\nTotal\nAmount\t5"
    fields = [item("Amount", "field"), item("Total", "field")]
    first = candidate("5000", evidence=[item("5"), *fields])
    new = candidate("5000", evidence=[item("5"), *fields, item("in thousands", "scale")])
    client = Client(envelope(first), new)
    result = execute(text, client, FIELDS_SCHEMA)
    assert any(e.get("status") == "evidence_repair" for e in result.record)
    assert result.candidates[0]["evidence"] == new["evidence"]
    assert_replays(result, text, FIELDS_SCHEMA)


def test_repair_reply_with_nine_field_items_is_a_protocol_failure():
    # A candidate can cite up to 8 field items (SPEC section 3 step 1).
    first = candidate(evidence=[item("5"), item("wrong", "field")])
    new = candidate(evidence=[item("5"), *[item("Amount", "field")] * 9])
    result = execute(FIELDS_TEXT, Client(envelope(first), new), FIELDS_SCHEMA)
    assert result.candidates[0]["evidence"] == first["evidence"]
    assert any(e.get("status") == "protocol_failure" for e in result.record)
    assert_replays(result, FIELDS_TEXT, FIELDS_SCHEMA)


@pytest.mark.parametrize(
    "evidence",
    [
        # Every role other than field keeps one item.
        [
            item("5"),
            item("Amount", "field"),
            item("Total", "field"),
            item("in thousands", "scale"),
            item("thousands", "scale"),
        ],
        # A repair that may not change field cannot drop one of two field items.
        [item("5"), item("Amount", "field"), item("in thousands", "scale")],
        # Or change their order, which the column rule reads.
        [item("5"), item("Total", "field"), item("Amount", "field"), item("in thousands", "scale")],
    ],
)
def test_repair_field_items_stay_inside_the_allowed_roles(evidence):
    text = "Amounts (in thousands)\nTotal\nAmount\t5"
    fields = [item("Amount", "field"), item("Total", "field")]
    first = candidate("5000", evidence=[item("5"), *fields])
    client = Client(envelope(first), candidate("5000", evidence=evidence))
    result = execute(text, client, FIELDS_SCHEMA)
    assert result.candidates[0]["evidence"] == first["evidence"]
    assert any(e.get("status") == "protocol_failure" for e in result.record)
    assert_replays(result, text, FIELDS_SCHEMA)


@pytest.mark.parametrize("not_found", [1, 1.0, "true", False, None])
def test_repair_not_found_requires_the_boolean_true(not_found):
    first = candidate(evidence=[item("missing")])
    result = execute("Amount 5.", Client(envelope(first), {"not_found": not_found}))
    assert not result.complete
    assert not any(e.get("status") == "repair_not_found" for e in result.record)
    assert_replays(result, "Amount 5.")


def test_replay_refuses_amplified_chunk_plan_before_prompt_allocation(monkeypatch):
    import groundgate.extract.runner as module

    result = execute("Amount 5.", Client(envelope(candidate())))
    record = copy.deepcopy(result.record)
    record[0]["settings"].update(chunk_chars=1, overlap_chars=0, max_calls=9007199254740991)
    planned_limits = []
    original = module._chunks

    def bounded_chunks(text, settings):
        planned_limits.append(settings.max_calls)
        assert settings.max_calls <= 2
        return original(text, settings)

    def unexpected_prompt(*args, **kwargs):
        pytest.fail("untrusted replay allocated prompts before refusing its plan")

    monkeypatch.setattr(module, "_chunks", bounded_chunks)
    monkeypatch.setattr(module._Engine, "prompt", unexpected_prompt)
    assert not replay(record, result.artifacts, "x" * 50000, SCHEMA).ok
    assert planned_limits == [1]


def test_replay_keeps_valid_interrupted_multichunk_initial_pass():
    text = "Amount 5.\nAmount 6.\nAmount 7."
    client = Client(RuntimeError("transport stopped"))
    result = execute(text, client, run_policy=RunPolicy(chunk_chars=10, overlap_chars=0))
    assert len(client.prompts) == 1 and not result.complete
    assert len(result.record[1]["chunks"]) == 3
    assert_replays(result, text)


def test_targeted_title_beats_earlier_common_description_words():
    schema = {
        "fields": {
            "revenue": {"type": "integer", "description": "Total revenue for the fiscal year"}
        }
    }
    text = ("the " + "x" * 20 + "\n") * 1100 + "Revenue 5."
    client = Client(envelope(missing=("revenue",)), envelope(candidate(field="revenue")))
    result = execute(
        text,
        client,
        schema,
        run_policy=RunPolicy(
            chunk_chars=50000, overlap_chars=0, search_context_chars=12, max_target_regions=1
        ),
    )
    search = next(e for e in result.record if e["kind"] == "search")
    assert search["regions"][0]["text"].endswith("Revenue 5.")
    assert len(search["matches"]) == search["match_limit"] == 1024
    assert search["omitted_matches"] == 77
    assert search["status"] == "search_truncated"
    assert result.receipt.decisions[0].outcome == "admitted"
    assert_replays(result, text, schema)


def test_repair_prompt_explains_unexpected_changed_value_terminal_path():
    first = candidate(evidence=[item("missing")])
    client = Client(envelope(first), candidate("6"))
    result = execute("Amount 6.", client)
    assert "even unexpectedly" in client.prompts[1]
    assert "neither receives another repair" in client.prompts[1]
    assert len(client.prompts) == 2
    assert any(e.get("status") == "changed_value" for e in result.record)


def test_replay_rejects_forged_dummy_plan_before_building_chunks(monkeypatch):
    import groundgate.extract.runner as module

    result = execute("Amount 5.", Client(envelope(candidate())))
    record = copy.deepcopy(result.record)
    record[0]["settings"].update(chunk_chars=1, overlap_chars=0, max_calls=9007199254740991)
    record[1]["chunks"] = [None] * 1000

    def unexpected_chunks(*args, **kwargs):
        pytest.fail("dummy saved plan authorized chunk generation")

    monkeypatch.setattr(module, "_chunks", unexpected_chunks)
    assert not replay(record, result.artifacts, "x" * 50000, SCHEMA).ok


def test_initial_prompt_validation_retains_one_prompt_before_first_client_call(monkeypatch):
    import groundgate.extract.runner as module

    original = module._Engine.prompt
    state = {"alive": 0, "peak": 0, "prompts": 0, "checked": False}

    class Watched(str):
        def __new__(cls, value):
            result = super().__new__(cls, value)
            state["alive"] += 1
            state["peak"] = max(state["peak"], state["alive"])
            return result

        def __del__(self):
            state["alive"] -= 1

    def prompt(self, *args, **kwargs):
        state["prompts"] += 1
        return Watched(original(self, *args, **kwargs))

    def client(prompt):
        assert state["prompts"] == 4  # Three validated, then the first recreated call.
        assert state["alive"] == state["peak"] == 1
        state["checked"] = True
        raise RuntimeError("stop after the first call")

    monkeypatch.setattr(module._Engine, "prompt", prompt)
    result = execute(
        "Amount 5.\nAmount 6.\nAmount 7.",
        client,
        run_policy=RunPolicy(chunk_chars=10, overlap_chars=0),
    )
    assert state["checked"] and not result.complete


def test_aggregate_candidate_limit_never_partially_applies_reply():
    result = execute(
        "Amount 5.",
        Client(envelope(candidate(), candidate())),
        run_policy=RunPolicy(max_total_candidates=1),
    )
    assert not result.complete and not result.candidates
    assert any(e.get("status") == "aggregate_candidate_limit" for e in result.record)
    assert_replays(result, "Amount 5.")


def test_changed_value_cannot_exceed_aggregate_candidate_limit():
    first = candidate(evidence=[item("missing")])
    result = execute(
        "Amount 6.",
        Client(envelope(first), candidate("6")),
        run_policy=RunPolicy(max_total_candidates=1),
    )
    assert not result.complete and len(result.candidates) == 1
    assert result.candidates[0]["value"] == "5"
    assert_replays(result, "Amount 6.")


def test_admission_history_limit_retains_last_recorded_packet():
    text = "Amount 5.\nAmount 6."
    settings = RunPolicy(chunk_chars=10, overlap_chars=0)
    baseline = execute(
        text, Client(envelope(candidate()), envelope(candidate("6"))), run_policy=settings
    )
    pairs = [e for e in baseline.record if e["kind"] == "admission"]
    sizes = [len(baseline.artifacts[e["admission_sha256"]].encode()) for e in pairs]
    budget = sizes[0] + sizes[1] // 2
    result = execute(
        text,
        Client(envelope(candidate()), envelope(candidate("6"))),
        run_policy=RunPolicy(chunk_chars=10, overlap_chars=0, max_admission_bytes=budget),
    )
    assert not result.complete and len(result.candidates) == 1
    assert result.receipt.decisions[0].value == "5"
    assert result.receipt.decisions[0].outcome == "admitted"
    assert any(e.get("status") == "admission_history_limit" for e in result.record)
    stored = [e for e in result.record if e["kind"] == "admission"]
    assert sum(len(result.artifacts[e["admission_sha256"]].encode()) for e in stored) <= budget
    assert_replays(result, text)


def test_admission_history_limit_names_fields_without_candidates():
    result = execute(
        "Amount 5.",
        Client({"candidates": [], "not_found": ["amount"]}),
        run_policy=RunPolicy(max_admission_bytes=100),
    )
    assert not result.complete
    states = result.record[-1]["fields"]["amount"]
    assert states == ["model_not_found", "admission_history_limit"]
    assert_replays(result, "Amount 5.")


def test_candidate_payload_byte_limit_applies_before_admission():
    first = candidate(evidence=[item("x" * 3000)])
    result = execute(
        "Amount 5.", Client(envelope(first)), run_policy=RunPolicy(max_admission_bytes=4096)
    )
    assert not result.complete and not result.candidates
    assert not any(e["kind"] == "admission" for e in result.record)
    assert_replays(result, "Amount 5.")


@pytest.mark.parametrize("artifacts", [{"bad": None}, {1: "bad"}, None, []])
def test_replay_malformed_artifacts_are_a_failed_verification(artifacts):
    result = execute("Amount 5.", Client(envelope(candidate())))
    assert not replay(result.record, artifacts, "Amount 5.", SCHEMA).ok


@pytest.mark.parametrize("replacement", [candidate(), candidate("6")])
def test_admission_history_rollback_after_repair_keeps_packet_and_outcome(replacement):
    text = "Amount 5. Other 6."
    first = candidate(evidence=[item("missing")])
    baseline = execute(text, Client(envelope(first), replacement))
    pairs = [e for e in baseline.record if e["kind"] == "admission"]
    sizes = [len(baseline.artifacts[e["admission_sha256"]].encode()) for e in pairs]
    budget = sizes[0] + sizes[1] // 2
    result = execute(
        text, Client(envelope(first), replacement), run_policy=RunPolicy(max_admission_bytes=budget)
    )
    assert not result.complete
    assert len(result.candidates) == 1
    assert result.candidates[0]["value"] == "5"
    assert result.candidates[0]["evidence"] == [item("missing")]
    assert result.receipt.decisions[0].outcome == "rejected"
    assert result.receipt.decisions[0].codes == ("QUOTE_NOT_FOUND",)
    states = result.record[-1]["fields"]["amount"]
    assert "admission_history_limit" in states
    assert "repair_limit" not in states
    stop = next(e for e in result.record if e.get("status") == "admission_history_limit")
    assert stop["retained_candidate_ids"] == [result.candidates[0]["id"]]
    assert_replays(result, text)


def test_fold_cache_builds_once_per_source_across_fields_and_queries(monkeypatch):
    import groundgate.extract.runner as module

    built = []
    original = module._Folded.build

    def build(cls, text):
        built.append(text)
        return original(text)

    monkeypatch.setattr(module._Folded, "build", classmethod(build))
    text = "First item. Second item."
    reference = {"id": "r", "text": "First reference. Second reference."}
    schema = {
        "fields": {
            "first": {"description": "A different item"},
            "second": {"description": "Another different item"},
        }
    }
    result = execute(
        text,
        Client(
            envelope(missing=("first", "second")),
            envelope(missing=("first",)),
            envelope(missing=("second",)),
        ),
        schema,
        references=[reference],
    )
    assert built == [text, reference["text"]]
    assert_replays(result, text, schema, references=[reference])


@pytest.mark.parametrize("source", ["ASCII only", "Σς Œ Å", "Straße İ ﬃ", "İßﬃ𝔘中é"])
def test_compact_fold_and_byte_maps_preserve_original_boundaries(source):
    from groundgate.extract.runner import _ByteOffsets, _Folded

    folded = _Folded.build(source)
    offsets = _ByteOffsets(source)
    position = 0
    for index, char in enumerate(source):
        assert folded.boundary(position) == index
        for intermediate in range(1, len(char.casefold())):
            assert folded.boundary(position + intermediate) is None
        position += len(char.casefold())
        assert folded.boundary(position) == index + 1
        assert offsets.to_bytes(index + 1) == len(source[: index + 1].encode())
    if len(source.casefold()) == len(source):
        assert folded.source_positions is None and folded.folded_ends is None
    else:
        assert len(folded.source_positions) == sum(len(c.casefold()) > 1 for c in source)
    assert len(offsets.positions) == sum(not c.isascii() for c in source)


def test_large_ascii_fold_and_offsets_need_no_character_map():
    from groundgate.extract.runner import _ByteOffsets, _Folded

    source = "A" * 100000
    folded = _Folded.build(source)
    offsets = _ByteOffsets(source)
    assert folded.source_positions is None and folded.folded_ends is None
    assert not offsets.positions and not offsets.extras
    assert offsets.to_bytes(len(source)) == len(source)


def test_rollback_names_dropped_ids_and_restores_accepted_raw(monkeypatch):
    import groundgate.extract.runner as module

    text = "Amount 5. Other 6."
    first = candidate(evidence=[item("missing")])
    replacement = candidate()
    baseline = execute(text, Client(envelope(first), replacement))
    pairs = [e for e in baseline.record if e["kind"] == "admission"]
    sizes = [len(baseline.artifacts[e["admission_sha256"]].encode()) for e in pairs]
    original = module._Engine.finish
    checked = []

    def finish(self):
        if self.admission_exhausted:
            checked.append(copy.deepcopy(self.raw))
        return original(self)

    monkeypatch.setattr(module._Engine, "finish", finish)
    result = execute(
        text,
        Client(envelope(first), replacement),
        run_policy=RunPolicy(max_admission_bytes=sizes[0] + sizes[1] // 2),
    )
    cid = result.candidates[0]["id"]
    assert checked == [{cid: first}]
    stop = next(e for e in result.record if e.get("status") == "admission_history_limit")
    assert stop["dropped_candidate_ids"] == []
    assert stop["reverted_candidate_ids"] == [cid]
    assert_replays(result, text)

    # An initial proposal that cannot be recorded has no retained candidate.
    initial = execute(text, Client(envelope(first)), run_policy=RunPolicy(max_admission_bytes=500))
    stop = next(e for e in initial.record if e.get("status") == "admission_history_limit")
    assert initial.candidates == [] and stop["retained_candidate_ids"] == []
    assert stop["dropped_candidate_ids"] == ["c1-1"]
    assert stop["reverted_candidate_ids"] == []
    assert_replays(initial, text)


def test_oversize_reply_is_retained_for_replay_but_never_parsed(monkeypatch):
    import groundgate.extract.runner as module

    def unexpected_parse(raw):
        pytest.fail("oversized reply was parsed")

    monkeypatch.setattr(module, "_strict_json", unexpected_parse)
    raw = "x" * 4096
    result = execute("Amount 5.", lambda prompt: raw, run_policy=RunPolicy(max_reply_bytes=32))
    call = next(e for e in result.record if e["kind"] == "call")
    assert call["status"] == "reply_limit" and call["reply_bytes"] == len(raw)
    assert result.artifacts[call["reply_sha256"]] == raw
    assert_replays(result, "Amount 5.")


@pytest.mark.parametrize("failure", [RuntimeError("stopped"), "invalid JSON"])
def test_aborted_initial_pass_reports_no_valid_disposition_for_every_field(failure):
    schema = {"fields": {"amount": {"type": "integer"}, "other": {"type": "integer"}}}
    text = "Amount 5.\nOther 6.\nAmount 7."
    client = Client(failure)
    result = execute(text, client, schema, run_policy=RunPolicy(chunk_chars=10, overlap_chars=0))
    assert not result.complete and len(client.prompts) == 1
    assert result.record[-1]["fields"] == {
        "amount": ["incomplete_no_disposition"],
        "other": ["incomplete_no_disposition"],
    }
    assert not any(e["kind"] == "not_found" for e in result.record)
    assert_replays(result, text, schema)


def test_targeted_query_count_is_hard_capped_before_source_scans(monkeypatch):
    import groundgate.extract.runner as module

    words = [f"term{i}" for i in range(5000)]
    schema = {
        "fields": {
            "annual_total": {
                "type": "integer",
                "aliases": ["Preferred", "Secondary"],
                "description": " ".join(words),
            }
        }
    }
    queries, omitted = _queries("annual_total", schema["fields"]["annual_total"])
    assert queries[:5] == ["annual total", "Preferred", "Secondary", "annual", "total"]
    assert len(queries) == 64 and omitted == 4941
    scans = []
    original = module._matches

    def matches(source, query):
        scans.append(query)
        yield from original(source, query)

    monkeypatch.setattr(module, "_matches", matches)
    result = execute(
        "Nothing here.",
        Client(envelope(missing=("annual_total",))),
        schema,
        run_policy=RunPolicy(max_prompt_chars=200000),
    )
    search = next(e for e in result.record if e["kind"] == "search")
    assert scans == queries
    assert search["queries"] == queries and search["omitted_queries"] == omitted
    assert search["query_limit"] == 64 and search["status"] == "search_truncated"
    assert_replays(result, "Nothing here.", schema)


def test_repair_prompt_limit_differs_from_call_budget():
    text = "Amount 5."
    first = envelope(candidate(evidence=[item("missing" * 1000)]))
    baseline = execute(text, Client(first, candidate()))
    first_call = next(e for e in baseline.record if e["kind"] == "call")
    initial = len(baseline.artifacts[first_call["prompt_sha256"]])
    # The complete repair prompt is larger than the initial prompt because it includes feedback.
    client = Client(first)
    result = execute(text, client, run_policy=RunPolicy(max_prompt_chars=initial))
    stop = next(e for e in result.record if e["kind"] == "limit")
    assert stop["phase"] == "repair" and stop["status"] == "prompt_limit"
    assert result.record[-1]["fields"]["amount"] == ["proposed", "prompt_limit"]
    assert len(client.prompts) == 1 and not result.complete
    assert_replays(result, text)

    budget = execute(text, Client(first), run_policy=RunPolicy(max_calls=1))
    stop = next(e for e in budget.record if e["kind"] == "limit")
    assert stop["status"] == "call_limit"
    assert budget.record[-1]["fields"]["amount"] == ["proposed", "call_limit"]
    assert_replays(budget, text)


def test_source_region_protocol_abort_reports_no_valid_disposition():
    references = [{"id": "r", "text": "Amount 5."}]
    result = execute("", Client(envelope(candidate())), references=references)
    assert not result.complete and result.candidates == []
    assert result.record[-1]["fields"]["amount"] == ["incomplete_no_disposition"]
    assert any(e.get("reason") == "source_region" for e in result.record)
    assert_replays(result, "", references=references)


def test_record_is_a_hash_chained_log_and_inputs_are_objects():
    refs = [{"id": "r1", "text": "Units are dollars."}]
    result = execute("Amount 5.", Client(envelope(candidate())), references=refs)
    lines = result.record
    assert [lines[0]["kind"], lines[-1]["kind"]] == ["header", "final"]
    assert [line["sequence"] for line in lines] == list(range(1, len(lines) + 1))
    assert lines[0]["previous"] is None
    assert all(b["previous"] == a["entry_sha256"] for a, b in itertools.pairwise(lines))
    assert result.run_sha256 == lines[-1]["entry_sha256"]
    # Keys use the stable runner prefix, not the core digest that names the spec version.
    inputs = lines[0]["inputs"]
    text_key = "sha256:" + hashlib.sha256(b"groundgate-run/2:text\0Amount 5.").hexdigest()
    assert inputs["document"] == {"kind": "text", "id": None, "source": None, "sha256": text_key}
    assert result.artifacts[text_key] == "Amount 5."
    assert result.receipt.document_sha256 != text_key
    assert (
        json.loads(result.artifacts[inputs["schema_sha256"]])
        == gg.Schema.from_dict(SCHEMA).to_dict()
    )
    assert [json.loads(result.artifacts[h]) for h in inputs["reference_sha256"]] == refs
    final = next(e for e in lines if e["kind"] == "final_admission")
    packet = json.loads(result.artifacts[final["admission_sha256"]])
    assert packet["candidates"] == result.candidates
    assert packet["receipt"]["receipt_sha256"] == result.receipt.receipt_sha256


def test_write_and_read_a_run_folder(tmp_path):
    result = execute("Amount 5.", Client(envelope(candidate())))
    result.write(tmp_path / "run")
    log = (tmp_path / "run" / "run.jsonl").read_text(encoding="utf-8")
    assert log == "".join(gg.jcs(line) + "\n" for line in result.record)
    names = {p.name for p in (tmp_path / "run" / "objects").iterdir()}
    assert names == {k.removeprefix("sha256:") for k in result.artifacts}
    again = RunResult.read(tmp_path / "run")
    assert gg.jcs(again.record) == gg.jcs(result.record)
    assert again.artifacts == result.artifacts and again.candidates == result.candidates
    assert again.receipt == result.receipt and again.complete == result.complete
    with pytest.raises(FileExistsError):
        result.write(tmp_path / "run")


def test_read_rejects_a_changed_object_or_line(tmp_path):
    result = execute("Amount 5.", Client(envelope(candidate())))
    reply = next(e for e in result.record if e["kind"] == "call")["reply_sha256"]
    result.write(tmp_path / "a")
    (tmp_path / "a" / "objects" / reply.removeprefix("sha256:")).write_text("{}")
    with pytest.raises(ValueError):
        RunResult.read(tmp_path / "a")
    result.write(tmp_path / "b")
    log = tmp_path / "b" / "run.jsonl"
    log.write_text(log.read_text().replace('"complete":true', '"complete":false'))
    with pytest.raises(ValueError):
        RunResult.read(tmp_path / "b")


def test_old_record_shape_and_node_citation_are_refused():
    result = execute("Amount 5.", Client(envelope(candidate())))
    assert not replay({"header": result.record[0]}, result.artifacts, "Amount 5.", SCHEMA).ok
    # `node` is reserved for node citations (#285). Today it makes the reply invalid.
    cited = candidate(evidence=[{**item("5"), "node": "n1"}])
    refused = execute("Amount 5.", Client(envelope(cited)))
    assert next(e for e in refused.record if e["kind"] == "call")["status"] == "invalid_reply"


def test_runs_share_one_object_folder(tmp_path):
    first = execute("Amount 5.", Client(envelope(candidate())))
    second = execute("Amount 7.", Client(envelope(candidate("7"))))
    first.write(tmp_path)
    (tmp_path / "run.jsonl").rename(tmp_path / "first.jsonl")
    second.write(tmp_path)
    assert RunResult.read(tmp_path).run_sha256 == second.run_sha256
    log = tmp_path / "run.jsonl"
    log.write_text(log.read_text().replace(second.record[0]["inputs"]["schema_sha256"], "../x"))
    with pytest.raises(ValueError, match="bad key"):
        RunResult.read(tmp_path)
    log.write_text(log.read_text().replace('"../x"', '["../x"]'))
    with pytest.raises(ValueError, match="bad key"):
        RunResult.read(tmp_path)


def test_read_names_a_missing_object_and_write_repairs_a_bad_one(tmp_path):
    result = execute("Amount 5.", Client(envelope(candidate())))
    reply = next(e for e in result.record if e["kind"] == "call")["reply_sha256"]
    result.write(tmp_path / "a")
    path = tmp_path / "a" / "objects" / reply.removeprefix("sha256:")
    path.unlink()
    with pytest.raises(ValueError, match="missing object"):
        RunResult.read(tmp_path / "a")
    path.write_text("trunc")  # an object left short, for example by a crash
    (tmp_path / "a" / "run.jsonl").unlink()
    result.write(tmp_path / "a")
    assert RunResult.read(tmp_path / "a").run_sha256 == result.run_sha256
    assert not [p for p in (tmp_path / "a" / "objects").iterdir() if p.name.startswith(".tmp-")]
    blocked = tmp_path / "b" / "objects" / reply.removeprefix("sha256:")
    blocked.mkdir(parents=True)  # a directory where an object goes
    with pytest.raises(OSError):
        result.write(tmp_path / "b")
    assert not [p for p in blocked.parent.iterdir() if p.name.startswith(".tmp-")]


def test_read_refuses_symlinks_special_files_and_oversized_runs(tmp_path):
    import os

    result = execute("Amount 5.", Client(envelope(candidate())))
    reply = next(e for e in result.record if e["kind"] == "call")["reply_sha256"]
    size = len(gg.jcs(result.record)) + sum(len(v.encode()) for v in result.artifacts.values())
    result.write(tmp_path / "a")
    assert RunResult.read(tmp_path / "a", max_bytes=size + 64).run_sha256 == result.run_sha256
    with pytest.raises(ValueError, match="larger than max_bytes"):
        RunResult.read(tmp_path / "a", max_bytes=size // 2)
    path = tmp_path / "a" / "objects" / reply.removeprefix("sha256:")
    (tmp_path / "copy").write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(tmp_path / "copy")
    with pytest.raises(ValueError, match="symlink"):
        RunResult.read(tmp_path / "a")
    if hasattr(os, "mkfifo"):
        path.unlink()
        os.mkfifo(path)  # an open for reading would wait for a writer
        with pytest.raises(ValueError, match="not a regular file"):
            RunResult.read(tmp_path / "a")


def test_read_refuses_a_deep_input_object(tmp_path):
    result = execute("Amount 5.", Client(envelope(candidate())))
    result.write(tmp_path)
    schema = result.record[0]["inputs"]["schema_sha256"].removeprefix("sha256:")
    (tmp_path / "objects" / schema).write_text("[" * 100000)
    with pytest.raises(ValueError):
        RunResult.read(tmp_path)


def test_write_checks_keys_and_the_log_before_any_object(tmp_path):
    result = execute("Amount 5.", Client(envelope(candidate())))
    bad = dataclasses.replace(result, artifacts={"sha256:../../x": "body"})
    with pytest.raises(ValueError, match="not a sha256 digest"):
        bad.write(tmp_path / "a")
    assert not (tmp_path / "x").exists() and not (tmp_path / "a").exists()
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "run.jsonl").write_text("")
    with pytest.raises(FileExistsError):
        result.write(tmp_path / "b")
    assert not (tmp_path / "b" / "objects").exists()
    result.write(tmp_path / "c")
    assert [p.name for p in (tmp_path / "c").iterdir() if p.name.startswith(".tmp-")] == []
    assert all(p.stat().st_mode & 0o044 for p in (tmp_path / "c" / "objects").iterdir())


CAUSE_SCHEMA = {"fields": {"amount": {"type": "integer", "aliases": ["Amount"]}}}


@pytest.mark.parametrize(
    "text,field,cause",
    [
        ("Amount 5.", "Amount 5", "holds_value"),
        ("Amount 5, Amount.", "Amount.", "after_value"),
    ],
)
def test_repair_names_the_cause_of_a_field_item_that_cannot_pass(text, field, cause):
    # A field item must end at or before the value (SPEC §4.6, #318).
    first = candidate(evidence=[item("5"), item(field, "field")])
    assert gg.admit(text, CAUSE_SCHEMA, [{"id": "a", **first}]).decisions[0].codes == (
        "FIELD_CITATION_INVALID",
    )
    new = candidate(evidence=[item("5"), item("Amount", "field")])
    client = Client(envelope(first), new)
    result = execute(text, client, CAUSE_SCHEMA)
    assert "It must not hold the value." in client.prompts[0]
    repair = json.loads(client.prompts[1].split("\n", 1)[1])
    expected = {"holds_value": "holds the value", "after_value": "comes after the value"}
    assert expected[cause] in repair["feedback"]
    assert "label before the value" in repair["feedback"]
    call = next(e for e in result.record if e["kind"] == "call" and e["phase"] == "repair")
    assert call["field_causes"] == [cause]
    assert result.receipt.decisions[0].outcome == "admitted"
    assert "field_causes" not in result.record[-2]
    assert_replays(result, text, CAUSE_SCHEMA)


def test_final_admission_keeps_the_field_cause_after_the_last_repair():
    first = candidate(evidence=[item("5"), item("Amount 5", "field")])
    client = Client(envelope(first), first)
    result = execute("Amount 5.", client, CAUSE_SCHEMA)
    final = next(e for e in result.record if e["kind"] == "final_admission")
    assert final["field_causes"] == {"c1-1": ["holds_value"]}
    assert_replays(result, "Amount 5.", CAUSE_SCHEMA)


ROUND_SCHEMA = {"fields": {"revenue": {"type": "number", "aliases": ["Revenue"]}}}


def rounded_and_exact(rounded_quote, rounded_value):
    text = f"Revenue rose to {rounded_quote}.\n(in millions)\nRevenue\t17,284"
    rounded = candidate(rounded_value, "revenue", evidence=[item(rounded_quote)])
    exact = candidate(
        "17284000000",
        "revenue",
        evidence=[item("17,284"), item("Revenue", "field"), item("in millions", "scale")],
    )
    return text, rounded, exact


def test_a_rounded_figure_beside_the_exact_figure_is_dropped_and_recorded():
    text, rounded, exact = rounded_and_exact("£17.3bn", "17300000000")
    both = gg.admit(text, ROUND_SCHEMA, [{"id": "a", **rounded}, {"id": "b", **exact}])
    assert all("CONFLICTING_CANDIDATES" in d.codes for d in both.decisions)
    result = execute(text, Client(envelope(rounded, exact)), ROUND_SCHEMA)
    assert [c["id"] for c in result.candidates] == ["c1-2"]
    assert [d.outcome for d in result.receipt.decisions] == ["admitted"]
    event = next(e for e in result.record if e["kind"] == "rounding")
    assert event["dropped"] == [
        {"candidate_id": "c1-1", "kept_ids": ["c1-2"], "precision": "100000000"}
    ]
    packet = json.loads(result.artifacts[event["admission_sha256"]])
    assert [c["id"] for c in packet["candidates"]] == ["c1-1", "c1-2"]
    assert_replays(result, text, ROUND_SCHEMA)


def test_two_figures_that_do_not_round_to_each_other_stay_a_conflict():
    text, rounded, exact = rounded_and_exact("£17.5bn", "17500000000")
    result = execute(text, Client(envelope(rounded, exact)), ROUND_SCHEMA)
    assert len(result.candidates) == 2
    assert all("CONFLICTING_CANDIDATES" in d.codes for d in result.receipt.decisions)
    assert not any(e["kind"] == "rounding" for e in result.record)
    assert_replays(result, text, ROUND_SCHEMA)


def test_a_rounded_figure_stays_when_the_exact_figure_meets_another_conflict():
    # Dropping the rounded figure must not hide a real conflict: 17,284 against 18,000.
    text, rounded, exact = rounded_and_exact("£17.3bn", "17300000000")
    text += "\nRevenue\t18,000"
    other = candidate(
        "18000000000",
        "revenue",
        evidence=[item("18,000"), item("Revenue", "field"), item("in millions", "scale")],
    )
    result = execute(text, Client(envelope(rounded, exact, other)), ROUND_SCHEMA)
    assert len(result.candidates) == 3
    assert all("CONFLICTING_CANDIDATES" in d.codes for d in result.receipt.decisions)
    assert not any(e["kind"] == "rounding" for e in result.record)
    assert_replays(result, text, ROUND_SCHEMA)


def test_a_groundgate_run_1_record_fails_replay_with_a_version_message(tmp_path):
    # 0.9.0 wrote groundgate-run/1 records. This runner writes groundgate-run/2 (#318, #319).
    result = execute("Amount 5.", Client(envelope(candidate())))
    assert result.record[0]["runner"] == "groundgate-run/2"
    old = copy.deepcopy(result.record)
    old[0]["runner"] = "groundgate-run/1"
    verification = replay(old, result.artifacts, "Amount 5.", SCHEMA)
    message = "runner version differs: the record is 'groundgate-run/1', this runner is "
    assert not verification.ok
    assert verification.problems == (message + "'groundgate-run/2'",)
    result.write(tmp_path)
    log = tmp_path / "run.jsonl"
    log.write_text(log.read_text().replace("groundgate-run/2", "groundgate-run/1", 1))
    with pytest.raises(ValueError, match="the record is 'groundgate-run/1'"):
        RunResult.read(tmp_path)
