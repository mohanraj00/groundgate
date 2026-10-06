"""The browser label tool, standard library only. It shows each document with its items marked,
and the question. It never shows spec 0.3's reading or a model answer: not the candidate's key,
and not an answer of a judge."""

from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from . import questions as q

if TYPE_CHECKING:
    from .cli import Work


def page(text: str, items: list[dict[str, Any]]) -> str:
    """The document text with a <mark> around each item's value. A mark lists its items in
    data-ids: two items on one value, or on values that overlap, share the first mark."""
    marks: list[tuple[int, int, list[str]]] = []
    for it in sorted(items, key=lambda x: (x["mark"][0], x["id"])):
        a, b = it["mark"]
        if marks and a < marks[-1][1]:
            marks[-1][2].append(it["id"])
        else:
            marks.append((a, b, [it["id"]]))
    out, at = [], 0
    for a, b, ids in marks:
        out += [html.escape(text[at:a]), f'<mark data-ids="{html.escape(" ".join(ids))}">']
        out += [html.escape(text[a:b]), "</mark>"]
        at = b
    out.append(html.escape(text[at:]))
    return "".join(out)


def serve(w: Work, port: int) -> None:
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
                self.send(files(__package__).joinpath("label.html").read_text("utf-8"), "text/html")
            elif self.path == "/state":
                labels = json.loads(path.read_text()) if path.exists() else {}
                state = {"question": question, "items": shown, "labels": labels}
                self.send(json.dumps(state))
            elif self.path.startswith("/doc/") and unquote(self.path[5:]) in pages:
                self.send(pages[unquote(self.path[5:])], "text/html")
            else:
                self.send("{}", code=404)

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            it = by_id.get(body.get("id"))
            value = body.get("value")
            if self.path != "/label" or it is None or not q.valid_label(question, it, value):
                self.send("{}", code=400)
                return
            labels = json.loads(path.read_text()) if path.exists() else {}
            if question == "key" and value is not None:
                value = [k for k in it["keys"] if k in value]
            labels[it["id"]] = value
            path.write_text(json.dumps(dict(sorted(labels.items())), indent=1) + "\n")
            self.send(json.dumps({"labels": labels}))

        def log_message(self, *args: Any) -> None:
            pass

    print(f"Open http://127.0.0.1:{port} and press Ctrl-C here when you finish.")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
