"""The label tool of the fields set in a browser, with each label shown as its SPL formats it.

    uv run python bench/fields/fields.py web     # then open http://127.0.0.1:8770

The page shows sections 2 and 3 of the pinned label with its headings, lists and tables, and
marks the dose to label. It saves to labels.json in the same format as the terminal tool. Like
that tool, it never shows what spec 0.3 or a model reads.
"""

from __future__ import annotations

import hashlib
import html
import json
import sys
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE.parent)]

from fetch import HL7, download  # noqa: E402  (bench/fetch.py)

PORT = 8770
# SPL element -> HTML element; an element not here keeps its text and adds no element
TAGS = {
    "title": "h4", "paragraph": "p", "list": "ul", "item": "li", "table": "table",
    "thead": "thead", "tbody": "tbody", "tfoot": "tfoot", "tr": "tr", "td": "td", "th": "th",
    "caption": "caption", "br": "br", "sup": "sup", "sub": "sub", "section": "section",
}  # fmt: skip
STYLE = {"bold": "b", "italics": "i", "underline": "u"}
SPAN = {"colspan", "rowspan"}
SKIP = {"code", "id", "effectiveTime", "renderMultiMedia"}


def local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def non_space(text: str) -> int:
    return sum(not c.isspace() for c in text)


class Page:
    """HTML of SPL sections, with a <mark> around each dose. A dose is found by its count of
    non-space characters, which the text in docs/ and the HTML have in common: xml_text keeps
    every non-space character and adds one (^ or _) before each sup or sub."""

    def __init__(self, marks: dict[int, tuple[int, str]]) -> None:
        self.marks = marks  # start -> (end, item id), in non-space characters
        self.n = 0
        self.open: tuple[int, str] | None = None
        self.out: list[str] = []
        self.seen = ""  # non-space characters, to check against docs/

    def text(self, data: str) -> None:
        for c in data:
            if not c.isspace():
                if self.open is None and self.n in self.marks:
                    self.open = self.marks[self.n]
                    self.out.append(f'<mark id="{html.escape(self.open[1])}">')
                self.seen += c
                self.n += 1
            self.out.append(html.escape(c))
            if self.open is not None and self.n == self.open[0]:
                self.out.append("</mark>")
                self.open = None

    def walk(self, e: ET.Element, depth: int) -> None:
        tag = local(e.tag)
        if tag in SKIP:
            return
        name = TAGS.get(tag) or STYLE.get(e.get("styleCode", "").lower(), "")
        if tag == "list" and e.get("listType") == "ordered":
            name = "ol"
        if tag == "title":
            name = f"h{min(6, 2 + depth)}"
        attrs = "".join(f' {a}="{html.escape(v)}"' for a, v in e.attrib.items() if a in SPAN)
        if tag in ("sup", "sub"):
            self.seen += "^" if tag == "sup" else "_"
            self.n += 1
        if name:
            self.out.append(f"<{name}{attrs}>")
        if self.open is not None:  # a dose never spans elements, but keep the HTML valid
            self.out.append("</mark>")
            self.open = None
        self.text(e.text or "")
        for child in e:
            self.walk(child, depth + (tag == "section"))
            self.text(child.tail or "")
        if self.open is not None:
            self.out.append("</mark>")
            self.open = None
        if name and name != "br":
            self.out.append(f"</{name}>")


def page(doc: str, items: list[dict[str, Any]], root: Path = HERE) -> str:
    """The HTML of the doc's sections in the set at root, with its doses marked; it fails if it
    does not match the text in docs/."""
    sources = json.loads((root / "sources.json").read_text())["sources"]
    src = next(s for s in sources if s["id"] == doc)
    (root / ".cache").mkdir(exist_ok=True)
    data = download(src["url"], root / ".cache" / f"{doc}.xml")
    if hashlib.sha256(data).hexdigest() != src["sha256"]:
        raise SystemExit(f"{doc}: the label is not the pinned revision; run bench/fetch.py")
    text = (root / "docs" / f"{doc}.txt").read_text(encoding="utf-8")
    marks = {}
    for it in items:
        a, b = it["span"]
        start = non_space(text[:a])
        marks[start] = (start + non_space(text[a:b]), it["id"])
    p = Page(marks)
    taken: set[int] = set()
    for sec in ET.fromstring(data).iter(f"{HL7}section"):
        code = sec.find(f"{HL7}code")
        if id(sec) in taken or code is None or code.get("code") not in src["select"]["sections"]:
            continue
        taken.update(id(e) for e in sec.iter())
        p.walk(sec, 0)
    want = "".join(c for c in text if not c.isspace())
    if p.seen != want:
        pairs = enumerate(zip(p.seen, want, strict=False))
        at = next((i for i, (x, y) in pairs if x != y), min(len(p.seen), len(want)))
        raise SystemExit(f"{doc}: the HTML text differs from docs/ at non-space character {at}")
    return "".join(p.out)


def serve(fields: dict[str, dict[str, Any]]) -> None:
    items = json.loads((HERE / "items.json").read_text())
    path = HERE / "labels.json"
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        by_doc.setdefault(it["doc"], []).append(it)
    pages = {doc: page(doc, its) for doc, its in by_doc.items()}  # check every doc at the start
    state = {
        "items": [{"id": it["id"], "doc": it["doc"]} for it in items],
        "fields": [{"name": f, "description": d["description"]} for f, d in fields.items()],
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
                self.send((HERE / "web.html").read_text(encoding="utf-8"), "text/html")
            elif self.path == "/state":
                labels = json.loads(path.read_text()) if path.exists() else {}
                self.send(json.dumps({**state, "labels": labels}))
            elif self.path.startswith("/doc/") and self.path[5:] in pages:
                self.send(pages[self.path[5:]], "text/html")
            else:
                self.send("{}", code=404)

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            names = [f["name"] for f in state["fields"]]
            value = body.get("value")
            ok = body.get("id") in {it["id"] for it in items} and (
                value is None or (isinstance(value, list) and all(v in names for v in value))
            )
            if self.path != "/label" or not ok:
                self.send("{}", code=400)
                return
            labels = json.loads(path.read_text()) if path.exists() else {}
            labels[body["id"]] = None if value is None else [n for n in names if n in value]
            path.write_text(json.dumps(dict(sorted(labels.items())), indent=1) + "\n")
            self.send(json.dumps({"labels": labels}))

        def log_message(self, *args: Any) -> None:
            pass

    print(f"Open http://127.0.0.1:{PORT} and press Ctrl-C here when you finish.")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
