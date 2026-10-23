"""`groundgate review serve` (docs/design/review.md §8, §9).

Each test of §9 sends a request that the server must refuse, and checks that the answer log
stays empty. Each response must have the CSP of §9 rule 4, and the frame of an HTML source the
CSP of rule 6.
"""

from __future__ import annotations

import http.client
import importlib.util
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from groundgate.cli import main
from groundgate.review import serve
from groundgate.review.resolve import write_resolution
from groundgate.review.serve import CSP, MAX_BODY, TOKEN_HEADER, Refused, Review, _Units, frame_csp
from groundgate.review.tasks import write_tasks
from groundgate.store import FolderStore, reviewer_key
from groundgate.store.packets import admit_packet, put_reading

HERE = Path(__file__).parent
PACKET = json.loads((HERE / "cases" / "conflict.json").read_text("utf-8"))["packet"]
EVERY = {
    "format": "review-policy@1",
    "audit": {"rate": "1", "seed": "s"},
    "agree": 1,
    "leads": [],
    "rejected": True,
}
CLOCK = datetime(2026, 10, 21, 9, 30, tzinfo=timezone.utc)

Response = tuple[int, dict[str, str], str]
Call = Callable[..., Response]


def store_with_tasks(root: Path) -> tuple[FolderStore, str, dict[str, str]]:
    """A store with the conflict packet and its tasks: the revenue task has two choices, and
    the net income task is an audit task with one choice."""
    store = FolderStore(root)
    k, _ = admit_packet(
        store, PACKET["text"], PACKET["schema"], PACKET["candidates"], PACKET["policy"],
        None, PACKET["judgments"],
    )  # fmt: skip
    tasks = {t["slot"]["field"]: tk for tk, t in write_tasks(store, k, EVERY).tasks}
    return store, k, tasks


@contextmanager
def running(review: Review) -> Iterator[tuple[Call, list[Response], int]]:
    """The review server on a free port, its port and the list of its responses.
    call(method, path, body, headers, host, token) sends one request with the right Host and
    token unless the arguments give others."""
    httpd, url = serve.server(review, 0)
    port, token = httpd.server_port, url.split("#", 1)[1]
    assert url == f"http://127.0.0.1:{port}/#{token}" and len(token) >= 32
    assert httpd.server_address[0] == "127.0.0.1"
    thread = Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    seen: list[Response] = []

    def call(
        method: str,
        path: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
        host: str | None = f"127.0.0.1:{port}",
        token: str | None = token,
    ) -> Response:
        """A dict or a list body goes as JSON; bytes go as they are."""
        sent = {} if token is None else {TOKEN_HEADER: token}
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            sent["Content-Type"] = "application/json"
        sent.update(headers or {})
        if body is not None:
            sent.setdefault("Content-Length", str(len(body)))
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            if host is not None:
                conn.putheader("Host", host)
            for k, v in sent.items():
                conn.putheader(k, v)
            conn.endheaders(body)
            r = conn.getresponse()
            out = (r.status, dict(r.getheaders()), r.read().decode())
        finally:
            conn.close()
        seen.append(out)
        return out

    try:
        yield call, seen, port
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def answer(task: str, verdict: str, **more: Any) -> dict[str, Any]:
    return {"task": task, "verdict": verdict, "decision": None, "codes_kept": [],
            "reason_seen": False, "keys": 1, "ms": 900, **more}  # fmt: skip


def log(store: FolderStore, k: str, name: str = "ana") -> list[dict[str, Any]]:
    return store.read(("answers", k, reviewer_key(name)))


@pytest.fixture
def served(
    tmp_path: Path,
) -> Iterator[tuple[FolderStore, str, dict[str, str], Call, list[Response]]]:
    store, k, tasks = store_with_tasks(tmp_path / "store")
    with store, running(Review(store, "ana", clock=lambda: CLOCK)) as (call, seen, _):
        yield store, k, tasks, call, seen


Served = tuple[FolderStore, str, dict[str, str], Call, list[Response]]


# §9: each request that the server refuses


def test_the_server_refuses_each_request_of_section_9(served: Served) -> None:
    store, k, tasks, call, seen = served
    good = answer(tasks["revenue"], "choose", decision=0)
    refused = [
        # rule 1: a bad Host, and no Host
        (call("GET", "/", host="localhost:80"), 421),
        (call("GET", "/api/queue", host="evil.example"), 421),
        (call("POST", "/api/answer", good, host="127.0.0.1"), 421),
        (call("GET", "/api/queue", host=None), 421),
        # rule 2: no token, and a wrong token
        (call("GET", "/api/queue", token=None), 403),
        (call("GET", f"/api/task/{tasks['revenue']}", token="x" * 43), 403),
        (call("POST", "/api/answer", good, token=None), 403),
        # rule 3: a bad content type, no length, and a body over 64 KiB
        (
            call("POST", "/api/answer", json.dumps(good).encode(), {"Content-Type": "text/plain"}),
            415,
        ),
        (
            call(
                "POST",
                "/api/answer",
                json.dumps(good).encode(),
                {"Content-Type": "application/x-www-form-urlencoded"},
            ),
            415,
        ),
        (
            call(
                "POST",
                "/api/answer",
                b"{}",
                {"Content-Type": "application/json", "Content-Length": "+2"},
            ),
            411,
        ),
        (call("POST", "/api/answer", {**good, "pad": "x" * MAX_BODY}), 413),
        (call("POST", "/api/answer", b"[" * 5000, {"Content-Type": "application/json"}), 400),
        (call("POST", "/api/answer", ["a list"]), 400),
        # rule 7: a path that is not a store key
        (call("GET", "/api/task/../../objects"), 400),
        (call("GET", "/api/task/sha256:" + "A" * 64), 400),
        (call("GET", "/api/reason/" + tasks["revenue"] + "?x=1"), 400),
        (call("GET", "/api/task/sha256:" + "0" * 64), 404),
        (call("GET", "/objects/" + k[7:9]), 404),
        (call("POST", "/api/answer", {**good, "task": "../../logs"}), 400),
        # rule 8: an answer that its task does not permit
        (call("POST", "/api/answer", answer(tasks["revenue"], "confirm")), 400),
        (call("POST", "/api/answer", answer(tasks["revenue"], "choose", decision=1)), 400),
        (call("POST", "/api/answer", answer(tasks["revenue"], "choose", decision="0")), 400),
        (call("POST", "/api/answer", answer(tasks["revenue"], "accept")), 400),
        (call("POST", "/api/answer", answer(tasks["net_income"], "unsure", decision=1)), 400),
        (call("POST", "/api/answer", answer(tasks["net_income"], "unsure", keys=-1)), 400),
        (call("POST", "/api/answer", answer(tasks["net_income"], "unsure", reason_seen=1)), 400),
        (
            call(
                "POST",
                "/api/answer",
                answer(tasks["net_income"], "unsure", codes_kept=["SCALE_WORD"]),
            ),
            400,
        ),
        (call("POST", "/api/answer", answer(tasks["revenue"], "correct", start=12, end=999)), 400),
        (call("POST", "/api/answer", answer(tasks["revenue"], "correct", start=20, end=12)), 400),
        (call("POST", "/api/answer", answer(tasks["revenue"], "correct", start=0, end=7)), 400),
        (
            call(
                "POST",
                "/api/answer",
                answer(
                    tasks["revenue"],
                    "correct",
                    start=12,
                    end=26,
                    parts=[{"role": "value", "start": 0, "end": 3}],
                ),
            ),
            400,
        ),
        (call("POST", "/api/answer", answer(tasks["net_income"], "unsure", ms=2**60)), 400),
        (call("POST", "/api/answer", answer(tasks["net_income"], "unsure", keys=2**31)), 400),
        # a kept code that the correction does not have, and a check with a verdict of no type
        (
            call(
                "POST",
                "/api/answer",
                answer(
                    tasks["revenue"],
                    "correct",
                    start=12,
                    end=17,
                    codes_kept=["SCALE_WORD", "NOT_A_CODE"],
                ),
            ),
            400,
        ),
        (call("POST", "/api/check", {"task": tasks["revenue"], "verdict": ["correct"]}), 400),
        (call("POST", "/api/check", {"task": [tasks["revenue"]], "verdict": "correct"}), 400),
        # a correction that the gate rejects, and one whose codes the person did not keep
        (
            call(
                "POST",
                "/api/answer",
                answer(tasks["revenue"], "correct", start=12, end=26, value="5"),
            ),
            409,
        ),
        (call("POST", "/api/answer", answer(tasks["revenue"], "correct", start=12, end=17)), 409),
        (call("POST", "/api/check", {"task": tasks["revenue"], "verdict": "choose"}), 400),
        (call("DELETE", "/api/queue"), 501),
    ]
    for (status, _, body), want in refused:
        assert status == want, body
    assert log(store, k) == []
    # each refusal of the server itself gives its reason as JSON
    assert json.loads(refused[0][0][2]) == {
        "error": "the Host header must be 127.0.0.1 and the port"
    }
    assert "the gate rejects this correction" in json.loads(refused[-4][0][2])["error"]
    assert "the correction has no code NOT_A_CODE" in json.loads(refused[-7][0][2])["error"]
    assert "keep each code of the correction: SCALE_WORD" in json.loads(refused[-3][0][2])["error"]
    for status, headers, _ in seen:
        if status != 501:  # http.server answers an unknown method itself
            assert headers["Content-Security-Policy"] == CSP


def test_the_page_and_its_files_need_no_token_and_hold_no_data(served: Served) -> None:
    _, _, _, call, seen = served
    status, headers, page = call("GET", "/", token=None)
    assert status == 200 and headers["Content-Type"] == "text/html; charset=utf-8"
    assert '<script src="/review.js"></script>' in page and "<script>" not in page
    assert " style=" not in page and " on" not in page.replace(" one", "")
    status, headers, script = call("GET", "/review.js", token=None)
    assert status == 200 and headers["Content-Type"].startswith("text/javascript")
    # rule 5: document text goes into the page only with textContent
    for unsafe in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert unsafe not in script
    assert call("GET", "/review.css", token=None)[0] == 200
    for _, h, _ in seen:
        assert h["Content-Security-Policy"] == CSP
        assert h["X-Content-Type-Options"] == "nosniff"
        assert h["Referrer-Policy"] == "no-referrer"
    # rule 4 as the note gives it
    assert CSP == (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "frame-src 'self'; img-src 'self'; form-action 'none'; base-uri 'none'; "
        "frame-ancestors 'none'"
    )


# §8: the queue and the answers


def test_an_answer_from_the_page_goes_into_the_answer_log(served: Served) -> None:
    store, k, tasks, call, _ = served
    status, _, body = call("GET", "/api/queue")
    assert status == 200
    queue = json.loads(body)
    # grouped by document, in page order: revenue is first in the text
    assert queue == {
        "reviewer": "ana",
        "tasks": [
            {"task": tasks["revenue"], "document": "", "page": None},
            {"task": tasks["net_income"], "document": "", "page": None},
        ],
    }
    status, _, body = call("POST", "/api/answer", answer(tasks["revenue"], "choose", decision=0))
    assert status == 200, body
    assert [t["task"] for t in json.loads(body)["tasks"]] == [tasks["net_income"]]
    (record,) = log(store, k)
    assert record == {
        "format": "answer@1", "task": tasks["revenue"], "reviewer": "ana", "verdict": "choose",
        "decision": 0, "candidate": None, "codes_kept": [], "statements": None, "nodes": None,
        "reason_seen": False, "keys": 1, "ms": 900, "time": "2026-10-21T09:30:00Z",
        "sequence": 1, "previous": None, "entry_sha256": record["entry_sha256"],
    }  # fmt: skip
    # the task view says that this reviewer answered it, and a new answer replaces it
    view = json.loads(call("GET", f"/api/task/{tasks['revenue']}")[2])
    assert view["answered"] == "choose"
    resolved = write_resolution(store, k, None, ["ana"])
    assert resolved.resolution is not None
    statuses = {s["field"]: s["status"] for s in resolved.resolution["slots"]}
    assert statuses == {"net_income": "admitted", "revenue": "chosen"}


def test_a_correction_runs_admit_and_shows_the_outcome_at_once(served: Served) -> None:
    store, k, tasks, call, _ = served
    revenue = tasks["revenue"]
    # the selection "4,200 thousand" holds its scale word: the page reads the value in full
    selection = {"task": revenue, "verdict": "correct", "start": 12, "end": 26}
    status, _, body = call("POST", "/api/check", selection)
    assert status == 200 and json.loads(body) == {
        "outcome": "admitted",
        "codes": [],
        "keep": [],
        "missing": [],
        "shown": "4,200,000 with no unit (written 4,200, in thousands, positive)",
        "ask": [],
    }
    # the selection "4,200" leaves the scale word out: it gives 4200, and the gate flags it
    number = {"task": revenue, "verdict": "correct", "start": 12, "end": 17}
    status, _, body = call("POST", "/api/check", number)
    assert status == 200 and json.loads(body) == {
        "outcome": "needs_verification",
        "codes": [{"code": "SCALE_WORD", "text": json.loads(body)["codes"][0]["text"]}],
        "keep": ["SCALE_WORD"],
        "missing": [],
        "shown": "4,200 with no unit (written 4,200, not scaled, positive)",
        "ask": [],
    }
    # the person types the value in full instead
    status, _, body = call("POST", "/api/check", {**number, "value": "4,200,000"})
    assert json.loads(body)["outcome"] == "admitted"
    assert (
        json.loads(body)["shown"]
        == "4,200,000 with no unit (written 4,200, in thousands, positive)"
    )
    assert log(store, k) == []  # a check writes nothing
    # the flagged correction counts when the person keeps its code
    kept = answer(revenue, "correct", start=12, end=17, codes_kept=["SCALE_WORD"], keys=3)
    status, _, body = call("POST", "/api/answer", kept)
    assert status == 200, body
    (record,) = log(store, k)
    assert record["candidate"] == {
        "field": "revenue", "value": "4200", "id": "review-1", "proposer": "person:ana",
        "evidence": [{"start": 12, "end": 17}],
    }  # fmt: skip
    resolved = write_resolution(store, k, None, ["ana"])
    assert resolved.resolution is not None
    (slot,) = [s for s in resolved.resolution["slots"] if s["field"] == "revenue"]
    assert (slot["status"], slot["value"]) == ("corrected", "4200")


def test_the_reason_is_closed_until_the_person_asks(served: Served) -> None:
    _, _, tasks, call, _ = served
    view = json.loads(call("GET", f"/api/task/{tasks['revenue']}")[2])
    text = json.dumps(view)
    for hidden in ("CONFLICTING_CANDIDATES", "SCALE_WORD", "needs_verification", "admitted"):
        assert hidden not in text
    assert view["question"] == "Which amount is revenue?"
    assert [c["quote"] for c in view["choices"]] == ["4,200 thousand", "4,200 thousand"]
    assert view["view"]["blocks"][0]["marks"] == [[12, 26, "value", [1, 2]]]
    reason = json.loads(call("GET", f"/api/reason/{tasks['revenue']}")[2])
    assert [c["code"] for c in reason["codes"]] == ["CONFLICTING_CANDIDATES", "SCALE_WORD"]
    assert [c["outcome"] for c in reason["choices"]] == ["needs_verification"] * 2


def test_a_settled_slot_leaves_the_queue_of_each_reviewer(tmp_path: Path) -> None:
    store, _, tasks = store_with_tasks(tmp_path / "store")
    with store:
        Review(store, "ben").answer(answer(tasks["net_income"], "confirm"))
        Review(store, "cy").answer(answer(tasks["revenue"], "unsure"))
        queue = Review(store, "ana").queue()["tasks"]
    # ben's audit confirm settles net income; an unsure answer settles nothing (§6.1 rule 2)
    assert [t["task"] for t in queue] == [tasks["revenue"]]


def test_a_packet_that_does_not_match_its_receipt_gives_no_task(tmp_path: Path) -> None:
    store, _, _ = store_with_tasks(tmp_path / "store")
    with store:
        broken = FolderStore(tmp_path / "store")
        # a task object of a packet that is not in the store
        broken.put("task@1", b'{"packet":"sha256:' + b"1" * 64 + b'"}')
        review = Review(broken, "ana")
        assert len(review.queue()["tasks"]) == 2
        (line,) = review.skipped
        assert line.startswith("packet sha256:1111") and "not in the store" in line


def test_a_packet_of_a_bad_shape_gives_a_skipped_line_and_not_a_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, k, _ = store_with_tasks(tmp_path / "store")

    def bad(*args: Any, **kwargs: Any) -> Any:
        raise KeyError("decisions")

    monkeypatch.setattr(serve, "make_tasks", bad)
    with store:
        review = Review(store, "ana")
    assert review.queue()["tasks"] == []
    assert review.skipped == [f"packet {k}: 'decisions'"]


# The source views


def test_an_html_source_goes_into_a_sandboxed_frame(tmp_path: Path) -> None:
    page = tmp_path / "lease.html"
    page.write_text(
        '<html><head><meta HTTP-EQUIV="refresh" content="0;url=https://example.org/">'
        "<title>Lease</title><script>alert(1)</script></head><body>"
        '<p>The monthly rent is <b>$2,450</b>.</p><img src="https://example.org/x.png">'
        '<a href = "https://example.org/">More</a><svg><a><set attributeName="xlink:Href" '
        'to="https://example.org/"/><text>Terms</text></a></svg>'
        "<p>The deposit is $4,900.</p></body></html>",
        "utf-8",
    )
    store = FolderStore(tmp_path / "store")
    with store:
        reading, doc = put_reading(store, page)
        schema = {"fields": {"rent": {"type": "integer", "unit": "USD"}}}
        at = doc.text.index("2,450")
        cand = [{"id": "c1", "field": "rent", "value": "2450", "unit": "USD",
                 "evidence": {"start": at, "end": at + 5}}]  # fmt: skip
        k, _ = admit_packet(store, doc.text, schema, cand, None, "lease", reading=reading)
        (tk,) = [t for t, _ in write_tasks(store, k, EVERY).tasks]
        with running(Review(store, "ana")) as (call, _, port):
            view = json.loads(call("GET", f"/api/task/{tk}")[2])["view"]
            assert view["kind"] == "html" and view["frame"].startswith("/frame/")
            assert view["note"] == "The box in the original page marks the value."
            # the frame needs no token, because a frame cannot send the header
            status, headers, html = call("GET", view["frame"], token=None)
            assert status == 200
            assert headers["Content-Security-Policy"] == frame_csp(f"http://127.0.0.1:{port}")
            assert "sandbox" in headers["Content-Security-Policy"].split("; ")
            assert '<b>$<mark style="' in html and ">2,450</mark></b>" in html
            # no meta refresh and no link: the frame cannot go to another host
            assert "equiv" in html and "http-equiv" not in html.lower()
            assert "data-href" in html and "href" not in html.lower().replace("data-href", "")
            # the ticket works one time, and a frame request still needs the right Host
            assert call("GET", view["frame"], token=None)[0] == 404
            again = json.loads(call("GET", f"/api/task/{tk}")[2])["view"]["frame"]
            assert call("GET", again, host="evil.example")[0] == 421


def test_a_pdf_source_shows_the_pages_of_the_task_with_the_value_in_a_box(tmp_path: Path) -> None:
    pytest.importorskip("pdfminer")
    spec = importlib.util.spec_from_file_location("pdfgen", HERE.parent / "pdfgen.py")
    assert spec is not None and spec.loader is not None
    pdfgen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pdfgen)
    make_pdf = pdfgen.make_pdf

    path = tmp_path / "lease.pdf"
    path.write_bytes(make_pdf([[(72, 72, "Lease summary")],
                               [(72, 100, "The monthly rent is $2,450.")]]))  # fmt: skip
    store = FolderStore(tmp_path / "store")
    with store:
        reading, doc = put_reading(store, path)
        at = doc.text.encode().index(b"2,450")
        cand = [{"id": "c1", "field": "rent", "value": "2450", "unit": "USD",
                 "evidence": {"start": at, "end": at + 5}}]  # fmt: skip
        schema = {"fields": {"rent": {"type": "integer", "unit": "USD"}}}
        k, _ = admit_packet(store, doc.text, schema, cand, None, "lease", reading=reading)
        (tk,) = [t for t, _ in write_tasks(store, k, EVERY).tasks]
        view = Review(store, "ana").view(tk)["view"]
    assert view["kind"] == "pdf"
    (page,) = view["pages"]  # only the page of the value
    assert page["page"] == 2 and (page["width"], page["height"]) == (612, 792)
    words = {w[1]: w[0] for w in page["words"]}
    assert doc.text[words["$2,450."] :].startswith("$2,450.")
    (mark,) = page["marks"]
    assert mark[4:] == ["value", [1]] and mark[0] > 72


def test_a_value_that_occurs_two_times_is_not_marked_in_the_frame() -> None:
    html = "<p>Rent $75.</p><p>Fee $75.</p>"
    assert serve._marked(html, "$75") == (html, False, 2)
    assert serve._marked('<a title="$75">x</a>', "$75")[1] is False  # inside a tag
    for inside in ("<script>var a = '$75';</script>", "<STYLE>p::after{content:'$75'}</style>",
                   "<title>$75</title>", "<textarea\n>$75</textarea>", "<!-- $75 -->"):  # fmt: skip
        assert serve._marked(f"<p>Rent</p>{inside}", "$75") == (f"<p>Rent</p>{inside}", False, 1)
    assert serve._marked("<script></script><p>$75</p>", "$75")[1] is True
    assert serve._marked("<!-- a --><p>$75</p>", "$75")[1] is True
    assert serve._marked("<p>a\n  b</p>", "a b")[0] == (
        '<p><mark style="background:#ffe066;outline:3px solid #c92a2a">a\n  b</mark></p>'
    )


def test_the_frame_marks_a_value_that_holds_href(tmp_path: Path) -> None:
    review = Review(FolderStore(tmp_path / "store"), "ana")
    review.docs["p"] = serve._Doc.__new__(serve._Doc)
    review.docs["p"].html = "<p>see href=x</p>"
    review.tickets["t"] = ("p", "href=x")
    html = review.frame("t")
    assert html is not None and "<mark" in html and "data-href=x</mark>" in html


def test_a_long_span_shows_its_two_ends_and_closes_the_middle() -> None:
    text = "".join(f"line {i}\n" for i in range(60))
    u = _Units(text)
    start, end = text.index("line 10"), text.index("line 40") + 7
    blocks = Review._blocks(u, "span", [((start, end), "value", [1])])
    assert [b["closed"] for b in blocks] == [False, True, False]
    assert blocks[0]["text"].startswith("line 5\n") and blocks[0]["text"].endswith("line 15\n")
    assert blocks[1]["text"].startswith("line 16\n") and blocks[1]["text"].endswith("line 34\n")
    assert blocks[2]["text"].startswith("line 35\n") and blocks[2]["text"].endswith("line 45\n")
    assert (
        "".join(b["text"] for b in blocks) == text[text.index("line 5\n") : text.index("line 46")]
    )
    # a text item shows the lines around the value, with no closed block
    (one,) = Review._blocks(u, "text", [((start, start + 7), "value", [1])])
    assert one["text"].startswith("line 5\n") and one["text"].endswith("line 15\n")


def test_offsets_go_between_bytes_code_points_and_utf_16() -> None:
    u = _Units("a\U0001f600b€c")
    assert [u.u16(i) for i in range(6)] == [0, 1, 3, 4, 5, 6]
    assert [u.from_u16(i) for i in range(7)] == [0, 1, None, 2, 3, 4, 5]
    assert u.chars(1, 5) == (1, 2) and u.chars(2, 5) is None
    assert [u.to_bytes(i) for i in range(6)] == [0, 1, 5, 6, 9, 10]


def test_review_serve_needs_a_store_and_a_reviewer(tmp_path: Path, capsys: Any) -> None:
    assert main(["review", "serve", "--store", str(tmp_path / "none"), "--reviewer", "ana"]) == 2
    with pytest.raises(ValueError, match="reviewer name"):
        Review(FolderStore(tmp_path / "s"), " ")
    assert main(["review", "serve", "--store", str(tmp_path), "--reviewer", "a", "--port",
                 "70000"]) == 2  # fmt: skip


def test_a_scale_suffix_in_the_selection_gives_the_value_in_full(tmp_path: Path) -> None:
    """#460: "$4.2m" reads as 4200000, and the task view gives the field definition."""
    text = "Revenue was $4.2m in 2025.\n"
    definition = "Revenue as the income statement gives it, before <b>tax</b>."
    schema = {"fields": {"revenue": {"type": "number", "unit": "USD", "description": definition}}}
    value = {"start": 12, "end": 17, "text": "$4.2m"}
    candidates = [{"id": "c1", "field": "revenue", "value": "4200000", "unit": "USD",
                   "evidence": value}]  # fmt: skip
    store = FolderStore(tmp_path / "store")
    k, _ = admit_packet(store, text, schema, candidates, None, None, None)
    ((tk, _),) = write_tasks(store, k, EVERY).tasks
    review = Review(store, "ana")
    # the definition is data in the JSON of the view, and the page sets it with textContent
    assert review.view(tk)["definition"] == definition
    check = review.check({"task": tk, "verdict": "correct", "start": 12, "end": 17})
    assert (check["outcome"], check["codes"]) == ("admitted", [])
    assert check["shown"].startswith("4,200,000 USD")
    # without the suffix, the selection gives the number as written, and the gate flags it
    check = review.check({"task": tk, "verdict": "correct", "start": 13, "end": 16})
    assert check["outcome"] != "admitted" and check["shown"].startswith("4.2 USD")


def test_a_correction_whose_parts_do_not_agree_asks_again(tmp_path: Path) -> None:
    """#496: the selection "-3,266.2" under "EUR million" as the value -3266.2. The scale is
    above the table, and the task gives a positive value. The page shows the parts and asks
    again before it saves."""
    text = (
        "Statement of income\nEUR million Note 2025 2024\nNet sales\t1\t3,960.2\t4,126.3\n"
        "Cost of sales\t\t-3,266.2\t-3,344.7\n"
    )
    schema = {"fields": {"cost_of_sales": {"type": "number", "unit": "EUR"}}}
    at = text.index("-3,266.2")
    scale = text.index("EUR million")
    candidates = [{"id": "c1", "field": "cost_of_sales", "value": "3266200000", "unit": "EUR",
                   "evidence": [{"start": at + 1, "end": at + 8},
                                {"role": "scale", "start": scale, "end": scale + 11}]}]  # fmt: skip
    store = FolderStore(tmp_path / "store")
    k, _ = admit_packet(store, text, schema, candidates, None, None, None)
    tasks = write_tasks(store, k, EVERY).tasks
    assert len(tasks) == 1
    ((tk, _),) = tasks
    review = Review(store, "ana")
    selection = {"task": tk, "verdict": "correct", "start": at, "end": at + 8}
    check = review.check(selection)
    assert [a["part"] for a in check["ask"]] == ["scale", "sign"]
    scale_text, sign_text = (a["text"] for a in check["ask"])
    assert 'scale: "EUR million Note 2025 2024"' in scale_text and "3266200000" in scale_text
    assert "value 1 of the task is positive" in sign_text
    plain = {"decision": None, "reason_seen": False, "keys": 2, "ms": 900}
    with pytest.raises(Refused) as refused:
        review.answer({**plain, **selection, "codes_kept": check["keep"]})
    assert refused.value.code == 409 and "do not agree" in str(refused.value)
    assert log(store, k) == []
    # the person cites the scale: the page reads the value in full, and the sign still differs
    part = {"role": "scale", "start": scale, "end": scale + 11}
    check = review.check({**selection, "parts": [part]})
    assert check["shown"].startswith("-3,266,200,000 EUR")
    assert [a["part"] for a in check["ask"]] == ["sign"]
    # a positive value under a negative written number is a question too
    check = review.check({**selection, "parts": [part], "value": "3266200000"})
    sign = "The value is positive, but the text writes the number -3,266.2 as negative."
    assert check["ask"] == [{"part": "sign", "text": sign}]
    # the number without its sign, with the scale: the parts agree, and the answer saves
    unsigned = {**selection, "start": at + 1, "parts": [part]}
    check = review.check(unsigned)
    assert check["ask"] == [] and check["shown"].startswith("3,266,200,000 EUR")
    review.answer({**plain, **unsigned, "codes_kept": check["keep"]})
    (record,) = log(store, k)
    assert record["candidate"]["value"] == "3266200000" and "parts_seen" not in record
    # a person who saw the parts can save a value that does not agree
    review.answer({**plain, **selection, "codes_kept": review.check(selection)["keep"],
                   "parts_seen": True})  # fmt: skip
    assert log(store, k)[-1]["candidate"]["value"] == "-3266.2"


def test_a_cited_scale_gives_the_value_in_full_with_no_rounding(tmp_path: Path) -> None:
    """#496: a number of 29 digits times a thousand keeps each digit."""
    number = "12345678901234567890123456789"
    text = f"Revenue in thousands\nRevenue was {number} in 2025.\n"
    schema = {"fields": {"revenue": {"type": "number"}}}
    at = text.index(number)
    candidates = [{"id": "c1", "field": "revenue", "value": "5",
                   "evidence": {"start": 0, "end": 7}}]  # fmt: skip
    store = FolderStore(tmp_path / "store")
    k, _ = admit_packet(store, text, schema, candidates, None, None, None)
    ((tk, _),) = write_tasks(store, k, EVERY).tasks
    review = Review(store, "ana")
    scale = text.index("in thousands")
    part = {"role": "scale", "start": scale, "end": scale + 12}
    body = {"task": tk, "verdict": "correct", "start": at, "end": at + len(number)}
    check = review.check({**body, "parts": [part]})
    assert check["shown"].startswith("12,345,678,901,234,567,890,123,456,789,000 ")
    # without the part, the scale question gives the value in full with each digit
    (asked,) = review.check(body)["ask"]
    assert asked["part"] == "scale" and f"{number}000," in asked["text"]


def test_a_field_with_no_definition_gives_none(served: Served) -> None:
    _, _, tasks, call, _ = served
    view = json.loads(call("GET", f"/api/task/{tasks['revenue']}")[2])
    assert view["definition"] is None
