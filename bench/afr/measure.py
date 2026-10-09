"""Measure the #164 rule on the held-out set of agency financial reports (#229): the two runs of
run.py, decided under spec 0.6 and under the 0.7 draft with the #164 rule. The rule ships only
if this measure says so (#164).

    uv run --isolated --no-project --no-sources --python 3.12 --with groundgate==0.6.1 \
        python bench/afr/measure.py decide              # spec 0.6, on the released wheel
    uv run python bench/afr/measure.py decide           # the 0.7 draft, with the #164 rule
    uv run python bench/afr/measure.py web              # blind labels, http://127.0.0.1:8777
    uv run python bench/afr/measure.py results [--check]

A person labels every value that a decision admits, and every value whose outcome differs
between the two specs. The page shows the PDF page with the value boxed, the text around it, the
field, the year and the value, but never a run, a spec, an outcome or a code.

The #164 rule is the only change of the 0.7 draft that a decision on this set can see. A later
0.7 rule that changes a decision adds the function that turns it off here, as
bench/sec3/measure.py does.
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
RUNS = ("claude-haiku-5-5", "gpt-6-luna")
SPECS = ("0.6", "0.7 #164")
VERDICTS = ("right", "wrong", "not sure")
BEFORE, AFTER = 500, 200  # code points of text around the value
PORT = 8777


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _name(run: str, spec: str) -> Path:
    return HERE / f"decisions-{run}-{spec.replace(' ', '-').replace('#', '')}.json"


def decide() -> None:
    """decisions-<run>-<spec>.json for the spec of the groundgate that runs this script: for each
    document, each candidate's outcome and codes. A document with no reply is listed with no
    candidates and counted in the results."""
    import groundgate as gg
    from groundgate.canonical import SPEC_VERSION

    specs = [spec for spec in SPECS if spec.split()[0] == SPEC_VERSION]
    if not specs:
        raise SystemExit(f"no spec here needs groundgate {SPEC_VERSION}: use the spec's wheel")
    (spec,) = specs
    schema = _read(HERE / "schema.json")
    for run in RUNS:
        found: dict[str, Any] = {}
        for doc_path in sorted((HERE / "docs").glob("*.txt")):
            doc = doc_path.stem
            reply = _read(HERE / "runs" / run / f"{doc}.json")["reply"]
            cands = [] if reply is None else reply["candidates"]
            cands = [{"id": f"c{i}", **c} for i, c in enumerate(cands)]
            text = doc_path.read_text(encoding="utf-8")
            by_sha = {d.candidate_sha256: d for d in gg.admit(text, schema, cands).decisions}
            rows = []
            for c in cands:
                d = by_sha[gg.digest("candidate", c)]
                rows.append(
                    {
                        "id": c["id"],
                        "field": d.field,
                        "key": d.key,
                        "value": d.value,
                        "evidence": None if d.evidence is None else list(d.evidence),
                        "outcome": d.outcome,
                        "codes": list(d.codes),
                        "unit": next((x.passed for x in d.parts if x.role == "unit"), None),
                    }
                )
            found[doc] = {"reply": reply is not None, "decisions": rows}
        _dump(_name(run, spec), found)
    print(f"wrote decisions for {', '.join(RUNS)} under spec {spec}")


def _decisions() -> dict[tuple[str, str], dict[str, Any]]:
    return {(run, spec): _read(_name(run, spec)) for run in RUNS for spec in SPECS}


def item_id(doc: str, field: str, key: str | None, value: str) -> str:
    """A label id that names the fact, not the run or the spec."""
    raw = json.dumps(["afr", doc, field, key, value])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def facts() -> dict[str, dict[str, Any]]:
    """Each value to label, once per fact: every value that a decision admits, and every value
    whose outcome under the 0.7 draft differs from its outcome under spec 0.6."""
    out: dict[str, dict[str, Any]] = {}
    found = _decisions()
    for (run, _), docs in found.items():
        base = found[run, SPECS[0]]
        for doc, got in docs.items():
            before = {r["id"]: r["outcome"] for r in base[doc]["decisions"]}
            for r in got["decisions"]:
                if r["outcome"] != "admitted" and r["outcome"] == before[r["id"]]:
                    continue
                if r["value"] is None:  # rejected before the value was read
                    continue
                fid = item_id(doc, r["field"], r["key"], r["value"])
                if fid not in out or (out[fid]["evidence"] is None and r["evidence"] is not None):
                    out[fid] = {k: r[k] for k in ("field", "key", "value", "evidence")}
                    out[fid]["doc"] = doc
    return out


def labels() -> dict[str, Any]:
    path = HERE / "labels.json"
    return _read(path) if path.exists() else {}


# ------------------------------------------------------------------------------------- labels


def _pdf(src: dict[str, Any]) -> Path:
    """The pinned PDF of a source, from .cache (afr.py pick puts it there)."""
    path = HERE / ".cache" / f"{src['id']}.pdf"
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != src["sha256"]:
        raise SystemExit(f"{src['id']}: {path} is not the pinned PDF; run afr.py pick")
    return path


def cards() -> list[dict[str, Any]]:
    """One card per fact, in id order: the field's description, the year, the value, the text
    around the evidence and its box on the PDF page. A fact with no evidence has no box."""
    from groundgate.extract import extract

    srcs = {s["id"]: s for s in _read(HERE / "sources.json")["sources"]}
    described = _read(HERE / "descriptions.json")
    got: dict[str, Any] = {}
    out = []
    for fid, f in sorted(facts().items()):
        doc = f["doc"]
        if doc not in got:
            got[doc] = extract(_pdf(srcs[doc]), pages=srcs[doc]["select"]["pages"])
            if got[doc].text != (HERE / "docs" / f"{doc}.txt").read_text(encoding="utf-8"):
                raise SystemExit(f"{doc}: docs/{doc}.txt is not the text of the pinned PDF")
        text, layout = got[doc].text, got[doc].layout
        card: dict[str, Any] = {
            "id": fid,
            "doc": doc,
            "field": f["field"],
            "description": described[f["field"]],
            "key": f["key"],
            "value": f["value"],
            "page": srcs[doc]["select"]["pages"][0],
            "box": None,
            "before": "",
            "mark": "",
            "after": text[:AFTER],
        }
        if f["evidence"] is not None:
            ba, bb = f["evidence"]
            raw = text.encode("utf-8")
            a, b = len(raw[:ba].decode()), len(raw[:bb].decode())
            boxes = [w.box for w in layout.words if w.start < bb and w.end > ba]
            if boxes:
                on_page = [x for x in boxes if x.page == boxes[0].page]
                card["page"] = boxes[0].page
                card["box"] = [
                    min(x.x0 for x in on_page),
                    min(x.top for x in on_page),
                    max(x.x1 for x in on_page),
                    max(x.bottom for x in on_page),
                ]
            card["before"] = text[max(0, a - BEFORE) : a]
            card["mark"] = text[a:b]
            card["after"] = text[b : b + AFTER]
        out.append(card)
    return out


def serve(port: int) -> None:
    items = cards()
    ids = {it["id"] for it in items}
    srcs = {s["id"]: s for s in _read(HERE / "sources.json")["sources"]}
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
                    body = {"items": items, "labels": labels()}
                self.send(200, json.dumps(body).encode(), "application/json")
            elif self.path.startswith("/pdf/") and self.path[5:] in srcs:
                self.send(200, _pdf(srcs[self.path[5:]]).read_bytes(), "application/pdf")
            else:
                self.send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            # a JSON body needs a preflight that this server never answers, so another site in
            # the browser cannot write a label
            if self.path != "/label" or self.headers.get("Content-Type") != "application/json":
                self.send(404, b"not found", "text/plain")
                return
            got = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if got.get("id") not in ids or got.get("verdict") not in VERDICTS:
                self.send(400, b"bad label", "text/plain")
                return
            with lock:  # requests run in threads; one read-modify-write at a time
                given = labels()
                given[got["id"]] = {"verdict": got["verdict"]}
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(dict(sorted(given.items())), indent=1) + "\n")
                tmp.replace(path)  # a reader never sees half a file
            self.send(200, b"{}", "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"{len(items)} items; open http://127.0.0.1:{port} (Ctrl-C to stop)")
    server.serve_forever()


# ------------------------------------------------------------------------------------ results


def score() -> dict[str, Any]:
    """For each run and spec: the right values admitted, the escapes (wrong values admitted),
    the admitted values labeled not sure or not yet labeled, the proposals and the documents with
    no reply. For each run, the proposals whose outcome the 0.7 draft changes, by label, and
    the unit parts that it changes: the #164 rule reads only the unit item."""
    given = labels()
    verdict = {"right": "right", "wrong": "escapes", "not sure": "not sure"}
    res: dict[str, Any] = {"runs": {}, "changed": {}, "unit parts": {}}
    found = _decisions()
    for (run, spec), docs in found.items():
        seen: set[str] = set()
        count = {"right": 0, "escapes": 0, "not sure": 0, "unlabeled": 0}
        for doc, got in docs.items():
            for r in got["decisions"]:
                if r["value"] is None or r["outcome"] != "admitted":
                    continue
                fid = item_id(doc, r["field"], r["key"], r["value"])
                if fid in seen:
                    continue
                seen.add(fid)
                v = given.get(fid, {}).get("verdict")
                count[verdict[v] if v else "unlabeled"] += 1
        count["proposals"] = sum(len(got["decisions"]) for got in docs.values())
        count["no reply"] = sum(not got["reply"] for got in docs.values())
        res["runs"].setdefault(run, {})[spec] = count
    for run in RUNS:
        old, new = found[run, SPECS[0]], found[run, SPECS[1]]
        moved: dict[str, dict[str, int]] = {}
        for doc, got in new.items():
            before = {r["id"]: r["outcome"] for r in old[doc]["decisions"]}
            for r in got["decisions"]:
                if r["value"] is None or r["outcome"] == before[r["id"]]:
                    continue
                way = f"{before[r['id']]} to {r['outcome']}"
                v = given.get(item_id(doc, r["field"], r["key"], r["value"]), {}).get("verdict")
                row = moved.setdefault(way, {"right": 0, "wrong": 0, "not sure": 0, "unlabeled": 0})
                row[v or "unlabeled"] += 1
        res["changed"][run] = dict(sorted(moved.items()))
        parts = {"unit checked": 0, "passed under 0.6": 0, "passed under 0.7": 0, "changed": 0}
        for doc, got in new.items():
            before = {r["id"]: r["unit"] for r in old[doc]["decisions"]}
            for r in got["decisions"]:
                if r["unit"] is None and before[r["id"]] is None:
                    continue
                parts["unit checked"] += 1
                parts["passed under 0.6"] += before[r["id"]] is True
                parts["passed under 0.7"] += r["unit"] is True
                parts["changed"] += r["unit"] != before[r["id"]]
        res["unit parts"][run] = parts
    return res


def render(res: dict[str, Any]) -> str:
    lines = [
        "# The #164 rule on the held-out set of agency financial reports (#229)",
        "",
        "Generated by `bench/afr/measure.py results` from `results.json`. Do not edit.",
        "",
        "The principal statements of 20 FY2025 agency financial reports, which no rule came from "
        "(`bench/afr`). Each run gives the model `gg.extractor_schema(schema)` as its structured "
        "output and the guide's instructions, with the CLI's default reasoning effort "
        "(`bench/afr/run.py`). A value counts once per document, field, key and value. An escape "
        "is a wrong value that a decision admits.",
        "",
    ]
    for run, rows in res["runs"].items():
        lines += [
            f"## {run}",
            "",
            "| Decision | Right admitted | Escapes | Not sure | Not labeled | Proposals "
            "| No reply |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for spec, c in rows.items():
            lines.append(
                f"| spec {spec} | {c['right']} | {c['escapes']} | {c['not sure']} | "
                f"{c['unlabeled']} | {c['proposals']} | {c['no reply']} |"
            )
        u = res["unit parts"][run]
        lines += [
            "",
            f"Proposals whose unit item reached the unit check: {u['unit checked']}. It passed in "
            f"{u['passed under 0.6']} under spec 0.6 and in {u['passed under 0.7']} under the 0.7 "
            f"draft; it changed in {u['changed']}.",
            "",
            "Proposals whose outcome the 0.7 draft changes:",
            "",
        ]
        moved = res["changed"][run]
        if not moved:
            lines += ["None.", ""]
            continue
        lines += [
            "| From 0.6 to 0.7 | Right | Wrong | Not sure | Not labeled |",
            "|---|---:|---:|---:|---:|",
        ]
        for way, c in moved.items():
            lines.append(
                f"| {way} | {c['right']} | {c['wrong']} | {c['not sure']} | {c['unlabeled']} |"
            )
        lines.append("")
    return "\n".join(lines)


def results(check: bool) -> None:
    res = score()
    body = json.dumps(res, indent=1) + "\n"
    md = render(res) + "\n"
    if check:
        old = (HERE / "results.json").read_text(), (HERE / "RESULTS.md").read_text()
        same = old == (body, md)
        print("results are up to date" if same else "out of date: run results")
        sys.exit(0 if same else 1)
    (HERE / "results.json").write_text(body)
    (HERE / "RESULTS.md").write_text(md)
    print(md)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("decide")
    w = sub.add_parser("web")
    w.add_argument("--port", type=int, default=PORT)
    r = sub.add_parser("results")
    r.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.command == "decide":
        decide()
    elif args.command == "web":
        serve(args.port)
    else:
        results(args.check)


if __name__ == "__main__":
    main()
