"""Label the outside-knowledge items (#132) in a browser. Each item shows the original document
with the cited text boxed: the pinned 10-K filing HTML, or the PDF page. Beside it are the field,
the value, the extractor's quote and the text around the cited span that groundgate reads. An FDA
label is XML, so its item shows only the text and a link. The page never shows which model
proposed the value, a spec, a decision or a code. Labels go to labels.json.

    uv run --group langextract python bench/outside/outside.py web   # http://127.0.0.1:8768

Since #230, groundgate writes a PDF table as rows with tabs, so its PDF text differs from the
committed text. A PDF item checks the text against the pinned PDF, so run the page on the 0.7.0
wheel, which writes it:

    uv run --isolated --no-project --no-sources --python 3.12 --with 'groundgate[pdf]==0.7.0' \
        python bench/outside/outside.py web
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import outside

HERE = Path(__file__).parent
AROUND = 600  # code points of text on each side of the cited span
BASES = ("document", "outside")
sys.path[:0] = [str(outside.BENCH), str(outside.BENCH / "sec")]


def _pinned(path: Path, sha256: str) -> Path:
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
        raise SystemExit(f"{path} is missing or is not the pinned file")
    return path


def _filing(src: dict[str, Any]) -> Path:
    """The pinned 10-K HTML in bench/sec/.cache, as bench/sec/sec.py downloaded it."""
    return _pinned(outside.BENCH / "sec" / ".cache" / f"{src['id'][4:]}.htm", src["sha256"])


def _pdf(src: dict[str, Any]) -> Path:
    """The pinned set-2 PDF in bench/set2/.cache, as bench/fetch.py downloaded it."""
    return _pinned(outside.BENCH / "set2" / ".cache" / f"{src['id']}.pdf", src["sha256"])


def _human(url: str) -> str:
    """The web page of a DailyMed label, not its XML service, which a browser shows blank."""
    m = re.fullmatch(r"https://dailymed\.nlm\.nih\.gov/dailymed/services/v2/spls/(.+)\.xml", url)
    return f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={m[1]}" if m else url


def _nth(full: str, at: int, needle: str) -> int:
    """How many matches of needle come before code point at in full, ignoring whitespace. The
    page finds the same match in the filing's own text."""
    flat = re.sub(r"\s+", "", full[:at])
    want = re.sub(r"\s+", "", needle)
    return flat.count(want) if want else 0


def _original(
    src: dict[str, Any], text: str, a: int, b: int, cache: dict[str, Any]
) -> dict[str, Any] | None:
    """Where the page finds the cited text in the original: the match in the filing HTML, or
    the box on the PDF page. None for an FDA label."""
    from groundgate.extract import extract

    if src["kind"] == "sec":
        import sec  # bench/sec/sec.py

        if src["id"] not in cache:
            full = extract(_filing(src)).text
            part = sec.item7(full)
            if part is None or part != text:
                raise SystemExit(f"{src['id']}: docs/ is not Item 7 of the pinned filing")
            cache[src["id"]] = (full, full.index(part))
        full, start = cache[src["id"]]
        return {"type": "html", "nth": _nth(full, start + a, text[a:b])}
    if (
        src["kind"] == "fda"
    ):  # the label is XML: the page shows the whole text that groundgate reads
        return {"type": "text", "full": text, "at": [a, b]}
    if src["id"] not in cache:
        got = extract(_pdf(src), pages=src.get("select", {}).get("pages"))
        if got.text != text:
            raise SystemExit(f"{src['id']}: docs/ is not the text of the pinned PDF")
        cache[src["id"]] = got
    got = cache[src["id"]]
    ba, bb = len(text[:a].encode()), len(text[:b].encode())
    boxes = [w.box for w in got.layout.words if w.start < bb and w.end > ba]
    page = boxes[0].page
    on = [x for x in boxes if x.page == page]
    box = [min(x.x0 for x in on), min(x.top for x in on), max(x.x1 for x in on)]
    return {"type": "pdf", "page": page, "box": [*box, max(x.bottom for x in on)]}


def sources() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for set_dir, _ in outside.SETS.values():
        for src in outside._read(set_dir / "sources.json")["sources"]:
            out[src["id"]] = src
    return out


def build(every: bool = False) -> list[dict[str, Any]]:
    """One card per item that spec 0.6.1 still rejects (with every, per item), from its first
    proposal. The cited span comes from the decision of the groundgate that runs this page."""
    fixed = {it["id"] for it in outside._read(HERE / "items.json")}
    want = fixed if every else outside.still_ids()
    srcs = sources()
    descriptions: dict[tuple[str, str], str] = {}
    for set_dir, _ in outside.SETS.values():
        for p in (set_dir / "gold").glob("*.json"):
            for f, spec in outside._read(p)["fields"].items():
                descriptions[p.stem, f] = spec.get("description", "")
    cards: dict[str, dict[str, Any]] = {}
    cache: dict[str, Any] = {}
    for it, cand, d, text in outside.walk(every=True):
        if it["id"] in cards or it["id"] not in want:
            continue
        quote = cand.get("extraction_text")
        before = after = cited = ""
        original = None
        if d.evidence is not None:
            raw = text.encode("utf-8")
            a = len(raw[: d.evidence[0]].decode("utf-8"))
            b = len(raw[: d.evidence[1]].decode("utf-8"))
            before, cited, after = text[max(0, a - AROUND) : a], text[a:b], text[b : b + AROUND]
            original = _original(srcs[it["doc"]], text, a, b, cache)
        elif srcs[it["doc"]]["kind"] == "sec":
            original = {"type": "html", "nth": 0}  # the filing, with no cited text to box
        elif srcs[it["doc"]]["kind"] == "fda":
            original = {"type": "text", "full": text, "at": None}
        else:  # the first page of the text, with no box
            pages = srcs[it["doc"]].get("select", {}).get("pages") or [1]
            original = {"type": "pdf", "page": pages[0], "box": None}
        cards[it["id"]] = {
            "id": it["id"],
            "kind": it["kind"],
            "doc": it["doc"],
            "url": _human(srcs[it["doc"]]["url"]),
            "field": it["field"],
            "description": descriptions.get((it["doc"], it["field"]), ""),
            "key": it["key"],
            "value": it["value"],
            "unit": it["unit"],
            "quote": quote if isinstance(quote, str) else "",
            "before": before,
            "cited": cited,
            "after": after,
            "original": original,
        }
    if set(cards) != want:
        raise SystemExit(f"{len(want - set(cards))} items have no proposal in the runs")
    return [cards[i] for i in sorted(cards)]


def valid(got: dict[str, Any], ids: set[str]) -> bool:
    if got.get("id") not in ids or got.get("verdict") not in outside.VERDICTS:
        return False
    if got["verdict"] != "right":
        return got.get("basis") is None and got.get("source") is None
    if got.get("basis") == "document":  # the document is the source
        return got.get("source") in (None, "", "the document")
    return got.get("basis") in BASES and isinstance(got.get("source"), str) and bool(got["source"])


def serve(port: int, every: bool = False) -> None:
    items = build(every)
    ids = {it["id"] for it in items}
    srcs = sources()
    files = {
        it["doc"]: (_filing if it["kind"] == "sec" else _pdf)(srcs[it["doc"]])
        for it in items
        if it["original"] is not None and it["original"]["type"] != "text"
    }
    path = HERE / "labels.json"
    page = (HERE / "web.html").read_bytes()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def send(self, code: int, body: bytes, kind: str, original: bool = False) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            if original:  # a filing runs no script and loads nothing, so it cannot post a label
                self.send_header(
                    "Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'"
                )
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
            elif self.path.startswith("/original/") and self.path[10:] in files:
                path = files[self.path[10:]]
                kind = "application/pdf" if path.suffix == ".pdf" else "text/html; charset=utf-8"
                self.send(200, path.read_bytes(), kind, original=True)
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
