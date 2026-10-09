"""Review answers against blind labels (#176). How far do the answers of a person who sees
groundgate's decision differ from the blind labels of the same items?

    uv run python bench/status/review.py reading            # review/reading.json
    uv run python bench/status/review.py web                # answers at 127.0.0.1:8776
    uv run python bench/status/review.py results [--check]  # review/results.json, RESULTS.md

The items are the 79 key items of bench/status/calibrate/work, with their blind labels in its
labels.json: the filing statuses that each amount belongs to, or null for not sure. reading.json
records, for each item, what the review report shows of its decision: the outcome, the codes,
the missing parts, each role item with its text and whether it passed, and the keys at the
value. The page shows the PDF page with the amount boxed, that reading, and the same question
as the label page. It never shows a blind label. The answers go to review/answers.json, in the
format of the labels. The plan is on #176.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
OUT = HERE / "review"
WORK = HERE / "calibrate" / "work"
sys.path[:0] = [str(HERE), str(HERE.parent)]

import status  # noqa: E402  (bench/status/status.py)
import web  # noqa: E402  (bench/status/web.py)

PORT = 8776


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False) + "\n"


def reading() -> None:
    """reading.json: the decision of each item, as the review report shows it."""
    import groundgate as gg
    from groundgate.canonical import SPEC_VERSION
    from groundgate.text import key_mentions, keys_at

    schema = _read(HERE / "calibrate" / "schema.json")
    keys = tuple(schema["fields"]["amount"]["keys"])
    found: dict[str, Any] = {}
    by_doc: dict[str, list[Any]] = {}
    for it in _read(WORK / "items.json"):
        by_doc.setdefault(it["doc"], []).append(it)
    for doc, items in sorted(by_doc.items()):
        text = (HERE / "docs" / f"{doc}.txt").read_text(encoding="utf-8")
        cands = _read(HERE / "calibrate" / "candidates" / f"{doc}.json")
        decisions = {d.candidate_id: d for d in gg.admit(text, schema, cands).decisions}
        raw = text.encode("utf-8")

        def chars(span: tuple[int, int], raw: bytes = raw) -> tuple[int, int]:
            return len(raw[: span[0]].decode()), len(raw[: span[1]].decode())

        mentions = key_mentions(text, keys)
        for it in items:
            hits = [
                d
                for c in cands
                if (d := decisions[c["id"]]).evidence is not None
                and d.key == it["key"]
                and d.value is not None
                and chars(d.evidence)[0] <= it["mark"][0] < chars(d.evidence)[1]
            ]
            if len(hits) != 1:
                raise SystemExit(f"{it['id']}: {len(hits)} decisions hold the amount")
            d = hits[0]
            parts = []
            for p in d.parts:
                shown = None if p.span is None else text[slice(*chars(p.span))]
                parts.append({"role": p.role, "text": shown, "passed": p.passed})
            held = keys_at(text, mentions, it["mark"][0])
            found[it["id"]] = {
                "key": d.key,
                "outcome": d.outcome,
                "codes": list(d.codes),
                "missing": list(d.missing),
                "parts": parts,
                "keys_at_value": [k for k in keys if k in held],
            }
    OUT.mkdir(exist_ok=True)
    body = {"groundgate": gg.__version__, "spec": SPEC_VERSION, "items": found}
    (OUT / "reading.json").write_text(_dump(body), encoding="utf-8")
    print(f"wrote reading.json: {len(found)} items")


def serve(port: int) -> None:
    given = _read(WORK / "items.json")
    read = _read(OUT / "reading.json")["items"]
    items = web.build([{"id": it["id"], "doc": it["doc"], "span": it["mark"]} for it in given])
    for it in items:
        it["reading"] = read[it["id"]]
    path = OUT / "answers.json"
    srcs = web.sources()
    page = (HERE / "review.html").read_bytes()
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
                    answers = _read(path) if path.exists() else {}
                body = {"keys": status.KEYS, "items": items, "labels": answers}
                self.send(200, json.dumps(body).encode(), "application/json")
            elif self.path.startswith("/pdf/") and self.path[5:] in srcs:
                self.send(200, web.pdf_of(srcs[self.path[5:]]).read_bytes(), "application/pdf")
            else:
                self.send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            # a JSON body needs a preflight that this server never answers, so another site in
            # the browser cannot write an answer
            if self.path != "/label" or self.headers.get("Content-Type") != "application/json":
                self.send(404, b"not found", "text/plain")
                return
            got = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            answer = got.get("label")
            ok = got.get("id") in read and (
                answer is None
                or (isinstance(answer, list) and all(k in status.KEYS for k in answer))
            )
            if not ok:
                self.send(400, b"bad answer", "text/plain")
                return
            with lock:  # requests run in threads; one read-modify-write at a time
                answers = _read(path) if path.exists() else {}
                answers[got["id"]] = (
                    None if answer is None else sorted(answer, key=status.KEYS.index)
                )
                tmp = path.with_suffix(".tmp")
                tmp.write_text(_dump(dict(sorted(answers.items()))), encoding="utf-8")
                tmp.replace(path)  # a reader never sees half a file
            self.send(200, b"{}", "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"{len(items)} amounts; open http://127.0.0.1:{port} (Ctrl-C to stop)")
    server.serve_forever()


def score() -> dict[str, Any]:
    labels = _read(WORK / "labels.json")
    read = _read(OUT / "reading.json")["items"]
    path = OUT / "answers.json"
    answers = _read(path) if path.exists() else {}
    counts = {"items": len(read), "answered": 0, "agree": 0, "follows_reading": 0, "against": 0}
    # the label that a threshold reads: is the candidate's key right (None: not sure)
    key = {"same": 0, "review_right_blind_wrong": 0, "review_wrong_blind_right": 0, "not_sure": 0}
    differ = []
    for item_id, r in sorted(read.items()):
        if item_id not in answers:
            continue
        counts["answered"] += 1
        a, b = answers[item_id], labels.get(item_id)
        ra, rb = (None if x is None else r["key"] in x for x in (a, b))
        if ra is None or rb is None:
            key["not_sure"] += 1
        elif ra == rb:
            key["same"] += 1
        else:
            key["review_right_blind_wrong" if ra else "review_wrong_blind_right"] += 1
        if a == b:
            counts["agree"] += 1
            continue
        follows = a == r["keys_at_value"]
        counts["follows_reading" if follows else "against"] += 1
        differ.append({"id": item_id, "key": r["key"], "review": a, "blind": b,
                       "follows_reading": follows})  # fmt: skip
    return {**counts, "key": key, "differ": differ}


def render(res: dict[str, Any]) -> str:
    md = [
        "# Review answers against blind labels",
        "",
        "Generated by `bench/status/review.py results` from `review/answers.json`, the blind "
        "labels of `calibrate/work` and `review/reading.json`. Do not edit.",
        "",
        f"Items: {res['items']}. Answered on the review page: {res['answered']}.",
        "",
        "| Review answer and blind label | Items |",
        "|---|---:|",
        f"| the same | {res['agree']} |",
        f"| differ, and the answer is groundgate's reading | {res['follows_reading']} |",
        f"| differ in another way | {res['against']} |",
        "",
        "A threshold reads one label for each item: is the candidate's key right?",
        "",
        "| Candidate's key | Items |",
        "|---|---:|",
        f"| the same in both | {res['key']['same']} |",
        f"| right in the review answer, wrong in the blind label | "
        f"{res['key']['review_right_blind_wrong']} |",
        f"| wrong in the review answer, right in the blind label | "
        f"{res['key']['review_wrong_blind_right']} |",
        f"| not sure in either | {res['key']['not_sure']} |",
        "",
        "## Each difference",
        "",
        "| Item | Candidate's key | Review answer | Blind label | "
        "The answer is groundgate's reading |",
        "|---|---|---|---|---|",
    ]
    for d in res["differ"]:

        def fmt(x: Any) -> str:
            return "not sure" if x is None else ("none" if not x else "; ".join(x))

        md.append(
            f"| `{d['id']}` | {d['key']} | {fmt(d['review'])} | {fmt(d['blind'])} | "
            f"{'yes' if d['follows_reading'] else 'no'} |"
        )
    return "\n".join(md) + "\n"


def results(check: bool) -> None:
    res = score()
    files = {OUT / "results.json": _dump(res), OUT / "RESULTS.md": render(res)}
    if check:
        stale = [p.name for p, b in files.items() if p.read_text(encoding="utf-8") != b]
        if stale:
            raise SystemExit(f"out of date: {', '.join(stale)}; run review.py results")
        print("results are up to date")
        return
    for p, b in files.items():
        p.write_text(b, encoding="utf-8")
    print("wrote review/results.json, review/RESULTS.md")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("reading")
    w = sub.add_parser("web")
    w.add_argument("--port", type=int, default=PORT)
    r = sub.add_parser("results")
    r.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.cmd == "reading":
        reading()
    elif args.cmd == "web":
        serve(args.port)
    else:
        results(args.check)


if __name__ == "__main__":
    main()
