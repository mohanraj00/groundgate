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
sys.path[:0] = [str(BENCH), str(BENCH / "label")]  # bench scripts are not a package

import app  # noqa: E402  (bench/label/app.py)
import score  # noqa: E402  (bench/score.py)

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


def test_a_nested_section_with_the_same_code_is_read_once() -> None:
    from fetch import spl_sections

    xml = (
        b'<document xmlns="urn:hl7-org:v3"><section><code code="34068-7"/><text>Dose 5 mg.</text>'
        b'<component><section><code code="34068-7"/><text>Adults: 10 mg.</text></section>'
        b"</component></section></document>"
    )
    text = spl_sections(xml, ["34068-7"])
    assert text.count("Adults: 10 mg.") == 1 and "Dose 5 mg." in text


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
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": '{"extractions": []}'},
        },
    ]
    done = subprocess.CompletedProcess([], 0, "\n".join(json.dumps(e) for e in events), "")
    monkeypatch.setattr(propose.subprocess, "run", lambda *a, **k: done)
    model = propose.CLIModel("codex", "m", 1, "low")
    assert model._codex("prompt") == ('{"extractions": []}', 1)
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
