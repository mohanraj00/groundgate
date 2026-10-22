"""The checks of the bench label servers (bench/localweb.py, #400)."""

from __future__ import annotations

import http.client
import re
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

BENCH = Path(__file__).parent.parent / "bench"
sys.path[:0] = [str(BENCH)]  # not a package

import localweb  # noqa: E402  (bench/localweb.py)

SEEN: list[str] = []


class Echo(localweb.LocalHandler):
    """A label server that saves each POST body that reaches it."""

    def do_GET(self) -> None:
        self.answer(b"page")

    def do_POST(self) -> None:
        SEEN.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
        self.answer(b"{}")

    def answer(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server() -> Iterator[localweb.LocalServer]:
    SEEN.clear()
    s = localweb.LocalServer(0, Echo)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()
    s.server_close()


def ask(
    s: localweb.LocalServer,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: str | None = None,
) -> http.client.HTTPResponse:
    conn = http.client.HTTPConnection("127.0.0.1", s.server_port)
    conn.request(method, path, body, headers or {})
    r = conn.getresponse()
    r.read()
    return r


def cookie(s: localweb.LocalServer, token: str | None = None) -> dict[str, str]:
    return {"Cookie": f"other=1; {s.cookie}={token or s.token}"}


def test_the_start_url_sets_the_cookie_and_drops_the_token(
    server: localweb.LocalServer,
) -> None:
    assert server.url == f"http://127.0.0.1:{server.server_port}/?token={server.token}"
    r = ask(server, "GET", f"/?token={server.token}")
    assert r.status == 303 and r.getheader("Location") == "/"
    set_cookie = r.getheader("Set-Cookie", "")
    assert set_cookie.startswith(f"{server.cookie}={server.token};")
    assert "HttpOnly" in set_cookie and "SameSite=Strict" in set_cookie
    assert ask(server, "GET", "/", cookie(server)).status == 200


def test_a_wrong_or_missing_token_is_refused(server: localweb.LocalServer) -> None:
    assert ask(server, "GET", "/?token=guess").status == 403
    assert ask(server, "GET", "/?token=").status == 403
    assert ask(server, "GET", "/").status == 403
    assert ask(server, "GET", "/state").status == 403
    assert ask(server, "GET", "/state", cookie(server, "guess")).status == 403
    near = {"Cookie": f"x{server.cookie}={server.token}"}
    assert ask(server, "GET", "/state", near).status == 403
    # a cookie of another port is not this server's cookie
    other = {"Cookie": f"groundgate-label-1={server.token}"}
    assert ask(server, "GET", "/state", other).status == 403
    json_post = {"Content-Type": "application/json", "Content-Length": "2"}
    assert ask(server, "POST", "/label", json_post, "{}").status == 403
    assert SEEN == []


def test_another_host_is_refused(server: localweb.LocalServer) -> None:
    for host in ("evil.test", f"evil.test:{server.server_port}", "localhost", "127.0.0.1"):
        headers = {"Host": host, **cookie(server)}
        assert ask(server, "GET", "/state", headers).status == 421
        assert ask(server, "GET", f"/?token={server.token}", {"Host": host}).status == 421
        post = {**headers, "Content-Type": "application/json"}
        assert ask(server, "POST", "/label", post, "{}").status == 421
    assert SEEN == []


def test_a_post_must_be_json_of_a_known_size(server: localweb.LocalServer) -> None:
    ok = {**cookie(server), "Content-Type": "application/json"}
    assert ask(server, "POST", "/label", ok, '{"id": 1}').status == 200
    assert SEEN == ['{"id": 1}']
    form = {**cookie(server), "Content-Type": "text/plain"}
    assert ask(server, "POST", "/label", form, '{"id": 2}').status == 415
    big = str(localweb.LocalHandler.max_body + 1)
    # the server refuses on the headers, so the client sends no body
    for length, code in ((big, 413), ("+5", 411), ("", 411)):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
        conn.putrequest("POST", "/label")
        for k, v in ok.items():
            conn.putheader(k, v)
        if length:
            conn.putheader("Content-Length", length)
        conn.endheaders()
        assert conn.getresponse().status == code
    assert SEEN == ['{"id": 1}']


def test_each_bench_server_uses_the_checks() -> None:
    """Each label server under bench/ builds on localweb, so a new route has the checks too.
    bench/requested/label_app.py has its own Host check, token and POST check."""
    own = {BENCH / "localweb.py", BENCH / "requested" / "label_app.py"}
    servers = []
    for path in sorted(BENCH.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if path in own:
            continue
        assert "http.server" not in text, path
        if re.search(r"def do_[A-Z]+\(", text):
            servers.append(path.relative_to(BENCH).as_posix())
            assert re.search(r"class Handler\(localweb\.LocalHandler\)", text), path
    assert len(servers) == 13
