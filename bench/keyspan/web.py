"""Label the values that spec 0.5 admits by a cited key span and that no set has labeled yet
(#131). Like bench/status/web.py: the PDF page with the value boxed for an IRS publication, the
text around the value, and the field's keys. It never shows which key the extractor gave, its
key span, or what any spec decides.

    uv run python bench/keyspan/web.py              # then open http://127.0.0.1:8769
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import keyspan

from groundgate.text import tokens

HERE = Path(__file__).parent
BEFORE, AFTER = 700, 300  # code points of text around the value


def _status_web() -> Any:
    """bench/status/web.py, for its pinned PDFs."""
    spec = importlib.util.spec_from_file_location("status_web", keyspan.STATUS / "web.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def todo() -> list[dict[str, Any]]:
    """The cited values with no label in the sets or in labels.json, in a fixed order. An amount
    that a set labels "not sure" has a label, so the page does not ask for it again."""
    decisions = json.loads((HERE / "decisions.json").read_text(encoding="utf-8"))
    known = {name: keyspan.labeled_ids(name, decisions) for name in decisions}
    out: dict[str, dict[str, Any]] = {}
    for c in keyspan.cited(decisions):
        lid = keyspan.label_id(c["set"], c["doc"], c["at"])
        if lid not in known[c["set"]]:
            out[lid] = {"id": lid, "set": c["set"], "doc": c["doc"], "at": c["at"],
                        "field": c["field"]}  # fmt: skip
    return [out[k] for k in sorted(out)]


def build() -> list[dict[str, Any]]:
    from groundgate.extract import extract

    sec_schema = keyspan._schema("sec")["fields"]
    status_web = _status_web()
    srcs = status_web.sources()
    layouts: dict[str, Any] = {}
    items = []
    for it in todo():
        set_dir = keyspan.STATUS if it["set"] == "status" else keyspan.SEC
        text = (set_dir / "docs" / f"{it['doc']}.txt").read_text(encoding="utf-8")
        a = it["at"]
        b = next(t.end for t in tokens(text, a) if t.start == a)
        keys = keyspan.STATUS_KEYS if it["set"] == "status" else sec_schema[it["field"]]["keys"]
        card: dict[str, Any] = {
            "id": it["id"],
            "doc": it["doc"],
            "keys": keys,
            "page": None,
            "box": None,
            "before": text[max(0, a - BEFORE) : a],
            "amount": text[a:b],
            "after": text[b : b + AFTER],
        }
        if it["set"] == "status":
            doc = it["doc"]
            if doc not in layouts:
                got = extract(status_web.pdf_of(srcs[doc]), pages=srcs[doc]["select"]["pages"])
                if got.text != text:
                    raise SystemExit(f"{doc}: docs/{doc}.txt is not the text of the pinned PDF")
                layouts[doc] = got
            got = layouts[doc]
            ba, bb = len(text[:a].encode()), len(text[:b].encode())
            boxes = [w.box for w in got.layout.words if w.start < bb and w.end > ba]
            on_page = [x for x in boxes if x.page == boxes[0].page]
            card["page"] = boxes[0].page
            card["box"] = [
                min(x.x0 for x in on_page),
                min(x.top for x in on_page),
                max(x.x1 for x in on_page),
                max(x.bottom for x in on_page),
            ]
        items.append(card)
    return items


def serve(port: int) -> None:
    items = build()
    keys_of = {it["id"]: it["keys"] for it in items}
    status_web = _status_web()
    srcs = status_web.sources()
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
                    labels = keyspan._extra_labels()
                body = {"items": items, "labels": labels}
                self.send(200, json.dumps(body).encode(), "application/json")
            elif self.path.startswith("/pdf/") and self.path[5:] in srcs:
                pdf = status_web.pdf_of(srcs[self.path[5:]]).read_bytes()
                self.send(200, pdf, "application/pdf")
            else:
                self.send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            # a JSON body needs a preflight that this server never answers, so another site in
            # the browser cannot write a label
            if self.path != "/label" or self.headers.get("Content-Type") != "application/json":
                self.send(404, b"not found", "text/plain")
                return
            got = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            keys = keys_of.get(got.get("id"))
            answer = got.get("label")
            ok = keys is not None and (
                answer is None or (isinstance(answer, list) and all(k in keys for k in answer))
            )
            if not ok:
                self.send(400, b"bad label", "text/plain")
                return
            assert keys is not None
            with lock:  # requests run in threads; one read-modify-write at a time
                labels = keyspan._extra_labels()
                labels[got["id"]] = None if answer is None else sorted(answer, key=keys.index)
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(dict(sorted(labels.items())), indent=1) + "\n")
                tmp.replace(path)  # a reader never sees half a file
            self.send(200, b"{}", "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"{len(items)} values; open http://127.0.0.1:{port} (Ctrl-C to stop)")
    server.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8769)
    serve(ap.parse_args().port)
