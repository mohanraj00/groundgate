"""A local page where the owner decides each disagreement of two blind label passes (#641).

    uv run python bench/label/decide.py --sources DIR --work WORK [--set bench/regulatory2]

The page reads ``WORK/compare.json`` from ``bench/regulatory/passes.py compare``. For each slot
that the passes do not agree on, it shows the request, the field rule, the reader text of the
named section, the answer of each pass and the absence checks. The owner picks pass a, pass b,
absent, or gives the value. Each choice goes to ``WORK/decisions.json`` at once.

The server is a ``bench/localweb.py`` server: 127.0.0.1 only, a Host check, and a token cookie.
The page writes all answer text with ``textContent``, never as HTML.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "regulatory"))
import localweb  # noqa: E402  (bench/localweb.py)
import passes  # noqa: E402  (bench/regulatory/passes.py)

CHOICES = ("a", "b", "absent", "other")
LOCK = threading.Lock()
WORK = Path()
ITEMS: list[dict[str, Any]] = []


def items(sources: Path, work: Path, directory: Path | None = None) -> list[dict[str, Any]]:
    """The disagreements, each with its slot and the reader text of its section."""
    import xml.etree.ElementTree as ET

    from groundgate.read.markup import xml_text

    data = json.loads((directory or BENCH / "regulatory").joinpath("slots.json").read_text())
    slots = {s["slot"]: s for s in data["slots"]}
    texts: dict[tuple[str, str], str] = {}
    out = []
    for row in json.loads((work / "compare.json").read_text()):
        if row["state"] == "agree":
            continue
        s = slots[row["slot"]]
        key = (s["id"], s["request"]["section"])
        if key not in texts:
            secs = passes.section_map((sources / f"{s['id']}.xml").read_bytes())
            texts[key] = xml_text(ET.tostring(secs[key[1]], encoding="unicode").encode())
        out.append({
            "slot": s["slot"], "id": s["id"], "split": s["split"], "kind": s["kind"],
            "request": s["request_text"], "rule": data["schema"][s["field"]]["description"],
            "text": texts[key], "a": row["a"], "b": row["b"], "checks": row["absence_checks"],
        })  # fmt: skip
    return out


def decisions() -> dict[str, Any]:
    path = WORK / "decisions.json"
    return json.loads(path.read_text()) if path.exists() else {}


class Handler(localweb.LocalHandler):
    def _json(self, code: int, body: Any) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/":
            raw = (HERE / "decide.html").read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
                "connect-src 'self'",
            )
            self.end_headers()
            self.wfile.write(raw)
        elif self.path == "/decide.js":
            raw = (HERE / "decide.js").read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        elif self.path == "/api/items":
            with LOCK:
                self._json(HTTPStatus.OK, {"items": ITEMS, "decisions": decisions()})
        else:
            self.refuse(404, "not found")

    def do_POST(self) -> None:
        if self.path != "/api/decide":
            self.refuse(404, "not found")
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            slot, choice = str(body["slot"]), body["choice"]
            value, unit, note = body.get("value"), body.get("unit"), str(body.get("note") or "")
        except (ValueError, KeyError, TypeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "bad request"})
            return
        if slot not in {i["slot"] for i in ITEMS} or choice not in CHOICES:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": "unknown slot or choice"})
            return
        item = next(i for i in ITEMS if i["slot"] == slot)
        why = passes.problem(
            item["kind"], passes.chosen(item, {"choice": choice, "value": value, "unit": unit})
        )
        if why:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": why})
            return
        with LOCK:
            got = decisions()
            got[slot] = {
                "choice": choice,
                "value": value if choice == "other" else None,
                "unit": unit if choice == "other" else None,
                "note": note,
                "by": "owner",
                "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            tmp = WORK / "decisions.tmp"
            tmp.write_text(json.dumps(got, indent=1, ensure_ascii=False) + "\n")
            tmp.replace(WORK / "decisions.json")
        self._json(HTTPStatus.OK, {"decided": len(got), "open": len(ITEMS) - len(got)})


def main(argv: list[str] | None = None) -> int:
    global WORK, ITEMS
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--port", type=int, default=8774)
    ap.add_argument("--set", type=Path, help="the set folder (default: bench/regulatory)")
    args = ap.parse_args(argv)
    WORK = args.work
    ITEMS = items(args.sources, args.work, args.set)
    localweb.serve(Handler, args.port, f"{len(ITEMS)} disagreements")
    return 0


if __name__ == "__main__":
    sys.exit(main())
