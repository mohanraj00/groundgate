"""A local app for checking the benchmark gold, one document at a time.

    uv run python bench/label/app.py          # opens http://127.0.0.1:8765

It shows the document, the draft facts and the fields the draft marks absent. You confirm,
correct or reject each fact, add any it missed, and confirm each absence. Saves go straight to
bench/gold/<id>.json. It never shows model output, so the labels stay blind to what the
benchmarked models extracted.

The server binds to 127.0.0.1 only, and every API call must carry a token that exists only in
the page it served, so other sites in your browser cannot read or write the gold. The header
links to the original document, and a pane shows a cached PDF at the page of the focused fact,
because flattened tables are hard to read as text.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import secrets
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from groundgate.text import parse_value

HERE = Path(__file__).parent
BENCH = HERE.parent
GOLD = BENCH / "gold"
DOCS = BENCH / "docs"
CACHE = BENCH / ".cache"  # fetch.py's downloads
SOURCES = BENCH / "sources.json"
TOKEN = secrets.token_urlsafe(24)
FACT_STATUS = {"draft", "confirmed", "rejected"}
ABSENT_STATUS = {"draft", "confirmed"}
LOCK = threading.Lock()


def doc_ids() -> list[str]:
    return sorted(p.stem for p in GOLD.glob("*.json"))


def source_link(doc_id: str) -> str | None:
    """Where to read the original: the cached PDF, or the label on DailyMed."""
    if (CACHE / f"{doc_id}.pdf").exists():
        return f"/source/{doc_id}"
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))["sources"]
    src = next((s for s in sources if s["id"] == doc_id), None)
    if src is None:
        return None
    if src["kind"] == "fda":
        setid = src["url"].rsplit("/", 1)[-1].removesuffix(".xml")
        return f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"
    return str(src["url"])


def pdf_pane(doc_id: str) -> dict[str, Any] | None:
    """The cached PDF for the side pane, with the PDF page number of each text page."""
    if not (CACHE / f"{doc_id}.pdf").exists():
        return None
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))["sources"]
    src = next((s for s in sources if s["id"] == doc_id), {})
    pages = src.get("select", {}).get("pages")
    return {"url": f"/source/{doc_id}", "pages": sorted(pages) if pages else None}


def unkeyed(gold: dict[str, Any], fact: dict[str, Any]) -> bool:
    """A kept fact on a keyed field that has no key yet."""
    keys = gold["fields"][fact["field"]]["schema"].get("keys")
    return bool(keys) and fact["status"] != "rejected" and fact.get("key") is None


def control(gold: dict[str, Any]) -> bool:
    """A set-2 control document: NTSB, IRS general or a general-only FDA label. Only its
    candidates that spec 0.1 and 0.2 decide differently are judged (#12), so it is not checked
    in full."""
    groups = gold.get("groups")
    return bool(groups) and set(groups) <= {"general", "control"}


def summary(gold: dict[str, Any]) -> dict[str, Any]:
    facts = gold["facts"]
    return {
        "id": gold["doc"],
        "kind": gold["kind"],
        "control": control(gold),
        "facts": len(facts),
        "open": sum(f["status"] == "draft" or unkeyed(gold, f) for f in facts)
        + sum(s == "draft" for s in gold["absent"].values()),
        "checked": gold.get("checked") is not None,
    }


def validate(gold: dict[str, Any], old: dict[str, Any], text: str) -> str | None:
    """Why ``gold`` may not be saved over ``old``, or None."""
    size = len(text.encode("utf-8"))
    if gold.get("doc") != old["doc"] or gold.get("fields") != old["fields"]:
        return "the document id and field definitions cannot change here"
    if not isinstance(gold.get("facts"), list):
        return "facts must be a list"
    for fact in gold["facts"]:
        if fact.get("field") not in old["fields"]:
            return f"unknown field {fact.get('field')!r}"
        if fact.get("status") not in FACT_STATUS or not isinstance(fact.get("value"), str):
            return "each fact needs a string value and a known status"
        if parse_value(fact["value"]) is None:
            return f"{fact['value']!r} is not a number (write 15750 or 15,750, no $ or unit)"
        keys = old["fields"][fact["field"]]["schema"].get("keys")
        if keys and fact.get("key") is not None and fact["key"] not in keys:
            return f"{fact['key']!r} is not a key of {fact['field']}"
        ev = fact.get("evidence")
        if not isinstance(ev, list):
            return "evidence must be a list"
        for span in ev:
            s, e = span.get("start"), span.get("end")
            if not (isinstance(s, int) and isinstance(e, int) and 0 <= s < e <= size):
                return "every evidence span must lie inside the document"
    absent, excluded = gold.get("absent"), gold.get("excluded")
    if not isinstance(absent, dict) or not isinstance(excluded, dict):
        return "absent and excluded must be objects"
    if any(k not in old["fields"] or v not in ABSENT_STATUS for k, v in absent.items()):
        return "absent entries need a known field and status"
    if any(k not in old["fields"] or not isinstance(v, str) for k, v in excluded.items()):
        return "excluded entries need a known field and a reason"
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "groundgate-label"

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: Any) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json")

    def _local(self) -> bool:
        return self.headers.get("Host", "").startswith("127.0.0.1:")

    def _authorized(self) -> bool:
        return self.headers.get("X-Label-Token") == TOKEN and self._local()

    def _doc(self) -> str | None:
        doc_id = self.path.split("?", 1)[0].rsplit("/", 1)[-1]
        return doc_id if doc_id in doc_ids() else None

    def do_GET(self) -> None:
        if self.path == "/":
            page = (HERE / "label.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
            self._send(HTTPStatus.OK, page.encode(), "text/html; charset=utf-8")
            return
        if self.path.startswith("/source/") and self._local() and (doc_id := self._doc()):
            # opened in a new tab, so no token; it is a public document
            pdf = CACHE / f"{doc_id}.pdf"
            if pdf.exists():
                self._send(HTTPStatus.OK, pdf.read_bytes(), "application/pdf")
                return
        if not self._authorized():
            self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            return
        if self.path == "/api/docs":
            docs = [summary(json.loads((GOLD / f"{d}.json").read_text())) for d in doc_ids()]
            docs.sort(key=lambda d: d["control"])  # controls last; stable, so ids stay sorted
            self._json(HTTPStatus.OK, docs)
        elif self.path.startswith("/api/doc/") and (doc_id := self._doc()):
            gold = json.loads((GOLD / f"{doc_id}.json").read_text(encoding="utf-8"))
            text = (DOCS / f"{doc_id}.txt").read_text(encoding="utf-8")
            self._json(
                HTTPStatus.OK,
                {
                    "gold": gold,
                    "text": text,
                    "source": source_link(doc_id),
                    "pdf": pdf_pane(doc_id),
                },
            )
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized():
            self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            return
        doc_id = self._doc() if self.path.startswith("/api/doc/") else None
        if doc_id is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length > 5_000_000:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "too large"})
            return
        try:
            body = json.loads(self.rfile.read(length))
            gold, done, seconds = body["gold"], bool(body.get("done")), int(body.get("seconds", 0))
        except (ValueError, KeyError, TypeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "bad request"})
            return
        path = GOLD / f"{doc_id}.json"
        with LOCK:
            old = json.loads(path.read_text(encoding="utf-8"))
            text = (DOCS / f"{doc_id}.txt").read_text(encoding="utf-8")
            problem = validate(gold, old, text)
            if problem is None and done and summary(gold)["open"]:
                problem = (
                    "decide every draft fact and absence, and pick a key for every kept fact on "
                    "a keyed field, before marking the document checked"
                )
            if problem:
                self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": problem})
                return
            gold["seconds_spent"] = int(old.get("seconds_spent", 0)) + max(0, seconds)
            for fact in gold["facts"]:
                fact["unit"] = old["fields"][fact["field"]]["schema"]["unit"]
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            gold["checked"] = {"by": "person", "at": stamp} if done else None
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(gold, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp.replace(path)
        self._json(HTTPStatus.OK, summary(gold))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--set", type=Path, default=BENCH, help="benchmark set directory")
    args = ap.parse_args()
    global GOLD, DOCS, CACHE, SOURCES
    root = args.set.resolve()
    GOLD, DOCS, CACHE = root / "gold", root / "docs", root / ".cache"
    SOURCES = root / "sources.json"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"labeling app at {url}  (Ctrl-C to stop)", file=sys.stderr)
    if not args.no_browser:
        webbrowser.open(url)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()


if __name__ == "__main__":
    main()
