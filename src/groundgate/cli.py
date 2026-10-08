"""groundgate command line.

  groundgate extract  FILE                              > doc.txt
  groundgate admit    DOC SCHEMA CANDIDATES             > receipt.json
  groundgate verify   RECEIPT DOC SCHEMA CANDIDATES
  groundgate report   RECEIPT DOC SCHEMA CANDIDATES -o report.html
  groundgate schema   SCHEMA                            > extractor.schema.json
  groundgate schema check SCHEMA

DOC may be "-" to read the document from standard input. Exit codes: 0 success, 1 the receipt
does not match its inputs (or schema check has a finding), 2 invalid input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .admit import admit, verify
from .model import PacketError, Schema, extractor_schema
from .text import key_mentions, normalize_ws


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for k, v in pairs:
        if k in obj:
            raise ValueError(f"duplicate JSON key {k!r}")  # parsers disagree on which one wins
        obj[k] = v
    return obj


def _constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


def _json(path: str) -> Any:
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text, object_pairs_hook=_unique, parse_constant=_constant)


def _text(path: str) -> str:
    data = sys.stdin.buffer.read() if path == "-" else Path(path).read_bytes()
    return data.decode("utf-8")


def _write(text: str, output: str | None) -> None:
    data = text.encode("utf-8")
    if output:
        Path(output).write_bytes(data)
    else:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()


MAX_PAGE = 100_000


def _dumps(obj: Any) -> str:
    out = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    try:
        out.encode("utf-8")
    except UnicodeEncodeError:  # a lone surrogate from a candidate: escape rather than fail
        out = json.dumps(obj, indent=2) + "\n"
    return out


def _pages(spec: str) -> list[int]:
    """'1-3,7' -> [1, 2, 3, 7]"""
    out: list[int] = []
    for part in spec.split(","):
        lo, dash, hi = part.strip().partition("-")
        try:
            a, b = int(lo), int(hi if dash else lo)
        except ValueError:
            raise argparse.ArgumentTypeError(f"bad page range {part!r}") from None
        if a < 1 or b < a or b > MAX_PAGE:
            raise argparse.ArgumentTypeError(f"bad page range {part!r}")
        out.extend(range(a, b + 1))
    return out


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="groundgate", description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = ap.add_subparsers(dest="command", required=True)

    x = sub.add_parser("extract", help="turn a PDF, HTML, XML or text file into NFC text")
    x.add_argument("file")
    x.add_argument("-o", "--output", help="write the text here instead of stdout")
    x.add_argument("--layout", help="also write page and word boxes (PDF only) as JSON")
    x.add_argument("--pages", type=_pages, help="PDF pages to extract, e.g. 1-12,15")

    s = sub.add_parser(
        "schema",
        help="write the JSON Schema for an extractor's output (or: schema check SCHEMA)",
    )
    s.add_argument("schema", help="schema JSON")
    s.add_argument("--references", help="JSON array of references; their ids become refs")
    s.add_argument("-o", "--output", help="write the JSON Schema here instead of stdout")

    def inputs(p: argparse.ArgumentParser) -> None:
        p.add_argument("document", help='UTF-8 NFC text file, or "-" for stdin')
        p.add_argument("schema", help="schema JSON")
        p.add_argument("candidates", help="JSON array of candidates")
        p.add_argument("--policy", help="policy JSON")
        p.add_argument("--judgments", help="JSON array of recorded judgments (SPEC §2.6)")
        p.add_argument("--references", help="JSON array of references (SPEC §2.1)")
        p.add_argument("--document-source", help="the URL of the document (SPEC §2.1)")

    a = sub.add_parser("admit", help="decide candidates and write a receipt")
    inputs(a)
    a.add_argument("--document-id")
    a.add_argument("-o", "--output", help="write the receipt here instead of stdout")

    v = sub.add_parser("verify", help="re-derive a receipt from its inputs and compare")
    v.add_argument("receipt")
    inputs(v)

    r = sub.add_parser("report", help="verify a receipt, then render an HTML review page")
    r.add_argument("receipt")
    inputs(r)
    r.add_argument("--layout", help="layout JSON from extract, to show page numbers")
    r.add_argument("--title")
    r.add_argument("-o", "--output", help="write the HTML here instead of stdout")
    return ap


def _check_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="groundgate schema check",
        description="Print the schema settings that docs/schema.md lists under 'Check a schema'. "
        "Exit codes: 0 no finding, 1 a finding, 2 invalid schema.",
    )
    ap.add_argument("schema", help="schema JSON")
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    check = argv[:2] == ["schema", "check"]
    args = _check_parser().parse_args(argv[2:]) if check else _parser().parse_args(argv)
    try:
        if check:
            return _check(args)
        if args.command == "extract":
            return _extract(args)
        if args.command == "schema":
            return _schema(args)
        policy = _json(args.policy) if args.policy else None
        text = _text(args.document)
        schema, candidates = _json(args.schema), _json(args.candidates)
        judgments = _json(args.judgments) if args.judgments else None
        extra = {
            "references": _json(args.references) if args.references else None,
            "document_source": args.document_source,
        }
        if args.command == "admit":
            receipt = admit(text, schema, candidates, policy, args.document_id, judgments, **extra)
            _write(_dumps(receipt.to_dict()), args.output)
            return 0
        stored = _json(args.receipt)
        result = verify(stored, text, schema, candidates, policy, judgments, **extra)
        for problem in result.problems:
            print(f"mismatch: {problem}", file=sys.stderr)
        if args.command == "verify":
            if result.ok:
                print("receipt verified")
            return 0 if result.ok else 1
        if not result.ok:
            print("groundgate: not rendering a receipt that does not match", file=sys.stderr)
            return 1
        return _report(args, stored, text, candidates, extra)
    except (PacketError, ValueError, OSError, ImportError) as e:  # JSON, UTF-8: ValueError
        print(f"groundgate: {e}", file=sys.stderr)
        return 2


def _schema(args: argparse.Namespace) -> int:
    ids = None
    if args.references:
        refs = _json(args.references)
        if not isinstance(refs, list) or not all(isinstance(r, dict) for r in refs):
            raise PacketError("references must be a list of objects")
        ids = [r.get("id") for r in refs]
    _write(_dumps(extractor_schema(_json(args.schema), ids)), args.output)
    return 0


def _findings(schema: Schema) -> list[str]:
    """The settings of a valid schema that make a check fail every time, or pass for the wrong
    key or field. Step 1 already refuses blank and repeated keys and aliases of one field."""
    out: list[str] = []
    owners: dict[str, tuple[str, list[str]]] = {}  # normalized alias: (as written, fields)
    for name, f in schema.fields.items():
        if f.aliases is None:
            if f.unit is not None:
                out.append(f"field {name!r} has a unit and no aliases: a unit item never passes")
            if f.keys is not None:
                out.append(
                    f"field {name!r} has keys and no aliases: "
                    "a key item never puts the key at the value"
                )
        else:
            inside = (k for a in f.aliases for _, _, k in key_mentions(a, f.keys or ()))
            for key in dict.fromkeys(inside):
                out.append(
                    f"field {name!r} has the key {key!r} in an alias: "
                    "each mention of the field puts that key at the value"
                )
            for alias in f.aliases:
                owners.setdefault(_norm(alias), (alias, []))[1].append(name)
        low, high = f.minimum, f.maximum
        if f.type != "string" and low is not None and high is not None and low > high:
            out.append(f"field {name!r} has a minimum above its maximum: no value is in range")
    for alias, names in owners.values():
        if len(names) > 1:
            listed = ", ".join(map(repr, names[:-1])) + f" and {names[-1]!r}"
            out.append(
                f"alias {alias!r} is on fields {listed}: a field item does not tell them apart"
            )
    for name, f in schema.fields.items():  # an alias in a longer alias of another field
        for other, g in schema.fields.items():
            if other == name or f.aliases is None or g.aliases is None:
                continue
            for b in g.aliases:
                for a in dict.fromkeys(a for _, _, a in key_mentions(b, f.aliases)):
                    if _norm(a) != _norm(b):
                        out.append(
                            f"alias {a!r} of field {name!r} is in alias {b!r} of field "
                            f"{other!r}: a field item for {other!r} passes for {name!r}"
                        )
    return out


def _norm(word: str) -> str:
    return normalize_ws(word).lower()


def _check(args: argparse.Namespace) -> int:
    found = _findings(Schema.from_dict(_json(args.schema)))
    for line in found:
        print(line)
    return 1 if found else 0


def _extract(args: argparse.Namespace) -> int:
    from .extract import extract

    doc = extract(args.file, pages=args.pages)
    for w in doc.warnings:
        print(f"groundgate: warning: {w}", file=sys.stderr)
    if args.layout:
        if doc.layout is None:
            print("groundgate: --layout needs a PDF", file=sys.stderr)
            return 2
        Path(args.layout).write_text(json.dumps(doc.layout.to_dict()) + "\n", encoding="utf-8")
    _write(doc.text, args.output)
    return 0


def _report(
    args: argparse.Namespace, receipt: Any, text: str, candidates: Any, extra: dict[str, Any]
) -> int:
    from .canonical import digest
    from .extract import Layout
    from .report import render

    layout = None
    if args.layout:
        layout = Layout.from_dict(_json(args.layout))
        if layout.document_sha256 != digest("document", {"text": text}):
            raise PacketError("the layout was extracted from a different document")
    doc_id = receipt.get("document", {}).get("id") if isinstance(receipt, dict) else None
    title = args.title or doc_id or (Path(args.document).name if args.document != "-" else None)
    schema, policy = _json(args.schema), _json(args.policy) if args.policy else None
    judgments = _json(args.judgments) if args.judgments else None
    page = render(
        receipt,
        text,
        candidates,
        schema=schema,
        policy=policy,
        layout=layout,
        title=title,
        judgments=judgments,
        **extra,
    )
    _write(page, args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
