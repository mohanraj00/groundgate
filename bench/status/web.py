"""Label the status set in a browser: the PDF page with the amount boxed, the text around it, and
the 5 filing statuses. It writes the same labels.json as ``status.py label``, and like it, never
shows which keys a spec puts at an amount.

    uv run python bench/status/web.py              # then open http://127.0.0.1:8767
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE), str(HERE.parent)]

import status  # noqa: E402  (bench/status/status.py)
from fetch import download  # noqa: E402  (bench/fetch.py)

BEFORE, AFTER = 700, 300  # code points of text around the amount


def sources() -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in json.loads((HERE / "sources.json").read_text())["sources"]}


def pdf_of(src: dict[str, Any]) -> Path:
    """The pinned PDF of a source, downloaded once into .cache."""
    (HERE / ".cache").mkdir(exist_ok=True)
    path = HERE / ".cache" / f"{src['id']}.pdf"
    if hashlib.sha256(download(src["url"], path)).hexdigest() != src["sha256"]:
        raise SystemExit(f"{src['id']}: the PDF is not the pinned file; delete {path}")
    return path


def build() -> list[dict[str, Any]]:
    """Each item with its text around it and its box on the PDF page."""
    from groundgate.extract import extract

    srcs = sources()
    items = json.loads((HERE / "items.json").read_text())
    out: list[dict[str, Any]] = []
    docs: dict[str, Any] = {}
    for it in items:
        doc = it["doc"]
        if doc not in docs:
            got = extract(pdf_of(srcs[doc]), pages=srcs[doc]["select"]["pages"])
            text = (HERE / "docs" / f"{doc}.txt").read_text(encoding="utf-8")
            if got.text != text:
                raise SystemExit(f"{doc}: docs/{doc}.txt is not the text of the pinned PDF")
            docs[doc] = got
        got = docs[doc]
        a, b = it["span"]
        ba, bb = len(got.text[:a].encode()), len(got.text[:b].encode())
        boxes = [w.box for w in got.layout.words if w.start < bb and w.end > ba]
        page = boxes[0].page
        on_page = [x for x in boxes if x.page == page]
        out.append(
            {
                "id": it["id"],
                "doc": doc,
                "page": page,
                "box": [
                    min(x.x0 for x in on_page),
                    min(x.top for x in on_page),
                    max(x.x1 for x in on_page),
                    max(x.bottom for x in on_page),
                ],
                "before": got.text[max(0, a - BEFORE) : a],
                "amount": got.text[a:b],
                "after": got.text[b : b + AFTER],
            }
        )
    return out


def serve(port: int) -> None:
    items = build()
    srcs = sources()
    path = HERE / "labels.json"
    page = (HERE / "web.html").read_bytes()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def send(self, code: int, body: bytes, kind: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/":
                self.send(200, page, "text/html; charset=utf-8")
            elif self.path == "/state":
                with lock:
                    labels = json.loads(path.read_text()) if path.exists() else {}
                body = {"keys": status.KEYS, "items": items, "labels": labels}
                self.send(200, json.dumps(body).encode(), "application/json")
            elif self.path.startswith("/pdf/") and self.path[5:] in srcs:
                self.send(200, pdf_of(srcs[self.path[5:]]).read_bytes(), "application/pdf")
            else:
                self.send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            # a JSON body needs a preflight that this server never answers, so another site in
            # the browser cannot write a label
            if self.path != "/label" or self.headers.get("Content-Type") != "application/json":
                self.send(404, b"not found", "text/plain")
                return
            got = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            ids = {it["id"] for it in items}
            answer = got.get("label")
            ok = got.get("id") in ids and (
                answer is None
                or (isinstance(answer, list) and all(k in status.KEYS for k in answer))
            )
            if not ok:
                self.send(400, b"bad label", "text/plain")
                return
            with lock:  # requests run in threads; one read-modify-write at a time
                labels = json.loads(path.read_text()) if path.exists() else {}
                labels[got["id"]] = (
                    None if answer is None else sorted(answer, key=status.KEYS.index)
                )
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(dict(sorted(labels.items())), indent=1) + "\n")
                tmp.replace(path)  # a reader never sees half a file
            self.send(200, b"{}", "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"{len(items)} amounts; open http://127.0.0.1:{port} (Ctrl-C to stop)")
    server.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8767)
    serve(ap.parse_args().port)
