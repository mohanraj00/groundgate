"""The browser label tool, standard library only. It shows each document with its items marked,
and the question. It never shows groundgate's reading or a model answer: not the candidate's key,
and not an answer of a judge.

The server binds to 127.0.0.1 and refuses a request from another web site (#391). The Host
header must be 127.0.0.1 and the port, so DNS rebinding cannot reach it. The API asks for a
random token that only the start URL holds, after #. A POST must be JSON of 64 KiB at most. A
Content-Security-Policy lets the page run only its own script and style."""

from __future__ import annotations

import contextlib
import hmac
import html
import json
import os
import secrets
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from . import questions as q

if TYPE_CHECKING:
    from .cli import Work


LOCK = ".labels.lock"


def judged(folder: Path) -> bool:
    """True once a judge run starts in the work folder: the labels are frozen then."""
    return any(folder.glob("answers-*.json")) or any(folder.glob(".answers-*.partial.json"))


@contextlib.contextmanager
def labels_lock(folder: Path) -> Iterator[None]:
    """Hold the labels lock of the work folder, ``W/.labels.lock``, for one short step. A label
    write holds it across the freeze check and the write, and ``ask`` holds it across its
    partial file and the label snapshot, so no label write falls between the two. The lock is
    on an open file (``flock``, or ``msvcrt.locking`` where there is no ``fcntl``): the system
    releases it when the process ends, so a stopped process leaves no stale lock. Both forms
    wait for the lock. The file stays in the folder."""
    fd = os.open(folder / LOCK, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        try:
            import fcntl
        except ImportError:  # Windows: no fcntl
            import msvcrt

            while True:
                try:
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)  # type: ignore[attr-defined]
                    break
                except OSError:  # LK_LOCK gives up after 10 tries: wait again
                    continue
            yield
        else:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
    finally:
        os.close(fd)  # closing the file releases the lock


def page(text: str, items: list[dict[str, Any]]) -> str:
    """The document text with a <mark> around each item's value. A mark lists its items in
    data-ids: two items on one value, or on values that overlap, share one mark over both."""
    marks: list[tuple[int, int, list[str]]] = []
    for it in sorted(items, key=lambda x: (x["mark"][0], x["id"])):
        a, b = it["mark"]
        if marks and a < marks[-1][1]:
            s0, e0, ids = marks[-1]
            marks[-1] = (s0, max(e0, b), [*ids, it["id"]])
        else:
            marks.append((a, b, [it["id"]]))
    out, at = [], 0
    for a, b, ids in marks:
        out += [html.escape(text[at:a]), f'<mark data-ids="{html.escape(" ".join(ids))}">']
        out += [html.escape(text[a:b]), "</mark>"]
        at = b
    out.append(html.escape(text[at:]))
    return tables("".join(out))


SIGN_BEFORE = {"$", "€", "£", "₹", "US$", "(", "$("}
SIGN_AFTER = {"%", ")", "%)"}


def cells(row: str) -> list[str]:
    """The cells of one table line. A cell that holds only a currency sign joins the next cell,
    and one that holds only a percent sign or a closing parenthesis joins the one before, so the
    numbers of each row stand in the same columns."""
    out: list[str] = []
    carry = ""
    for c in row.split("\t"):
        if c.strip() in SIGN_BEFORE:
            # a currency sign stands apart from its number, an opening parenthesis does not
            carry += c.strip() + ("" if c.strip().endswith("(") else " ")
        elif c.strip() in SIGN_AFTER and out:
            out[-1] += c.strip()
        else:
            out.append(carry + c)
            carry = ""
    if carry:
        out.append(carry.strip())
    return out


def tables(marked: str) -> str:
    """Draw each run of lines that hold a tab as an HTML table, one cell for each tab-separated
    part. A run where a mark crosses a cell or a line stays plain text."""
    out: list[str] = []
    rows: list[str] = []

    def flush() -> None:
        if not rows:
            return
        split = [cells(r) for r in rows]
        # a mark that crosses a cell or a line (the evidence of a string field can) would break
        # the table, so such a run stays plain text
        if all(c.count("<mark") == c.count("</mark>") for row in split for c in row):
            trs = ["<tr><td>" + "</td><td>".join(row) + "</td></tr>" for row in split]
            out.append('<table class="t">' + "".join(trs) + "</table>")
        else:
            out.extend(r + "\n" for r in rows)
        rows.clear()

    for line in marked.split("\n"):
        if "\t" in line:
            rows.append(line)
        else:
            flush()
            out.append(line + "\n")
    flush()
    return "".join(out)


MAX_BODY = 64 * 1024
TOKEN_HEADER = "X-Groundgate-Token"
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
# the page and its script and style hold no data, so they need no token; the API does
STATIC = {
    "/": ("label.html", "text/html"),
    "/label.js": ("label.js", "text/javascript"),
    "/label.css": ("label.css", "text/css"),
}


def server(w: Work, port: int) -> tuple[ThreadingHTTPServer, str]:
    """The label server on 127.0.0.1 and its start URL, which holds the token after #."""
    cfg, items = w.config, w.read("items.json")
    question = cfg["question"]
    by_id = {it["id"]: it for it in items}
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        by_doc.setdefault(it["doc"], []).append(it)
    pages = {doc: page(w.text(doc), its) for doc, its in by_doc.items()}
    shown = [
        {
            "id": it["id"],
            "doc": it["doc"],
            "field": it["field"],
            "description": cfg["descriptions"].get(it["field"], ""),
            **({"keys": it["keys"]} if question == "key" else {}),
        }
        for it in items
    ]
    path = w.path / "labels.json"
    # links.json, when the user gives one, maps a document to its original, such as the source
    # web page, for text whose tables lost their shape in extraction
    links = w.read("links.json", {})
    token = secrets.token_urlsafe(32)
    host = ""  # 127.0.0.1 and the bound port, set once the server binds

    class Handler(BaseHTTPRequestHandler):
        timeout = 30  # a client that sends less than its Content-Length holds a thread no longer

        def send(self, body: str, kind: str = "application/json", code: int = 200) -> None:
            raw = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def refuse(self, code: int, why: str) -> None:
            self.close_connection = True
            self.send(json.dumps({"error": why}), code=code)

        def allowed(self, api: bool) -> bool:
            """Refuse a request for another host, and an API request without the token."""
            if self.headers.get("Host") != host:
                self.refuse(421, "the Host header must be 127.0.0.1 and the port")
                return False
            sent = self.headers.get(TOKEN_HEADER, "")
            if api and not hmac.compare_digest(sent.encode(), token.encode()):
                self.refuse(403, "open the start URL with its token")
                return False
            return True

        def do_GET(self) -> None:
            if self.path in STATIC:
                if self.allowed(api=False):
                    name, kind = STATIC[self.path]
                    self.send(files(__package__).joinpath(name).read_text("utf-8"), kind)
            elif not self.allowed(api=True):
                return
            elif self.path == "/state":
                labels = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                state = {"question": question, "items": shown, "labels": labels, "links": links}
                self.send(json.dumps(state))
            elif self.path.startswith("/doc/") and unquote(self.path[5:]) in pages:
                self.send(pages[unquote(self.path[5:])], "text/html")
            else:
                self.send("{}", code=404)

        def do_POST(self) -> None:
            if not self.allowed(api=True):
                return
            kind = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if kind != "application/json":
                self.refuse(415, "the body must be application/json")
                return
            length = self.headers.get("Content-Length", "")
            # only digits: int() also takes "+5", "1_0" and spaces
            if not (length.isascii() and length.isdigit()):
                self.refuse(411, "the request needs a Content-Length")
                return
            size = int(length)
            if size > MAX_BODY:
                self.refuse(413, f"the body must be {MAX_BODY} bytes at most")
                return
            try:
                body = json.loads(self.rfile.read(size))
            except (ValueError, RecursionError):  # deep nesting fits in 64 KiB
                self.refuse(400, "the body is not JSON")
                return
            if not isinstance(body, dict) or not isinstance(body.get("id"), str):
                self.send("{}", code=400)  # an id that is a list or a dict cannot be a key
                return
            it, value = by_id.get(body["id"]), body.get("value")
            if self.path != "/label" or it is None or not q.valid_label(question, it, value):
                self.send("{}", code=400)
                return
            with labels_lock(w.path):
                if judged(w.path):
                    self.send('{"error": "the labels are frozen once a judge has answered"}',
                              code=409)  # fmt: skip
                    return
                labels = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                if question == "key" and value is not None:
                    value = [k for k in it["keys"] if k in value]
                labels[it["id"]] = value
                out = json.dumps(dict(sorted(labels.items())), indent=1) + "\n"
                path.write_text(out, encoding="utf-8")
            self.send(json.dumps({"labels": labels}))

        def log_message(self, *args: Any) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    host = f"127.0.0.1:{httpd.server_port}"
    return httpd, f"http://{host}/#{token}"


def serve(w: Work, port: int) -> None:
    httpd, url = server(w, port)
    print(f"Open {url} and press Ctrl-C here when you finish.")
    httpd.serve_forever()
