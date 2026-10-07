"""Measure the spec 0.5 evidence list (#141) on two sets that its rules did not come from: the
new 10-K set (bench/sec2) and the status set (bench/status). The plan is on #141.

    uv run --isolated --no-project --no-sources --python 3.12 --with groundgate==0.4.0 \
        python bench/evidence/measure.py decide04           # spec 0.4, on the released wheel
    uv run python bench/evidence/measure.py decide          # spec 0.5, and one role removed
    uv run python bench/evidence/measure.py web             # blind labels, http://127.0.0.1:8770
    uv run python bench/evidence/measure.py results [--check]

Each run is decided in several ways: spec 0.4, spec 0.5 with every evidence item, and spec 0.5
with the items of one role removed (the ablation). A person labels every value that a decision
admits, on a page that shows the value, the field, the key and the document, but never a spec, an
outcome or a code. The status set's own labels decide its amounts first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
BENCH = HERE.parent
RUN = "Claude_Haiku_4.5_roles/4000"
SETS = {"sec2": BENCH / "sec2", "status": BENCH / "status"}
ROLES = ("sign", "scale", "unit", "field", "key")
SPECS = ("0.4", "0.5", *(f"0.5 without {r}" for r in ROLES))
VERDICTS = ("right", "wrong", "not sure")
PORT = 8770


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _packets(name: str) -> list[tuple[str, str, dict[str, Any], list[dict[str, Any]]]]:
    """(doc, text, schema, candidates) for each run file of a set, with the adapter of the
    groundgate that runs this script."""
    from groundgate.adapters.langextract import to_candidates

    set_dir = SETS[name]
    out = []
    for path in sorted((set_dir / "runs" / RUN).glob("*.json")):
        rec = _read(path)
        doc = rec["document"]["document_id"]
        gold = _read(set_dir / "gold" / f"{doc}.json")
        schema = {"fields": {f: s["schema"] for f, s in gold["fields"].items()}}
        text = (set_dir / "docs" / f"{doc}.txt").read_text(encoding="utf-8")
        rec["document"]["text"] = text
        out.append((doc, text, schema, to_candidates(rec["document"])))
    return out


def _decide(
    spec: str, text: str, schema: dict[str, Any], cands: list[Any]
) -> tuple[list[Any], list[Any]]:
    """The candidates as decided, and their decisions."""
    import groundgate as gg

    if spec == "0.4":  # spec 0.4 has no aliases (SPEC §2.3)
        fields = schema["fields"]
        schema = {
            "fields": {f: {k: v for k, v in s.items() if k != "aliases"} for f, s in fields.items()}
        }
    if spec.startswith("0.5 without "):
        role = spec.removeprefix("0.5 without ")
        cands = [
            {**c, "evidence": [i for i in c["evidence"] if i.get("role", "value") != role]}
            if isinstance(c.get("evidence"), list)
            else c
            for c in cands
        ]
    return cands, list(gg.admit(text, schema, cands).decisions)


def decide(specs: tuple[str, ...], out: Path) -> None:
    """decisions-<spec>.json: for each set and document, each candidate's outcome and codes."""
    import groundgate as gg

    found: dict[str, Any] = {spec: {} for spec in specs}
    for name in SETS:
        for spec in specs:
            found[spec][name] = {}
        for doc, text, schema, cands in _packets(name):
            for spec in specs:
                used, ds = _decide(spec, text, schema, cands)
                by_sha = {d.candidate_sha256: d for d in ds}
                rows = []
                for c in used:
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
                            "why": _why(text, d) if spec == "0.5" else [],
                        }
                    )
                found[spec][name][doc] = rows
    for spec in specs:
        _dump(out / f"decisions-{spec.replace(' ', '-')}.json", found[spec])
    print(f"wrote decisions for {', '.join(specs)}")


def _why(text: str, d: Any) -> list[str]:
    """Why the unit and scale items of a decision fail, for the report: a unit item whose number
    already has a unit form next to it, and a scale item that is not in the text as written."""
    from groundgate.text import builtin_units, form_next, tokens

    out = []
    parts = {p.role: p for p in d.parts}
    if "UNIT_CITATION_INVALID" in d.codes and d.evidence is not None:
        raw = text.encode("utf-8")
        a, b = len(raw[: d.evidence[0]].decode()), len(raw[: d.evidence[1]].decode())
        units = builtin_units().values()
        prefixes = [x for pre, _ in units for x in pre]
        suffixes = sorted({x for _, suf in units for x in suf})
        toks = [t for t in tokens(text, a, b) if t.value is not None]
        if toks and form_next(text, toks[0], prefixes, suffixes, 24):
            out.append("unit next to the number")
    if "SCALE_CITATION_INVALID" in d.codes and parts["scale"].span is None:
        out.append("scale not in the text")
    return out


def _decisions() -> dict[str, Any]:
    return {spec: _read(HERE / f"decisions-{spec.replace(' ', '-')}.json") for spec in SPECS}


def item_id(name: str, doc: str, field: str, key: str | None, value: str) -> str:
    """A label id that names the fact, not the spec or the run."""
    raw = json.dumps([name, doc, field, key, value])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _token_start(text: str, span: list[int], value: str) -> int | None:
    """The start of the first number token in a byte span whose value is the value as written."""
    from groundgate.text import tokens

    raw = text.encode("utf-8")
    a, b = len(raw[: span[0]].decode()), len(raw[: span[1]].decode())
    for t in tokens(text, a, b):
        if t.value is not None and t.value == Decimal(value):
            return t.start
    return None


def _status_labels() -> dict[tuple[str, int], list[str] | None]:
    """(doc, amount start) -> the keys that the status labels give, None for not sure."""
    labels = _read(BENCH / "status" / "labels.json")
    out = {}
    for it in _read(BENCH / "status" / "items.json"):
        if it["id"] in labels:
            out[it["doc"], it["span"][0]] = labels[it["id"]]
    return out


def facts() -> dict[str, dict[str, Any]]:
    """Every value that a decision admits, once per fact, with the verdict that the set's own
    labels give, if any."""
    status = _status_labels()
    texts: dict[str, str] = {}
    out: dict[str, dict[str, Any]] = {}
    for sets in _decisions().values():
        for name, docs in sets.items():
            for doc, rows in docs.items():
                for r in rows:
                    if r["outcome"] != "admitted":
                        continue
                    fid = item_id(name, doc, r["field"], r["key"], r["value"])
                    if fid in out:
                        continue
                    own = None
                    if name == "status" and r["evidence"] is not None:  # its text is in git
                        if doc not in texts:
                            path = SETS[name] / "docs" / f"{doc}.txt"
                            texts[doc] = path.read_text(encoding="utf-8")
                        at = _token_start(texts[doc], r["evidence"], r["value"])
                        if at is not None and (doc, at) in status:
                            keys = status[doc, at]
                            own = (
                                "not sure"
                                if keys is None
                                else ("right" if r["key"] in keys else "wrong")
                            )
                    out[fid] = {
                        "set": name,
                        "doc": doc,
                        "field": r["field"],
                        "key": r["key"],
                        "value": r["value"],
                        "evidence": r["evidence"],
                        "own": own,
                    }
    return out


def labels() -> dict[str, Any]:
    path = HERE / "labels.json"
    return _read(path) if path.exists() else {}


def verdict(fid: str, fact: dict[str, Any], given: dict[str, Any]) -> str | None:
    if fact["own"] is not None:
        return str(fact["own"])
    got = given.get(fid)
    return None if got is None else str(got["verdict"])


# ------------------------------------------------------------------------------------- labels


def cards() -> list[dict[str, Any]]:
    """One card per admitted fact that the set's own labels do not decide, in id order."""
    out = []
    descriptions: dict[tuple[str, str], str] = {}
    for fid, f in sorted(facts().items()):
        if f["own"] is not None:
            continue
        set_dir = SETS[f["set"]]
        if (f["set"], f["doc"]) not in descriptions:
            gold = _read(set_dir / "gold" / f"{f['doc']}.json")
            for field, spec in gold["fields"].items():
                descriptions[f["set"] + f["doc"], field] = spec.get("description", "")
        text = (set_dir / "docs" / f"{f['doc']}.txt").read_text(encoding="utf-8")
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
                "description": descriptions.get((f["set"] + f["doc"], f["field"]), ""),
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

NAMES = {"sec2": "New 10-K set (bench/sec2)", "status": "Status set (bench/status)"}


def score() -> dict[str, Any]:
    """For each set and decision: the right values admitted, the escapes (wrong values admitted),
    the admitted values labeled not sure or not yet labeled, and the values that a missing part
    sent to review."""
    fs, given = facts(), labels()
    res: dict[str, Any] = {"run": RUN, "sets": {}}
    for name in SETS:
        rows: dict[str, Any] = {}
        for spec, sets in _decisions().items():
            seen: set[str] = set()
            count = {"right": 0, "escapes": 0, "not sure": 0, "unlabeled": 0, "part missing": 0}
            fails: dict[str, int] = {}
            missing: set[str] = set()
            for doc, ds in sets[name].items():
                for r in ds:
                    if r["outcome"] != "rejected":
                        for code in r["codes"]:
                            if code.endswith("_CITATION_INVALID"):
                                fails[code] = fails.get(code, 0) + 1
                        for why in r.get("why", []):
                            fails[why] = fails.get(why, 0) + 1
                    fid = item_id(name, doc, r["field"], r["key"], r["value"])
                    if r["outcome"] == "needs_verification" and "PART_MISSING" in r["codes"]:
                        missing.add(fid)  # one fact, many proposals
                    if r["outcome"] != "admitted":
                        continue
                    if fid in seen:  # one fact, many proposals
                        continue
                    seen.add(fid)
                    v = verdict(fid, fs[fid], given)
                    key = {"right": "right", "wrong": "escapes", "not sure": "not sure"}
                    count[key[v] if v else "unlabeled"] += 1
            count["part missing"] = len(missing)
            rows[spec] = count
            if spec == "0.5":
                res.setdefault("role failures", {})[name] = dict(sorted(fails.items()))
        res["sets"][name] = rows
    return res


def render(res: dict[str, Any]) -> str:
    lines = [
        "# The spec 0.5 evidence list, measured (#141)",
        "",
        "Generated by `bench/evidence/measure.py results` from `results.json`. Do not edit.",
        "",
        f"Run: `{res['run']}`, the `--roles` prompt of `bench/propose.py`. A value counts once per "
        "document, field, key and value. An escape is a wrong value that a decision admits. Part "
        "missing counts the values that a missing part sent to review.",
        "",
    ]
    for name, rows in res["sets"].items():
        lines += [
            f"## {NAMES[name]}",
            "",
            "| Decision | Right admitted | Escapes | Not sure | Not labeled | Part missing |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for spec, c in rows.items():
            lines.append(
                f"| spec {spec} | {c['right']} | {c['escapes']} | {c['not sure']} | "
                f"{c['unlabeled']} | {c['part missing']} |"
            )
        lines.append("")
    lines += [
        "## Failed role items under spec 0.5",
        "",
        "Proposals, not facts: a fact can have several. A unit item fails when a unit form is "
        "already next to the number, and a scale item fails when its quote is not in the text "
        "as written.",
        "",
        "| Set | Failure | Proposals |",
        "|---|---|---:|",
    ]
    for name, fails in res.get("role failures", {}).items():
        for what, n in fails.items():
            lines.append(f"| {NAMES[name]} | {what} | {n} |")
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
    sub.add_parser("decide04")
    sub.add_parser("decide")
    w = sub.add_parser("web")
    w.add_argument("--port", type=int, default=PORT)
    r = sub.add_parser("results")
    r.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.command == "decide04":
        decide(("0.4",), HERE)
    elif args.command == "decide":
        decide(SPECS[1:], HERE)
    elif args.command == "web":
        serve(args.port)
    else:
        results(args.check)


if __name__ == "__main__":
    main()
