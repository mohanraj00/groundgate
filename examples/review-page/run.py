"""The review and audit page: one command for a local run (#647).

    uv run python examples/review-page/run.py

The command gets the UI kit at the commit that ``kit.json`` pins, makes a store with one made-up
invoice, starts the review API of ``groundgate review api`` (SPEC §4.20) with a static token, and
serves the page. It prints the start URL. The page reads and writes only through the API.

One server on 127.0.0.1 gives the page one origin, because the API sends no CORS header:

- ``/``, ``/page.js`` and ``/page.css``: the page.
- ``/kit.json``: the pin of the kit, and if the server has the kit.
- ``/kit/src/...`` and ``/kit/catalog/...``: the files of the kit.
- ``/v1/...``: each request goes to the API as it is, with its ``Authorization`` header.

The kit is not a part of groundgate, and the page does not need it. ``fetch_kit`` gets it with
``git`` by its commit, so git checks the content against the pin. It starts ``git`` with a list
of arguments, no shell and a time limit. With ``--no-kit``, or if git cannot get the kit, the
page draws plain controls.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from groundgate.review import api
from groundgate.review.tasks import write_tasks
from groundgate.store import FolderStore
from groundgate.store.packets import admit_packet

HERE = Path(__file__).parent
PAGE = HERE / "page"
KIT = json.loads((HERE / "kit.json").read_text("utf-8"))
API = "groundgate-review/1"  # the API version that the page needs
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "form-action 'none'; base-uri 'none'; frame-ancestors 'none'"
)
PAGE_FILES = {
    "/": ("index.html", "text/html"),
    "/page.js": ("page.js", "text/javascript"),
    "/page.css": ("page.css", "text/css"),
}
KIT_TYPES = {".js": "text/javascript", ".json": "application/json", ".css": "text/css"}
MAX_BODY = 64 * 1024
GIT_SECONDS = 120

# A made-up invoice. The first field has two candidates, so it gives a review task. The gate
# admits the tax, and the audit rate of 1 gives it an audit task, which is blind.
TEXT = "Invoice 0007\nTotal due: 4,200 thousand USD\nTax: 310 thousand USD\nDue date: not given\n"
SCHEMA = {
    "fields": {
        "total": {"type": "number", "description": "The total of the invoice, with tax."},
        "tax": {"type": "number", "description": "The tax of the invoice."},
    }
}
REVIEW_POLICY = {
    "format": "review-policy@1",
    "audit": {"rate": "1", "seed": "review-page"},
    "agree": 1,
    "leads": [],
    "rejected": False,
}


def _span(words: str) -> dict[str, Any]:
    start = TEXT.encode("utf-8").index(words.encode("utf-8"))
    return {"start": start, "end": start + len(words.encode("utf-8")), "text": words}


def fixture_store(root: Path) -> str:
    """Make a store with the invoice and its two tasks. The result is the packet key."""
    candidates = [
        {"id": "c1", "field": "total", "value": "4200000", "evidence": _span("4,200 thousand")},
        {"id": "c2", "field": "total", "value": "4200", "evidence": _span("4,200 thousand")},
        {"id": "c3", "field": "tax", "value": "310000", "evidence": _span("310 thousand")},
    ]
    with FolderStore(root) as store:
        packet, _ = admit_packet(store, TEXT, SCHEMA, candidates, None, "invoice-0007")
        write_tasks(store, packet, REVIEW_POLICY)
    return packet


def _git(folder: Path, *args: str) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    done = subprocess.run(
        ["git", "-C", str(folder), *args],
        capture_output=True, text=True, timeout=GIT_SECONDS, env=env, check=False,
    )  # fmt: skip
    if done.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {done.stderr.strip()[:300]}")
    return done.stdout.strip()


def kit_commit(folder: Path) -> str | None:
    """The commit of the kit checkout in ``folder``, or None if it is not a clean checkout."""
    if not (folder / ".git").exists():
        return None
    try:
        if _git(folder, "status", "--porcelain", "--", *KIT["serve"]):
            return None
        return _git(folder, "rev-parse", "HEAD")
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return None


def fetch_kit(folder: Path) -> Path:
    """Get the kit at the pinned commit into ``folder``, unless it is there. Git names a commit
    by a hash of its content, so a commit with this name has the pinned files."""
    if kit_commit(folder) == KIT["commit"]:
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if not (folder / ".git").exists():
            _git(folder, "init", "--quiet")
        _git(folder, "fetch", "--quiet", "--depth", "1", KIT["repository"], KIT["commit"])
        _git(folder, "checkout", "--quiet", "--force", "--detach", "FETCH_HEAD")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"git cannot get the kit: {exc}") from exc
    if kit_commit(folder) != KIT["commit"]:
        raise RuntimeError(f"the kit in {folder} is not at the commit {KIT['commit']}")
    return folder


def find_kit(folder: Path | None) -> Path | None:
    """The kit checkout at the pin in ``folder``. None for no folder, or if git cannot get the
    kit: the page then draws plain controls."""
    if folder is None:
        return None
    try:
        return fetch_kit(folder)
    except RuntimeError as exc:
        print(f"The UI kit is not available: {exc}", file=sys.stderr)
        print("The page draws plain controls.", file=sys.stderr)
        return None


def page_server(kit: Path | None, api_port: int, port: int = 0) -> ThreadingHTTPServer:
    """The server of the page: the page files, the files of the kit in ``kit``, and each
    ``/v1/`` request to the review API on ``api_port``. Without a kit, it gives no kit file."""
    roots = [(kit / name).resolve() for name in KIT["serve"]] if kit else []
    pin = {"available": kit is not None, "tag": KIT["tag"], "commit": KIT["commit"]}
    host = ""  # 127.0.0.1 and the bound port, set once the server binds

    class Handler(BaseHTTPRequestHandler):
        timeout = 30

        def send(self, status: int, kind: str, body: bytes, more: dict[str, str] | None = None):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            for name, value in (more or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def refuse(self, status: int, why: str) -> None:
            self.close_connection = True
            self.send(status, "text/plain; charset=utf-8", why.encode("utf-8"))

        def kit_file(self, path: str) -> Path | None:
            """The file of the kit for a ``/kit/`` path, or None. Only a file below a served
            folder of the kit, with a known type, and no folder list."""
            if kit is None:
                return None
            parts = path.split("/")[2:]
            if (
                not parts
                or parts[0] not in KIT["serve"]
                or any(p in ("", ".", "..") for p in parts)
            ):
                return None
            found = kit.joinpath(*parts).resolve()
            inside = any(found.is_relative_to(root) for root in roots)
            return found if inside and found.suffix in KIT_TYPES and found.is_file() else None

        def do_GET(self) -> None:
            if self.headers.get_all("Host") != [host]:
                self.refuse(421, "the Host header must be 127.0.0.1 and the port")
            elif self.path.startswith("/v1/"):
                self.proxy()
            elif self.path == "/kit.json":
                body = json.dumps(pin).encode("utf-8")
                self.send(200, "application/json; charset=utf-8", body)
            elif self.path in PAGE_FILES:
                name, kind = PAGE_FILES[self.path]
                self.send(200, f"{kind}; charset=utf-8", (PAGE / name).read_bytes())
            elif self.path.startswith("/kit/") and (found := self.kit_file(self.path)):
                kind = KIT_TYPES[found.suffix]
                self.send(200, f"{kind}; charset=utf-8", found.read_bytes())
            else:
                self.refuse(404, "no such path")

        def do_POST(self) -> None:
            if self.headers.get_all("Host") != [host]:
                self.refuse(421, "the Host header must be 127.0.0.1 and the port")
            elif self.path.startswith("/v1/"):
                self.proxy()
            else:
                self.refuse(404, "no such path")

        def proxy(self) -> None:
            """Send the request to the API as it is, and send the response back. The API does
            each check: the claim, the path, the method and the body."""
            sent = {"Host": f"127.0.0.1:{api_port}"}
            for name in ("Authorization", "Content-Type", "Content-Length"):
                values = self.headers.get_all(name) or []
                if len(values) > 1:  # the API refuses a second Authorization header
                    self.refuse(400, f"the request has two {name} headers")
                    return
                if values:
                    sent[name] = values[0]
            length = sent.get("Content-Length", "")
            body = None
            if length.isascii() and length.isdigit() and int(length) <= MAX_BODY:
                body = self.rfile.read(int(length))  # if not, the API refuses with no read
            conn = http.client.HTTPConnection("127.0.0.1", api_port, timeout=30)
            try:
                conn.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
                for name, value in sent.items():
                    conn.putheader(name, value)
                conn.endheaders(body)
                response = conn.getresponse()
                data = response.read()
            except (OSError, http.client.HTTPException):
                self.refuse(502, "the review API gives no response")
                return
            finally:
                conn.close()
            more = {
                name: value
                for name in ("WWW-Authenticate", "Allow")
                if (value := response.getheader(name)) is not None
            }
            self.close_connection = True
            kind = response.getheader("Content-Type", "application/json; charset=utf-8")
            self.send(response.status, kind, data, more)

        def log_message(self, *args: Any) -> None:
            pass

    class Server(ThreadingHTTPServer):
        request_queue_size = 64  # a browser opens a connection for each module of the kit

    httpd = Server(("127.0.0.1", port), Handler)
    host = f"127.0.0.1:{httpd.server_port}"
    return httpd


def start(
    store: Path, kit: Path | None, reviewer: str, token: str, port: int = 0
) -> tuple[ThreadingHTTPServer, ThreadingHTTPServer, str]:
    """Start the review API and the page server, each on its thread. The result is the two
    servers and the start URL, which holds the token after ``#``."""
    service = api.Service(store, api.read_token(token, reviewer))
    api_httpd = api.server(service)
    page_httpd = page_server(kit, api_httpd.server_port, port)
    for httpd in (api_httpd, page_httpd):
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return api_httpd, page_httpd, f"http://127.0.0.1:{page_httpd.server_port}/#{token}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the review and audit page on 127.0.0.1.")
    parser.add_argument("--store", metavar="DIR", help="a store with tasks; without it, a new "
                        "store with one made-up invoice")  # fmt: skip
    parser.add_argument("--reviewer", metavar="NAME", default="ana", help="the reviewer name")
    parser.add_argument("--kit", metavar="DIR", default=str(HERE / ".kit"),
                        help="the folder of the kit checkout")  # fmt: skip
    parser.add_argument("--port", type=int, default=0, help="the port; 0 takes a free one")
    parser.add_argument("--no-kit", action="store_true", help="draw plain controls: get no kit")
    args = parser.parse_args(argv)
    if args.store:
        store = Path(args.store)
        if not store.is_dir():
            print(f"error: {args.store}: the store folder is not there", file=sys.stderr)
            return 2
    else:
        store = Path(tempfile.mkdtemp(prefix="groundgate-review-page-")) / "store"
        fixture_store(store)
        print(f"The store with the made-up invoice is in {store}")
    kit = find_kit(None if args.no_kit else Path(args.kit))
    try:
        servers = start(store, kit, args.reviewer, secrets.token_urlsafe(32), args.port)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Open {servers[2]} and press Ctrl-C here when you finish.", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        for httpd in servers[:2]:
            httpd.shutdown()
            httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
