"""The calibration tool from sample to report, on hand-written text, with a fake judge."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

if importlib.util.find_spec("groundgate_calibrate") is None:  # the release job tests the wheel
    sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from groundgate_calibrate import cli, judges, label
from groundgate_calibrate import questions as q
from groundgate_calibrate.stats import needed, pick, upper_95

from groundgate.canonical import SPEC_VERSION

TEXT = "In fiscal 2024 sales fell.\nRevenue was 4,100.\nIn fiscal 2025 revenue was 5,200.\n"
SCHEMA = {
    "fields": {
        "revenue": {"type": "number", "multiple": True, "keys": ["fiscal 2025", "fiscal 2024"]}
    }
}


def evidence(text: str, s: str) -> dict[str, int]:
    i = text.encode().index(s.encode())
    return {"start": i, "end": i + len(s.encode())}


def inputs(tmp: Path, docs: int) -> tuple[Path, Path, Path]:
    d, c = tmp / "docs", tmp / "cands"
    d.mkdir()
    c.mkdir()
    for n in range(docs):
        (d / f"doc{n}.txt").write_text(TEXT)
        cands = [
            {"field": "revenue", "value": "4100", "key": "fiscal 2025",
             "evidence": evidence(TEXT, "Revenue was 4,100.")},
            {"field": "revenue", "value": "5200", "key": "fiscal 2025",
             "evidence": evidence(TEXT, "revenue was 5,200")},
        ]  # fmt: skip
        (c / f"doc{n}.json").write_text(json.dumps(cands))
    s = tmp / "schema.json"
    s.write_text(json.dumps(SCHEMA))
    return d, c, s


def test_upper_95_and_the_clears_that_each_ceiling_needs() -> None:
    assert upper_95(0, 0) == 1.0
    assert upper_95(0, 59) < 0.05 <= upper_95(0, 58)
    assert [needed(c) for c in (0.05, 0.1, 0.2)] == [59, 29, 14]
    assert upper_95(3, 20) == 0.3437  # the same as the bench judges' bound on small counts
    assert 0.1 < upper_95(960, 10000) < 0.102  # no underflow on a large count
    bound = {0.5: 0.3, 0.7: 0.04, 0.9: 0.01}.__getitem__
    assert pick((0.5, 0.7, 0.9), bound, 0.05, "lowest") == 0.7
    assert pick((0.5, 0.7, 0.9), bound, 0.05, "highest") == 0.9
    assert pick((0.5,), bound, 0.05, "lowest") is None


def test_sample_takes_key_flags_and_admitted_values() -> None:
    cands = json.loads(json.dumps([
        {"field": "revenue", "value": "4100", "key": "fiscal 2025",
         "evidence": evidence(TEXT, "Revenue was 4,100.")},
        {"field": "revenue", "value": "5200", "key": "fiscal 2025",
         "evidence": evidence(TEXT, "revenue was 5,200")},
    ]))  # fmt: skip
    (key,) = q.sample("key", "d", TEXT, SCHEMA, cands)
    assert key["key"] == "fiscal 2025" and key["keys"] == ["fiscal 2025", "fiscal 2024"]
    a, b = key["mark"]
    assert TEXT[a:b] == "4,100"  # the value, not the whole evidence
    (field,) = q.sample("field", "d", TEXT, SCHEMA, cands)
    assert field["id"] == "d:1"
    # a key judgment can admit the flagged one, so with a key threshold it gets the field question
    both = q.sample("field", "d", TEXT, SCHEMA, cands, key_clear=True)
    assert [it["id"] for it in both] == ["d:0", "d:1"]
    st, qs = q.prompt("key", TEXT, key, "The text is from a 10-K filing.", {})
    assert "[4,100]" in st
    assert qs["key"]["criteria"] == {
        "k1": "fiscal 2025",
        "k2": "fiscal 2024",
        "none": qs["key"]["criteria"]["none"],
    }
    assert qs["key"]["instructions"].startswith("The text is from a 10-K filing. The text marks")


def test_a_label_is_checked_and_the_page_hides_the_candidates_key() -> None:
    it = {
        "id": "d:0",
        "keys": ["fiscal 2025", "fiscal 2024"],
        "mark": [37, 42],
        "key": "fiscal 2025",
    }
    assert q.valid_label("key", it, ["fiscal 2024"])
    assert q.valid_label("key", it, None)
    assert not q.valid_label("key", it, ["fiscal 2023"])
    assert q.valid_label("field", it, False)
    assert not q.valid_label("field", it, "no")
    html = label.page(TEXT, [it, {**it, "id": "d:1", "mark": [38, 44]}])
    assert html.count("<mark") == 1 and 'data-ids="d:0 d:1"' in html
    assert f">{TEXT[37:44]}</mark>" in html  # one mark over both values


class Fake:
    id = "fake"
    digest = "fake-1"

    def __init__(self, answers: dict[str, dict[str, Any]]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    def ask(self, state: str, qs: dict[str, Any]) -> dict[str, Any]:
        self.asked.append(state)
        return {k: self.answers[k] for k in qs}


def fake(answers: dict[str, dict[str, Any]]) -> Any:
    return lambda: Fake(answers)


@pytest.mark.parametrize("question", ["field", "key"])
@pytest.mark.parametrize("schema_description", [None, "Total revenue for the fiscal year."])
@pytest.mark.parametrize("override", [None, "Revenue from sales, excluding other income."])
def test_sample_uses_descriptions_in_prompts_and_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    schema_description: str | None,
    override: str | None,
) -> None:
    if schema_description is not None and SPEC_VERSION < "0.6":
        pytest.skip("schema descriptions are spec 0.6 (#171)")
    d, c, s = inputs(tmp_path, 1)
    schema = json.loads(s.read_text())
    descriptions = {}
    if schema_description is not None:
        schema["fields"]["revenue"]["description"] = schema_description
        schema["fields"]["cost"] = {"description": "The cost of sales."}
        descriptions = {"revenue": schema_description, "cost": "The cost of sales."}
    s.write_text(json.dumps(schema))
    extra = []
    if override is not None:
        path = tmp_path / "descriptions.json"
        path.write_text(json.dumps({"revenue": override}))
        descriptions["revenue"] = override
        extra = ["--descriptions", str(path)]
    work = cli.Work(tmp_path / "work")
    cli.main(["sample", "--work", str(work.path), "--docs", str(d), "--candidates", str(c),
              "--schema", str(s), "--question", question, *extra])  # fmt: skip
    assert work.config["descriptions"] == descriptions
    assert work.config["schema"] == schema
    ((_, _, questions),) = cli.prompts(work)
    if question == "field":
        assert questions["field"]["instructions"] == (
            "The text marks one value in brackets. Does the text state it as this value? "
            + descriptions.get("revenue", "revenue")
        )
    else:
        assert questions["key"]["instructions"] == (
            "The text marks one value in brackets. Which of these does it belong to?"
        )

    state: dict[str, Any] = {}

    class Server:
        def __init__(self, address: Any, handler: Any) -> None:
            self.handler = handler

        def serve_forever(self) -> None:
            request = object.__new__(self.handler)
            request.path = "/state"
            request.send = lambda body: state.update(json.loads(body))
            request.do_GET()

    monkeypatch.setattr(label, "ThreadingHTTPServer", Server)
    label.serve(work, 0)
    assert state["items"][0]["description"] == descriptions.get("revenue", "")
    assert "key" not in state["items"][0]


@pytest.mark.skipif(SPEC_VERSION < "0.6", reason="schema descriptions are spec 0.6 (#171)")
def test_a_changed_field_description_needs_a_new_calibration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d, c, s = inputs(tmp_path, 1)
    schema = json.loads(s.read_text())
    schema["fields"]["revenue"]["description"] = "Total revenue for the fiscal year."
    s.write_text(json.dumps(schema))
    work = cli.Work(tmp_path / "work")
    run = ["--work", str(work.path)]
    cli.main(["sample", *run, "--docs", str(d), "--candidates", str(c), "--schema", str(s),
              "--question", "field"])  # fmt: skip
    cli.main(["split", *run])
    digest = cli.prompts_sha256(work)
    cfg = work.config
    changed = {**cfg, "descriptions": {"revenue": "Revenue from sales, excluding other income."}}
    work.write("config.json", changed)
    assert cli.prompts_sha256(work) != digest
    with pytest.raises(SystemExit, match="changed after the split"):
        cli.main(["ask", *run, "--judge", "fake"])

    work.write("config.json", cfg)
    work.write("labels.json", {it["id"]: True for it in work.read("items.json")})
    monkeypatch.setitem(judges.BUILT_IN, "fake", fake({"field": {"noul": 0.9}}))
    cli.main(["ask", *run, "--judge", "fake"])
    assert work.read("answers-fake.json")["meta"]["prompts_sha256"] == digest
    work.write("config.json", changed)
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(cli.policy("field", {"judge": "fake", "model": "fake-1"}, 0.2)))
    with pytest.raises(SystemExit, match="calibrate again"):
        cli.main(["judge", "--docs", str(d), "--candidates", str(c), "--schema", str(s),
                  "--policy", str(policy), "--calibration", str(work.path),
                  "--out", str(tmp_path / "judgments")])  # fmt: skip

    # the production schema must give the field the description that was calibrated
    work.write("config.json", cfg)
    cands = json.loads((c / "doc0.json").read_text())
    (c / "doc0.json").write_text(json.dumps([{"id": f"c{i}", **x} for i, x in enumerate(cands)]))
    other = tmp_path / "other-schema.json"
    schema["fields"]["revenue"]["description"] = "Revenue from sales, excluding other income."
    other.write_text(json.dumps(schema))
    for path, ok in ((other, False), (s, True)):
        judge = ["judge", "--docs", str(d), "--candidates", str(c), "--schema", str(path),
                 "--policy", str(policy), "--calibration", str(work.path),
                 "--out", str(tmp_path / "judgments")]  # fmt: skip
        if ok:
            cli.main(judge)
        else:
            with pytest.raises(SystemExit, match="description of revenue differs"):
                cli.main(judge)
    assert (tmp_path / "judgments" / "doc0.json").exists()


def test_the_steps_from_sample_to_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d, c, s = inputs(tmp_path, 4)
    work = tmp_path / "work"
    run = ["--work", str(work)]
    cli.main(["sample", *run, "--docs", str(d), "--candidates", str(c), "--schema", str(s),
              "--question", "key"])  # fmt: skip
    items = json.loads((work / "items.json").read_text())
    assert len(items) == 4
    monkeypatch.setitem(
        judges.BUILT_IN, "fake", fake({"key": {"choice": "k1", "confidence": 0.97}})
    )
    with pytest.raises(SystemExit, match=r"split\.json"):
        cli.main(["ask", *run, "--judge", "fake"])
    cli.main(["split", *run])
    with pytest.raises(SystemExit, match="label before a judge answers"):
        cli.main(["ask", *run, "--judge", "fake"])
    labels = {it["id"]: ["fiscal 2025"] for it in items}
    (work / "labels.json").write_text(json.dumps(labels))
    cli.main(["ask", *run, "--judge", "fake"])
    with pytest.raises(SystemExit, match="already"):
        cli.main(["split", *run])
    (work / "labels.json").write_text(json.dumps({**labels, items[0]["id"]: []}))
    with pytest.raises(SystemExit, match="labels changed"):
        cli.main(["report", *run])
    (work / "labels.json").write_text(json.dumps(labels))
    split = json.loads((work / "split.json").read_text())
    moved = {k: "calibration" for k in split}
    (work / "split.json").write_text(json.dumps(moved))
    with pytest.raises(SystemExit, match="split changed"):
        cli.main(["report", *run])
    (work / "split.json").write_text(json.dumps(split, indent=1, sort_keys=True) + "\n")
    cli.main(["report", *run])
    rep = json.loads((work / "report.json").read_text())["judges"]["fake"]
    parts = json.loads((work / "split.json").read_text())
    cal = sum(v == "calibration" for v in parts.values())
    assert rep["calibration"]["by_threshold"]["0.95"]["clears_right"] == cal
    assert rep["calibration"]["by_threshold"]["0.99"]["clears_right"] == 0
    assert "Calibration report" in (work / "REPORT.md").read_text()
    cli.main(["report", *run, "--check"])


def test_field_scoring_catches_wrong_values_and_counts_right_ones_doubted() -> None:
    items = [{"id": f"d{n}:0", "doc": f"d{n}"} for n in range(4)]
    labels = {"d0:0": True, "d1:0": False, "d2:0": True, "d3:0": None}
    parts = {it["id"]: "calibration" for it in items}
    answers = {"d0:0": {"p": 0.9}, "d1:0": {"p": 0.02}, "d2:0": {"p": 0.04}, "d3:0": {"p": 0.0}}
    s = q.score("field", items, labels, parts, answers)
    cal = s["calibration"]
    assert (cal["items"], cal["right"], cal["wrong"]) == (3, 2, 1)
    assert cal["by_threshold"]["0.05"] == {
        "wrong_caught": 1,
        "right_doubted": 1,
        "right_doubted_upper_95": upper_95(1, 2),
    }
    assert s["by_ceiling"]["0.05"]["threshold"] is None


def test_a_document_without_its_candidates_stops_the_sample(tmp_path: Path) -> None:
    d, c, s = inputs(tmp_path, 2)
    (c / "doc1.json").unlink()
    with pytest.raises(SystemExit, match="write"):
        cli.main(["sample", "--work", str(tmp_path / "w"), "--docs", str(d), "--candidates",
                  str(c), "--schema", str(s), "--question", "key"])  # fmt: skip


def test_the_policy_blocks_use_the_names_of_the_design() -> None:
    meta = {"judge": "jev", "model": "jev-1.13.0"}
    assert cli.policy("key", meta, 0.9)["judge"]["clear"] == {"KEY_NOT_AT_VALUE": 0.9}
    assert cli.policy("field", meta, 0.2)["judge"]["doubt"] == {"field_match": 0.2}


def test_a_text_that_is_not_nfc_stops_the_sample(tmp_path: Path) -> None:
    d, c, s = inputs(tmp_path, 1)
    (d / "doc0.txt").write_text("Cafe\u0301 " + TEXT)
    with pytest.raises(SystemExit, match="NFC"):
        cli.main(["sample", "--work", str(tmp_path / "w"), "--docs", str(d), "--candidates",
                  str(c), "--schema", str(s), "--question", "key"])  # fmt: skip


def test_answers_to_other_prompts_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d, c, s = inputs(tmp_path, 2)
    work = tmp_path / "work"
    run = ["--work", str(work)]
    cli.main(["sample", *run, "--docs", str(d), "--candidates", str(c), "--schema", str(s),
              "--question", "key"])  # fmt: skip
    monkeypatch.setitem(judges.BUILT_IN, "fake", fake({"key": {"choice": "k1", "confidence": 0.9}}))
    cli.main(["split", *run])
    cfg = json.loads((work / "config.json").read_text())
    (work / "config.json").write_text(json.dumps({**cfg, "context": "Another context."}))
    with pytest.raises(SystemExit, match="changed after the split"):
        cli.main(["ask", *run, "--judge", "fake"])
    (work / "config.json").write_text(json.dumps(cfg))
    labels = {i["id"]: ["fiscal 2025"] for i in json.loads((work / "items.json").read_text())}
    (work / "labels.json").write_text(json.dumps(labels))
    cli.main(["ask", *run, "--judge", "fake"])
    rec = json.loads((work / "answers-fake.json").read_text())
    rec["meta"]["prompts_sha256"] = "0" * 64
    (work / "answers-fake.json").write_text(json.dumps(rec))
    with pytest.raises(SystemExit, match="other prompts"):
        cli.main(["report", *run])


def test_a_sample_with_no_items_stops(tmp_path: Path) -> None:
    d, c, s = inputs(tmp_path, 1)
    (c / "doc0.json").write_text("[]")
    with pytest.raises(SystemExit, match="nothing to label"):
        cli.main(["sample", "--work", str(tmp_path / "w"), "--docs", str(d), "--candidates",
                  str(c), "--schema", str(s), "--question", "key"])  # fmt: skip


def test_a_work_directory_of_another_spec_is_refused(tmp_path: Path) -> None:
    d, c, s = inputs(tmp_path, 2)
    work = tmp_path / "work"
    cli.main(["sample", "--work", str(work), "--docs", str(d), "--candidates", str(c),
              "--schema", str(s), "--question", "key"])  # fmt: skip
    cfg = json.loads((work / "config.json").read_text())
    (work / "config.json").write_text(json.dumps({**cfg, "spec": "0.2"}))
    with pytest.raises(SystemExit, match=r"sampled under spec 0\.2"):
        cli.main(["split", "--work", str(work)])


def test_the_label_page_draws_tab_lines_as_a_table() -> None:
    text = "Results\nRevenue\t2025\t2024\nTotal\t5,200\t4,100\nEnd.\n"
    a = text.index("4,100")
    html = label.page(text, [{"id": "d:0", "mark": [a, a + 5]}])
    assert html.count("<table") == 1 and html.count("<tr>") == 2
    assert '<td><mark data-ids="d:0">4,100</mark></td>' in html
    assert html.startswith("Results\n") and html.endswith("</table>End.\n\n")


def test_signs_join_their_numbers_in_a_table_row() -> None:
    assert label.cells("Net income\t$\t35,116\t$\t19,168\t83.2\t%") == [
        "Net income", "$ 35,116", "$ 19,168", "83.2%"
    ]  # fmt: skip
    assert label.cells("Loss\t(\t123\t)\t$\t(\t45\t)") == ["Loss", "(123)", "$ (45)"]


def test_a_mark_across_table_cells_keeps_the_run_as_text() -> None:
    text = "a\tfoo\nb\tbar\n"
    a, b = text.index("foo"), text.index("bar") + 3
    html = label.page(text, [{"id": "d:0", "mark": [a, b]}])
    assert "<table" not in html and '<mark data-ids="d:0">foo\nb\tbar</mark>' in html


def test_a_plug_in_judge_comes_from_an_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    class EP:
        def __init__(self, name: str) -> None:
            self.name = name

        def load(self) -> Any:
            return fake({})

    monkeypatch.setattr(judges, "entry_points", lambda group: [EP("fake")])
    assert judges.load("fake").digest == "fake-1"
    monkeypatch.setattr(judges, "entry_points", lambda group: [EP("mine")])
    with pytest.raises(SystemExit, match="must be equal"):
        judges.load("mine")
    with pytest.raises(SystemExit, match="no judge"):
        judges.load("other")
    monkeypatch.setattr(judges, "entry_points", lambda group: [EP("jev")])
    with pytest.raises(SystemExit, match="two judges"):
        judges.load("jev")

    class Broken(EP):
        def load(self) -> Any:
            raise ImportError("a broken plug-in")

    monkeypatch.setattr(judges, "entry_points", lambda group: [Broken("broken"), EP("fake")])
    assert judges.load("fake").id == "fake"  # the broken plug-in is never imported


def calibrated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path, Path]:
    """A key calibration of the fake judge on 2 documents, and its inputs."""
    d, c, s = inputs(tmp_path, 2)
    for n in range(2):  # judged candidates need ids
        cands = json.loads((c / f"doc{n}.json").read_text())
        (c / f"doc{n}.json").write_text(
            json.dumps([{**x, "id": f"c{i}"} for i, x in enumerate(cands)])
        )
    work = tmp_path / "work"
    run = ["--work", str(work)]
    cli.main(["sample", *run, "--docs", str(d), "--candidates", str(c), "--schema", str(s),
              "--question", "key"])  # fmt: skip
    monkeypatch.setitem(
        judges.BUILT_IN, "fake", fake({"key": {"choice": "k1", "confidence": 0.97}})
    )
    cli.main(["split", *run])
    labels = {i["id"]: ["fiscal 2025"] for i in json.loads((work / "items.json").read_text())}
    (work / "labels.json").write_text(json.dumps(labels))
    cli.main(["ask", *run, "--judge", "fake"])
    return d, c, s, work


def test_judge_writes_recorded_judgments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d, c, s, work = calibrated(tmp_path, monkeypatch)
    policy = tmp_path / "policy.json"
    block = {"id": "fake", "digest": "fake-1", "clear": {"KEY_NOT_AT_VALUE": 0.9}}
    policy.write_text(json.dumps({"judge": block}))
    out = tmp_path / "judgments"
    run = ["--docs", str(d), "--candidates", str(c), "--schema", str(s), "--policy", str(policy)]
    cli.main(["judge", *run, "--calibration", str(work), "--out", str(out)])
    js = json.loads((out / "doc0.json").read_text())
    assert js == [
        {"candidate_id": "c0", "judge": {"id": "fake", "digest": "fake-1"}, "question": "key",
         "answer": "fiscal 2025", "p": 0.97}
    ]  # fmt: skip
    # a field threshold without a field calibration is refused
    policy.write_text(json.dumps({"judge": {**block, "doubt": {"field_match": 0.2}}}))
    with pytest.raises(SystemExit, match="give its calibration"):
        cli.main(["judge", *run, "--calibration", str(work), "--out", str(out)])
    # two calibrations for one question are refused
    with pytest.raises(SystemExit, match="two calibrations"):
        cli.main(["judge", *run, "--calibration", str(work), str(work), "--out", str(out)])
    # a malformed candidate next to a judged one is left to groundgate to reject
    good = (c / "doc0.json").read_text()
    (c / "doc0.json").write_text(json.dumps([*json.loads(good), "not a candidate"]))
    policy.write_text(json.dumps({"judge": block}))
    cli.main(["judge", *run, "--calibration", str(work), "--out", str(out)])
    assert len(json.loads((out / "doc0.json").read_text())) == 1
    (c / "doc0.json").write_text(good)
    # a judged candidate with an id that a judgment cannot name is refused
    cands = json.loads(good)
    (c / "doc0.json").write_text(json.dumps([{**cands[0], "id": True}, *cands[1:]]))
    with pytest.raises(SystemExit, match="string or int id"):
        cli.main(["judge", *run, "--calibration", str(work), "--out", str(out)])
    (c / "doc0.json").write_text(good)
    # a calibration whose context changed after its run is refused
    cfg = json.loads((work / "config.json").read_text())
    (work / "config.json").write_text(json.dumps({**cfg, "context": "Another context."}))
    policy.write_text(json.dumps({"judge": block}))
    with pytest.raises(SystemExit, match="calibrate again"):
        cli.main(["judge", *run, "--calibration", str(work), "--out", str(out)])
    (work / "config.json").write_text(json.dumps(cfg))
    # another model version is refused
    policy.write_text(json.dumps({"judge": {**block, "digest": "fake-2"}}))
    with pytest.raises(SystemExit, match="fake-2"):
        cli.main(["judge", *run, "--calibration", str(work), "--out", str(out)])


@pytest.mark.skipif(SPEC_VERSION < "0.4", reason="recorded judgments are spec 0.4 (#116)")
def test_recorded_judgments_clear_the_flag_in_groundgate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import groundgate as gg

    d, c, s, work = calibrated(tmp_path, monkeypatch)
    pol = {"judge": {"id": "fake", "digest": "fake-1", "clear": {"KEY_NOT_AT_VALUE": 0.9}}}
    (tmp_path / "policy.json").write_text(json.dumps(pol))
    out = tmp_path / "judgments"
    pol_path = str(tmp_path / "policy.json")
    cli.main(["judge", "--docs", str(d), "--candidates", str(c), "--schema", str(s),
              "--policy", pol_path, "--calibration", str(work), "--out", str(out)])  # fmt: skip
    cands = json.loads((c / "doc0.json").read_text())
    js = json.loads((out / "doc0.json").read_text())
    r = gg.admit(TEXT, SCHEMA, cands, pol, judgments=js)
    (d0,) = [x for x in r.decisions if x.candidate_id == "c0"]
    assert (d0.outcome, d0.codes) == ("admitted", ("MODEL_CLEARED",))


def chat_reply(content: str | None, model: str = "model-1") -> dict[str, Any]:
    return {"model": model, "choices": [{"message": {"content": content}}]}


class ChatServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.replies: list[Any] = [chat_reply('{"choice": "k1", "confidence": 0.97}')]


@pytest.fixture
def chat_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[ChatServer]:
    fake = ChatServer()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            fake.requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "content_type": self.headers.get("Content-Type"),
                    "body": json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                }
            )
            reply = fake.replies[min(len(fake.requests) - 1, len(fake.replies) - 1)]
            body = reply if isinstance(reply, bytes) else json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        monkeypatch.setenv("GROUNDGATE_CHAT_URL", f"http://127.0.0.1:{server.server_port}/v1/")
        monkeypatch.setenv("GROUNDGATE_CHAT_MODEL", "model-1")
        monkeypatch.setenv("GROUNDGATE_CHAT_VERSION", "file-sha256")
        monkeypatch.delenv("GROUNDGATE_CHAT_KEY", raising=False)
        monkeypatch.setenv("no_proxy", "127.0.0.1")
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            yield fake
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.parametrize(
    "variable", ["GROUNDGATE_CHAT_URL", "GROUNDGATE_CHAT_MODEL", "GROUNDGATE_CHAT_VERSION"]
)
@pytest.mark.parametrize("value", [None, "", "   "])
def test_chat_names_a_missing_setting(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str | None
) -> None:
    for name in ("GROUNDGATE_CHAT_URL", "GROUNDGATE_CHAT_MODEL", "GROUNDGATE_CHAT_VERSION"):
        monkeypatch.setenv(name, "set")
    if value is None:
        monkeypatch.delenv(variable)
    else:
        monkeypatch.setenv(variable, value)
    with pytest.raises(SystemExit, match=variable):
        judges.load("chat")


@pytest.mark.parametrize("key", [None, "test-key"])
def test_chat_sends_one_request_per_question(
    chat_server: ChatServer, monkeypatch: pytest.MonkeyPatch, key: str | None
) -> None:
    if key is not None:
        monkeypatch.setenv("GROUNDGATE_CHAT_KEY", key)
    jd = judges.load("chat")
    assert (jd.id, jd.digest) == ("chat", "chat-1:model-1@file-sha256")
    questions = {
        "key": {"type": "choice", "instructions": "Which key?", "criteria": {"k1": "2025"}},
        "field": {"type": "noul", "instructions": "Is this revenue?"},
    }
    chat_server.replies = [
        chat_reply('{"choice": "k1", "confidence": 1}'),
        chat_reply('{"p": 0}'),
    ]
    assert jd.ask("Revenue: [5,200].", questions) == {
        "key": {"choice": "k1", "confidence": 1},
        "field": {"noul": 0},
    }
    assert len(chat_server.requests) == 2
    texts = [
        "Which key?\n\nText:\nRevenue: [5,200].\n\nOptions:\nk1: 2025\n\n"
        'Return {"choice": name, "confidence": p}. name is the name of one option, such as '
        '"k1", not its text. p is the probability that this option is right.',
        "Is this revenue?\n\nText:\nRevenue: [5,200].\n\n"
        'Return {"p": p}. p is the probability that the answer is yes.',
    ]
    for req, text in zip(chat_server.requests, texts, strict=True):
        assert req["path"] == "/v1/chat/completions"
        assert req["authorization"] == (f"Bearer {key}" if key else None)
        assert req["content_type"] == "application/json"
        assert req["body"] == {
            "model": "model-1",
            "temperature": 0,
            "messages": [
                {"role": "system", "content": judges.Chat.system},
                {"role": "user", "content": text},
            ],
        }


def test_chat_retries_an_invalid_answer_twice(chat_server: ChatServer) -> None:
    chat_server.replies = [
        chat_reply("not JSON"),
        chat_reply('{"choice": "unknown", "confidence": 0.9}'),
        chat_reply('{"choice": "none", "confidence": 0.75}'),
    ]
    question = {"type": "choice", "criteria": {"k1": "2025", "none": "none of these"}}
    assert judges.load("chat").ask("[5,200]", {"key": question}) == {
        "key": {"choice": "none", "confidence": 0.75}
    }
    assert len(chat_server.requests) == 3
    assert chat_server.requests[0] == chat_server.requests[1] == chat_server.requests[2]


@pytest.mark.parametrize("question_type", ["choice", "noul"])
@pytest.mark.parametrize("p", [True, False, None, "0.9", -0.01, 1.01, float("nan"), float("inf")])
def test_chat_stops_and_shows_an_invalid_probability(
    chat_server: ChatServer, question_type: str, p: Any
) -> None:
    answer = {"choice": "k1", "confidence": p} if question_type == "choice" else {"p": p}
    reply = json.dumps(answer)
    chat_server.replies = [chat_reply(reply)]
    with pytest.raises(SystemExit, match="invalid reply after 3 attempts") as exc:
        judges.load("chat").ask(
            "[5,200]", {"q": {"type": question_type, "criteria": {"k1": "2025"}}}
        )
    assert reply in str(exc.value)
    assert len(chat_server.requests) == 3


@pytest.mark.parametrize(
    "reply",
    [
        "not JSON",
        '```json\n{"p": 0.9}\n```',
        "[]",
        "null",
        "{}",
        '{"choice": "unknown", "confidence": 0.9}',
        '{"choice": ["k1"], "confidence": 0.9}',
        '{"choice": "2025", "confidence": 0.9}',
    ],
)
def test_chat_stops_and_shows_an_invalid_answer(chat_server: ChatServer, reply: str) -> None:
    chat_server.replies = [chat_reply(reply)]
    with pytest.raises(SystemExit, match="invalid reply after 3 attempts") as exc:
        judges.load("chat").ask("[5,200]", {"key": {"type": "choice", "criteria": {"k1": "2025"}}})
    assert reply in str(exc.value)
    assert len(chat_server.requests) == 3


@pytest.mark.parametrize(
    "reply",
    [b"not JSON", b"\xff", [], {"model": "model-1", "choices": []}, chat_reply(None)],
)
def test_chat_retries_a_malformed_response(chat_server: ChatServer, reply: Any) -> None:
    chat_server.replies = [reply, chat_reply('{"p": 0.25}')]
    assert judges.load("chat").ask("[5,200]", {"field": {"type": "noul"}}) == {
        "field": {"noul": 0.25}
    }
    assert len(chat_server.requests) == 2


@pytest.mark.parametrize("model", ["model-2", None])
def test_chat_refuses_another_or_missing_reported_model(
    chat_server: ChatServer, model: str | None
) -> None:
    reply = chat_reply('{"p": 0.9}')
    if model is None:
        del reply["model"]
    else:
        reply["model"] = model
    chat_server.replies = [reply]
    with pytest.raises(SystemExit, match=r"answered by.*not 'model-1'"):
        judges.load("chat").ask("[5,200]", {"field": {"type": "noul"}})
    assert len(chat_server.requests) == 1


@pytest.mark.parametrize("question", ["key", "field"])
def test_chat_calibrates_and_writes_recorded_judgments(
    tmp_path: Path, chat_server: ChatServer, monkeypatch: pytest.MonkeyPatch, question: str
) -> None:
    d, c, s = inputs(tmp_path, 2)
    for path in c.glob("*.json"):
        candidates = json.loads(path.read_text())
        path.write_text(json.dumps([{**x, "id": f"c{i}"} for i, x in enumerate(candidates)]))
    if question == "field":
        chat_server.replies = [chat_reply('{"p": 0.125}')]
    work = tmp_path / "work"
    cli.main(["sample", "--work", str(work), "--docs", str(d), "--candidates", str(c),
              "--schema", str(s), "--question", question])  # fmt: skip
    cli.main(["split", "--work", str(work)])
    items = json.loads((work / "items.json").read_text())
    labels = {it["id"]: ["fiscal 2025"] if question == "key" else True for it in items}
    (work / "labels.json").write_text(json.dumps(labels))
    cli.main(["ask", "--work", str(work), "--judge", "chat"])
    cli.main(["report", "--work", str(work)])
    cli.main(["report", "--work", str(work), "--check"])
    meta = json.loads((work / "answers-chat.json").read_text())["meta"]
    assert (meta["judge"], meta["model"]) == ("chat", "chat-1:model-1@file-sha256")
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(cli.policy(question, meta, 0.9 if question == "key" else 0.2)))
    out = tmp_path / "judgments"
    run = ["judge", "--docs", str(d), "--candidates", str(c), "--schema", str(s),
           "--policy", str(policy), "--calibration", str(work), "--out", str(out)]  # fmt: skip
    cli.main(run)
    expected: dict[str, Any] = {
        "candidate_id": "c0" if question == "key" else "c1",
        "judge": {"id": "chat", "digest": "chat-1:model-1@file-sha256"},
        "question": "key" if question == "key" else "field_match",
        "p": 0.97 if question == "key" else 0.125,
    }
    if question == "key":
        expected["answer"] = "fiscal 2025"
    assert json.loads((out / "doc0.json").read_text()) == [expected]
    # A new user version needs a new calibration, before any request is sent.
    before = len(chat_server.requests)
    monkeypatch.setenv("GROUNDGATE_CHAT_VERSION", "new-file-sha256")
    with pytest.raises(SystemExit, match="the judge is chat-1:model-1@new-file-sha256"):
        cli.main(run)
    assert len(chat_server.requests) == before
    monkeypatch.setenv("GROUNDGATE_CHAT_VERSION", "file-sha256")
    # Both commands stop on a reported model change, without retrying it.
    chat_server.requests.clear()
    chat_server.replies = [chat_reply('{"p": 0.9}', model="model-2")]
    (work / "answers-chat.json").unlink()
    for command in (["ask", "--work", str(work), "--judge", "chat"], run):
        with pytest.raises(SystemExit, match="answered by 'model-2'"):
            cli.main(command)
        assert len(chat_server.requests) == 1
        chat_server.requests.clear()
        # judge reads the calibration answers before calling the server.
        (work / "answers-chat.json").write_text(json.dumps({"meta": meta}))
