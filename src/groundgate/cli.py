"""groundgate command line.

  groundgate extract  FILE                              > doc.txt
  groundgate admit    DOC SCHEMA CANDIDATES             > receipt.json
  groundgate admit    --docs D --candidates C --schema S --out R
  groundgate verify   RECEIPT DOC SCHEMA CANDIDATES
  groundgate report   RECEIPT DOC SCHEMA CANDIDATES -o report.html
  groundgate schema   SCHEMA                            > extractor.schema.json

DOC may be "-" to read the document from standard input. Exit codes: 0 success, 1 the receipt
does not match its inputs, 2 invalid input.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from .admit import admit, verify
from .model import PacketError, extractor_schema


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

    s = sub.add_parser("schema", help="write the JSON Schema for an extractor's output")
    s.add_argument("schema", help="schema JSON")
    s.add_argument("--references", help="JSON array of references; their ids become refs")
    s.add_argument("-o", "--output", help="write the JSON Schema here instead of stdout")

    def inputs(p: argparse.ArgumentParser, *, batch: bool = False) -> None:
        nargs = "?" if batch else None
        p.add_argument("document", nargs=nargs, help='UTF-8 NFC text file, or "-" for stdin')
        p.add_argument("schema", nargs=nargs, help="schema JSON")
        p.add_argument("candidates", nargs=nargs, help="JSON array of candidates")
        p.add_argument("--policy", help="policy JSON")
        p.add_argument(
            "--judgments",
            help="JSON array of recorded judgments (SPEC §2.6)"
            + ("; a folder in batch mode" if batch else ""),
        )
        p.add_argument("--references", help="JSON array of references (SPEC §2.1)")
        p.add_argument("--document-source", help="the URL of the document (SPEC §2.1)")

    a = sub.add_parser("admit", help="decide candidates and write a receipt")
    inputs(a, batch=True)
    a.add_argument("--document-id")
    a.add_argument("-o", "--output", help="write the receipt here instead of stdout")
    a.add_argument("--docs", help="folder of <doc>.txt files")
    a.add_argument("--schema", dest="batch_schema", help="schema JSON for batch mode")
    a.add_argument("--candidates", dest="batch_candidates", help="folder of <doc>.json files")
    a.add_argument("--out", help="folder for batch receipts and summary.json")

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


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "admit":
        _admit_inputs(parser, args)
    try:
        if args.command == "extract":
            return _extract(args)
        if args.command == "schema":
            return _schema(args)
        if args.command == "admit" and args.docs is not None:
            return _batch_admit(args)
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


def _admit_inputs(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    batch = (args.docs, args.batch_candidates, args.batch_schema, args.out)
    single = (args.document, args.schema, args.candidates)
    if any(value is not None for value in batch):
        if not all(batch):
            parser.error("batch admit requires --docs, --candidates, --schema and --out")
        if any(value is not None for value in (*single, args.output, args.document_id)):
            parser.error("batch admit cannot use positional inputs, --output or --document-id")
    elif not all(value is not None for value in single):
        parser.error("admit requires DOC SCHEMA CANDIDATES, or the batch options")


def _batch_admit(args: argparse.Namespace) -> int:
    for folder in (args.docs, args.batch_candidates, args.judgments):
        if folder is not None and not Path(folder).is_dir():
            raise ValueError(f"{folder}: expected a folder")
    resolved_output = Path(args.out).resolve()
    for option, folder in (
        ("--candidates", args.batch_candidates),
        ("--judgments", args.judgments),
    ):
        if folder is not None and resolved_output == Path(folder).resolve():
            raise ValueError(f"--out must not be the same folder as {option}: {resolved_output}")
    paths = sorted(path for path in Path(args.docs).glob("*.txt") if path.is_file())
    if not paths:
        raise ValueError(f"{args.docs}: no .txt documents")
    names: dict[str, str] = {}
    for path in paths:
        name = path.stem.casefold()
        if name in names:
            raise ValueError(
                f"{names[name]} and {path.name}: document names are equal in any letter case"
            )
        names[name] = path.name
    for path in paths:
        if path.stem.casefold() == "summary":
            raise ValueError(f"{path.name}: summary.json is reserved for the batch summary")
        candidates_path = Path(args.batch_candidates) / f"{path.stem}.json"
        if not candidates_path.is_file():
            raise ValueError(
                f"{candidates_path} is not there; write [] for a document with no candidates"
            )
        if args.judgments:
            judgments_path = Path(args.judgments) / f"{path.stem}.json"
            if not judgments_path.is_file():
                raise ValueError(
                    f"{judgments_path} is not there; write [] for a document with no judgments"
                )

    schema = _json(args.batch_schema)
    policy = _json(args.policy) if args.policy else None
    references = _json(args.references) if args.references else None
    receipts: dict[str, Any] = {}
    documents: dict[str, Any] = {}
    outcomes = Counter({"admitted": 0, "needs_verification": 0, "rejected": 0})
    codes: Counter[str] = Counter()
    for path in paths:
        doc = path.stem
        try:
            candidates = _json(str(Path(args.batch_candidates) / f"{doc}.json"))
            judgments = _json(str(Path(args.judgments) / f"{doc}.json")) if args.judgments else None
            receipt = admit(
                _text(str(path)),
                schema,
                candidates,
                policy,
                doc,
                judgments,
                references=references,
                document_source=args.document_source,
            )
        except (PacketError, ValueError, OSError) as e:
            raise ValueError(f"{path.name}: {e}") from e
        doc_codes = Counter(code for decision in receipt.decisions for code in decision.codes)
        doc_codes.update(code for _, code in receipt.coverage)
        body = receipt.to_dict()
        receipts[doc] = body
        documents[doc] = {"outcomes": body["summary"], "codes": dict(sorted(doc_codes.items()))}
        outcomes.update(body["summary"])
        codes.update(doc_codes)

    totals = {"outcomes": dict(outcomes), "codes": dict(sorted(codes.items()))}
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    for doc, body in receipts.items():
        _write(_dumps(body), str(output / f"{doc}.json"))
    _write(_dumps({"documents": documents, "totals": totals}), str(output / "summary.json"))
    print("| Outcome | Total |")
    print("|---|---:|")
    for outcome, count in outcomes.items():
        print(f"| {outcome} | {count} |")
    print("\n| Code | Total |")
    print("|---|---:|")
    for code, count in sorted(codes.items()):
        print(f"| {code} | {count} |")
    return 0


def _schema(args: argparse.Namespace) -> int:
    ids = None
    if args.references:
        refs = _json(args.references)
        if not isinstance(refs, list) or not all(isinstance(r, dict) for r in refs):
            raise PacketError("references must be a list of objects")
        ids = [r.get("id") for r in refs]
    _write(_dumps(extractor_schema(_json(args.schema), ids)), args.output)
    return 0


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
