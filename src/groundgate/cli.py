"""groundgate command line.

  groundgate extract  FILE                              > doc.txt
  groundgate admit    DOC SCHEMA CANDIDATES             > receipt.json
  groundgate admit    --docs D --candidates C --schema S --out R
  groundgate verify   RECEIPT DOC SCHEMA CANDIDATES
  groundgate report   RECEIPT DOC SCHEMA CANDIDATES -o report.html
  groundgate schema   SCHEMA                            > extractor.schema.json
  groundgate schema check SCHEMA

DOC may be "-" to read the document from standard input. Exit codes: 0 success, 1 the receipt
does not match its inputs (or schema check has a finding), 2 invalid input.
"""

from __future__ import annotations

import argparse
import functools
import json
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Callable
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
    parser = _check_parser() if check else _parser()
    args = parser.parse_args(argv[2:] if check else argv)
    if not check and args.command == "admit":
        _admit_inputs(parser, args)
    try:
        if check:
            return _check(args)
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
    # An alias in a longer alias of another field. One pass over all aliases finds each alias
    # in each other alias, with letters folded as re.I matches them (Aho-Corasick). key_mentions
    # then confirms each pair, so the work grows with the aliases and the findings.
    rank = {name: n for n, name in enumerate(schema.fields)}
    # folded alias: normalized alias: (field, place, alias). Equal normalized aliases are
    # reported above, so a pair needs two of them.
    groups: dict[str, dict[str, list[tuple[str, int, str]]]] = {}
    for other, g in schema.fields.items():
        for n, b in enumerate(g.aliases or ()):
            group = groups.setdefault(_folded(b)[0], {})
            group.setdefault(_norm(b), []).append((other, n, b))
    patterns = list(groups)
    automaton = _automaton(patterns)
    pairs: set[tuple[str, str, int, str]] = set()
    for holders in groups.values():
        for norm_b, places in holders.items():  # one spelling: the same word boundaries
            for p in _found(patterns, automaton, places[0][2]):
                for norm_a, named in groups[patterns[p]].items():
                    if norm_a != norm_b:
                        pairs.update(
                            (name, other, n, b)
                            for name, _, _ in named
                            for other, n, b in places
                            if other != name
                        )
    for name, other, _, b in sorted(pairs, key=lambda p: (rank[p[0]], rank[p[1]], p[2])):
        aliases = schema.fields[name].aliases or ()
        for a in dict.fromkeys(a for _, _, a in key_mentions(b, aliases)):
            if _norm(a) != _norm(b):
                out.append(
                    f"alias {a!r} of field {name!r} is in alias {b!r} of field "
                    f"{other!r}: a field item for {other!r} passes for {name!r}"
                )
    return out


def _norm(word: str) -> str:
    return normalize_ws(word).lower()


def _folded(text: str) -> tuple[str, list[int]]:
    """The text with each letter folded as re.I matches it and each run of whitespace as one
    space, as key_mentions reads a key, and the place in the text of each character."""
    out: list[str] = []
    places: list[int] = []
    for i, c in enumerate(text):
        if _SPACE.match(c):
            if out and out[-1] != " ":
                out.append(" ")
                places.append(i)
            continue
        out.append(_fold(c))
        places.append(i)
    if out and out[-1] == " ":
        out.pop()
        places.pop()
    return "".join(out), places


_Automaton = tuple[list[dict[str, int]], list[int], list[list[int]]]


def _found(patterns: list[str], automaton: _Automaton, raw: str) -> set[int]:
    """The patterns that occur in the folded raw text with no letter or digit of the raw text
    next to them."""
    goto, fail, ends = automaton
    folded, places = _folded(raw)
    found: set[int] = set()
    state = 0
    for j, c in enumerate(folded):
        while state and c not in goto[state]:
            state = fail[state]
        state = goto[state].get(c, 0)
        for p in ends[state]:
            first, last = places[j - len(patterns[p]) + 1], places[j]
            before = raw[first - 1] if first else " "
            after = raw[last + 1] if last + 1 < len(raw) else " "
            if not _WORD.match(before) and not _WORD.match(after):
                found.add(p)
    return found


def _automaton(patterns: list[str]) -> _Automaton:
    """The Aho-Corasick automaton of the patterns: goto, fail and the patterns that end at each
    state."""
    goto: list[dict[str, int]] = [{}]
    ends: list[list[int]] = [[]]
    for p, pattern in enumerate(patterns):
        state = 0
        for c in pattern:
            if c not in goto[state]:
                goto.append({})
                ends.append([])
                goto[state][c] = len(goto) - 1
            state = goto[state][c]
        ends[state].append(p)
    fail = [0] * len(goto)
    queue = list(goto[0].values())
    for state in queue:
        for c, child in goto[state].items():
            queue.append(child)
            back = fail[state]
            while back and c not in goto[back]:
                back = fail[back]
            fail[child] = goto[back].get(c, 0)
            ends[child] = ends[child] + ends[fail[child]]
    return goto, fail, ends


_SPACE, _WORD = re.compile(r"\s"), re.compile(r"[^\W_]")
_ONE_LETTER = {"\ufb05": "\ufb06"}  # re.I matches the two "st" ligatures


@functools.lru_cache(maxsize=4096)
def _fold(c: str) -> str:
    """One letter for each set of letters that re.I matches with each other."""
    seen, todo = {c}, [c]
    while todo:
        x = todo.pop()
        for y in (x.lower(), x.upper(), x.casefold(), x.title(), unicodedata.normalize("NFC", x)):
            d = y[:1]
            if d not in seen and re.fullmatch(re.escape(x), d, re.I):
                seen.add(d)
                todo.append(d)
    k = min(_single(str.lower, _single(str.upper, x)) for x in seen)
    return _ONE_LETTER.get(k, k)


def _single(case: Callable[[str], str], c: str) -> str:
    out = case(c)
    return out if len(out) == 1 else c


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
