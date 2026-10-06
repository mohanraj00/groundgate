"""The label tool of the conflicts set, in a browser: for each label and field, the person clicks
the dose that the text states as the field, or says that the text states none.

    uv run python bench/conflicts/conflicts.py web     # then open http://127.0.0.1:8771

The page shows sections 2 and 3 as the pinned SPL formats them (bench/fields/web.py) and marks
every dose. It never shows what spec 0.3 or a model reads.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE.parent / "fields")]

import web  # noqa: E402  (bench/fields/web.py)
from conflicts import FIELDS  # noqa: E402  (bench/conflicts/conflicts.py)

PORT = 8771


def serve() -> None:
    items = json.loads((HERE / "items.json").read_text())
    docs = [s["id"] for s in json.loads((HERE / "sources.json").read_text())["sources"]]
    path = HERE / "labels.json"
    by_doc: dict[str, list[dict[str, Any]]] = {d: [] for d in docs}
    for it in items:
        by_doc[it["doc"]].append(it)
    pages = {d: web.page(d, its, HERE) for d, its in by_doc.items()}  # check every doc first
    doc_of = {it["id"]: it["doc"] for it in items}
    groups = [{"id": f"{d}|{f}", "doc": d, "field": f} for d in docs for f in FIELDS]
    state = {
        "groups": groups,
        "fields": [{"name": f, "description": d["description"]} for f, d in FIELDS.items()],
    }

    class Handler(BaseHTTPRequestHandler):
        def send(self, body: str, kind: str = "application/json", code: int = 200) -> None:
            raw = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if self.path == "/":
                self.send((HERE / "labeler.html").read_text(encoding="utf-8"), "text/html")
            elif self.path == "/state":
                labels = json.loads(path.read_text()) if path.exists() else {}
                self.send(json.dumps({**state, "labels": labels}))
            elif self.path.startswith("/doc/") and self.path[5:] in pages:
                self.send(pages[self.path[5:]], "text/html")
            else:
                self.send("{}", code=404)

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            group = next((g for g in groups if g["id"] == body.get("id")), None)
            value = body.get("value")
            # a label is a dose of the group's document, "none", or None for not sure
            ok = group is not None and (
                value is None or value == "none" or doc_of.get(value) == group["doc"]
            )
            if self.path != "/label" or not ok:
                self.send("{}", code=400)
                return
            labels = json.loads(path.read_text()) if path.exists() else {}
            labels[body["id"]] = value
            path.write_text(json.dumps(dict(sorted(labels.items())), indent=1) + "\n")
            self.send(json.dumps({"labels": labels}))

        def log_message(self, *args: Any) -> None:
            pass

    print(f"Open http://127.0.0.1:{PORT} and press Ctrl-C here when you finish.")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
