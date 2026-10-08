"""Measure spec 0.6 on the held-out 10-K set (#170): the two runs of run.py, decided under spec 0.5
and, as each 0.6 rule lands, under that rule alone. The plan is on #170 and #172.

    uv run --isolated --no-project --no-sources --python 3.12 --with groundgate==0.5.1 \
        python bench/sec3/measure.py decide             # spec 0.5, on the released wheel
    uv run python bench/sec3/measure.py decide          # each 0.6 rule
    uv run python bench/sec3/measure.py web             # blind labels, http://127.0.0.1:8774
    uv run python bench/sec3/measure.py results [--check]

A person labels every value that a decision admits, and every value whose outcome differs
between spec 0.5 and a 0.6 rule, on a page that shows the value, the field, the key and the
document, but never a run, a spec, an outcome or a code. The page is that of bench/evidence.
The decisions hold values and byte spans, not text, so they are in git. The documents are not.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
RUNS = ("claude-haiku-5-5", "gpt-6-luna")
# each 0.6 rule adds its spec here, decided alone
SPECS = ("0.5", "0.6 #145 unit", "0.6 #145 scale", "0.6 #159")
# decided once and kept: the scale part of #145 (a scale quote in any case) did not ship
RECORDED = ("0.6 #145 scale",)
# the function that turns each 0.6 rule off when it returns False
OFF = {
    "0.6 #145 unit": ("groundgate.admit", "_repeats"),
    "0.6 #159": ("groundgate.text", "_between_words_before"),
}
VERDICTS = ("right", "wrong", "not sure")
PORT = 8774


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _name(run: str, spec: str) -> Path:
    return HERE / f"decisions-{run}-{spec.replace(' ', '-').replace('#', '')}.json"


def _schema() -> dict[str, Any]:
    return dict(_read(HERE / "schema.json"))


def _decide(spec: str, text: str, cands: list[Any]) -> list[Any]:
    """The decisions under one spec, by the groundgate that runs this script. A 0.6 rule is
    decided alone: the other rules of the draft are turned off (OFF)."""
    from unittest import mock

    import groundgate as gg

    if spec not in SPECS or spec in RECORDED:
        raise SystemExit(f"no decision for spec {spec!r}")
    with contextlib.ExitStack() as stack:
        for other, (module, name) in OFF.items():
            if other != spec:
                off = mock.patch.object(sys.modules[module], name, lambda *a: False)
                stack.enter_context(off)
        return list(gg.admit(text, _schema(), cands).decisions)


def decide() -> None:
    """decisions-<run>-<spec>.json for each spec that the groundgate that runs this script
    implements: for each document, each candidate's outcome and codes. A document with no reply
    is listed with no candidates and counted in the results."""
    import groundgate as gg
    from groundgate.canonical import SPEC_VERSION

    specs = [spec for spec in SPECS if spec.split()[0] == SPEC_VERSION and spec not in RECORDED]
    if not specs:
        raise SystemExit(f"no spec here needs groundgate {SPEC_VERSION}: use the spec's wheel")
    for run in RUNS:
        found: dict[str, dict[str, Any]] = {spec: {} for spec in specs}
        for doc_path in sorted((HERE / "docs").glob("*.txt")):
            doc = doc_path.stem
            rec = _read(HERE / "runs" / run / f"{doc}.json")
            text = doc_path.read_text(encoding="utf-8")
            reply = rec["reply"]
            cands = [] if reply is None else reply["candidates"]
            cands = [{"id": f"c{i}", **c} for i, c in enumerate(cands)]
            for spec in specs:
                by_sha = {d.candidate_sha256: d for d in _decide(spec, text, cands)}
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
                        }
                    )
                found[spec][doc] = {"reply": reply is not None, "decisions": rows}
        for spec in specs:
            _dump(_name(run, spec), found[spec])
    print(f"wrote decisions for {', '.join(RUNS)} under {', '.join(specs)}")


def _decisions() -> dict[tuple[str, str], dict[str, Any]]:
    return {(run, spec): _read(_name(run, spec)) for run in RUNS for spec in SPECS}


def item_id(doc: str, field: str, key: str | None, value: str) -> str:
    """A label id that names the fact, not the run or the spec."""
    raw = json.dumps(["sec3", doc, field, key, value])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def facts() -> dict[str, dict[str, Any]]:
    """Each value to label, once per fact: every value that a decision admits, and every value
    whose outcome under a 0.6 rule differs from its outcome under spec 0.5."""
    out: dict[str, dict[str, Any]] = {}
    found = _decisions()
    for (run, _), docs in found.items():
        base = found[run, "0.5"]
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


def cards() -> list[dict[str, Any]]:
    """One card per fact, in id order, with the field's description from the gold file."""
    out = []
    for fid, f in sorted(facts().items()):
        gold = _read(HERE / "gold" / f"{f['doc']}.json")
        text = (HERE / "docs" / f"{f['doc']}.txt").read_text(encoding="utf-8")
        a = b = None
        if f["evidence"] is not None:
            raw = text.encode("utf-8")
            a = len(raw[: f["evidence"][0]].decode())
            b = len(raw[: f["evidence"][1]].decode())
        out.append(
            {
                "id": fid,
                "doc": f["doc"],
                "field": f["field"],
                "description": gold["fields"][f["field"]].get("description", ""),
                "key": f["key"],
                "value": f["value"],
                "text": text,
                "start": a,
                "end": b,
            }
        )
    return out


def serve(port: int) -> None:
    items = cards()
    ids = {it["id"] for it in items}
    path = HERE / "labels.json"
    page = (HERE.parent / "evidence" / "web.html").read_bytes()
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
    the admitted values labeled not sure or not yet labeled, the values that a missing part sent
    to review, the proposals and the documents with no reply."""
    given = labels()
    res: dict[str, Any] = {"runs": {}}
    for (run, spec), docs in _decisions().items():
        seen: set[str] = set()
        missing: set[str] = set()
        count = {"right": 0, "escapes": 0, "not sure": 0, "unlabeled": 0, "part missing": 0}
        proposals = sum(len(got["decisions"]) for got in docs.values())
        for doc, got in docs.items():
            for r in got["decisions"]:
                if r["value"] is None:
                    continue
                fid = item_id(doc, r["field"], r["key"], r["value"])
                if r["outcome"] == "needs_verification" and "PART_MISSING" in r["codes"]:
                    missing.add(fid)  # one fact, many proposals
                if r["outcome"] != "admitted" or fid in seen:
                    continue
                seen.add(fid)
                v = given.get(fid, {}).get("verdict")
                key = {"right": "right", "wrong": "escapes", "not sure": "not sure"}
                count[key[v] if v else "unlabeled"] += 1
        count["part missing"] = len(missing)
        count["proposals"] = proposals
        count["no reply"] = sum(not got["reply"] for got in docs.values())
        res["runs"].setdefault(run, {})[spec] = count
    return res


def render(res: dict[str, Any]) -> str:
    lines = [
        "# Spec 0.6 on the held-out 10-K set (#170)",
        "",
        "Generated by `bench/sec3/measure.py results` from `results.json`. Do not edit.",
        "",
        "20 filings that no rule came from (`bench/sec3`). Each run gives the model "
        "`gg.extractor_schema(schema)` as its structured output and the guide's instructions, "
        "with the CLI's default reasoning effort (`bench/sec3/run.py`). A value counts once per "
        "document, field, key and value. An escape is a wrong value that a decision admits. Part "
        "missing counts the values that a missing part sent to review.",
        "",
    ]
    for run, rows in res["runs"].items():
        lines += [
            f"## {run}",
            "",
            "| Decision | Right admitted | Escapes | Not sure | Not labeled | Part missing "
            "| Proposals | No reply |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for spec, c in rows.items():
            lines.append(
                f"| spec {spec} | {c['right']} | {c['escapes']} | {c['not sure']} | "
                f"{c['unlabeled']} | {c['part missing']} | {c['proposals']} | {c['no reply']} |"
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
