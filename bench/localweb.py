"""The checks that each label server under bench/ makes before its handler sees a request (#400).

A label server binds to 127.0.0.1. LocalHandler refuses a request before it reaches do_GET or
do_POST in these cases:

1. The Host header is not 127.0.0.1 and the bound port. Thus DNS rebinding cannot reach the
   server.
2. The request has no token. The start URL holds a random token in its query. The server answers
   it with a cookie that holds the token, and a redirect to / that removes the token from the
   address bar. Each other request must send that cookie. The cookie is SameSite=Strict, so a
   request from another web site does not carry it.
3. A POST is not application/json, has no Content-Length, or is larger than max_body bytes.

A handler that has its own token (bench/label/app.py) sets needs_cookie to False and keeps the
Host check and the POST check. The tokens are compared with hmac.compare_digest.
"""

from __future__ import annotations

import hmac
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def same(sent: str, token: str) -> bool:
    """True if sent is the token, in a time that does not depend on where they differ."""
    return hmac.compare_digest(sent.encode("utf-8", "replace"), token.encode("utf-8"))


class LocalServer(ThreadingHTTPServer):
    """A ThreadingHTTPServer on 127.0.0.1 with a new random token."""

    daemon_threads = True

    def __init__(self, port: int, handler: type[LocalHandler]) -> None:
        super().__init__(("127.0.0.1", port), handler)
        self.token = secrets.token_urlsafe(32)
        self.host = f"127.0.0.1:{self.server_port}"
        # a cookie is shared by all ports of a host, so each port has its own name
        self.cookie = f"groundgate-label-{self.server_port}"

    @property
    def url(self) -> str:
        """The start URL. Only the person who started the server sees it."""
        return f"http://{self.host}/?token={self.token}"


class LocalHandler(BaseHTTPRequestHandler):
    server: LocalServer
    needs_cookie = True
    max_body = 1 << 20
    timeout = 30  # a client that sends less than its Content-Length holds a thread no longer

    def log_message(self, *args: Any) -> None:
        pass

    def end_headers(self) -> None:
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def refuse(self, code: int, why: str) -> None:
        body = (why + "\n").encode()
        self.close_connection = True
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def cookie_token(self) -> str:
        """The value of this server's cookie, or an empty string."""
        for header in self.headers.get_all("Cookie") or []:
            for part in header.split(";"):
                name, _, value = part.strip().partition("=")
                if name == self.server.cookie:
                    return value
        return ""

    def parse_request(self) -> bool:
        if not super().parse_request():
            return False
        if self.headers.get("Host") != self.server.host:
            self.refuse(421, "the Host header must be 127.0.0.1 and the port")
            return False
        target, _, query = self.path.partition("?")
        if self.needs_cookie and target == "/" and query.startswith("token="):
            if not same(query[len("token=") :], self.server.token):
                self.refuse(403, "the token is wrong: open the start URL that the server printed")
                return False
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header(
                "Set-Cookie",
                f"{self.server.cookie}={self.server.token}; Path=/; HttpOnly; SameSite=Strict",
            )
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return False
        if self.needs_cookie and not same(self.cookie_token(), self.server.token):
            self.refuse(403, "open the start URL that the server printed")
            return False
        if self.command == "POST":
            return self.body_ok()
        return True

    def body_ok(self) -> bool:
        """Refuse a POST that is not JSON or has no Content-Length, or is too large."""
        kind = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if kind != "application/json":
            self.refuse(415, "the body must be application/json")
            return False
        length = self.headers.get("Content-Length", "")
        # only digits: int() also takes "+5", "1_0" and spaces
        if self.headers.get("Transfer-Encoding") or not (length.isascii() and length.isdigit()):
            self.refuse(411, "the request needs a Content-Length")
            return False
        if int(length) > self.max_body:
            self.refuse(413, f"the body must be {self.max_body} bytes at most")
            return False
        return True


def serve(handler: type[LocalHandler], port: int, what: str) -> None:
    """Start the server, print its start URL, and serve until Ctrl-C."""
    server = LocalServer(port, handler)
    print(f"{what}; open {server.url} (Ctrl-C to stop)", flush=True)
    server.serve_forever()
