"""Calibrate labels through the review server and the answer logs (#406, #413).

The same answers go to the old label page in one work folder, and to the review page in a
second work folder with a store. The labels, and the report, must be the same.
"""

from __future__ import annotations

import http.client
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from groundgate.calibrate import cli, judges, label, stored
from groundgate.review import format_schema, serve
from groundgate.review.labels import QUESTIONS, label_task
from groundgate.review.resolve import write_resolution
from groundgate.review.serve import CSP, TOKEN_HEADER, Review
from groundgate.store import FolderStore, reviewer_key
from groundgate.store.maintain import rebuild

TEXT = "In fiscal 2024 sales fell.\nRevenue was 4,100.\nIn fiscal 2025 revenue was 5,200.\n"
SCHEMA = {
    "fields": {
        "revenue": {"type": "number", "multiple": True, "keys": ["fiscal 2025", "fiscal 2024"]}
    }
}
KEYS = ["fiscal 2025", "fiscal 2024"]

Call = Callable[..., tuple[int, dict[str, str], str]]


def evidence(s: str) -> dict[str, int]:
    i = TEXT.encode().index(s.encode())
    return {"start": i, "end": i + len(s.encode())}


def inputs(tmp: Path, docs: int) -> tuple[Path, Path, Path]:
    d, c = tmp / "docs", tmp / "cands"
    d.mkdir(parents=True)
    c.mkdir()
    for n in range(docs):
        (d / f"doc{n}.txt").write_text(TEXT)
        cands = [
            {"field": "revenue", "value": "4100", "key": "fiscal 2025",
             "evidence": evidence("Revenue was 4,100.")},
            {"field": "revenue", "value": "5200", "key": "fiscal 2025",
             "evidence": evidence("revenue was 5,200")},
        ]  # fmt: skip
        (c / f"doc{n}.json").write_text(json.dumps(cands))
    s = tmp / "schema.json"
    s.write_text(json.dumps(SCHEMA))
    return d, c, s


def sampled(tmp: Path, question: str, store: Path | None) -> Path:
    d, c, s = inputs(tmp / "in", 4) if not (tmp / "in").exists() else (
        tmp / "in" / "docs", tmp / "in" / "cands", tmp / "in" / "schema.json"
    )  # fmt: skip
    work = tmp / ("stored" if store else "old")
    more = [] if store is None else ["--store", str(store)]
    cli.main(["sample", "--work", str(work), "--docs", str(d), "--candidates", str(c),
              "--schema", str(s), "--question", question, *more])  # fmt: skip
    cli.main(["split", "--work", str(work)])
    return work


@contextmanager
def running(httpd: Any, url: str) -> Iterator[Call]:
    """A server on a free port. call(method, path, body, host, token) sends one request with
    the right Host and token unless the arguments give others."""
    port, token = httpd.server_port, url.split("#", 1)[1]
    thread = Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()

    def call(
        method: str,
        path: str,
        body: Any = None,
        host: str | None = f"127.0.0.1:{port}",
        token: str | None = token,
    ) -> tuple[int, dict[str, str], str]:
        sent = {} if token is None else {TOKEN_HEADER: token}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            sent |= {"Content-Type": "application/json", "Content-Length": str(len(data))}
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            if host is not None:
                conn.putheader("Host", host)
            for k, v in sent.items():
                conn.putheader(k, v)
            conn.endheaders(data)
            r = conn.getresponse()
            return r.status, dict(r.getheaders()), r.read().decode()
        finally:
            conn.close()

    try:
        yield call
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def answer(task: str, verdict: str, **more: Any) -> dict[str, Any]:
    return {"task": task, "verdict": verdict, "decision": None, "codes_kept": [],
            "reason_seen": False, "keys": 1, "ms": 700, **more}  # fmt: skip


def body(label_value: Any) -> dict[str, Any]:
    """The review page answer for a label of the old page."""
    if label_value is None:
        return {"verdict": "unsure"}
    if isinstance(label_value, list):
        return {"verdict": "confirm", "field_keys": label_value}
    return {"verdict": "confirm" if label_value else "wrong"}


def label_both(old: Path, new: Path, store: Path, given: dict[str, Any]) -> None:
    """Give each label to the old page of ``old`` and to the review page of ``new``."""
    httpd, url = label.server(cli.Work(old), 0)
    with running(httpd, url) as call:
        for iid, value in given.items():
            assert call("POST", "/label", {"id": iid, "value": value})[0] == 200
    tasks = json.loads((new / "tasks.json").read_text())
    with FolderStore(store) as s:
        review = Review(s, "ana", only={t["task"] for t in tasks.values()})
        httpd, url = serve.server(review, 0)
        with running(httpd, url) as call:
            for iid, value in given.items():
                status, _, text = call("POST", "/api/answer",
                                       answer(tasks[iid]["task"], **body(value)))  # fmt: skip
                assert status == 200, text


def fake(answers: dict[str, dict[str, Any]]) -> Any:
    class Fake:
        id = "fake"
        digest = "fake-1"

        def ask(self, state: str, qs: dict[str, Any]) -> dict[str, Any]:
            return {k: answers[k] for k in qs}

    return Fake


@pytest.mark.parametrize(
    ("question", "values", "judge"),
    [
        ("key", [["fiscal 2024", "fiscal 2025"], [], None, ["fiscal 2025"]],
         {"key": {"choice": "k1", "confidence": 0.97}}),
        ("field", [True, False, None, True], {"field": {"noul": 0.2}}),
    ],
)  # fmt: skip
def test_the_answer_logs_give_the_labels_and_the_report_of_the_old_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    values: list[Any],
    judge: dict[str, Any],
) -> None:
    store = tmp_path / "store"
    old, new = sampled(tmp_path, question, None), sampled(tmp_path, question, store)
    items = json.loads((old / "items.json").read_text())
    assert items == json.loads((new / "items.json").read_text())
    assert not (old / "tasks.json").exists()
    given = {it["id"]: v for it, v in zip(items, values, strict=True)}
    label_both(old, new, store, given)
    assert not (new / "labels.json").exists()
    # the view of the answer logs equals the file of the old page, byte for byte
    found, _ = cli.stored_labels(cli.Work(new), store, "ana")
    expected = {
        k: sorted(v, key=KEYS.index) if isinstance(v, list) else v for k, v in given.items()
    }
    assert found == expected
    assert stored.dump(found) == (old / "labels.json").read_text()
    # the same report from the work folder and from the answer logs
    monkeypatch.setitem(judges.BUILT_IN, "fake", fake(judge))
    cli.main(["ask", "--work", str(old), "--judge", "fake"])
    with pytest.raises(SystemExit, match="--store and --reviewer"):
        cli.main(["ask", "--work", str(new), "--judge", "fake", "--store", str(store)])
    cli.main(["ask", "--work", str(new), "--judge", "fake", "--store", str(store),
              "--reviewer", "ana"])  # fmt: skip
    with pytest.raises(SystemExit, match="give --store"):
        cli.main(["report", "--work", str(new)])
    cli.main(["report", "--work", str(old)])
    cli.main(["report", "--work", str(new), "--store", str(store)])
    assert (new / "REPORT.md").read_text() == (old / "REPORT.md").read_text()
    a = json.loads((old / "report.json").read_text())["judges"]["fake"]
    b = json.loads((new / "report.json").read_text())["judges"]["fake"]
    assert set(b["meta"].pop("labels_from")) == {"reviewer", "heads"}
    assert a == b
    # an answer after ask does not change the labels that the judge was scored on
    tasks = json.loads((new / "tasks.json").read_text())
    first = items[0]["id"]
    with FolderStore(store) as s:
        Review(s, "ana").answer(answer(tasks[first]["task"], "unsure"))
    cli.main(["report", "--work", str(new), "--store", str(store), "--check"])
    assert cli.stored_labels(cli.Work(new), store, "ana")[0][first] is None
    # the labels are frozen: no label page after a judge run, and no judge on the moved logs
    with pytest.raises(SystemExit, match="labels are frozen"):
        cli.main(["label", "--work", str(new), "--store", str(store), "--reviewer", "ana"])
    monkeypatch.setitem(judges.BUILT_IN, "fake2", fake(judge))
    with pytest.raises(SystemExit, match=r"answers-fake\.json has its labels from another source"):
        cli.main(["ask", "--work", str(new), "--judge", "fake2", "--store", str(store),
                  "--reviewer", "ana"])  # fmt: skip
    assert not list(new.glob("*answers-fake2*"))


def test_a_partial_judge_run_freezes_the_labels(tmp_path: Path) -> None:
    store = tmp_path / "store"
    work = sampled(tmp_path, "field", store)
    (work / ".answers-fake.partial.json").write_text('{"meta": {}, "answers": {}}')
    with pytest.raises(SystemExit, match="labels are frozen"):
        cli.main(["label", "--work", str(work), "--store", str(store), "--reviewer", "ana"])


def test_the_review_page_asks_a_blind_calibrate_question(tmp_path: Path) -> None:
    store = tmp_path / "store"
    work = sampled(tmp_path, "key", store)
    tasks = json.loads((work / "tasks.json").read_text())
    tk = next(iter(tasks.values()))["task"]
    with FolderStore(store) as s:
        task = json.loads(s.get("task@1", tk))
        assert QUESTIONS[task["template"]] == "key"
        assert task["mode"] == "audit" and task["codes"] == [] and task["choices"] == []
        review = Review(s, "ana", only={tk})
        view = review.view(tk)
        # the page gets the keys of the field, and no key of the candidate and no gate output
        assert view["label"] == {"question": "key", "keys": KEYS}
        assert view["definition"] is None
        assert view["question"] == (
            "Which keys of the revenue does the marked value give? It can give none."
        )
        assert "KEY_NOT_AT_VALUE" not in json.dumps(view) and "slot" not in view
        assert review.reason(tk) == {"codes": [], "choices": []}
        assert [t["task"] for t in review.queue()["tasks"]] == [tk]


def test_the_security_rules_hold_for_calibrate_tasks(tmp_path: Path) -> None:
    store = tmp_path / "store"
    key_work = sampled(tmp_path, "key", store)
    field_work = sampled(tmp_path / "f", "field", store)
    key_task = next(iter(json.loads((key_work / "tasks.json").read_text()).values()))
    field_task = next(iter(json.loads((field_work / "tasks.json").read_text()).values()))
    kt, ft = key_task["task"], field_task["task"]
    with FolderStore(store) as s:
        review = Review(s, "ana")
        httpd, url = serve.server(review, 0)
        with running(httpd, url) as call:
            port = httpd.server_port
            refused = [
                (call("GET", f"/api/task/{kt}", host="localhost"), 421),
                (call("GET", f"/api/task/{kt}", token=None), 403),
                (call("POST", "/api/answer", answer(kt, "unsure"), host=f"evil:{port}"), 421),
                (call("POST", "/api/answer", answer(kt, "unsure"), token="x" * 43), 403),
                # rule 8: an answer that a calibrate task does not permit
                (call("POST", "/api/answer", answer(kt, "wrong")), 400),
                (call("POST", "/api/answer", answer(kt, "confirm")), 400),
                (call("POST", "/api/answer", answer(kt, "confirm", field_keys=["fiscal 2023"])),
                 400),
                (call("POST", "/api/answer", answer(kt, "confirm", field_keys=KEYS[:1] * 2)), 400),
                (call("POST", "/api/answer", answer(kt, "confirm", field_keys="fiscal 2025")), 400),
                (call("POST", "/api/answer", answer(kt, "unsure", field_keys=[])), 400),
                (call("POST", "/api/answer", answer(ft, "confirm", field_keys=[])), 400),
                (call("POST", "/api/answer", answer(ft, "choose", decision=1)), 400),
                (call("POST", "/api/answer", answer(ft, "not_in_document")), 400),
                (call("POST", "/api/answer", answer(ft, "correct", start=27, end=45)), 400),
                (call("POST", "/api/check", {"task": ft, "verdict": "correct", "start": 27,
                                             "end": 45}), 400),
            ]  # fmt: skip
            for (status, headers, text), want in refused:
                assert status == want, text
                assert headers["Content-Security-Policy"] == CSP
            assert call("POST", "/api/answer", answer(ft, "wrong"))[0] == 200
            assert call("POST", "/api/answer", answer(kt, "confirm", field_keys=[]))[0] == 200
    with FolderStore(store) as s:
        # the two work folders have the same documents, so their items share each packet
        assert field_task["packet"] == key_task["packet"]
        records = s.read(("answers", field_task["packet"], reviewer_key("ana")))
        assert [(r["format"], r["verdict"], r["field_keys"]) for r in records] == [
            ("answer@2", "wrong", None),
            ("answer@2", "confirm", []),
        ]
        # a calibrate label is not a review answer: the resolution reads it and names no task
        resolved = write_resolution(s, field_task["packet"], None, ["ana"])
        assert resolved.resolution is not None
        assert not {x["task"] for x in resolved.resolution["slots"]} & {kt, ft}
        assert rebuild(s)[1] == "views/calibrate-labels.json"
    view = json.loads((store / "views" / "calibrate-labels.json").read_text())
    assert view == {
        "format": "calibrate-labels@1",
        "labels": sorted(
            [{"task": ft, "reviewer": "ana", "label": False},
             {"task": kt, "reviewer": "ana", "label": []}],
            key=lambda row: row["task"],
        ),
    }  # fmt: skip


def test_wrong_on_a_review_task_leaves_the_slot_open(tmp_path: Path) -> None:
    case = json.loads((Path(__file__).parent / "review" / "cases" / "conflict.json").read_text())
    p = case["packet"]
    from groundgate.review.tasks import write_tasks
    from groundgate.store.packets import admit_packet

    every = {"format": "review-policy@1", "audit": {"rate": "1", "seed": "s"}, "agree": 1,
             "leads": [], "rejected": True}  # fmt: skip
    with FolderStore(tmp_path / "store") as s:
        k, _ = admit_packet(s, p["text"], p["schema"], p["candidates"], p["policy"], None,
                            p["judgments"])  # fmt: skip
        tasks = {t["slot"]["field"]: tk for tk, t in write_tasks(s, k, every).tasks}
        Review(s, "ana").answer(answer(tasks["net_income"], "wrong"))
        (record,) = s.read(("answers", k, reviewer_key("ana")))
        assert record["format"] == "answer@2" and record["field_keys"] is None
        resolved = write_resolution(s, k, every, ["ana"])
    assert resolved.resolution is not None
    statuses = {x["field"]: x["status"] for x in resolved.resolution["slots"]}
    assert statuses["net_income"] == "open"


def test_a_label_task_needs_a_value_in_the_document() -> None:
    from groundgate.model import PacketError, Schema

    receipt = {"decisions": [{"field": "revenue", "value": None, "evidence": None}]}
    with pytest.raises(PacketError, match="no value"):
        label_task("sha256:" + "0" * 64, receipt, TEXT, Schema.from_dict(SCHEMA), 0, "field")
    with pytest.raises(ValueError, match="not a calibrate question"):
        label_task("sha256:" + "0" * 64, receipt, TEXT, Schema.from_dict(SCHEMA), 0, "other")


def test_a_label_task_is_only_for_a_decision_that_the_sample_takes(tmp_path: Path) -> None:
    import groundgate as gg
    from groundgate.model import PacketError, Schema
    from groundgate.review.labels import label_tasks
    from groundgate.store.packets import admit_packet

    _, c, _ = inputs(tmp_path / "in", 1)
    cands = json.loads((c / "doc0.json").read_text())
    receipt = gg.admit(TEXT, SCHEMA, cands, None).to_dict()
    # decision 0 is flagged KEY_NOT_AT_VALUE, decision 1 is admitted with a key and no flag
    assert [(d["outcome"], d["codes"]) for d in receipt["decisions"]] == [
        ("needs_verification", ["KEY_NOT_AT_VALUE"]), ("admitted", []),
    ]  # fmt: skip
    schema, pk = Schema.from_dict(SCHEMA), "sha256:" + "0" * 64
    with pytest.raises(PacketError, match="not a key item"):
        label_task(pk, receipt, TEXT, schema, 1, "key")
    with pytest.raises(PacketError, match="not a field item"):
        label_task(pk, receipt, TEXT, schema, 0, "field")
    with FolderStore(tmp_path / "store") as s:
        k, _ = admit_packet(s, TEXT, SCHEMA, cands, None, "doc0")
        given = gg.admit(TEXT, SCHEMA, cands, None).to_dict()
        # the tasks that the old code made for the two decisions: the task text does not hold
        # the outcome or the codes, so a receipt that passes the predicate gives the same task
        loose = json.loads(json.dumps(given))
        for d in loose["decisions"]:
            d["outcome"], d["codes"] = "admitted", ["KEY_NOT_AT_VALUE"]
        made = {(q, i): label_task(k, loose, TEXT, schema, i, q) for q in QUESTIONS.values()
                for i in (0, 1)}  # fmt: skip
        from groundgate.canonical import jcs
        from groundgate.store import key as store_key

        handmade = {store_key("task@1", jcs(made[q]).encode()) for q in (("key", 1), ("field", 0))}
        for t in made.values():
            s.put("task@1", jcs(t).encode())
        assert set(label_tasks(k, given, TEXT, schema)) == {
            store_key("task@1", jcs(made[q]).encode()) for q in (("key", 0), ("field", 1))
        }
        review = Review(s, "ana")
        httpd, url = serve.server(review, 0)
        with running(httpd, url) as call:
            for tk in handmade:
                assert call("GET", f"/api/task/{tk}")[0] == 404
                assert call("POST", "/api/answer", answer(tk, "unsure"))[0] == 404
            good = store_key("task@1", jcs(made["field", 1]).encode())
            assert call("POST", "/api/answer", answer(good, "unsure"))[0] == 200
        (record,) = s.read(("answers", k, reviewer_key("ana")))
        chain = {"sequence", "previous", "entry_sha256"}
        for tk in sorted(handmade):
            bad = {m: v for m, v in record.items() if m not in chain} | {"task": tk}
            s.append(("answers", k, reviewer_key("ana")), bad)
        from groundgate.review.resolve import AnswerError

        with pytest.raises(AnswerError, match="not a task of a slot of this packet"):
            write_resolution(s, k, None, ["ana"])


def test_a_stored_task_asks_with_the_description_of_the_field(tmp_path: Path) -> None:
    d, c, s = inputs(tmp_path / "in", 1)
    described = {
        "fields": {
            "revenue": {**SCHEMA["fields"]["revenue"], "description": "the total sales of the year"}
        }
    }
    s.write_text(json.dumps(described))
    over = tmp_path / "over.json"
    over.write_text(json.dumps({"revenue": "the net sales of the fiscal year"}))
    asked = {}
    for name, more in (("schema", []), ("override", ["--descriptions", str(over)])):
        store, work = tmp_path / f"store-{name}", tmp_path / f"work-{name}"
        for question in ("field", "key"):
            cli.main(["sample", "--work", str(work / question), "--docs", str(d),
                      "--candidates", str(c), "--schema", str(s), "--question", question,
                      "--store", str(store), *more])  # fmt: skip
            (item,) = json.loads((work / question / "tasks.json").read_text()).values()
            with FolderStore(store) as st:
                asked[name, question] = json.loads(st.get("task@1", item["task"]))["question"]
    shown = "5,200 with no unit (written 5,200, not scaled, positive)"
    start = f"Is {shown} the revenue? The field means: "
    assert asked == {
        ("schema", "field"): start + "the total sales of the year",
        ("schema", "key"): "Which keys of the revenue does the marked value give? It can give "
        "none. The field means: the total sales of the year",
        ("override", "field"): start + "the net sales of the fiscal year",
        ("override", "key"): "Which keys of the revenue does the marked value give? It can give "
        "none. The field means: the net sales of the fiscal year",
    }


def test_answer_2_adds_wrong_and_field_keys_to_answer_1() -> None:
    one, two = format_schema("answer@1"), format_schema("answer@2")
    assert set(two["required"]) - set(one["required"]) == {"field_keys"}
    assert set(two["properties"]["verdict"]["enum"]) - set(
        one["properties"]["verdict"]["enum"]
    ) == {"wrong"}


def test_the_splits_log_comes_before_any_answer_to_an_item(tmp_path: Path) -> None:
    d, c, s = inputs(tmp_path / "in", 2)
    store, work = tmp_path / "store", tmp_path / "w"
    cli.main(["sample", "--work", str(work), "--docs", str(d), "--candidates", str(c),
              "--schema", str(s), "--question", "field", "--store", str(store)])  # fmt: skip
    tk = next(iter(json.loads((work / "tasks.json").read_text()).values()))["task"]
    with FolderStore(store) as fs:
        Review(fs, "ana").answer(answer(tk, "confirm"))
    with pytest.raises(SystemExit, match="splits log comes first"):
        cli.main(["split", "--work", str(work), "--store", str(store), "--set", "a"])
    assert not (work / "split.json").exists()


def test_a_review_answer_to_the_packet_does_not_stop_the_split(tmp_path: Path) -> None:
    from groundgate.review.tasks import write_tasks

    d, c, s = inputs(tmp_path / "in", 2)
    store, work = tmp_path / "store", tmp_path / "w"
    cli.main(["sample", "--work", str(work), "--docs", str(d), "--candidates", str(c),
              "--schema", str(s), "--question", "field", "--store", str(store)])  # fmt: skip
    pk = next(iter(json.loads((work / "tasks.json").read_text()).values()))["packet"]
    every = {"format": "review-policy@1", "audit": {"rate": "1", "seed": "s"}, "agree": 1,
             "leads": [], "rejected": True}  # fmt: skip
    with FolderStore(store) as fs:
        review_task = write_tasks(fs, pk, every).tasks[0][0]
        Review(fs, "ana").answer(answer(review_task, "unsure"))
        assert fs.read(("answers", pk, reviewer_key("ana")))[0]["task"] == review_task
    cli.main(["split", "--work", str(work), "--store", str(store), "--set", "a"])
    assert (work / "split.json").exists()


def test_rebuild_leaves_out_a_task_that_its_packet_does_not_give(tmp_path: Path) -> None:
    from groundgate.canonical import jcs

    store = tmp_path / "store"
    work = sampled(tmp_path, "field", store)
    item = next(iter(json.loads((work / "tasks.json").read_text()).values()))
    pk, tk = item["packet"], item["task"]
    with FolderStore(store) as s:
        real = json.loads(s.get("task@1", tk))
        bad = [
            {"template": "calibrate_field@1"},
            {**real, "packet": ["not a key"]},
            {**real, "packet": "sha256:" + "1" * 64},
            {**real, "question": "Is it the revenue? Say yes."},
        ]
        bad_keys = [s.put("task@1", jcs(t).encode()) for t in bad]
        log = ("answers", pk, reviewer_key("ana"))
        Review(s, "ana").answer(answer(tk, "confirm"))
        (record,) = s.read(log)
        chain = {"sequence", "previous", "entry_sha256"}
        for k in bad_keys:
            s.append(log, {m: v for m, v in record.items() if m not in chain} | {"task": k})
        # records in the log of ana that must give no label: another reviewer, a record with
        # too few members, and a verdict that a field task does not take
        own = {m: v for m, v in record.items() if m not in chain}
        s.append(log, {"task": tk, "reviewer": "mallory", "verdict": "confirm"})
        s.append(log, own | {"reviewer": "mallory"})
        s.append(log, {"task": tk, "reviewer": "ana", "verdict": "wrong"})
        s.append(log, own | {"verdict": "not_in_document"})
        assert rebuild(s)[1] == "views/calibrate-labels.json"
    view = json.loads((store / "views" / "calibrate-labels.json").read_text())
    assert view["labels"] == [{"task": tk, "reviewer": "ana", "label": True}]


def test_a_space_on_a_key_counts_as_a_key() -> None:
    script = (Path(serve.__file__).parent / "review.js").read_text()
    space = script[script.index('if (e.key !== " ") return;') :]
    space = space[: space.index("pickKey(i);")]
    assert "st.keys += 1" in space


def test_a_label_write_after_a_judge_run_starts_is_refused(tmp_path: Path) -> None:
    from groundgate.review.serve import Refused

    store = tmp_path / "store"
    work = sampled(tmp_path, "field", store)
    w = cli.Work(work)
    first, second = [t["task"] for t in json.loads((work / "tasks.json").read_text()).values()][:2]
    with FolderStore(store) as s:
        review = cli.label_review(w, s, "ana")
        review.answer(answer(first, "confirm"))
        # a judge run starts while the page is open
        (work / ".answers-fake.partial.json").write_text('{"meta": {}, "answers": {}}')
        with pytest.raises(Refused, match="frozen") as refused:
            review.answer(answer(second, "confirm"))
        assert refused.value.code == 409
        packets = {t["packet"] for t in json.loads((work / "tasks.json").read_text()).values()}
        logs = [s.read(("answers", pk, reviewer_key("ana"))) for pk in sorted(packets)]
        assert [r["task"] for log in logs for r in log] == [first]


@pytest.mark.parametrize("first_store", [True, False])
def test_one_folder_never_mixes_label_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first_store: bool
) -> None:
    store = tmp_path / "store"
    work = sampled(tmp_path, "field", store)
    items = json.loads((work / "items.json").read_text())
    tasks = json.loads((work / "tasks.json").read_text())
    with FolderStore(store) as s:
        for it in items:
            Review(s, "ana").answer(answer(tasks[it["id"]]["task"], "confirm"))
    (work / "labels.json").write_text(json.dumps({it["id"]: True for it in items}))
    monkeypatch.setitem(judges.BUILT_IN, "fake", fake({"field": {"noul": 0.2}}))
    monkeypatch.setitem(judges.BUILT_IN, "fake2", fake({"field": {"noul": 0.2}}))
    with_store = ["--store", str(store), "--reviewer", "ana"]
    first, then = (with_store, []) if first_store else ([], with_store)
    cli.main(["ask", "--work", str(work), "--judge", "fake", *first])
    with pytest.raises(SystemExit, match="labels from another source"):
        cli.main(["ask", "--work", str(work), "--judge", "fake2", *then])
    assert not list(work.glob("*answers-fake2*"))


def test_ask_freezes_the_labels_before_its_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from groundgate.review.serve import Refused

    store = tmp_path / "store"
    work = sampled(tmp_path, "field", store)
    w, partial = cli.Work(work), work / ".answers-fake.partial.json"
    items = json.loads((work / "items.json").read_text())
    tasks = json.loads((work / "tasks.json").read_text())
    with FolderStore(store) as s:
        for it in items[1:]:
            Review(s, "ana").answer(answer(tasks[it["id"]]["task"], "confirm"))
    monkeypatch.setitem(judges.BUILT_IN, "fake", fake({"field": {"noul": 0.2}}))
    ask = [
        "ask",
        "--work",
        str(work),
        "--judge",
        "fake",
        "--store",
        str(store),
        "--reviewer",
        "ana",
    ]
    # an ask that stops before the first judge call opens the labels again
    with pytest.raises(SystemExit, match="not labeled yet"):
        cli.main(ask)
    assert not partial.exists()
    with FolderStore(store) as s:
        Review(s, "ana").answer(answer(tasks[items[0]["id"]]["task"], "confirm"))
    snapshot, seen, late = cli.stored_labels, [], []

    def write_late() -> None:
        with FolderStore(store) as s:
            try:
                cli.label_review(w, s, "ana").answer(
                    answer(tasks[items[0]["id"]]["task"], "unsure")
                )
            except Refused as exc:
                late.append(exc.code)

    def frozen_snapshot(*a: Any, **k: Any) -> Any:
        # the marker is there before the snapshot, and ask holds the labels lock: a label write
        # now waits for the lock, and then the freeze refuses it
        assert partial.exists()
        writer = threading.Thread(target=write_late)
        writer.start()
        writer.join(0.3)
        assert writer.is_alive()
        threads.append(writer)
        return snapshot(*a, **k)

    threads: list[threading.Thread] = []

    class Judge(fake({"field": {"noul": 0.2}})):  # type: ignore[misc]
        def ask(self, state: str, qs: dict[str, Any]) -> dict[str, Any]:
            # the marker holds the meta of the run before the first judge call
            seen.append(json.loads(partial.read_text())["meta"].get("labels_from"))
            return super().ask(state, qs)

    monkeypatch.setattr(cli, "stored_labels", frozen_snapshot)
    monkeypatch.setitem(judges.BUILT_IN, "fake", Judge)
    cli.main(ask)
    assert seen and all(x is not None and x["reviewer"] == "ana" for x in seen)
    assert not partial.exists() and (work / "answers-fake.json").exists()
    assert cli.stored_labels is frozen_snapshot
    (writer,) = threads
    writer.join(10)
    assert late == [409]
    labels, _ = snapshot(w, store, "ana")
    assert set(labels.values()) == {True}


def test_a_deep_task_object_is_left_out(tmp_path: Path) -> None:
    from groundgate.store import key as store_key

    store = tmp_path / "store"
    work = sampled(tmp_path, "field", store)
    item = next(iter(json.loads((work / "tasks.json").read_text()).values()))
    depth = 200_000  # 400 KB, far under the byte limit of the store
    data = b'{"template":"calibrate_field@1","packet":' + b"[" * depth + b"]" * depth + b"}"
    k = store_key("task@1", data)
    folder = store / "objects" / k[7:9]
    folder.mkdir(exist_ok=True)
    (folder / k[9:]).write_bytes(data)  # put refuses it, so a local writer puts it in place
    with FolderStore(store) as s:
        Review(s, "ana").answer(answer(item["task"], "confirm"))
        s.append(("answers", item["packet"], reviewer_key("ana")),
                 {**{m: v for m, v in s.read(("answers", item["packet"],
                     reviewer_key("ana")))[0].items()
                     if m not in {"sequence", "previous", "entry_sha256"}}, "task": k})  # fmt: skip
        assert rebuild(s)[1] == "views/calibrate-labels.json"
        assert k not in {t["task"] for t in Review(s, "ana").queue()["tasks"]}
    view = json.loads((store / "views" / "calibrate-labels.json").read_text())
    assert view["labels"] == [{"task": item["task"], "reviewer": "ana", "label": True}]


def test_ask_waits_for_a_label_write_that_holds_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading
    import time

    store = tmp_path / "store"
    work = sampled(tmp_path, "field", store)
    w = cli.Work(work)
    items = json.loads((work / "items.json").read_text())
    tasks = json.loads((work / "tasks.json").read_text())
    with FolderStore(store) as s:
        for it in items:
            Review(s, "ana").answer(answer(tasks[it["id"]]["task"], "confirm"))
    checked = threading.Event()
    real = cli.judged

    def slow(x: Any) -> bool:
        # the first writer passes the freeze check, then waits inside the lock
        frozen = real(x)
        if threading.current_thread() is not threading.main_thread():
            checked.set()
            time.sleep(0.5)
        return frozen

    monkeypatch.setattr(cli, "judged", slow)
    monkeypatch.setitem(judges.BUILT_IN, "fake", fake({"field": {"noul": 0.2}}))
    first = tasks[items[0]["id"]]
    results: list[Any] = []

    def write() -> None:
        with FolderStore(store) as s:
            results.append(cli.label_review(w, s, "ana").answer(answer(first["task"], "unsure")))

    writer = threading.Thread(target=write)
    writer.start()
    assert checked.wait(10)
    # the second writer: ask takes the lock only after the label write ends
    cli.main(["ask", "--work", str(work), "--judge", "fake", "--store", str(store),
              "--reviewer", "ana"])  # fmt: skip
    writer.join(10)
    assert results  # the write was in time, so it is a label of the snapshot
    with FolderStore(store) as s:
        last = s.read(("answers", first["packet"], reviewer_key("ana")))[-1]
    meta = json.loads((work / "answers-fake.json").read_text())["meta"]
    assert last["verdict"] == "unsure"
    assert meta["labels_from"]["heads"][first["packet"]] == last["entry_sha256"]
    # after the run, a label write is refused
    with FolderStore(store) as s, pytest.raises(Exception, match="frozen"):
        cli.label_review(w, s, "ana").answer(answer(first["task"], "confirm"))


def test_a_reviewer_name_with_no_utf8_is_left_out(tmp_path: Path) -> None:
    store = tmp_path / "store"
    work = sampled(tmp_path, "field", store)
    item = next(iter(json.loads((work / "tasks.json").read_text()).values()))
    log = ("answers", item["packet"], reviewer_key("ana"))
    with FolderStore(store) as s:
        Review(s, "ana").answer(answer(item["task"], "confirm"))
        (record,) = s.read(log)
        own = {m: v for m, v in record.items() if m not in {"sequence", "previous", "entry_sha256"}}
        s.append(log, own | {"reviewer": "\ud800", "verdict": "wrong"})
        assert rebuild(s)[1] == "views/calibrate-labels.json"
    view = json.loads((store / "views" / "calibrate-labels.json").read_text())
    assert view["labels"] == [{"task": item["task"], "reviewer": "ana", "label": True}]
    # the command line refuses such a name before it reads a log
    for cmd in ("label", "ask"):
        more = ["--judge", "fake"] if cmd == "ask" else []
        with pytest.raises(SystemExit, match="valid Unicode"):
            cli.main([cmd, "--work", str(work), *more, "--store", str(store),
                      "--reviewer", "\ud800"])  # fmt: skip
