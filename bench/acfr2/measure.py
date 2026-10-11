"""Measure the rules of #249 on the held-out set bench/acfr2: the two runs of run.py, decided
under the 0.8 draft with the rules of #249 turned off and turned on. A rule ships only if this
measure says so. The plan is on #249, made before anyone read the set.

    uv run python bench/acfr2/measure.py decide          # each spec of SPECS, in process
    uv run python bench/acfr2/measure.py web             # blind labels, http://127.0.0.1:8780
    uv run python bench/acfr2/measure.py results [--check]

A person labels every value that a decision admits, and every value whose outcome differs
between the specs. The page shows the PDF page with the value boxed, the text around it, the
field and the value, but never a run, a spec, an outcome or a code.

Each spec turns off the rules of the other specs (OFF), as bench/sec3/measure.py does. "0.8" is
the draft with every rule here turned off. A later rule adds its spec and its functions to OFF.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
RUNS = ("claude-haiku-5-5", "gpt-6-luna")
SPECS = ("0.8", "0.8 #249")
# the functions that turn each rule off when they return False
OFF = {
    "0.8 #249": (("groundgate.admit", "_field_passes"), ("groundgate.admit", "_unit_at_place")),
}
VERDICTS = ("right", "wrong", "not sure")
BEFORE, AFTER = 500, 200  # code points of text around the value
PORT = 8780


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _name(run: str, spec: str) -> Path:
    return HERE / f"decisions-{run}-{spec.replace(' ', '-').replace('#', '')}.json"


def decide() -> None:
    """decisions-<run>-<spec>.json for each spec: for each document, each candidate's outcome and
    codes. A document with no reply is listed with no candidates and counted in the results."""
    import contextlib
    from unittest import mock

    import groundgate as gg
    from groundgate.canonical import SPEC_VERSION

    if SPEC_VERSION != "0.8":
        raise SystemExit(f"this measure decides with the 0.8 draft, not {SPEC_VERSION}")
    schema = _read(HERE / "schema.json")
    for spec in SPECS:
        for run in RUNS:
            found: dict[str, Any] = {}
            for doc_path in sorted((HERE / "docs").glob("*.txt")):
                doc = doc_path.stem
                reply = _read(HERE / "runs" / run / f"{doc}.json")["reply"]
                cands = [] if reply is None else reply["candidates"]
                cands = [{"id": f"c{i}", **c} for i, c in enumerate(cands)]
                text = doc_path.read_text(encoding="utf-8")
                with contextlib.ExitStack() as stack:
                    for other, names in OFF.items():
                        for module, name in names if other != spec else ():
                            off = mock.patch.object(sys.modules[module], name, lambda *a: False)
                            stack.enter_context(off)
                    got = gg.admit(text, schema, cands).decisions
                by_sha = {d.candidate_sha256: d for d in got}
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
                            "missing": list(d.missing),
                        }
                    )
                found[doc] = {"reply": reply is not None, "decisions": rows}
            _dump(_name(run, spec), found)
    print(f"wrote decisions for {', '.join(RUNS)} under {', '.join(SPECS)}")


def _decisions() -> dict[tuple[str, str], dict[str, Any]]:
    return {(run, spec): _read(_name(run, spec)) for run in RUNS for spec in SPECS}


def item_id(doc: str, field: str, key: str | None, value: str) -> str:
    """A label id that names the fact, not the run or the spec."""
    raw = json.dumps(["acfr2", doc, field, key, value])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def facts() -> dict[str, dict[str, Any]]:
    """Each value to label, once per fact: every value that a decision admits, and every value
    whose outcome under a rule differs from its outcome under the draft with every rule off."""
    out: dict[str, dict[str, Any]] = {}
    found = _decisions()
    for (run, _), docs in found.items():
        other = found[run, SPECS[0]]
        for doc, got in docs.items():
            before = {r["id"]: r["outcome"] for r in other[doc]["decisions"]}
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
    """The pinned PDF of a source, from .cache (acfr2.py pick puts it there)."""
    path = HERE / ".cache" / f"{src['id']}.pdf"
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != src["sha256"]:
        raise SystemExit(f"{src['id']}: {path} is not the pinned PDF; run acfr2.py pick")
    return path


def cards() -> list[dict[str, Any]]:
    """One card per fact, in id order: the field's description, the value, the text around the
    evidence and its box on the PDF page. A fact with no evidence has no box."""
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
    no reply. For each run and rule, the proposals whose outcome the rule changes, by label. For
    each run and spec, the codes and the missing parts of the proposals that are not admitted."""
    given = labels()
    verdict = {"right": "right", "wrong": "escapes", "not sure": "not sure"}
    res: dict[str, Any] = {"runs": {}, "changed": {}, "codes": {}}
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
        base = found[run, SPECS[0]]
        for spec in SPECS[1:]:
            moved: dict[str, dict[str, int]] = {}
            for doc, got in found[run, spec].items():
                before = {r["id"]: r["outcome"] for r in base[doc]["decisions"]}
                for r in got["decisions"]:
                    if r["value"] is None or r["outcome"] == before[r["id"]]:
                        continue
                    way = f"{before[r['id']]} to {r['outcome']}"
                    fid = item_id(doc, r["field"], r["key"], r["value"])
                    v = given.get(fid, {}).get("verdict")
                    row = moved.setdefault(
                        way, {"right": 0, "wrong": 0, "not sure": 0, "unlabeled": 0}
                    )
                    row[v or "unlabeled"] += 1
            res["changed"].setdefault(run, {})[spec] = dict(sorted(moved.items()))
        codes = {
            spec: collections.Counter(
                tag
                for got in found[run, spec].values()
                for r in got["decisions"]
                if r["outcome"] != "admitted"
                for tag in [*r["codes"], *(f"missing {m}" for m in r["missing"])]
            )
            for spec in SPECS
        }
        names = sorted({c for got in codes.values() for c in got})
        res["codes"][run] = {c: {spec: codes[spec][c] for spec in SPECS} for c in names}
    return res


def render(res: dict[str, Any]) -> str:
    lines = [
        "# The rules of #249 on the held-out set bench/acfr2",
        "",
        "Generated by `bench/acfr2/measure.py results` from `results.json`. Do not edit.",
        "",
        "The statement of net position and the statement of activities of 10 more FY2025 state "
        "annual comprehensive financial reports, which no rule came from (`bench/acfr2`), as the "
        "text of #230. Each run gives the model `gg.extractor_schema(schema)` as its structured "
        "output and the guide's instructions, with the CLI's default reasoning effort "
        "(`bench/acfr2/run.py`). Spec 0.8 is the draft with every rule here turned off; each "
        "rule is decided alone. A value counts once per document, field, key and value. An "
        "escape is a wrong value that a decision admits.",
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
        lines += [
            "",
            "Codes and missing parts on the proposals that are not admitted (a proposal can have "
            "more than one):",
            "",
            "| Code | " + " | ".join(f"spec {s}" for s in SPECS) + " |",
            "|---|" + "---:|" * len(SPECS),
        ]
        for code, by in res["codes"][run].items():
            lines.append(f"| `{code}` | " + " | ".join(str(by[s]) for s in SPECS) + " |")
        for spec, moved in res["changed"][run].items():
            lines += ["", f"Proposals whose outcome {spec.split()[-1]} changes:", ""]
            if not moved:
                lines += ["None."]
                continue
            lines += [
                "| From 0.8 to " + spec + " | Right | Wrong | Not sure | Not labeled |",
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
