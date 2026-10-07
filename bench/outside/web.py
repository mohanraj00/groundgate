"""Label the outside-knowledge items (#132) in a browser. Each item shows the document's source,
the field, the value, the extractor's quote and the text around the cited span. It never shows
which model proposed the value. Labels go to labels.json.

    uv run --group langextract python bench/outside/outside.py web   # http://127.0.0.1:8768
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import outside

HERE = Path(__file__).parent
AROUND = 600  # code points of text on each side of the cited span
BASES = ("document", "outside")


def build() -> list[dict[str, Any]]:
    """One card per item, from its first proposal."""
    urls: dict[str, str] = {}
    descriptions: dict[tuple[str, str], str] = {}
    for set_dir, _ in outside.SETS.values():
        for s in outside._read(set_dir / "sources.json")["sources"]:
            urls[s["id"]] = s["url"]
        for p in (set_dir / "gold").glob("*.json"):
            for f, spec in outside._read(p)["fields"].items():
                descriptions[p.stem, f] = spec.get("description", "")
    cards: dict[str, dict[str, Any]] = {}
    for it, cand, d, text in outside.walk():
        if it["id"] in cards:
            continue
        quote = cand.get("extraction_text")
        before = after = cited = ""
        if d.evidence is not None:
            raw = text.encode("utf-8")
            a = len(raw[: d.evidence[0]].decode("utf-8"))
            b = len(raw[: d.evidence[1]].decode("utf-8"))
            before, cited, after = text[max(0, a - AROUND) : a], text[a:b], text[b : b + AROUND]
        cards[it["id"]] = {
            "id": it["id"],
            "kind": it["kind"],
            "doc": it["doc"],
            "url": urls.get(it["doc"], ""),
            "field": it["field"],
            "description": descriptions.get((it["doc"], it["field"]), ""),
            "key": it["key"],
            "value": it["value"],
            "unit": it["unit"],
            "quote": quote if isinstance(quote, str) else "",
            "before": before,
            "cited": cited,
            "after": after,
        }
    return [cards[i] for i in sorted(cards)]


def valid(got: dict[str, Any], ids: set[str]) -> bool:
    if got.get("id") not in ids or got.get("verdict") not in outside.VERDICTS:
        return False
    if got["verdict"] != "right":
        return got.get("basis") is None and got.get("source") is None
    if got.get("basis") == "document":  # the document is the source
        return got.get("source") in (None, "", "the document")
    return got.get("basis") in BASES and isinstance(got.get("source"), str) and bool(got["source"])


def serve(port: int) -> None:
    items = build()
    ids = {it["id"] for it in items}
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
                    labels = outside.labels()
                body = {"items": items, "labels": labels}
                self.send(200, json.dumps(body).encode(), "application/json")
            else:
                self.send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            # a JSON body needs a preflight that this server never answers, so another site in
            # the browser cannot write a label
            if self.path != "/label" or self.headers.get("Content-Type") != "application/json":
                self.send(404, b"not found", "text/plain")
                return
            got = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if not valid(got, ids):
                self.send(400, b"bad label", "text/plain")
                return
            with lock:  # requests run in threads; one read-modify-write at a time
                labels = outside.labels()
                labels[got["id"]] = {
                    "verdict": got["verdict"],
                    "basis": got.get("basis"),
                    "source": "the document"
                    if got.get("basis") == "document"
                    else got.get("source"),
                }
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(dict(sorted(labels.items())), indent=1) + "\n")
                tmp.replace(path)  # a reader never sees half a file
            self.send(200, b"{}", "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"{len(items)} items; open http://127.0.0.1:{port} (Ctrl-C to stop)")
    server.serve_forever()
