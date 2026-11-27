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
from groundgate.store import FolderStore, Locked, StoreError, reviewer_key
from groundgate.store import key as object_key
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
NO_AUDIT = {**EVERY, "audit": {"rate": "0", "seed": "s"}}  # no blind task
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


def make_store(
    root: Path, policy: dict[str, Any] = EVERY, document: str = "doc-1"
) -> tuple[str, dict[str, str]]:
    """A store with one packet and its two tasks: the revenue task is a review task with two
    choices, and the net income task is an audit task, so it is blind. With NO_AUDIT, the packet
    has the revenue task only."""
    with FolderStore(root) as store:
        k, _ = admit_packet(store, TEXT, SCHEMA, CANDIDATES, None, document, None)
        tasks = {t["slot"]["field"]: tk for tk, t in write_tasks(store, k, policy).tasks}
    return k, tasks


def fill(root: Path, task: str, name: str = "zed") -> None:
    """``name`` answers the blind task ``task`` through the page. With agree 1, the blind task
    then has its actor, so the next actor of the packet gets the review group (SPEC §4.20)."""
    with FolderStore(root) as store:
        Review(store, name, EVERY, clock=lambda: CLOCK).write(
            {"task": task, "verdict": "not_in_document", "decision": None, "codes_kept": [],
             "reason_seen": False, "keys": 0, "ms": 0}
        )  # fmt: skip


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


@pytest.fixture
def reviewing(tmp_path: Path) -> Iterator[tuple[Path, str, dict[str, str], Call]]:
    """As ``served``, but zed answered the blind task, so the group of ana is the review
    group."""
    root = tmp_path / "store"
    k, tasks = make_store(root)
    fill(root, tasks["net_income"])
    service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
    with serving(api.server(service, first_agree=1), {"Authorization": claim()}) as call:
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
def test_vector(path: Path, request: pytest.FixtureRequest) -> None:
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
            sources = {int(index): d for index, d in v["sources"].items()}
            view = api.task_view(v["task"], sources)
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
        elif kind == "group":
            got = {"group": api.group(v["tasks"], v["logs"], v["actor"], v["agree"])}
        elif kind == "start":
            got = run_start_vector(v, request.getfixturevalue("tmp_path"))
        elif kind == "left-out":
            got = {"decisions": api.left_out(v["tasks"], v["task"], v["count"])}
        elif kind == "errors":
            got = api.STATUS
        else:
            assert kind == "request"
            empty: Call = request.getfixturevalue("empty")
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
        "claim", "token", "task", "task-id", "statements", "page", "answer", "group", "start",
        "left-out", "request", "errors",
    }  # fmt: skip
    claims = {v["expected"].get("error") for v in vectors if v["kind"] == "claim"}
    assert claims == {None, "no_claim", "bad_claim", "unknown_issuer", "expired_claim"}
    requests = {v["expected"].get("error") for v in vectors if v["kind"] == "request"}
    # the other codes need a task: the store tests below give them
    assert requests == {
        None, "wrong_host", "no_claim", "bad_claim", "not_found", "method_not_allowed",
        "bad_request", "unsupported_media_type", "length_required", "body_too_large",
    }  # fmt: skip


# The recorded value of agree


def recorded_agree(root: Path) -> int:
    name = (root / "state" / "review-api").read_text(encoding="ascii")
    return json.loads(FolderStore(root).get("review-api-state@1", name))["agree"]


def run_start_vector(v: dict[str, Any], root: Path) -> dict[str, Any]:
    store = FolderStore(root)
    if v["recorded_agree"] is not None:
        with store.review_api(v["recorded_agree"]):
            pass
    if v["answer_log"]:
        _, tasks = make_store(root)
        fill(root, tasks["net_income"])
    before = answer_logs(root)
    got: dict[str, Any] = {}
    try:
        with store.review_api(v["agree"], first_agree=v.get("first_agree")):
            pass
    except StoreError as exc:
        got["error"] = str(exc)
    assert answer_logs(root) == before
    got["agree"] = recorded_agree(root) if (root / "state" / "review-api").exists() else None
    return got


@pytest.mark.parametrize(
    "data",
    [b'{"agree":', b'{"agree":true}', b'{"agree":1.0}', b'{"agree":0}', b'{"agree":1,"x":2}'],
)
def test_start_refuses_invalid_review_api_state(tmp_path: Path, data: bytes) -> None:
    store = FolderStore(tmp_path)
    with store.review_api(1):
        pass
    state_key = object_key("review-api-state@1", data)[7:]
    objects = tmp_path / "objects" / state_key[:2]
    objects.mkdir(exist_ok=True)
    (objects / state_key[2:]).write_bytes(data)
    pointer = tmp_path / "state" / "review-api"
    pointer.write_text("sha256:" + state_key, encoding="ascii")

    with pytest.raises(StoreError, match="cannot read the review API state"), store.review_api(1):
        pytest.fail("the store accepted invalid state")
    assert pointer.read_text(encoding="ascii") == "sha256:" + state_key


def test_start_refuses_a_torn_key_or_a_missing_or_changed_state_object(tmp_path: Path) -> None:
    store = FolderStore(tmp_path)
    with store.review_api(1):
        pass
    pointer = tmp_path / "state" / "review-api"
    name = pointer.read_text(encoding="ascii")
    obj = tmp_path / "objects" / name[7:9] / name[9:]

    pointer.write_text(name[:-1], encoding="ascii")
    with pytest.raises(StoreError, match="cannot read the review API state"), store.review_api(2):
        pytest.fail("the store accepted a torn key")
    pointer.write_text(name, encoding="ascii")
    obj.write_bytes(b'{"agree":2}')
    with pytest.raises(StoreError, match="does not match its key"), store.review_api(2):
        pytest.fail("the store accepted a changed object")
    obj.unlink()
    with pytest.raises(StoreError, match="cannot read the review API state"), store.review_api(2):
        pytest.fail("the store accepted a missing object")
    assert pointer.read_text(encoding="ascii") == name


@pytest.mark.parametrize(
    ("recorded", "error"),
    [(None, "the store has answers and no recorded agree"), (1, "the store has an answer log")],
)
def test_start_refuses_an_empty_log_or_bad_log_path(
    tmp_path: Path, recorded: int | None, error: str
) -> None:
    store = FolderStore(tmp_path)
    if recorded is not None:
        with store.review_api(recorded):
            pass
    folder = tmp_path / "logs" / "answers" / ("0" * 64)
    folder.mkdir(parents=True)
    log = folder / ("0" * 64 + ".jsonl")
    log.touch()
    with pytest.raises(StoreError, match=error), store.review_api(2):
        pytest.fail("the store accepted the start with an empty log")
    log.unlink()
    log.mkdir()
    with pytest.raises(StoreError, match="cannot check for an answer log"), store.review_api(2):
        pytest.fail("the store accepted the start with a bad log path")
    if recorded is None:
        assert not (tmp_path / "state" / "review-api").exists()
    else:
        assert recorded_agree(tmp_path) == recorded


# The read operations


def test_the_list_and_a_review_task_and_its_document(reviewing: Served) -> None:
    _, k, tasks, call = reviewing
    revenue = id_of(tasks["revenue"])
    status, headers, body = call("GET", "/v1/tasks")
    assert status == 200 and headers["Cache-Control"] == "no-store"
    assert headers["Content-Security-Policy"] == api.CSP
    assert json.loads(body) == {
        "api": "groundgate-review/1",
        "actor": "ana",
        "tasks": [
            {"task": revenue, "document": "doc-1", "mode": "review", "field": "revenue",
             "key": None},
        ],
        "next": None,
    }  # fmt: skip
    # the blind task is in the group of zed, so it is not in the list of ana
    page = json.loads(call("GET", "/v1/tasks?limit=1")[2])
    assert [t["field"] for t in page["tasks"]] == ["revenue"] and page["next"] is None

    status, _, body = call("GET", f"/v1/tasks/{revenue}")
    task = json.loads(body)
    with FolderStore(reviewing[0]) as store:
        stored = json.loads(store.get("task@1", tasks["revenue"]))
    # the body is the task object without its packet key and without an index of the receipt:
    # each choice has its number in the task, and the source of its evidence
    assert stored.pop("packet") == k
    assert stored["slot"].pop("decisions") == [1, 2]
    assert [choice.pop("decision") for choice in stored["choices"]] == [1, 2]
    stored["choices"] = [
        {"choice": number, **choice, "source": "document", "ref": None}
        for number, choice in enumerate(stored["choices"], 1)
    ]
    assert status == 200 and task == {
        "api": "groundgate-review/1", "task": revenue, "document": "doc-1", "mode": "review",
        "field": "revenue", "key": None, "definition": None, "options": None, "answered": None,
            "body": stored,
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
    reviewing: Served,
) -> None:
    root, k, tasks, call = reviewing
    revenue = id_of(tasks["revenue"])
    good = {"task": revenue, "verdict": "choose", "choice": 1}
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
    k, tasks = make_store(root, NO_AUDIT)
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
    k, tasks = make_store(by_cli, NO_AUDIT)
    assert make_store(by_api, NO_AUDIT) == (k, tasks)
    revenue = id_of(tasks["revenue"])
    plain = {"reason_seen": False, "keys": 2, "ms": 900}
    number = "4,200"  # without its scale word: the gate flags it, and the person keeps the code
    answers: list[tuple[dict[str, Any], dict[str, Any]]] = [
        # the verdict wrong gives an answer@2 record
        ({"task": tasks["revenue"], "verdict": "wrong"}, {"task": revenue, "verdict": "wrong"}),
        ({"task": tasks["revenue"], "verdict": "choose", "decision": 1},
         {"task": revenue, "verdict": "choose", "choice": 1}),
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
    # the response gives the record without its task key and without the members of the store,
    # and with the number of the choice in place of the index of the decision
    left_out = ("task", "decision", "sequence", "previous", "entry_sha256")
    assert [r["decision"] for r in stored] == [None, 1, None, None]
    for response, record in zip(written, stored, strict=True):
        assert record["task"] == tasks["revenue"]
        assert response == {
            "api": "groundgate-review/1", "actor": "ana", "task": revenue,
            "record": {
                **{name: v for name, v in record.items() if name not in left_out},
                "choice": None if record["decision"] is None else 1,
            },
        }  # fmt: skip
    # the resolution of each store is the same too
    with FolderStore(by_cli) as a, FolderStore(by_api) as b:
        resolved = [write_resolution(s, k, None, ["ana"]).resolution for s in (a, b)]
    assert resolved[0] == resolved[1] and resolved[0] is not None


def test_the_gate_checks_a_correction_again(reviewing: Served) -> None:
    root, k, tasks, call = reviewing
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
        {"task": revenue, "verdict": "choose", "choice": 3},  # not a choice
        {"task": revenue, "verdict": "choose"},
        {"task": revenue, "verdict": "unsure", "statements": []},
    ]
    for body in refused:
        assert error(call("POST", "/v1/answers", body)) == (400, "bad_answer"), body
    assert records(root, k) == []
    assert call("POST", "/v1/answers", {**number, "codes_kept": ["SCALE_WORD"]})[0] == 201
    # the answer settles the slot: the task leaves the list, and the task names the verdict
    listed = json.loads(call("GET", "/v1/tasks")[2])
    assert listed["tasks"] == []
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
        "field": "net_income", "key": None, "definition": "The profit after tax.", "options": None,
        "answered": None, "body": None, "statements": None,
    }  # fmt: skip
    # a blind task takes no verdict about a shown value
    for verdict in ("confirm", "choose", "adjust_span", "wrong"):
        body = {"task": blind, "verdict": verdict, "choice": 1, "span": at("310")}
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


def test_a_choice_names_the_source_of_its_evidence(tmp_path: Path) -> None:
    """#702: two choices have the same offsets, one in the document and one in a reference.
    Only the source tells which text the span is in."""
    text, reference = "Limit: $7,000 for this year.\n", "Limit: $8,000 for each year.\n"
    span = {"start": 7, "end": 13}
    candidates = [
        {"id": "c1", "field": "limit", "value": "7000", "unit": "USD",
         "evidence": [{**span, "text": "$7,000"}]},
        {"id": "c2", "field": "limit", "value": "8000", "unit": "USD",
         "evidence": [{"source": "reference", "ref": "r", **span, "text": "$8,000"}]},
    ]  # fmt: skip
    schema = {"fields": {"limit": {"type": "number", "unit": "USD"}}}
    root = tmp_path / "store"
    with FolderStore(root) as store:
        k, _ = admit_packet(
            store, text, schema, candidates, None, "doc-1", None,
            references=[{"id": "r", "text": reference}],
        )  # fmt: skip
        ((key, _),) = write_tasks(store, k, EVERY).tasks
    service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
    with serving(api.server(service), {"Authorization": claim()}) as call:
        task = json.loads(call("GET", f"/v1/tasks/{id_of(key)}")[2])
        document = json.loads(call("GET", f"/v1/tasks/{id_of(key)}/document")[2])["text"]
    choices = {c["value"]: c for c in task["body"]["choices"]}
    assert {value: (c["evidence"], c["source"], c["ref"]) for value, c in choices.items()} == {
        "7000": (span, "document", None),
        "8000": (span, "reference", "r"),
    }
    assert sorted(c["choice"] for c in choices.values()) == [1, 2]
    assert document == text and reference not in json.dumps(task)


def test_no_response_gives_an_index_of_the_receipt(tmp_path: Path) -> None:
    """The receipt sorts its decisions by the digest of the candidate. So the indexes of the
    revenue task change with the value of the blind tax task: 0 and 2 for one value, 0 and 1
    for the other. Each response is the same for the two values."""
    text = "Revenue was 10. Revenue was 20. Tax was 10. Tax was 20."
    schema = {"fields": {"revenue": {"type": "number"}, "tax": {"type": "number"}}}

    def span(words: str) -> dict[str, Any]:
        return {"start": text.index(words), "end": text.index(words) + len(words), "text": words}

    seen, indexes = [], []
    for value in ("10", "20"):
        candidates = [
            {"id": "c1", "field": "revenue", "value": "10", "evidence": span("Revenue was 10")},
            {"id": "c2", "field": "revenue", "value": "20", "evidence": span("Revenue was 20")},
            {"id": "n5", "field": "tax", "value": value, "evidence": span(f"Tax was {value}")},
        ]
        root = tmp_path / value
        with FolderStore(root) as store:
            k, _ = admit_packet(store, text, schema, candidates, None, "doc-1", None)
            tasks = {t["slot"]["field"]: (tk, t) for tk, t in write_tasks(store, k, EVERY).tasks}
        assert (
            tasks["tax"][1]["mode"] == "audit" and tasks["tax"][1]["choices"][0]["value"] == value
        )
        indexes.append(tasks["revenue"][1]["slot"]["decisions"])
        names = {id_of(tk): field for field, (tk, _) in tasks.items()}
        service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
        with serving(api.server(service), {"Authorization": claim()}) as call:
            revenue, tax = (id_of(tasks[field][0]) for field in ("revenue", "tax"))
            # ana gets the blind task, and ben then gets the review group
            ben = {"Authorization": claim(sub="ben")}
            gone = {"task": tax, "verdict": "not_in_document"}
            responses = [
                call("GET", "/v1/tasks"),
                call("GET", f"/v1/tasks/{tax}"),
                call("POST", "/v1/answers", gone),
                call("GET", "/v1/tasks", None, ben),
                call("GET", f"/v1/tasks/{revenue}", None, ben),
                call("GET", f"/v1/tasks/{revenue}/document", None, ben),
                call("POST", "/v1/answers", {"task": revenue, "verdict": "choose", "choice": 2},
                     ben),
                call("POST", "/v1/answers", {"task": revenue, "verdict": "choose", "choice": 3},
                     ben),
            ]  # fmt: skip
        bodies = []
        for status, _, body in responses:
            for name, field in names.items():
                body = body.replace(name, field)
            bodies.append((status, json.loads(body)))
        seen.append(bodies)
        # the answer names choice 2, and the record has the index of its decision
        assert bodies[6][1]["record"]["choice"] == 2 and bodies[7][0] == 400
        assert records(root, k, "ben")[0]["decision"] == indexes[-1][1]
    assert indexes == [[0, 2], [0, 1]]
    assert seen[0] == seen[1]
    assert [status for status, _ in seen[0]] == [200, 200, 201, 200, 200, 200, 201, 400]


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
    assert len(first) == len(second) == 1 and len(set(first + second)) == 2
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
    other, more = make_store(root, NO_AUDIT, "doc-2")
    assert other != k and list(more) == ["revenue"]
    tasks["revenue of doc-2"] = more["revenue"]
    text = "Revenue was 4,300 thousand."
    model_text = {
        "format": "model-text@1", "packet": other, "name": "summary", "text": text,
        "statements": [{"start": 0, "end": len(text), "cites": [at("4,200 thousand")]}],
    }  # fmt: skip
    with FolderStore(root) as store:
        written = write_tasks(store, other, NO_AUDIT, model_text).tasks
        tasks["summary"] = next(tk for tk, t in written if t["item"] == "model_text")
    ids = {field: id_of(tk) for field, tk in tasks.items()}
    service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
    seen = []
    ben = {"Authorization": claim(sub="ben")}
    with serving(api.server(service), {"Authorization": claim()}) as call:

        def ask(method: str, path: str, body: Any = None, who: Any = None) -> int:
            seen.append(call(method, path, body, who))
            return seen[-1][0]

        def every_read(who: Any, fields: list[str]) -> None:
            assert ask("GET", "/v1/tasks", None, who) == 200
            assert ask("GET", "/v1/tasks?limit=1", None, who) == 200
            for field in fields:
                assert ask("GET", f"/v1/tasks/{ids[field]}", None, who) == 200
                assert ask("GET", f"/v1/tasks/{ids[field]}/document", None, who) == 200
                assert ask("GET", f"/v1/tasks?cursor={ids[field]}", None, who) == 200

        # ana gets the blind task of doc-1 and the review group of doc-2
        mine = ["net_income", "revenue of doc-2", "summary"]
        every_read(None, mine)
        revenue, blind = ids["revenue"], ids["net_income"]
        guess = {"task": blind, "verdict": "correct", "span": at("310")}
        assert ask("POST", "/v1/answers", guess) == 409
        assert ask("POST", "/v1/answers", {**guess, "span": at("310 thousand")}) == 201
        # the blind task has its actor, so ben gets the review group of doc-1
        every_read(ben, ["revenue", "revenue of doc-2", "summary"])
        number = {"task": revenue, "verdict": "correct", "span": at("4,200")}
        assert ask("POST", "/v1/answers", number, ben) == 409  # codes_not_kept
        assert ask("POST", "/v1/answers", {**number, "value": "5"}, ben) == 409  # rejected
        assert ask("POST", "/v1/answers", {"task": revenue, "verdict": "confirm"}, ben) == 400
        assert ask("POST", "/v1/answers", {**number, "codes_kept": ["SCALE_WORD"]}, ben) == 201
        assert ask("POST", "/v1/answers", {"task": revenue, "verdict": "wrong"}, ben) == 201
        choose = {"task": revenue, "verdict": "choose", "choice": 1}
        assert ask("POST", "/v1/answers", choose, ben) == 201
        verdicts = [{"statement": 0, "verdict": "supported"}]
        sent = {"task": ids["summary"], "verdict": "confirm", "statements": verdicts}
        assert ask("POST", "/v1/answers", sent) == 201
        # a refused log: another writer holds it
        httpd, held, token = page_server(root)
        with held, serving(httpd, token) as page:
            body = {"task": tasks["revenue"], "verdict": "unsure", "decision": None,
                    "codes_kept": [], "reason_seen": False, "keys": 1, "ms": 1}  # fmt: skip
            assert page("POST", "/api/answer", body)[0] == 200
            assert ask("POST", "/v1/answers", {"task": blind, "verdict": "unsure"}) == 409
            assert error(seen[-1]) == (409, "log_refused")
        every_read(None, mine)
        every_read(ben, ["revenue", "revenue of doc-2", "summary"])
    # each hash that a person can test: each key of the store, and each entry hash of a log
    with FolderStore(root) as store:
        keys, _ = store.object_keys()
        log = store.read(("answers", k, reviewer_key("ana")))
        log += store.read(("answers", other, reviewer_key("ana")))
        log += store.read(("answers", k, reviewer_key("ben")))
    testable = {key[7:] for key in keys} | {k[7:], other[7:], *(tk[7:] for tk in tasks.values())}
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
    k, _ = make_store(root, NO_AUDIT)
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
        written = write_tasks(store, k, NO_AUDIT, model_text).tasks
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


def test_a_model_text_task_of_a_packet_with_a_blind_task_is_in_the_review_group(
    tmp_path: Path,
) -> None:
    """A statement can state the value that the blind task hides. The model text task is in the
    review group, so an actor who gets the blind task never gets the statements."""
    root = tmp_path / "store"
    k, tasks = make_store(root)
    text = "Net income was 310 thousand."
    model_text = {
        "format": "model-text@1", "packet": k, "name": "summary", "text": text,
        "statements": [{"start": 0, "end": len(text), "cites": [at("310 thousand")]}],
    }  # fmt: skip
    with FolderStore(root) as store:
        written = write_tasks(store, k, EVERY, model_text).tasks
        summary = id_of(next(tk for tk, t in written if t["item"] == "model_text"))
    blind = id_of(tasks["net_income"])
    ben = {"Authorization": claim(sub="ben")}
    service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
    with serving(api.server(service), {"Authorization": claim()}) as call:
        for _ in range(2):
            listed = json.loads(call("GET", "/v1/tasks")[2])["tasks"]
            assert [t["field"] for t in listed] in (["net_income"], [])
            seen = [
                call("GET", "/v1/tasks"),
                call("GET", f"/v1/tasks/{summary}"),
                call("GET", f"/v1/tasks/{summary}/document"),
                call("POST", "/v1/answers", {"task": summary, "verdict": "unsure"}),
            ]
            assert [error(response) for response in seen[1:]] == [(403, "not_assigned")] * 3
            assert all("310 thousand." not in body for _, _, body in seen)
            # the second pass: ana answered the blind task, and the rule is the same
            call(
                "POST",
                "/v1/answers",
                {"task": blind, "verdict": "correct", "span": at("310 thousand")},
            )
        assert json.loads(call("GET", f"/v1/tasks/{blind}")[2])["answered"] == "correct"
        # ben gets the review group, with the statements
        listed = json.loads(call("GET", "/v1/tasks", None, ben)[2])["tasks"]
        assert sorted(t["field"] for t in listed) == ["revenue", "summary"]
        task = json.loads(call("GET", f"/v1/tasks/{summary}", None, ben)[2])
        assert task["statements"] == [{"text": text, "cites": [at("310 thousand")]}]
    assert [r["verdict"] for r in records(root, k)] == ["correct", "correct"]


def test_one_actor_never_gets_a_blind_task_and_another_task_of_its_packet(served: Served) -> None:
    """#703: the group of an actor is one blind task or the review group. The rule holds after
    an answer, and after a later answer that replaces it."""
    root, k, tasks, call = served
    revenue, blind = id_of(tasks["revenue"]), id_of(tasks["net_income"])
    ben = {"Authorization": claim(sub="ben")}

    def fields(who: Any = None) -> list[str]:
        return [t["field"] for t in json.loads(call("GET", "/v1/tasks", None, who)[2])["tasks"]]

    def refused(task: str, who: Any = None) -> list[tuple[int, str]]:
        return [
            error(call("GET", f"/v1/tasks/{task}", None, who)),
            error(call("GET", f"/v1/tasks/{task}/document", None, who)),
            error(call("POST", "/v1/answers", {"task": task, "verdict": "unsure"}, who)),
        ]

    # with no answer, each actor gets the blind task first
    assert fields() == fields(ben) == ["net_income"]
    assert refused(revenue) == [(403, "not_assigned")] * 3
    # an unsure answer counts as no answer, so ben still gets the blind task
    assert call("POST", "/v1/answers", {"task": blind, "verdict": "unsure"})[0] == 201
    assert fields() == [] and fields(ben) == ["net_income"]
    assert refused(revenue) == [(403, "not_assigned")] * 3
    # a later answer replaces it, and the group of ana stays the blind task
    gone = {"task": blind, "verdict": "not_in_document"}
    assert call("POST", "/v1/answers", gone)[0] == 201
    assert refused(revenue) == [(403, "not_assigned")] * 3
    assert json.loads(call("GET", f"/v1/tasks/{blind}")[2])["answered"] == "not_in_document"
    # the blind task has agree actors now, so ben gets the review group and never the blind task
    assert fields(ben) == ["revenue"]
    assert refused(blind, ben) == [(403, "not_assigned")] * 3
    assert call("POST", "/v1/answers", {"task": revenue, "verdict": "wrong"}, ben)[0] == 201
    assert refused(blind, ben) == [(403, "not_assigned")] * 3
    assert [r["verdict"] for r in records(root, k)] == ["unsure", "not_in_document"]
    assert [r["verdict"] for r in records(root, k, "ben")] == ["wrong"]


def test_the_check_of_a_blind_correction_reads_no_hidden_candidate(tmp_path: Path) -> None:
    """#703: with the relation total = part and two blind tasks, the outcome of a correction of
    total depended on the hidden value of part. Now the responses are the same for the hidden
    values 10 and 20. The resolution still reads each candidate."""
    text = "Total 10. Total 20. Part 10. Part 20."
    schema = {
        "fields": {"total": {"type": "integer"}, "part": {"type": "integer"}},
        "relations": [{"id": "same", "total": "total", "parts": [{"field": "part"}]}],
    }

    def span(words: str) -> dict[str, Any]:
        return {"start": text.index(words), "end": text.index(words) + len(words), "text": words}

    seen, statuses = [], []
    for value in ("10", "20"):
        candidates = [
            {"id": "t", "field": "total", "value": value, "evidence": span(f"Total {value}")},
            {"id": "p", "field": "part", "value": value, "evidence": span(f"Part {value}")},
        ]
        root = tmp_path / value
        with FolderStore(root) as store:
            k, _ = admit_packet(store, text, schema, candidates, None, "doc-1", None)
            tasks = {t["slot"]["field"]: (tk, t) for tk, t in write_tasks(store, k, EVERY).tasks}
        assert {t["mode"] for _, t in tasks.values()} == {"audit"}
        fill(root, tasks["part"][0])  # zed takes part, so ana gets total
        names = {id_of(tk): field for field, (tk, _) in tasks.items()}
        total = id_of(tasks["total"][0])
        start = text.index("10")
        correction = {
            "task": total,
            "verdict": "correct",
            "span": {"start": start, "end": start + 2},
        }
        service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
        with serving(api.server(service, first_agree=1), {"Authorization": claim()}) as call:
            responses = [
                call("GET", "/v1/tasks"),
                call("GET", f"/v1/tasks/{total}"),
                call("POST", "/v1/answers", correction),
                call("GET", "/v1/tasks"),
                call("GET", f"/v1/tasks/{total}"),
            ]
        bodies = []
        for status, _, body in responses:
            for name, field in names.items():
                body = body.replace(name, field)
            bodies.append((status, json.loads(body)))
        seen.append(bodies)
        with FolderStore(root) as store:
            resolution = write_resolution(store, k, EVERY, ["ana", "zed"]).resolution
        assert resolution is not None
        statuses.append({s["field"]: s["status"] for s in resolution["slots"]})
    assert seen[0] == seen[1]
    assert [status for status, _ in seen[0]] == [200, 200, 201, 200, 200]
    # the resolution reads the hidden candidate of part: the value 10 holds with 10 only
    assert statuses[0] != statuses[1]


def test_the_check_of_a_blind_correction_reads_no_candidate_of_an_audit_task_not_written_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``review tasks`` stops after the audit task of part, before the audit task of total. The
    check of a correction of part keeps only the candidates of the review tasks in the store,
    so the responses are the same for the hidden values 10 and 20."""
    text = "Total 10. Total 20. Part 10. Part 20."
    schema = {
        "fields": {"total": {"type": "integer"}, "part": {"type": "integer"}},
        "relations": [{"id": "same", "total": "total", "parts": [{"field": "part"}]}],
    }

    def span(words: str) -> dict[str, Any]:
        return {"start": text.index(words), "end": text.index(words) + len(words), "text": words}

    put = FolderStore.put
    fields: list[str] = []

    def stops(self: FolderStore, kind: str, data: bytes) -> str:
        if kind == "task@1":
            fields.append(json.loads(data)["slot"]["field"])
            if len(fields) == 2:
                raise OSError("the disk is full")
        return put(self, kind, data)

    seen = []
    for value in ("10", "20"):
        candidates = [
            {"id": "t", "field": "total", "value": value, "evidence": span(f"Total {value}")},
            {"id": "p", "field": "part", "value": value, "evidence": span(f"Part {value}")},
        ]
        root, fields[:] = tmp_path / value, []
        with FolderStore(root) as store:
            k, _ = admit_packet(store, text, schema, candidates, None, "doc-1", None)
            monkeypatch.setattr(FolderStore, "put", stops)
            with pytest.raises(OSError, match="disk"):
                write_tasks(store, k, EVERY)
            monkeypatch.setattr(FolderStore, "put", put)
        assert fields == ["part", "total"]  # the store has the audit task of part only
        service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
        with serving(api.server(service), {"Authorization": claim()}) as call:
            ((task,),) = [[t["task"] for t in json.loads(call("GET", "/v1/tasks")[2])["tasks"]]]
            start = text.index("Part 10") + 5
            correction = {
                "task": task,
                "verdict": "correct",
                "span": {"start": start, "end": start + 2},
            }
            status, _, body = call("POST", "/v1/answers", correction)
        seen.append((status, json.loads(body.replace(task, "part"))))
    assert seen[0] == seen[1] and seen[0][0] == 201


def test_the_check_of_a_blind_correction_reads_no_candidate_of_a_review_task(
    tmp_path: Path,
) -> None:
    """The task of total is blind, and the task of part is a review task: its value has a
    qualifier. The check of a correction of total leaves out the candidate of part too, so the
    responses are the same for the hidden values 10 and 20. Before, a guess of 10 gave 201 for
    10 and ``codes_not_kept`` for 20, and a failed guess writes no record."""
    text = "Total 10. Total 20. Part about 10. Part about 20."
    schema = {
        "fields": {"total": {"type": "integer"}, "part": {"type": "integer"}},
        "relations": [{"id": "same", "total": "total", "parts": [{"field": "part"}]}],
    }

    def span(words: str) -> dict[str, Any]:
        return {"start": text.index(words), "end": text.index(words) + len(words), "text": words}

    seen = []
    for value in ("10", "20"):
        candidates = [
            {"id": "t", "field": "total", "value": value, "evidence": span(f"Total {value}")},
            {"id": "p", "field": "part", "value": value, "evidence": span(f"Part about {value}")},
        ]
        root = tmp_path / value
        with FolderStore(root) as store:
            k, _ = admit_packet(store, text, schema, candidates, None, "doc-1", None)
            tasks = {
                t["slot"]["field"]: (tk, t["mode"]) for tk, t in write_tasks(store, k, EVERY).tasks
            }
        assert {field: mode for field, (_, mode) in tasks.items()} == {
            "part": "review",
            "total": "audit",
        }
        total = id_of(tasks["total"][0])
        start = text.index("10")
        correction = {
            "task": total,
            "verdict": "correct",
            "span": {"start": start, "end": start + 2},
        }
        service = Service(root, ISSUERS, EVERY, clock=lambda: CLOCK, id_key=KEY)
        with serving(api.server(service), {"Authorization": claim()}) as call:
            listed = [t["task"] for t in json.loads(call("GET", "/v1/tasks")[2])["tasks"]]
            status, _, body = call("POST", "/v1/answers", correction)
        seen.append((listed == [total], status, json.loads(body.replace(total, "total"))))
    assert seen[0] == seen[1] and seen[0][:2] == (True, 201)


def test_a_restart_keeps_the_review_group_when_agree_stays_the_same_or_goes_down(
    tmp_path: Path, unbound_server: None
) -> None:
    """A read writes no record. The server refuses an increase before ana can get a blind task."""
    root = tmp_path / "store"
    k, tasks = make_store(root)
    with FolderStore(root).review_api(2):
        pass
    fill(root, tasks["net_income"])
    fill(root, tasks["net_income"], "ben")

    def fields(agree: int) -> list[str]:
        service = Service(root, ISSUERS, {**EVERY, "agree": agree}, clock=lambda: CLOCK, id_key=KEY)
        with api.server(service):
            return [t["field"] for t in service.tasks("ana")["tasks"]]

    assert fields(2) == ["revenue"]
    assert fields(2) == ["revenue"]
    assert fields(1) == ["revenue"]
    assert not records(root, k, "ana")
    with pytest.raises(StoreError, match=r"Recorded agree is 1\. New agree is 3\."):
        fields(3)


def test_a_cursor_holds_when_the_group_of_the_actor_changes_between_two_pages(
    tmp_path: Path,
) -> None:
    """The cursor of the first page is the blind task of doc-1. zed then answers it, so the
    group of ana for doc-1 is the review group, and the cursor names a task outside it."""
    root = tmp_path / "store"
    _, first = make_store(root, document="doc-1")
    make_store(root, document="doc-2")
    service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
    with serving(api.server(service), {"Authorization": claim()}) as call:
        page = json.loads(call("GET", "/v1/tasks?limit=1")[2])
        assert [(t["document"], t["field"]) for t in page["tasks"]] == [("doc-1", "net_income")]
        assert page["next"] == id_of(first["net_income"])
        fill(root, first["net_income"])
        status, _, body = call("GET", f"/v1/tasks?limit=1&cursor={page['next']}")
        assert status == 200
        listed = json.loads(body)["tasks"]
        assert [(t["document"], t["field"]) for t in listed] == [("doc-1", "revenue")]
        assert error(call("GET", f"/v1/tasks/{page['next']}")) == (403, "not_assigned")


def test_review_tasks_writes_no_new_audit_task_for_a_packet_with_tasks(tmp_path: Path) -> None:
    """A new blind task could go to an actor who got the review group of its packet."""
    root = tmp_path / "store"
    k, _ = make_store(root, NO_AUDIT)
    with FolderStore(root) as store:
        assert len(write_tasks(store, k, NO_AUDIT).tasks) == 1  # the same tasks again
        before = store.object_keys()
        with pytest.raises(ValueError, match="new audit"):
            write_tasks(store, k, EVERY)
        assert store.object_keys() == before
    other = tmp_path / "other"
    k, tasks = make_store(other)
    with FolderStore(other) as store:
        assert {tk for tk, _ in write_tasks(store, k, EVERY).tasks} == set(tasks.values())


def test_an_answer_log_that_the_store_cannot_read_gives_no_group(reviewing: Served) -> None:
    """A read can see a torn last line while another writer appends. A log left out would
    remove the record of zed from the count, and ana would get the blind task after the review
    group. So the actor gets no group of the packet until the log reads again."""
    root, _, tasks, call = reviewing
    revenue, blind = id_of(tasks["revenue"]), id_of(tasks["net_income"])

    def fields() -> list[str]:
        return [t["field"] for t in json.loads(call("GET", "/v1/tasks")[2])["tasks"]]

    assert fields() == ["revenue"]
    ((name, data),) = answer_logs(root).items()  # the log of zed
    (root / name).write_bytes(data + b'{"format":"answer@1","reviewer":"zed"')
    assert fields() == []
    for task in (revenue, blind):
        assert error(call("GET", f"/v1/tasks/{task}")) == (403, "not_assigned")
        assert error(call("POST", "/v1/answers", {"task": task, "verdict": "unsure"})) == (
            403,
            "not_assigned",
        )
    (root / name).write_bytes(data)
    assert fields() == ["revenue"] and answer_logs(root) == {name: data}


def test_the_review_group_never_comes_before_the_blind_tasks_of_its_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A listing of the store reads each object folder at a different time, so it can give the
    review task without the blind task. ``review tasks`` writes the audit tasks first, and the
    service lists the store a second time for the audit tasks."""
    written: list[str] = []
    put = FolderStore.put

    def watched(self: FolderStore, kind: str, data: bytes) -> str:
        if kind == "task@1":
            written.append(json.loads(data)["mode"])
        return put(self, kind, data)

    monkeypatch.setattr(FolderStore, "put", watched)
    root = tmp_path / "store"
    # the slot of the review task comes first: revenue, then tax
    schema = {"fields": {"revenue": {"type": "number"}, "tax": {"type": "number"}}}
    given = [{**c, "field": "tax"} if c["field"] == "net_income" else c for c in CANDIDATES]
    with FolderStore(root) as store:
        k, _ = admit_packet(store, TEXT, schema, given, None, "doc-1", None)
        result = write_tasks(store, k, EVERY).tasks
    tasks = {t["slot"]["field"]: tk for tk, t in result}
    assert written == ["audit", "review"]
    assert [t["mode"] for _, t in result] == ["review", "audit"]  # the result keeps slot order

    hidden: list[str] = []  # the task key that the next listing does not give
    listing = FolderStore.object_keys

    def partial(self: FolderStore) -> tuple[list[str], list[str]]:
        keys, problems = listing(self)
        if hidden:
            gone = hidden.pop()
            keys = [x for x in keys if x != gone]
        return keys, problems

    monkeypatch.setattr(FolderStore, "object_keys", partial)
    service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
    with serving(api.server(service), {"Authorization": claim()}) as call:
        hidden.append(tasks["tax"])
        listed = json.loads(call("GET", "/v1/tasks")[2])["tasks"]
        assert not hidden and [t["field"] for t in listed] == ["tax"]
        hidden.append(tasks["tax"])
        revenue = call("GET", f"/v1/tasks/{id_of(tasks['revenue'])}")
        assert not hidden and error(revenue) == (403, "not_assigned")


def test_review_tasks_runs_again_after_a_stop_in_its_audit_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stop between two audit tasks leaves no task of the review group, so no actor got that
    group. A second run then writes the tasks that are not in the store."""
    root = tmp_path / "store"
    schema = {"fields": {**SCHEMA["fields"], "year": {"type": "integer"}}}
    year = {
        "id": "y1",
        "field": "year",
        "value": "2025",
        "evidence": {**at("2025"), "text": "2025"},
    }
    put = FolderStore.put
    audits: list[int] = []

    def stops(self: FolderStore, kind: str, data: bytes) -> str:
        if kind == "task@1" and json.loads(data)["mode"] == "audit":
            audits.append(1)
            if len(audits) == 2:
                raise OSError("the disk is full")
        return put(self, kind, data)

    with FolderStore(root) as store:
        k, _ = admit_packet(store, TEXT, schema, [*CANDIDATES, year], None, "doc-1", None)
        monkeypatch.setattr(FolderStore, "put", stops)
        with pytest.raises(OSError, match="disk"):
            write_tasks(store, k, EVERY)
        monkeypatch.setattr(FolderStore, "put", put)
        modes = [t["mode"] for _, t in write_tasks(store, k, EVERY).tasks]
    assert sorted(modes) == ["audit", "audit", "review"]


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
        assert [t["task"] for t in listed] == [id_of(tasks["net_income"])]
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
        k, tasks = make_store(root, NO_AUDIT)
        assert len(json.loads(call("GET", "/v1/tasks")[2])["tasks"]) == 1
        revenue = id_of(tasks["revenue"])
        body = {"task": revenue, "verdict": "unsure"}
        assert call("POST", "/v1/answers", body)[0] == 201
        assert list((root / "logs").rglob("*.lock")) == []
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
        assert json.loads(call("GET", "/v1/tasks")[2])["tasks"] == []
        answered = json.loads(call("GET", f"/v1/tasks/{revenue}")[2])["answered"]
        assert answered == "choose"
        assert call("POST", "/v1/answers", body)[0] == 201
    assert [r["verdict"] for r in records(root, k)] == ["unsure", "choose", "unsure"]
    assert vars(service).keys() == {"root", "auth", "_policy", "_clock", "_id_key"}


def test_service_policy_returns_a_copy(tmp_path: Path) -> None:
    policy = {**EVERY, "audit": {**EVERY["audit"]}, "leads": ["ana"]}
    service = Service(tmp_path, ISSUERS, policy)
    snapshot = service.policy
    assert snapshot == policy
    snapshot["agree"] = 2
    snapshot["audit"]["seed"] = "other"
    snapshot["leads"].append("bea")
    assert service.policy == policy
    with pytest.raises(AttributeError):
        service.policy = snapshot


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


@pytest.fixture
def unbound_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the start and close steps with no port."""
    monkeypatch.setattr(ThreadingHTTPServer, "server_bind", lambda server: None)
    monkeypatch.setattr(ThreadingHTTPServer, "server_activate", lambda server: None)
    monkeypatch.setattr(ThreadingHTTPServer, "server_port", 0, raising=False)


def test_a_second_server_cannot_change_agree_while_the_first_runs(
    tmp_path: Path, unbound_server: None
) -> None:
    with api.server(Service(tmp_path, ISSUERS, {**EVERY, "agree": 2})):
        with pytest.raises(
            Locked,
            match=r"state/review-api\.lock exists\. Delete this file only when no review API "
            r"server runs on this store\.",
        ):
            api.server(Service(tmp_path, ISSUERS)).server_close()
        assert recorded_agree(tmp_path) == 2
    with api.server(Service(tmp_path, ISSUERS)):
        assert recorded_agree(tmp_path) == 1


def test_review_api_refuses_a_higher_agree_before_it_serves(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    unbound_server: None,
) -> None:
    root = tmp_path / "store"
    _, tasks = make_store(root)
    token = tmp_path / "token"
    token.write_text(TOKEN + "\n", encoding="utf-8")
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({**EVERY, "agree": 2}), encoding="utf-8")
    starts = []
    monkeypatch.setattr(ThreadingHTTPServer, "serve_forever", lambda server: starts.append(server))
    args = ["review", "api", "--store", str(root), "--token-file", str(token), "--reviewer", "ana"]
    assert main(args) == 0
    assert recorded_agree(root) == 1
    fill(root, tasks["net_income"])
    capsys.readouterr()

    assert main([*args, "--policy", str(policy)]) == 2
    out, err = capsys.readouterr()
    assert not out
    assert "Recorded agree is 1. New agree is 2." in err
    assert recorded_agree(root) == 1
    assert len(starts) == 1


def test_review_api_records_the_previous_agree_once(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    unbound_server: None,
) -> None:
    root = tmp_path / "store"
    _, tasks = make_store(root)
    fill(root, tasks["net_income"])
    before = answer_logs(root)
    token = tmp_path / "token"
    token.write_text(TOKEN + "\n", encoding="utf-8")
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({**EVERY, "agree": 2}), encoding="utf-8")
    starts = []
    monkeypatch.setattr(ThreadingHTTPServer, "serve_forever", lambda server: starts.append(server))
    args = ["review", "api", "--store", str(root), "--token-file", str(token), "--reviewer", "ana"]
    higher = [*args, "--policy", str(policy)]
    option = ["--first-agree", "1"]
    pointer = root / "state" / "review-api"

    assert main(higher) == 2
    out, err = capsys.readouterr()
    assert not out and "the store has answers and no recorded agree" in err
    assert main([*higher, *option]) == 2
    out, err = capsys.readouterr()
    assert not out and "--first-agree must equal the policy agree (2)." in err
    assert not starts and not pointer.exists()

    assert main([*args, *option]) == 0
    assert recorded_agree(root) == 1
    capsys.readouterr()
    assert main([*args, *option]) == 2
    out, err = capsys.readouterr()
    assert not out and "--first-agree requires a store with no recorded agree." in err
    assert main(args) == 0
    assert len(starts) == 2
    assert recorded_agree(root) == 1 and answer_logs(root) == before


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
    assert status == 200 and len(json.loads(body)["tasks"]) == 1
