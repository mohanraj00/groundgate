"""The benchmark's scoring rules and the labeling app's safeguards."""

from __future__ import annotations

import copy
import http.client
import json
import sys
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

BENCH = Path(__file__).parent.parent / "bench"
sys.path[:0] = [str(BENCH), str(BENCH / "label"), str(BENCH / "patterns")]  # not a package

import app  # noqa: E402  (bench/label/app.py)
import pairs  # noqa: E402  (bench/patterns/pairs.py)
import score  # noqa: E402  (bench/score.py)
import triage  # noqa: E402  (bench/patterns/triage.py)

TEXT = "Tablets: 10 mg. The maximum dose is 40 mg once daily."


def gold() -> score.Gold:
    fields = {
        "tablet_strengths": {"type": "number", "unit": "mg", "multiple": True},
        "max_dose": {"type": "number", "unit": "mg"},
        "pediatric_min_age": {"type": "integer", "unit": "years"},
        "hepatic_dose": {"type": "number", "unit": "mg"},
    }
    return score.Gold(
        doc="d",
        kind="fda",
        text=TEXT,
        schema={"fields": fields, "units": {}},
        values={"tablet_strengths": {"10"}, "max_dose": {"40"}},
        evidence={("tablet_strengths", "10"): [(9, 14)], ("max_dose", "40"): [(36, 41)]},
        absent={"pediatric_min_age"},
        excluded=set(),
        checked=True,
    )


def cand(field: str, value: object, unit: str | None = "mg", at: str | None = None) -> dict:
    c: dict[str, Any] = {"field": field, "value": value}
    if unit:
        c["unit"] = unit
    if at:
        s = TEXT.index(at)
        c["evidence"] = {"start": s, "end": s + len(at), "text": at}
    return c


@pytest.mark.parametrize(
    ("c", "label", "cites"),
    [
        (cand("max_dose", "40", at="40 mg"), "correct", True),
        (cand("max_dose", 40, at="40 mg"), "correct", True),
        (cand("max_dose", "40.0"), "correct", False),
        (cand("tablet_strengths", "40", at="40 mg"), "wrong_value", False),
        (cand("max_dose", "40", unit="mcg"), "wrong_unit", False),
        (cand("max_dose", "null"), "unparsable", False),
        (cand("pediatric_min_age", "6", unit="years"), "absent_field", False),
        (cand("hepatic_dose", "5"), "unscored", False),
        (cand("dose", "40"), "off_schema", False),
    ],
)
def test_judge(c: dict, label: str, cites: bool) -> None:
    assert score.judge(gold(), c) == (label, cites)


def test_right_value_from_the_wrong_place_is_correct_but_not_cited() -> None:
    assert score.judge(gold(), cand("tablet_strengths", "10", at="10 mg")) == ("correct", True)
    wrong_place = cand("max_dose", "40")
    wrong_place["evidence"] = {"start": 9, "end": 14, "text": "10 mg"}
    assert score.judge(gold(), wrong_place) == ("correct", False)


def test_wilson() -> None:
    lo, hi = score.wilson(0, 10)
    assert lo == 0 and hi == pytest.approx(0.2775, abs=1e-4)
    lo, hi = score.wilson(5, 10)
    assert (lo, hi) == (pytest.approx(0.2366, abs=1e-4), pytest.approx(0.7634, abs=1e-4))
    assert score.rate(0, 0)["rate"] is None


def test_groundgate_decisions_map_to_accept_review_reject() -> None:
    g = gold()
    rows = score.rows_for(
        g,
        [
            cand("max_dose", "40", at="40 mg"),
            cand("max_dose", "400", at="40 mg"),
            cand("tablet_strengths", "10", at="10 mg"),
        ],
        "m",
        1000,
    )
    assert [score.decide("groundgate", r) for r in rows] == ["accept", "reject", "accept"]
    assert [score.decide("lx_all", r) for r in rows] == ["accept"] * 3
    assert [r.label for r in rows] == ["correct", "wrong_value", "correct"]


def test_near_miss_changes_the_second_digit() -> None:
    from decimal import Decimal

    assert score._near(Decimal(1800)) == Decimal(1000)
    assert score._near(Decimal(7)) == Decimal(8)
    assert score._near(Decimal("0.4")) == Decimal("0.6")


def test_a_keyed_fact_is_judged_on_its_key() -> None:
    g = gold()
    g.schema["fields"]["max_dose"]["keys"] = ["Hypertension", "Heart Failure"]
    g.keyed = {"max_dose": {("Heart Failure", "40")}}
    assert score.judge(g, cand("max_dose", "40", at="40 mg") | {"key": "heart  failure"}) == (
        "correct",
        True,
    )
    assert score.judge(g, cand("max_dose", "40") | {"key": "Hypertension"})[0] == "wrong_key"
    assert score.judge(g, cand("max_dose", "40"))[0] == "wrong_key"  # no key at all
    assert score.judge(g, cand("max_dose", "20") | {"key": "Hypertension"})[0] == "wrong_value"


def test_spec_01_sees_a_keyed_field_as_multiple() -> None:
    import decide  # bench/decide.py

    schema = {"fields": {"d": {"type": "number", "keys": ["A", "B"]}, "e": {"type": "number"}}}
    assert decide.as_01(schema)["fields"] == {
        "d": {"type": "number", "multiple": True},
        "e": {"type": "number"},
    }
    assert schema["fields"]["d"]["keys"] == ["A", "B"]  # the 0.2 schema is not changed


def test_a_control_judgment_is_saved_and_checked(
    served: tuple[int, dict], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    port, _ = served
    item = {"doc": "d", "field": "max_dose", "key": None, "value": "40", "unit": "mg"}
    item |= {"start": 36, "end": 41, "quote": "40 mg", "judgment": None, "note": ""}
    (tmp_path / "controls.json").write_text(json.dumps({"items": [item]}))
    monkeypatch.setattr(app, "CONTROLS", True)
    docs = call(port, "GET", "/api/docs", token=app.TOKEN)[1]
    assert docs == [app.control_summary("d", [item])] and docs[0]["open"] == 1
    bad = {"index": 0, "judgment": "maybe"}
    assert call(port, "POST", "/api/controls/d", bad, app.TOKEN)[0] == 422
    assert (
        call(port, "POST", "/api/controls/d", {"index": 3, "judgment": "wrong"}, app.TOKEN)[0]
        == 422
    )
    status, body = call(
        port, "POST", "/api/controls/d", {"index": 0, "judgment": "wrong"}, app.TOKEN
    )
    assert status == 200 and body["open"] == 0
    saved = json.loads((tmp_path / "controls.json").read_text())["items"][0]
    assert saved["judgment"] == "wrong"
    assert call(port, "POST", "/api/controls/d", {"index": 0, "judgment": "wrong"})[0] == 403


# ---------------------------------------------------------------------------- label app


@pytest.fixture
def served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[int, dict]]:
    (tmp_path / "gold").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "d.txt").write_text(TEXT, encoding="utf-8")
    g = {
        "doc": "d",
        "kind": "fda",
        "fields": {"max_dose": {"schema": {"type": "number", "unit": "mg"}, "description": ""}},
        "units": {},
        "facts": [
            {
                "id": "f1",
                "field": "max_dose",
                "value": "40",
                "unit": "mg",
                "evidence": [{"start": 36, "end": 41}],
                "status": "draft",
            }
        ],
        "absent": {},
        "excluded": {},
        "checked": None,
    }
    (tmp_path / "gold" / "d.json").write_text(json.dumps(g))
    monkeypatch.setattr(app, "GOLD", tmp_path / "gold")
    monkeypatch.setattr(app, "DOCS", tmp_path / "docs")
    server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], g
    server.shutdown()


def call(port: int, method: str, path: str, body: Any = None, token: str | None = None) -> tuple:
    conn = http.client.HTTPConnection("127.0.0.1", port)
    headers = {"X-Label-Token": token} if token else {}
    conn.request(method, path, json.dumps(body) if body is not None else None, headers)
    r = conn.getresponse()
    return r.status, json.loads(r.read() or b"null")


def test_api_needs_the_page_token(served: tuple[int, dict]) -> None:
    port, _ = served
    assert call(port, "GET", "/api/docs")[0] == 403
    assert call(port, "GET", "/api/docs", token="guess")[0] == 403
    status, docs = call(port, "GET", "/api/docs", token=app.TOKEN)
    assert status == 200 and docs[0]["open"] == 1


def test_the_absent_pass_lists_only_documents_with_an_absence(
    served: tuple[int, dict], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    port, g = served
    monkeypatch.setattr(app, "ABSENT_PASS", "fda")
    assert call(port, "GET", "/api/docs", token=app.TOKEN)[1] == []
    g["absent"] = {"max_dose": "confirmed"}
    (tmp_path / "gold" / "d.json").write_text(json.dumps(g))
    assert [d["id"] for d in call(port, "GET", "/api/docs", token=app.TOKEN)[1]] == ["d"]
    monkeypatch.setattr(app, "ABSENT_PASS", "irs")
    assert call(port, "GET", "/api/docs", token=app.TOKEN)[1] == []


def test_save_rules(served: tuple[int, dict], tmp_path: Path) -> None:
    port, g = served
    status, body = call(port, "POST", "/api/doc/d", {"gold": g, "done": True}, app.TOKEN)
    assert status == 422 and "decide every" in body["error"]

    bad = copy.deepcopy(g)
    bad["facts"][0]["evidence"] = [{"start": 0, "end": 10_000}]
    assert call(port, "POST", "/api/doc/d", {"gold": bad}, app.TOKEN)[0] == 422

    bad = copy.deepcopy(g)
    bad["facts"][0]["value"] = "$40"
    assert call(port, "POST", "/api/doc/d", {"gold": bad}, app.TOKEN)[0] == 422

    ok = copy.deepcopy(g)
    ok["facts"][0].update(status="confirmed", unit="mcg")
    status, _ = call(
        port, "POST", "/api/doc/d", {"gold": ok, "done": True, "seconds": 90}, app.TOKEN
    )
    assert status == 200
    saved = json.loads((tmp_path / "gold" / "d.json").read_text())
    assert saved["checked"]["by"] == "person"
    assert saved["seconds_spent"] == 90
    assert saved["facts"][0]["unit"] == "mg"  # units always come from the field


def test_the_pdf_pane_maps_text_pages_to_pdf_pages(
    served: tuple[int, dict], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    port, _ = served
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "d.pdf").write_bytes(b"%PDF-1.4 test")
    sources = {"sources": [{"id": "d", "kind": "irs", "url": "u", "select": {"pages": [11, 6]}}]}
    (tmp_path / "sources.json").write_text(json.dumps(sources))
    monkeypatch.setattr(app, "CACHE", tmp_path / ".cache")
    monkeypatch.setattr(app, "SOURCES", tmp_path / "sources.json")
    status, body = call(port, "GET", "/api/doc/d", token=app.TOKEN)
    assert status == 200 and body["pdf"] == {"url": "/source/d", "pages": [6, 11]}
    # the pane adds a query so the viewer loads the page again
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/source/d?p=11")
    r = conn.getresponse()
    assert r.status == 200 and r.read() == b"%PDF-1.4 test"


def test_a_nested_section_with_the_same_code_is_read_once() -> None:
    from fetch import spl_sections

    xml = (
        b'<document xmlns="urn:hl7-org:v3"><section><code code="34068-7"/><text>Dose 5 mg.</text>'
        b'<component><section><code code="34068-7"/><text>Adults: 10 mg.</text></section>'
        b"</component></section></document>"
    )
    text = spl_sections(xml, ["34068-7"])
    assert text.count("Adults: 10 mg.") == 1 and "Dose 5 mg." in text


def test_keyed_facts_need_a_key_from_the_list(served: tuple[int, dict], tmp_path: Path) -> None:
    port, g = served
    keyed = copy.deepcopy(g)
    keyed["doc"] = "k"
    keyed["fields"]["max_dose"]["schema"]["keys"] = ["Hypertension", "Angina"]
    (tmp_path / "docs" / "k.txt").write_text(TEXT, encoding="utf-8")
    (tmp_path / "gold" / "k.json").write_text(json.dumps(keyed))

    keyed["facts"][0]["status"] = "confirmed"
    status, body = call(port, "POST", "/api/doc/k", {"gold": keyed, "done": True}, app.TOKEN)
    assert status == 422 and "pick a key" in body["error"]
    keyed["facts"][0]["key"] = "Migraine"
    assert call(port, "POST", "/api/doc/k", {"gold": keyed}, app.TOKEN)[0] == 422
    keyed["facts"][0]["key"] = "Angina"
    assert call(port, "POST", "/api/doc/k", {"gold": keyed, "done": True}, app.TOKEN)[0] == 200


def test_set2_drafts_must_write_their_value() -> None:
    sys.path.insert(0, str(BENCH / "set2" / "gold"))
    import build

    assert build.stated("141900000000000", "$141.9 trillion")
    assert build.stated("1600", "$1,600") and not build.stated("16000", "$1,600")
    text = "Limit: $7,000.\nOver 50:  $8,000."
    span, quote = build.locate(text, "Over 50: [[$8,000]]")
    assert quote == "$8,000" and span == {"start": 25, "end": 31}
    with pytest.raises(ValueError, match="2 times"):
        build.locate("$5 and $5", "[[$5]]")


def test_original_document_opens_without_the_token(
    served: tuple[int, dict], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    port, _ = served
    monkeypatch.setattr(app, "CACHE", tmp_path)
    assert call(port, "GET", "/api/doc/d", token=app.TOKEN)[1]["source"] is None
    (tmp_path / "d.pdf").write_bytes(b"%PDF-1.4")
    assert call(port, "GET", "/api/doc/d", token=app.TOKEN)[1]["source"] == "/source/d"
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/source/d")
    r = conn.getresponse()
    assert (r.status, r.getheader("Content-Type"), r.read()) == (
        200,
        "application/pdf",
        b"%PDF-1.4",
    )
    assert call(port, "GET", "/source/other")[0] == 403


# ---------------------------------------------------------------------------- planting


def test_text_plants_qualify_the_value_where_it_is_written() -> None:
    g = gold()
    text = "The fee is $1,500 per year."
    (num,) = [t for t in score.tokens(text) if t.value is not None]
    g.schema["fields"]["fee"] = {"type": "number", "unit": "USD"}
    plants = score._plant_text(g, text, "fee", num)
    assert plants["qualifier_in_text"][0] == "The fee is more than $1,500 per year."
    assert plants["scale_word_in_text"][0] == "The fee is $1,500 million per year."
    g.schema["fields"]["fee"]["comparator"] = "gt"
    assert "qualifier_in_text" not in score._plant_text(g, text, "fee", num)
    assert "scale_word_in_text" not in score._plant_text(g, TEXT, "max_dose", score.tokens(TEXT)[0])


def test_extraction_plants() -> None:
    pytest.importorskip("langextract")
    g = gold()
    text = "Flight time: 0.4 hours. Wage base: 184,500 dollars."
    g.schema["fields"]["t"] = {"type": "number", "unit": "hours"}
    g.schema["fields"]["w"] = {"type": "number", "unit": "USD"}
    (chunk,) = score._chunks(text)
    for name, value, quote in (("t", "0.4", "0.4 hours"), ("w", "184500", "184,500 dollars")):
        s = text.index(quote)
        num = score.tokens(text, s, s + len(quote))[0]
        plants = score._plant(g, text, chunk, name, value, s, s + len(quote), num)
        if name == "t":
            assert plants["decimal_dropped"][1] == "4"
            assert "comma_as_decimal" not in plants
        else:
            assert plants["comma_as_decimal"][1] == "184.5"
            assert "decimal_dropped" not in plants


# ---------------------------------------------------------------------------- codex harness


def test_codex_replies_that_used_a_tool_are_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("langextract")
    import subprocess

    import propose

    events = [
        {"type": "item.completed", "item": {"type": "reasoning", "text": "..."}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "cat x"}},
        {"type": "item.completed", "item": {"type": "error", "message": "Skill descriptions..."}},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": '{"extractions": []}'},
        },
    ]
    done = subprocess.CompletedProcess([], 0, "\n".join(json.dumps(e) for e in events), "")
    monkeypatch.setattr(propose.subprocess, "run", lambda *a, **k: done)
    model = propose.CLIModel("codex", "m", 1, "low")
    assert model._codex("prompt") == ('{"extractions": []}', 1, ["Skill descriptions..."])
    assert 'model_reasoning_effort="low"' in model.command()
    assert model.command()[model.command().index("-s") + 1] == "read-only"

    failed = {"type": "turn.failed", "error": {"message": "model is not supported"}}
    monkeypatch.setattr(
        propose.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], 1, json.dumps(failed), ""),
    )
    with pytest.raises(RuntimeError, match="not supported"):
        model._codex("prompt")


def test_claude_replies_from_another_model_are_discarded(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("langextract")
    import subprocess

    import propose

    def reply(model: str, turns: int = 1) -> subprocess.CompletedProcess[str]:
        body = {"result": '{"extractions": []}', "modelUsage": {model: {}}, "num_turns": turns}
        return subprocess.CompletedProcess([], 0, json.dumps(body), "")

    replies = iter([reply("fallback"), reply("m", turns=2), reply("m")])
    monkeypatch.setattr(propose.subprocess, "run", lambda *a, **k: next(replies))
    monkeypatch.setattr(propose.time, "sleep", lambda s: None)
    model = propose.CLIModel("claude-cli", "m", 1, None)
    out, notes = model._one("prompt")
    assert out == '{"extractions": []}'
    assert notes == {"discarded_for_harness": 2}
    cmd = model.command()
    assert cmd[cmd.index("--tools") + 1] == "" and cmd[cmd.index("--setting-sources") + 1] == ""


def test_a_refused_chunk_is_recorded_and_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("langextract")
    import subprocess

    import langextract as lx
    import propose

    body = {"is_error": True, "stop_reason": "refusal", "result": "API Error: ..."}
    calls = []

    def run(*a: object, **k: object) -> subprocess.CompletedProcess[str]:
        calls.append(a)
        return subprocess.CompletedProcess([], 1, json.dumps(body), "")

    monkeypatch.setattr(propose.subprocess, "run", run)
    model = propose.CLIModel("claude-cli", "m", 1, None)
    assert model._one("prompt") == ("", {"refused": 1})
    assert len(calls) == 1  # not retried
    result = lx.extract(
        text_or_documents="Some text.",
        prompt_description="Extract amounts.",
        examples=propose.EXAMPLES["irs"],
        fence_output=False,
        use_schema_constraints=False,
        show_progress=False,
        model=model,
    )
    assert result.extractions == []
    assert model.raw[0]["harness"] == {"refused": 1}


def test_prompts_ask_for_keys_only_on_keyed_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("langextract")
    import propose

    v01 = json.loads((BENCH / "gold" / "fda-lisinopril.json").read_text(encoding="utf-8"))
    assert not propose.keyed(v01)
    assert "one per key" not in propose.prompt_for(v01)
    assert propose.examples_for(v01) is propose.EXAMPLES["fda"]

    monkeypatch.setattr(propose, "SET", BENCH / "set2")
    gold = json.loads((BENCH / "set2" / "gold" / "fda-diltiazem.json").read_text(encoding="utf-8"))
    prompt = propose.prompt_for(gold)
    assert '- starting_dose [mg] (one per key; keys: "Hypertension"; "Angina"): ' in prompt
    assert prompt.endswith(propose.KEYS_NOTE)
    example = propose.examples_for(gold)[0].extractions
    assert {(x.extraction_class, (x.attributes or {}).get("key")) for x in example} >= {
        ("starting_dose", "Gout"),
        ("starting_dose", "Psoriasis"),
    }
    irs = json.loads((BENCH / "set2" / "gold" / "irs-p5.json").read_text(encoding="utf-8"))
    assert propose.prompt_for(irs).startswith("Extract the fields listed below from one page")


def test_targeted_fields_beyond_the_counted_matches_are_dropped() -> None:
    sys.path.insert(0, str(BENCH / "set2" / "gold"))
    import build

    text = " ".join(f"Item {i} cost ${i}0 million." for i in range(1, 8)) + "\nFootnote: $99."
    raw = text.encode()

    def fact(name: str, quote: str) -> dict:
        start = raw.index(quote.encode())
        return {"field": name, "evidence": [{"start": start, "end": start + len(quote)}]}

    names = [f"cost_{i}" for i in range(1, 8)]
    gold = {
        "kind": "irs",
        "groups": ["scale"],
        "fields": {n: {} for n in [*names, "footnote", "absent_one"]},
        "facts": [fact(n, f"${i}0 million") for i, n in enumerate(names, 1)]
        + [fact("footnote", "$99")],
        "absent": {"absent_one": "draft"},
        "excluded": {},
    }
    assert build.apply_cap(gold, text) == 2
    assert set(gold["fields"]) == {*names[:5], "footnote", "absent_one"}


def test_a_pattern_pair_is_from_a_number_a_connector_and_a_number() -> None:
    text = (
        "Raised from $1,200 to $950. Doses from 20 mg to 10 mg. From 2 through 5 years. Ages "
        "from 2-5. Taken from 5 tons of 7. From 10% to 5%. Moved from 4 to the 6th floor."
    )
    found = [(m.group(1), m.group(2)) for m in pairs.pairs_in(text)]
    assert found == [("1,200", "950"), ("20", "10"), ("2", "5"), ("2", "5"), ("10", "5")]


def test_the_label_context_marks_x_and_y_and_nothing_else() -> None:
    text = "The fee went\nfrom $5 to $7 in 2027."
    m = pairs.pairs_in(text)[0]
    shown = pairs.context(text, {"x": [m.start(1), m.end(1)], "y": [m.start(2), m.end(2)]})
    assert shown == "The fee went from $\033[1;7m5\033[0m to $\033[1;7m7\033[0m in 2027."


def test_a_pattern_pair_is_tallied_by_its_label_and_reading() -> None:
    pairs_read = [
        {"id": "a", "spec_0.3": "change"},
        {"id": "b", "spec_0.3": "range"},
        {"id": "c", "spec_0.3": "change"},
    ]
    labels = {"a": "change", "b": "change", "c": "range"}
    counts = pairs.tally(pairs_read, labels, "spec_0.3")
    assert counts["change read as change"] == 1
    assert counts["change read as range"] == 1
    assert counts["range read as change"] == 1
    assert sum(counts.values()) == 3


def test_a_results_snippet_is_the_sentence_with_x_and_y_in_bold() -> None:
    text = "First one. The fee rose\nfrom $5 to $7 in 2027. Next one."
    m = pairs.pairs_in(text)[0]
    p = {"x": [m.start(1), m.end(1)], "y": [m.start(2), m.end(2)]}
    assert pairs.snippet(text, p) == "The fee rose from $**5** to $**7** in 2027."


def test_a_model_sees_the_pair_in_brackets_and_one_fixed_question() -> None:
    text = "The fee went\nfrom $5 to $7 in 2027."
    m = pairs.pairs_in(text)[0]
    p = {"x": [m.start(1), m.end(1)], "y": [m.start(2), m.end(2)]}
    assert triage.state(text, p) == "The fee went from $[5] to $[7] in 2027."
    q = triage.question("5", "7")["pair"]
    assert q["type"] == "choice" and list(q["criteria"]) == ["change", "range", "neither"]


def test_a_dot_is_a_listed_abbreviation_before_whitespace() -> None:
    sys.path.insert(0, str(BENCH / "dots"))
    import dots

    text = "Up to Rs. 5 at 6 p.m. in the U.S. Mrs. Lee paid $9.50 on No.4 in Inc."
    assert [m.group() for m in dots.dots_in(text)] == ["Rs.", "p.m.", "U.S.", "Mrs."]
    head = "Next.\n12 Federal Register / Vol. 90, No. 5 / Rules\nSee No. 4 here."
    assert [m.start() for m in dots.dots_in(head)] == [head.index("No. 4")]
    split = "Federal Register\nVol. 90, No. 123 / Rules\nSee No. 4 here."
    assert [m.start() for m in dots.dots_in(split)] == [split.index("No. 4")]


def test_an_india_token_is_a_number_token_with_a_comma() -> None:
    sys.path.insert(0, str(BENCH / "india"))
    import india

    text = "Rs 2,00,000 and 1,2,3, then 5,000, x12,3, page-width,-16,842 and 7."
    assert [text[t.start : t.end] for t in india.commas_in(text)] == [
        "2,00,000",
        "1,2,3",
        "5,000",
    ]


def test_a_caps_dot_is_us_or_no_before_whitespace_and_an_uppercase_letter() -> None:
    sys.path.insert(0, str(BENCH / "caps"))
    import caps

    text = "In the U.S. Tax Court, Docket No. DEA-1086 and Nos. A-1 but no. 4 and U.S. citizens."
    assert [m.group() for m in caps.caps_in(text)] == ["U.S.", "No.", "Nos."]
    assert not caps.caps_in("Made in the U.S.A. Here.\nU.S.\n\nThe end. No.\r\n  \nThe")
    assert [m.start() for m in caps.caps_in("Sold in the U.S.\r\n The")] == [12]
    head = "Federal Register / Vol. 89, No. 5 / Rules\nSee No. Five."
    assert [m.start() for m in caps.caps_in(head)] == [head.index("No. Five")]


def test_a_caps_dot_with_the_text_of_an_earlier_dot_does_not_count_again() -> None:
    sys.path.insert(0, str(BENCH / "caps"))
    import caps

    find = caps.fresh_finder()
    page = "Rules of the U.S. Tax Court apply here."
    assert len(find(page)) == 1
    assert find("Rules of the  U.S.\nTax Court apply here.") == []
    assert len(find("Rules in the U.S. Code apply here.")) == 1
    seeded = caps.fresh_finder(caps.dot_keys(page, caps.caps_in(page)[0]))
    assert seeded(page) == []
    sign = "Captain, U.S. Coast Guard, Captain of the Port San Francisco."
    find = caps.fresh_finder()
    assert len(find("Dated: May 1. " + sign + " [FR Doc. 1]")) == 1
    assert find("Dated: June 9. " + sign + " [FR Doc. 2]") == []
