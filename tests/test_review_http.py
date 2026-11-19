"""The review API (SPEC §4.20, #649): the vectors in ``conformance/review-api/``, and the
service on a store.

The store tests use a document with a letter of two bytes and a character of four bytes before
each value. So a span in UTF-8 bytes differs from the same span in UTF-16 units, which the page
of ``groundgate review serve`` sends.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import re
import socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from groundgate.cli import main
from groundgate.review import api, serve
from groundgate.review.api import ApiError, Issuers, Service, Static
from groundgate.review.resolve import write_resolution
from groundgate.review.serve import TOKEN_HEADER, Review
from groundgate.review.tasks import write_tasks
from groundgate.store import FolderStore, reviewer_key
from groundgate.store.packets import admit_packet

VECTORS = sorted((Path(__file__).parent.parent / "conformance" / "review-api").glob("*.json"))
CLOCK = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
NOW = int(CLOCK.timestamp())
SECRET = b"a-test-secret-of-the-review-api-0123456789"
ISSUER = "https://id.example.test"
ISSUERS = Issuers({ISSUER: SECRET})
TOKEN = "local-token-0123456789-abcdefghijklmnopqrstuvwxyz"
EVERY = {
    "format": "review-policy@1",
    "audit": {"rate": "1", "seed": "s"},
    "agree": 1,
    "leads": [],
    "rejected": True,
}
TEXT = "Café \U0001f600 revenue was 4,200 thousand in 2025.\nNet income was 310 thousand in 2025.\n"
SCHEMA = {
    "fields": {
        "net_income": {"type": "number", "description": "The profit after tax."},
        "revenue": {"type": "number"},
    }
}

Response = tuple[int, dict[str, str], str]
Call = Callable[..., Response]


def at(words: str) -> dict[str, int]:
    """The span of ``words`` in TEXT, in UTF-8 bytes."""
    start = TEXT.encode("utf-8").index(words.encode("utf-8"))
    return {"start": start, "end": start + len(words.encode("utf-8"))}


def u16(words: str) -> dict[str, int]:
    """The span of ``words`` in TEXT, in UTF-16 units, as the page sends it."""
    start = len(TEXT[: TEXT.index(words)].encode("utf-16-le")) // 2
    return {"start": start, "end": start + len(words.encode("utf-16-le")) // 2}


CANDIDATES = [
    {"id": "c1", "field": "revenue", "value": "4200000",
     "evidence": {**at("4,200 thousand"), "text": "4,200 thousand"}},
    {"id": "c2", "field": "revenue", "value": "4200",
     "evidence": {**at("4,200 thousand"), "text": "4,200 thousand"}},
    {"id": "n1", "field": "net_income", "value": "310000",
     "evidence": {**at("310 thousand"), "text": "310 thousand"}},
]  # fmt: skip


KEY = bytes(range(32, 64))  # the key of the task IDs of a service in a test


def id_of(task: str) -> str:
    """The task ID that a service with KEY gives to a task key."""
    return api.task_id(KEY, task)


def make_store(root: Path) -> tuple[str, dict[str, str]]:
    """A store with one packet and its two tasks: the revenue task is a review task with two
    choices, and the net income task is an audit task, so it is blind."""
    with FolderStore(root) as store:
        k, _ = admit_packet(store, TEXT, SCHEMA, CANDIDATES, None, "doc-1", None)
        tasks = {t["slot"]["field"]: tk for tk, t in write_tasks(store, k, EVERY).tasks}
    return k, tasks


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def claim(secret: bytes = SECRET, **members: Any) -> str:
    """The Authorization value of a signed claim for ana, good for one minute."""
    payload = {"iss": ISSUER, "sub": "ana", "aud": "groundgate-review", "exp": NOW + 60, **members}
    parts = [
        b64(json.dumps(part).encode("utf-8")) for part in ({"alg": "HS256", "typ": "JWT"}, payload)
    ]
    signed = ".".join(parts)
    return (
        f"Bearer {signed}.{b64(hmac.new(secret, signed.encode('ascii'), hashlib.sha256).digest())}"
    )


@contextmanager
def serving(httpd: ThreadingHTTPServer, default: dict[str, str]) -> Iterator[Call]:
    """A server on its thread. call(method, path, body, headers) sends one request with the
    right Host and the ``default`` headers. A header of None removes a default header. A dict
    body goes as JSON, and a str body as it is."""
    port = httpd.server_port
    assert httpd.server_address[0] == "127.0.0.1"
    thread = Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()

    def call(
        method: str, path: str, body: Any = None, headers: dict[str, str | None] | None = None
    ) -> Response:
        sent: dict[str, str | None] = {"Host": f"127.0.0.1:{port}", **default}
        raw = None
        if isinstance(body, dict):
            raw = json.dumps(body).encode("utf-8")
            sent["Content-Type"] = "application/json"
        elif isinstance(body, str):
            raw = body.encode("utf-8")
        if raw is not None:
            sent["Content-Length"] = str(len(raw))
        sent.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for name, value in sent.items():
                if value is not None:
                    conn.putheader(name, value.replace("{port}", str(port)))
            conn.endheaders(raw)
            r = conn.getresponse()
            return r.status, dict(r.getheaders()), r.read().decode("utf-8")
        finally:
            conn.close()

    try:
        yield call
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def answer_logs(root: Path) -> dict[str, bytes]:
    """The bytes of each answer log of a store, by its path in the store."""
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*.jsonl"))
        if "answers" in p.relative_to(root).parts
    }


def records(root: Path, k: str, name: str = "ana") -> list[dict[str, Any]]:
    with FolderStore(root) as store:
        return store.read(("answers", k, reviewer_key(name)))


def error(response: Response) -> tuple[int, str]:
    body = json.loads(response[2])
    assert body["api"] == api.API and set(body) == {"api", "error"}
    assert response[1]["Content-Type"] == "application/json; charset=utf-8"
    return response[0], body["error"]["code"]


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[Path, str, dict[str, str], Call]]:
    """The API on a store with one packet, with a signed claim for ana in each request."""
    root = tmp_path / "store"
    k, tasks = make_store(root)
    service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
    with serving(api.server(service), {"Authorization": claim()}) as call:
        yield root, k, tasks, call


Served = tuple[Path, str, dict[str, str], Call]


# The vectors


@pytest.fixture(scope="module")
def empty(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Call]:
    """The service of the request vectors: a static token, the reviewer ana, an empty store."""
    root = tmp_path_factory.mktemp("empty")
    FolderStore(root).close()
    service = Service(root, api.read_token(TOKEN, "ana"))
    with serving(api.server(service), {}) as call:
        yield call


@pytest.mark.parametrize("path", VECTORS, ids=lambda p: p.stem)
def test_vector(path: Path, empty: Call) -> None:
    v = json.loads(path.read_text("utf-8"))
    kind, expected = v["kind"], v["expected"]
    got: Any
    try:
        if kind in ("claim", "token"):
            sent = [] if v["authorization"] is None else [v["authorization"]]
            if kind == "claim":
                issuers = api.read_issuers(
                    {"groundgate_review_issuers": 1, "issuers": v["issuers"]}
                )
                got = {"actor": api.check_claim(sent, issuers, v["now"])}
            else:
                assert v["token"] == TOKEN
                got = {"actor": api.check_static(sent, api.read_token(v["token"], v["reviewer"]))}
        elif kind == "task":
            view = api.task_view(v["task"])
            got = {"served": view is not None, **(view or {})}
        elif kind == "statements":
            got = {"statements": api.statement_list(v["model_text"])}
        elif kind == "page":
            page, cursor = api.list_page(v["entries"], v["query"])
            got = {"tasks": [e["task"] for e in page], "next": cursor}
        elif kind == "answer":
            api.check_body(v["body"], v["blind"])
            got = {"valid": True}
        elif kind == "task-id":
            got = {"id": api.task_id(bytes.fromhex(v["key"]), v["task"])}
        elif kind == "errors":
            got = api.STATUS
        else:
            assert kind == "request"
            response = empty(v["method"], v["path"], v["body"], v["headers"])
            got = {"status": response[0]}
            if "error" in expected:
                assert error(response) == (expected["status"], expected["error"])
                got["error"] = expected["error"]
            else:
                got["body"] = json.loads(response[2])
    except ApiError as exc:
        got = {"error": exc.code}
    assert got == expected


def test_the_vectors_cover_each_kind_and_each_error_of_the_claim_check() -> None:
    vectors = [json.loads(p.read_text("utf-8")) for p in VECTORS]
    assert {v["kind"] for v in vectors} == {
        "claim", "token", "task", "task-id", "statements", "page", "answer", "request",
        "errors",
    }  # fmt: skip
    claims = {v["expected"].get("error") for v in vectors if v["kind"] == "claim"}
    assert claims == {None, "no_claim", "bad_claim", "unknown_issuer", "expired_claim"}
    requests = {v["expected"].get("error") for v in vectors if v["kind"] == "request"}
    # the other codes need a task: the store tests below give them
    assert requests == {
        None, "wrong_host", "no_claim", "bad_claim", "not_found", "method_not_allowed",
        "bad_request", "unsupported_media_type", "length_required", "body_too_large",
    }  # fmt: skip


# The read operations


def test_the_list_and_a_review_task_and_its_document(served: Served) -> None:
    _, k, tasks, call = served
    revenue = id_of(tasks["revenue"])
    status, headers, body = call("GET", "/v1/tasks")
    assert status == 200 and headers["Cache-Control"] == "no-store"
    assert headers["Content-Security-Policy"] == api.CSP
    assert json.loads(body) == {
        "api": "groundgate-review/1",
        "actor": "ana",
        "tasks": [
            {"task": id_of(tasks["net_income"]), "document": "doc-1", "mode": "audit",
             "field": "net_income", "key": None},
            {"task": revenue, "document": "doc-1", "mode": "review", "field": "revenue",
             "key": None},
        ],
        "next": None,
    }  # fmt: skip
    # one page for each task: the cursor of page 1 gives page 2
    page = json.loads(call("GET", "/v1/tasks?limit=1")[2])
    assert [t["field"] for t in page["tasks"]] == ["net_income"]
    assert page["next"] == id_of(tasks["net_income"])
    page = json.loads(call("GET", f"/v1/tasks?limit=1&cursor={page['next']}")[2])
    assert [t["field"] for t in page["tasks"]] == ["revenue"] and page["next"] is None

    status, _, body = call("GET", f"/v1/tasks/{revenue}")
    task = json.loads(body)
    with FolderStore(served[0]) as store:
        stored = json.loads(store.get("task@1", tasks["revenue"]))
    # the body is the task object without its packet key
    assert stored.pop("packet") == k
    assert status == 200 and task == {
        "api": "groundgate-review/1", "task": revenue, "document": "doc-1", "mode": "review",
        "field": "revenue", "key": None, "definition": None, "answered": None, "body": stored,
        "statements": None,
    }  # fmt: skip
    # the evidence of each choice is a span of the document text in UTF-8 bytes
    status, _, body = call("GET", f"/v1/tasks/{revenue}/document")
    document = json.loads(body)
    assert status == 200 and document == {
        "api": "groundgate-review/1", "task": revenue, "document": "doc-1", "text": TEXT,
    }  # fmt: skip
    span = stored["choices"][0]["evidence"]
    data = document["text"].encode("utf-8")
    assert data[span["start"] : span["end"]].decode("utf-8") == "4,200 thousand"


# The claim


def test_a_request_with_no_claim_an_expired_claim_or_an_unknown_issuer_is_refused(
    served: Served,
) -> None:
    root, k, tasks, call = served
    revenue = id_of(tasks["revenue"])
    good = {"task": revenue, "verdict": "choose", "decision": 1}
    refused = {
        "no_claim": None,
        "expired_claim": claim(exp=NOW),
        "unknown_issuer": claim(iss="https://other.example.test"),
        "bad_claim": claim(b"another-secret-of-32-bytes-or-more-0123456789"),
    }
    for code, authorization in refused.items():
        for method, path, body in (
            ("GET", "/v1/tasks", None),
            ("GET", f"/v1/tasks/{revenue}", None),
            ("GET", f"/v1/tasks/{revenue}/document", None),
            ("POST", "/v1/answers", good),
        ):
            response = call(method, path, body, {"Authorization": authorization})
            assert error(response) == (401, code), (code, path)
            assert response[1]["WWW-Authenticate"] == "Bearer"
            assert "revenue" not in response[2] and "4,200" not in response[2]
    # a claim for another actor is good, and the answer names that actor
    assert records(root, k) == []
    ben = {"Authorization": claim(sub="ben")}
    response = call("POST", "/v1/answers", good, ben)
    assert response[0] == 201, response[2]
    assert records(root, k) == [] and records(root, k, "ben")[0]["reviewer"] == "ben"


def test_the_static_token_gives_the_reviewer_of_the_service(tmp_path: Path) -> None:
    root = tmp_path / "store"
    k, tasks = make_store(root)
    token = api.read_token(TOKEN + "\n", "ana")
    service = Service(root, token, clock=lambda: CLOCK, id_key=KEY)
    with serving(api.server(service), {}) as call:
        assert error(call("GET", "/v1/tasks")) == (401, "no_claim")
        other = {"Authorization": "Bearer " + TOKEN[::-1]}
        assert error(call("GET", "/v1/tasks", None, other)) == (401, "bad_claim")
        # a signed claim is not the token
        assert error(call("GET", "/v1/tasks", None, {"Authorization": claim()})) == (
            401,
            "bad_claim",
        )
        good = {"Authorization": "Bearer " + TOKEN}
        assert json.loads(call("GET", "/v1/tasks", None, good)[2])["actor"] == "ana"
        body = {"task": id_of(tasks["revenue"]), "verdict": "unsure"}
        assert call("POST", "/v1/answers", body, good)[0] == 201
    assert [r["reviewer"] for r in records(root, k)] == ["ana"]


def test_the_issuers_file_and_the_token_file_are_checked() -> None:
    secret = b64(SECRET)
    good = {"groundgate_review_issuers": 1, "issuers": [{"issuer": ISSUER, "secret": secret}]}
    assert api.read_issuers(good) == ISSUERS
    bad: list[Any] = [
        [],
        {"issuers": good["issuers"]},
        {**good, "groundgate_review_issuers": 2},
        {**good, "groundgate_review_issuers": True},
        {**good, "issuers": []},
        {**good, "issuers": [{"issuer": ISSUER}]},
        {**good, "issuers": [{"issuer": "", "secret": secret}]},
        {**good, "issuers": [{"issuer": ISSUER, "secret": secret}] * 2},
        {**good, "issuers": [{"issuer": ISSUER, "secret": b64(b"short")}]},
        {**good, "issuers": [{"issuer": ISSUER, "secret": secret + "="}]},
        {**good, "issuers": [{"issuer": ISSUER, "secret": 7}]},
        {**good, "extra": 1},
    ]
    for obj in bad:
        with pytest.raises(ValueError):
            api.read_issuers(obj)
    assert api.read_token(f"  {TOKEN}\n", "ana") == Static(TOKEN, "ana")
    for text, name in (("short", "ana"), (TOKEN + " x", "ana"), (TOKEN, " "), (TOKEN, "é")):
        with pytest.raises(ValueError):
            api.read_token(text, name)


# The answer


def page_server(root: Path) -> tuple[ThreadingHTTPServer, FolderStore, dict[str, str]]:
    """The page server of ``groundgate review serve`` for ana, and its token header."""
    store = FolderStore(root)
    httpd, url = serve.server(Review(store, "ana", clock=lambda: CLOCK), 0)
    return httpd, store, {TOKEN_HEADER: url.split("#", 1)[1]}


def test_an_answer_through_the_api_and_through_review_serve_give_identical_records(
    tmp_path: Path,
) -> None:
    """The same four answers go to two copies of one store: through the page server of
    ``groundgate review serve`` with the task key and spans in UTF-16 units, and through the API
    with the task ID and spans in UTF-8 bytes. The answer logs have the same bytes."""
    by_cli, by_api = tmp_path / "cli", tmp_path / "api"
    k, tasks = make_store(by_cli)
    assert make_store(by_api) == (k, tasks)
    revenue = id_of(tasks["revenue"])
    plain = {"reason_seen": False, "keys": 2, "ms": 900}
    number = "4,200"  # without its scale word: the gate flags it, and the person keeps the code
    answers: list[tuple[dict[str, Any], dict[str, Any]]] = [
        # the verdict wrong gives an answer@2 record
        ({"task": tasks["revenue"], "verdict": "wrong"}, {"task": revenue, "verdict": "wrong"}),
        ({"task": tasks["revenue"], "verdict": "choose", "decision": 1},
         {"task": revenue, "verdict": "choose", "decision": 1}),
        ({"task": tasks["revenue"], "verdict": "correct", **u16(number),
          "codes_kept": ["SCALE_WORD"]},
         {"task": revenue, "verdict": "correct", "span": at(number),
          "codes_kept": ["SCALE_WORD"]}),
        ({"task": tasks["revenue"], "verdict": "correct", **u16("4,200 thousand"),
          "parts": [{"role": "field", **u16("revenue")}], "value": "4,200,000"},
         {"task": revenue, "verdict": "correct", "span": at("4,200 thousand"),
          "parts": [{"role": "field", **at("revenue")}], "value": "4,200,000"}),
    ]  # fmt: skip
    assert u16(number) != at(number)
    httpd, store, token = page_server(by_cli)
    with store, serving(httpd, token) as call:
        for page_body, _ in answers:
            sent = {"decision": None, "codes_kept": [], **plain, **page_body}
            status, _, body = call("POST", "/api/answer", sent)
            assert status == 200, body
    written = []
    service = Service(by_api, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
    with serving(api.server(service), {"Authorization": claim()}) as call:
        for _, api_body in answers:
            status, _, body = call("POST", "/v1/answers", {**plain, **api_body})
            assert status == 201, body
            written.append(json.loads(body))
    logs = answer_logs(by_cli)
    assert len(logs) == 1 and logs == answer_logs(by_api)
    stored = records(by_api, k)
    assert [r["format"] for r in stored] == ["answer@2", "answer@1", "answer@1", "answer@1"]
    assert [r["verdict"] for r in stored] == ["wrong", "choose", "correct", "correct"]
    assert stored[2]["candidate"] == {
        "field": "revenue", "value": "4200", "id": "review-1", "proposer": "person:ana",
        "evidence": [at(number)],
    }  # fmt: skip
    assert stored[3]["candidate"]["evidence"] == [
        at("4,200 thousand"),
        {"role": "field", **at("revenue")},
    ]
    assert {r["time"] for r in stored} == {"2026-11-19T12:00:00Z"}
    # the response gives the record without its task key and without the members of the store
    left_out = ("task", "sequence", "previous", "entry_sha256")
    for response, record in zip(written, stored, strict=True):
        assert record["task"] == tasks["revenue"]
        assert response == {
            "api": "groundgate-review/1", "actor": "ana", "task": revenue,
            "record": {name: v for name, v in record.items() if name not in left_out},
        }  # fmt: skip
    # the resolution of each store is the same too
    with FolderStore(by_cli) as a, FolderStore(by_api) as b:
        resolved = [write_resolution(s, k, None, ["ana"]).resolution for s in (a, b)]
    assert resolved[0] == resolved[1] and resolved[0] is not None


def test_the_gate_checks_a_correction_again(served: Served) -> None:
    root, k, tasks, call = served
    revenue = id_of(tasks["revenue"])
    number = {"task": revenue, "verdict": "correct", "span": at("4,200")}
    response = call("POST", "/v1/answers", number)
    assert error(response) == (409, "codes_not_kept")
    assert json.loads(response[2])["error"]["codes"] == ["SCALE_WORD"]
    response = call("POST", "/v1/answers", {**number, "value": "5"})
    assert error(response) == (409, "correction_rejected")
    assert json.loads(response[2])["error"]["codes"]
    refused = [
        {**number, "codes_kept": ["SCALE_WORD", "NOT_A_CODE"]},  # a code that it does not have
        {**number, "span": {"start": 0, "end": 4}},  # the second byte of a letter
        {**number, "span": {"start": 0, "end": 999}},  # after the end of the text
        {**number, "span": at("revenue")},  # no number
        {"task": revenue, "verdict": "confirm"},  # two choices
        {"task": revenue, "verdict": "choose", "decision": 0},  # not a choice
        {"task": revenue, "verdict": "choose"},
        {"task": revenue, "verdict": "unsure", "statements": []},
    ]
    for body in refused:
        assert error(call("POST", "/v1/answers", body)) == (400, "bad_answer"), body
    assert records(root, k) == []
    assert call("POST", "/v1/answers", {**number, "codes_kept": ["SCALE_WORD"]})[0] == 201
    # the answer settles the slot: the task leaves the list, and the task names the verdict
    listed = json.loads(call("GET", "/v1/tasks")[2])
    assert [t["field"] for t in listed["tasks"]] == ["net_income"]
    assert json.loads(call("GET", f"/v1/tasks/{revenue}")[2])["answered"] == "correct"


# The blind task


def test_a_blind_audit_task_never_shows_the_proposed_value(served: Served) -> None:
    root, k, tasks, call = served
    real, blind = tasks["net_income"], id_of(tasks["net_income"])
    with FolderStore(root) as store:
        stored = json.loads(store.get("task@1", real))
    assert stored["mode"] == "audit" and stored["choices"][0]["value"] == "310000"
    seen = [call("GET", "/v1/tasks"), call("GET", f"/v1/tasks/{blind}")]
    assert json.loads(seen[1][2]) == {
        "api": "groundgate-review/1", "task": blind, "document": "doc-1", "mode": "audit",
        "field": "net_income", "key": None, "definition": "The profit after tax.",
        "answered": None, "body": None, "statements": None,
    }  # fmt: skip
    # a blind task takes no verdict about a shown value
    for verdict in ("confirm", "choose", "adjust_span", "wrong"):
        body = {"task": blind, "verdict": verdict, "decision": 2, "span": at("310")}
        if verdict in ("confirm", "wrong"):
            body = {"task": blind, "verdict": verdict}
        seen.append(call("POST", "/v1/answers", body))
        assert error(seen[-1]) == (400, "bad_answer"), verdict
    # a value that the gate flags, and a value that it rejects
    correct = {"task": blind, "verdict": "correct"}
    seen.append(call("POST", "/v1/answers", {**correct, "span": at("310")}))
    assert error(seen[-1]) == (409, "codes_not_kept")
    seen.append(call("POST", "/v1/answers", {**correct, "span": at("310 thousand"), "value": "7"}))
    assert error(seen[-1]) == (409, "correction_rejected")
    assert records(root, k) == []
    seen.append(call("POST", "/v1/answers", {"task": blind, "verdict": "unsure"}))
    seen.append(call("POST", "/v1/answers", {"task": blind, "verdict": "correct",
                                             "span": at("310 thousand")}))  # fmt: skip
    assert [r[0] for r in seen[-2:]] == [201, 201]
    assert json.loads(seen[-1][2]) == {
        "api": "groundgate-review/1", "actor": "ana", "task": blind, "record": None,
    }  # fmt: skip
    document = call("GET", f"/v1/tasks/{blind}/document")
    assert json.loads(document[2]) == {
        "api": "groundgate-review/1", "task": blind, "document": "doc-1", "text": TEXT,
    }  # fmt: skip
    seen += [call("GET", "/v1/tasks"), call("GET", f"/v1/tasks/{blind}")]
    assert json.loads(seen[-1][2])["answered"] == "correct"
    # no response gives the value, the evidence, the question or a member of the task object,
    # and none gives the task key or the packet key: each is a hash over them
    span = stored["choices"][0]["evidence"]
    for _, _, text in [*seen, document]:
        assert real[7:] not in text and k[7:] not in text
    for _, _, text in seen:
        for word in ("310000", "310,000", "310 thousand", "choices", "evidence", "shown",
                     "question", "places", '"item"', '"unit"', "Is net income", '"start"',
                     f": {span['start']}", f": {span['end']}"):  # fmt: skip
            assert word not in text, (word, text)
    # the record in the store has the value that the actor selected
    last = records(root, k)[-1]
    assert (last["verdict"], last["candidate"]["value"]) == ("correct", "310000")
    assert last["candidate"]["evidence"] == [at("310 thousand")]
    # the document is the one response with the text of the value
    assert "310 thousand" in json.loads(document[2])["text"]


def test_a_task_key_is_no_task_id(served: Served, monkeypatch: pytest.MonkeyPatch) -> None:
    """A task key is a hash over the task object. If the API took one, a person could make the
    object for each guess of a hidden value and test its hash with one request. The API refuses
    a task key by its form, before it opens the store, so a key of the store and a key of
    nothing get the same response after the same work."""
    root, k, tasks, call = served
    reads: list[tuple[str, tuple[Any, ...]]] = []
    for name in ("object_bytes", "object_keys", "get", "read"):
        real = getattr(FolderStore, name)

        def spy(self: FolderStore, *args: Any, _real: Any = real, _name: str = name) -> Any:
            reads.append((_name, args))
            return _real(self, *args)

        monkeypatch.setattr(FolderStore, name, spy)

    def ask(method: str, path: str, body: Any = None) -> tuple[Any, ...]:
        del reads[:]
        response = call(method, path, body)
        return *error(response), json.loads(response[2])["error"]["message"], list(reads)

    seen = []
    for key in (tasks["net_income"], tasks["revenue"], k, "sha256:" + "0" * 64):
        seen.append([
            ask("GET", f"/v1/tasks/{key}"),
            ask("GET", f"/v1/tasks/{key}/document"),
            ask("POST", "/v1/answers", {"task": key, "verdict": "unsure"}),
            ask("GET", f"/v1/tasks?cursor={key}"),
        ])  # fmt: skip
    assert [r[:2] for r in seen[0]] == [(404, "not_found")] * 2 + [(400, "bad_request")] * 2
    assert seen[0] == seen[1] == seen[2] == seen[3]
    # the path and the body fail on their form: the service reads nothing from the store
    assert [r[3] for r in seen[0][:3]] == [[], [], []]
    # an ID that names no task: each such ID needs the same reads of the store
    unknown = []
    for name in ("task:" + "0" * 64, "task:" + "f" * 64, id_of(k)):
        unknown.append([
            ask("GET", f"/v1/tasks/{name}"),
            ask("GET", f"/v1/tasks/{name}/document"),
            ask("POST", "/v1/answers", {"task": name, "verdict": "unsure"}),
            ask("GET", f"/v1/tasks?cursor={name}"),
        ])  # fmt: skip
    assert [r[:2] for r in unknown[0]] == [(404, "not_found")] * 3 + [(400, "bad_request")]
    assert unknown[0] == unknown[1] == unknown[2] and unknown[0][0][3]
    assert records(root, k) == []


def test_a_task_id_needs_the_key_of_its_service(tmp_path: Path) -> None:
    root = tmp_path / "store"
    _, tasks = make_store(root)

    def listed(service: Service) -> list[str]:
        with serving(api.server(service), {"Authorization": claim()}) as call:
            return [t["task"] for t in json.loads(call("GET", "/v1/tasks")[2])["tasks"]]

    first = listed(Service(root, ISSUERS, clock=lambda: CLOCK))
    second = listed(Service(root, ISSUERS, clock=lambda: CLOCK))
    # each service makes its own random key, so a task ID is good for one service only
    assert len(set(first + second)) == 4
    assert all(re.fullmatch(r"task:[0-9a-f]{64}", name) for name in first + second)
    with serving(
        api.server(Service(root, ISSUERS, clock=lambda: CLOCK)), {"Authorization": claim()}
    ) as call:
        assert error(call("GET", f"/v1/tasks/{first[0]}")) == (404, "not_found")
    # the ID is not a plain hash of the task key
    plain = {hashlib.sha256(tk.encode()).hexdigest() for tk in tasks.values()}
    assert not plain & {name[5:] for name in first + second}
    with pytest.raises(ValueError, match="32 bytes"):
        Service(root, ISSUERS, id_key=b"k" * 31)


HEX = re.compile(r"[0-9a-f]{64}")


def test_an_error_message_gives_no_key_of_the_store() -> None:
    """A message from the store can name an object or a log by its key."""
    key = "sha256:" + "ab" * 32
    for text in (f"object {key} is not there", f"answers/sha256-{'ab' * 32}/x.jsonl is held"):
        message = ApiError("bad_answer", text).message
        assert not HEX.search(message) and "(a key of the store)" in message
    assert (
        ApiError("bad_answer", "a correction needs a span").message == "a correction needs a span"
    )


def test_no_response_gives_a_key_of_the_store_or_a_hash_over_it(tmp_path: Path) -> None:
    """#698: a store key is a hash of its object. The object of a blind task holds the proposed
    value, and so does the packet. The key of each other task of the packet, of a model text and
    of each log entry is a hash over the packet key. With one of them, a person could test a
    guess of the value with no request. So the only hash in a response is a task ID, which
    needs the key of the service."""
    root = tmp_path / "store"
    k, tasks = make_store(root)
    text = "Revenue was 4,300 thousand."
    model_text = {
        "format": "model-text@1", "packet": k, "name": "summary", "text": text,
        "statements": [{"start": 0, "end": len(text), "cites": [at("4,200 thousand")]}],
    }  # fmt: skip
    with FolderStore(root) as store:
        written = write_tasks(store, k, EVERY, model_text).tasks
        tasks["summary"] = next(tk for tk, t in written if t["item"] == "model_text")
    ids = {field: id_of(tk) for field, tk in tasks.items()}
    service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
    seen = []
    with serving(api.server(service), {"Authorization": claim()}) as call:

        def ask(method: str, path: str, body: Any = None) -> int:
            seen.append(call(method, path, body))
            return seen[-1][0]

        def every_read() -> None:
            assert ask("GET", "/v1/tasks") == 200 and ask("GET", "/v1/tasks?limit=1") == 200
            for name in ids.values():
                assert ask("GET", f"/v1/tasks/{name}") == 200
                assert ask("GET", f"/v1/tasks/{name}/document") == 200
                assert ask("GET", f"/v1/tasks?cursor={name}") == 200

        every_read()
        revenue, blind = ids["revenue"], ids["net_income"]
        number = {"task": revenue, "verdict": "correct", "span": at("4,200")}
        assert ask("POST", "/v1/answers", number) == 409  # codes_not_kept
        assert ask("POST", "/v1/answers", {**number, "value": "5"}) == 409  # rejected
        assert ask("POST", "/v1/answers", {"task": revenue, "verdict": "confirm"}) == 400
        assert ask("POST", "/v1/answers", {**number, "codes_kept": ["SCALE_WORD"]}) == 201
        assert ask("POST", "/v1/answers", {"task": revenue, "verdict": "wrong"}) == 201
        assert (
            ask("POST", "/v1/answers", {"task": revenue, "verdict": "choose", "decision": 1}) == 201
        )
        guess = {"task": blind, "verdict": "correct", "span": at("310")}
        assert ask("POST", "/v1/answers", guess) == 409
        assert ask("POST", "/v1/answers", {**guess, "span": at("310 thousand")}) == 201
        verdicts = [{"statement": 0, "verdict": "supported"}]
        sent = {"task": ids["summary"], "verdict": "confirm", "statements": verdicts}
        assert ask("POST", "/v1/answers", sent) == 201
        # a refused log: another writer holds it
        httpd, held, token = page_server(root)
        with held, serving(httpd, token) as page:
            body = {"task": tasks["revenue"], "verdict": "unsure", "decision": None,
                    "codes_kept": [], "reason_seen": False, "keys": 1, "ms": 1}  # fmt: skip
            assert page("POST", "/api/answer", body)[0] == 200
            assert ask("POST", "/v1/answers", {"task": revenue, "verdict": "unsure"}) == 409
            assert error(seen[-1]) == (409, "log_refused")
        every_read()
    # each hash that a person can test: each key of the store, and each entry hash of a log
    with FolderStore(root) as store:
        keys, _ = store.object_keys()
        log = store.read(("answers", k, reviewer_key("ana")))
    testable = {key[7:] for key in keys} | {k[7:], *(tk[7:] for tk in tasks.values())}
    testable |= {r[name][7:] for r in log for name in ("entry_sha256", "previous") if r[name]}
    testable |= {hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    testable |= {m for p in root.rglob("*") for m in HEX.findall(str(p.relative_to(root)))}
    assert len(log) == 6 and len(testable) > 12
    good = {name[5:] for name in ids.values()}
    for status, _, text in seen:
        found = set(HEX.findall(text))
        assert not found & testable, (status, text)
        # the only hash in a response is a task ID
        assert found <= good, (status, text)
        assert "sha256" not in text and "entry_sha256" not in text and '"packet"' not in text

    # a member of a response is never a store key, at each depth
    def strings(value: Any) -> Iterator[str]:
        if isinstance(value, dict):
            for name, member in value.items():
                yield name
                yield from strings(member)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
        elif isinstance(value, str):
            yield value

    for _, _, text in seen:
        for string in strings(json.loads(text)):
            assert not re.fullmatch(r"(sha256:)?[0-9a-f]{64}", string), string


def test_a_blind_task_gets_no_question_about_a_choice(served: Served) -> None:
    """#496: the page asks again when the value differs from a choice only in its sign. A blind
    task does not get that question, because it tells the sign of the proposed value."""
    root, k, tasks, call = served
    real, blind = tasks["net_income"], id_of(tasks["net_income"])
    with FolderStore(root) as store:
        # the page server asks about the sign of the text and about the sign of the choice
        selection = {"task": real, "verdict": "correct", **u16("310 thousand"),
                     "value": "-310000"}  # fmt: skip
        asked = [a["text"] for a in Review(store, "ben").check(selection)["ask"]]
    assert ["value 1 of the task is positive" in a for a in asked] == [False, True]
    body = {"task": blind, "verdict": "correct", "span": at("310 thousand"), "value": "-310000"}
    response = call("POST", "/v1/answers", body)
    assert error(response) == (409, "codes_not_kept")  # the gate check comes first
    kept = json.loads(response[2])["error"]["codes"]
    response = call("POST", "/v1/answers", {**body, "codes_kept": kept})
    assert error(response) == (409, "parts_disagree")
    message = json.loads(response[2])["error"]["message"]
    assert message == "the parts of the correction do not agree: " + asked[0]
    assert "of the task" not in message and "310,000" not in message
    assert records(root, k) == []


def test_a_model_text_task_gives_its_statements_and_takes_a_verdict_for_each(
    tmp_path: Path,
) -> None:
    """The task holds no model text, so the task response gives each statement and its cites.
    The model text has a letter of two bytes, and the statement spans are in bytes."""
    root = tmp_path / "store"
    k, _ = make_store(root)
    text = "Caf\u00e9 revenue was 4,300 thousand. Net income rose."
    first = len("Caf\u00e9 revenue was 4,300 thousand.".encode())
    model_text = {
        "format": "model-text@1", "packet": k, "name": "summary", "text": text,
        "statements": [
            {"start": 0, "end": first, "cites": [at("4,200 thousand")]},
            {"start": first + 1, "end": len(text.encode()), "cites": []},
        ],
    }  # fmt: skip
    with FolderStore(root) as store:
        written = write_tasks(store, k, EVERY, model_text).tasks
        tk = id_of(next(tk for tk, t in written if t["item"] == "model_text"))
    service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
    with serving(api.server(service), {"Authorization": claim()}) as call:
        task = json.loads(call("GET", f"/v1/tasks/{tk}")[2])
        assert (task["mode"], task["field"], task["definition"]) == ("review", "summary", None)
        # the body has the count of the statements, and not the key of the model text
        assert task["body"]["model_text"] == {"statements": 2} and "packet" not in task["body"]
        assert task["statements"] == [
            {"text": "Caf\u00e9 revenue was 4,300 thousand.", "cites": [at("4,200 thousand")]},
            {"text": "Net income rose.", "cites": []},
        ]
        # each cite is a span of the document of the task
        document = json.loads(call("GET", f"/v1/tasks/{tk}/document")[2])["text"].encode()
        cite = task["statements"][0]["cites"][0]
        assert document[cite["start"] : cite["end"]] == b"4,200 thousand"
        verdicts = [{"statement": 0, "verdict": "unsupported"},
                    {"statement": 1, "verdict": "unsure"}]  # fmt: skip
        short = {"task": tk, "verdict": "confirm", "statements": verdicts[:1]}
        assert error(call("POST", "/v1/answers", short)) == (400, "bad_answer")
        response = call("POST", "/v1/answers", {**short, "statements": verdicts})
        assert response[0] == 201, response[2]
        record = json.loads(response[2])["record"]
        assert record["statements"] == verdicts and "task" not in record
    assert records(root, k)[0]["statements"] == verdicts


def test_a_calibrate_label_task_is_not_a_task_of_the_api(tmp_path: Path) -> None:
    from groundgate.review.labels import label_tasks
    from groundgate.store import key
    from groundgate.store.packets import load_packet

    root = tmp_path / "store"
    k, tasks = make_store(root)
    with FolderStore(root) as store:
        packet = load_packet(store, k)
        labels = label_tasks(k, packet.receipt, packet.text, Review(store, "ana").docs[k].schema,
                             raw_schema=packet.schema)  # fmt: skip
        assert labels
        for _, task in labels.values():
            data = json.dumps(task, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            store.put("task@1", data.encode("utf-8"))
        label = next(iter(labels))
        assert key("task@1", store.get("task@1", label)) == label
    service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
    with serving(api.server(service), {"Authorization": claim()}) as call:
        listed = json.loads(call("GET", "/v1/tasks")[2])["tasks"]
        served = [id_of(tasks["net_income"]), id_of(tasks["revenue"])]
        assert [t["task"] for t in listed] == served
        # the label task gets no task ID
        name = id_of(label)
        assert error(call("GET", f"/v1/tasks/{name}")) == (404, "not_found")
        assert error(call("GET", f"/v1/tasks/{name}/document")) == (404, "not_found")
        body = {"task": name, "verdict": "unsure"}
        assert error(call("POST", "/v1/answers", body)) == (404, "not_found")
        assert error(call("GET", f"/v1/tasks?cursor={name}")) == (400, "bad_request")
    assert records(root, k) == []


# No state outside the store


def test_the_service_keeps_no_state_outside_the_store(tmp_path: Path) -> None:
    """The service starts on an empty store. It serves a packet that comes later, it holds no
    lock of an answer log between two requests, and it reads an answer that another writer
    appends."""
    root = tmp_path / "store"
    FolderStore(root).close()
    service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
    with serving(api.server(service), {"Authorization": claim()}) as call:
        assert json.loads(call("GET", "/v1/tasks")[2])["tasks"] == []
        k, tasks = make_store(root)
        assert len(json.loads(call("GET", "/v1/tasks")[2])["tasks"]) == 2
        revenue = id_of(tasks["revenue"])
        body = {"task": revenue, "verdict": "unsure"}
        assert call("POST", "/v1/answers", body)[0] == 201
        assert list(root.rglob("*.lock")) == []
        # another writer appends to the same log: the page server, as ana
        httpd, store, token = page_server(root)
        with store, serving(httpd, token) as page:
            sent = {"task": tasks["revenue"], "verdict": "choose", "decision": 1,
                    "codes_kept": [], "reason_seen": False, "keys": 1, "ms": 1}  # fmt: skip
            assert page("POST", "/api/answer", sent)[0] == 200
            # while that writer holds the log, the API cannot append
            refused = call("POST", "/v1/answers", body)
            assert error(refused) == (409, "log_refused")
            # the message names no log: the path of a log has the packet key
            message = json.loads(refused[2])["error"]["message"]
            assert message == "the answer log cannot take the answer now"
        listed = json.loads(call("GET", "/v1/tasks")[2])["tasks"]
        assert [t["field"] for t in listed] == ["net_income"]
        answered = json.loads(call("GET", f"/v1/tasks/{revenue}")[2])["answered"]
        assert answered == "choose"
        assert call("POST", "/v1/answers", body)[0] == 201
    assert [r["verdict"] for r in records(root, k)] == ["unsure", "choose", "unsure"]
    assert vars(service).keys() == {"root", "auth", "policy", "_clock", "_id_key"}


def test_a_packet_that_does_not_match_its_receipt_gives_no_task(tmp_path: Path) -> None:
    root = tmp_path / "store"
    k, tasks = make_store(root)
    service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
    assert service.skipped() == []
    with FolderStore(root) as store:
        packet = json.loads(store.get("packet@1", k))
        store.forget(packet["document"]["text"], "a test")
    assert len(service.skipped()) == 1
    assert service.tasks("ana")["tasks"] == []
    with pytest.raises(ApiError) as refused:
        service.task("ana", id_of(tasks["revenue"]))
    assert refused.value.code == "not_found" and refused.value.status == 404


# The server


def test_a_head_request_and_an_unknown_method_get_the_same_checks(served: Served) -> None:
    _, _, _, call = served
    status, headers, body = call("HEAD", "/v1/tasks")
    assert (status, headers["Allow"], body) == (405, "GET", "")
    assert error(call("BREW", "/v1/tasks")) == (405, "method_not_allowed")
    assert error(call("BREW", "/v1/tasks", None, {"Authorization": None})) == (401, "no_claim")
    response = call("GET", "/v1/answers")
    assert error(response) == (405, "method_not_allowed") and response[1]["Allow"] == "POST"


def test_a_bad_request_line_gets_a_json_error(tmp_path: Path) -> None:
    root = tmp_path / "store"
    FolderStore(root).close()
    httpd = api.server(Service(root, ISSUERS))
    address = ("127.0.0.1", httpd.server_port)
    with serving(httpd, {}), socket.create_connection(address, timeout=10) as sock:
        # one line only: bytes that the server does not read can reset the connection
        sock.sendall(b"GET /v1/tasks HTTP/1.1 extra words\r\n")
        data = b""
        while chunk := sock.recv(65536):
            data += chunk
    # When http.server cannot read the request line, an older release of Python sends the body
    # only. A newer release sends a status line and the headers first.
    body = data
    if data.startswith(b"HTTP/"):
        assert data.startswith(b"HTTP/1.0 400 ")
        body = data.split(b"\r\n\r\n", 1)[1]
    assert b"html" not in data and json.loads(body)["error"]["code"] == "bad_request"


def test_a_failure_of_the_service_gives_no_store_data(tmp_path: Path) -> None:
    root = tmp_path / "store"
    make_store(root)
    service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)

    def fail(actor: str, query: str = "") -> dict[str, Any]:
        raise RuntimeError("the text of the document: 4,200 thousand")

    service.tasks = fail  # type: ignore[method-assign]
    with serving(api.server(service), {"Authorization": claim()}) as call:
        response = call("GET", "/v1/tasks")
        assert error(response) == (500, "server_error") and "4,200" not in response[2]


# The command


def test_review_api_checks_its_arguments(tmp_path: Path, capsys: Any) -> None:
    root = tmp_path / "store"
    make_store(root)
    token = tmp_path / "token"
    token.write_text(TOKEN + "\n", encoding="utf-8")
    issuers = tmp_path / "issuers.json"
    issuers.write_text(
        json.dumps({
            "groundgate_review_issuers": 1,
            "issuers": [{"issuer": ISSUER, "secret": b64(SECRET)}],
        }),
        encoding="utf-8",
    )  # fmt: skip
    base = ["review", "api", "--store", str(root)]
    static = ["--token-file", str(token), "--reviewer", "ana"]
    short = tmp_path / "short"
    short.write_text("short\n", encoding="utf-8")
    refused = [
        base,  # no claim source
        [*base, "--token-file", str(token)],  # no reviewer
        [*base, "--reviewer", "ana"],  # no token
        [*base, *static, "--issuers", str(issuers)],  # both
        [*base, "--token-file", str(short), "--reviewer", "ana"],
        [*base, "--token-file", str(tmp_path / "none"), "--reviewer", "ana"],
        [*base, "--issuers", str(token)],  # not JSON
        [*base, *static, "--port", "70000"],
        ["review", "api", "--store", str(tmp_path / "none"), *static],
    ]
    for args in refused:
        assert main(args) == 2, args
    assert "The review API" not in capsys.readouterr().out


def test_review_api_serves_until_ctrl_c(
    tmp_path: Path, capsys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "store"
    make_store(root)
    token = tmp_path / "token"
    token.write_text(TOKEN + "\n", encoding="utf-8")
    seen: list[tuple[int, str]] = []

    def one_request(httpd: ThreadingHTTPServer, poll_interval: float = 0.5) -> None:
        thread = Thread(target=httpd.handle_request, daemon=True)
        thread.start()
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
        conn.request("GET", "/v1/tasks", headers={"Authorization": "Bearer " + TOKEN})
        r = conn.getresponse()
        seen.append((r.status, r.read().decode("utf-8")))
        conn.close()
        thread.join()
        raise KeyboardInterrupt

    monkeypatch.setattr(ThreadingHTTPServer, "serve_forever", one_request)
    args = ["review", "api", "--store", str(root), "--token-file", str(token), "--reviewer", "ana"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert out.startswith("The review API groundgate-review/1 is on http://127.0.0.1:")
    assert TOKEN not in out
    ((status, body),) = seen
    assert status == 200 and len(json.loads(body)["tasks"]) == 2
