"""groundgate command line.

  groundgate read     FILE                              > doc.txt
  groundgate read     --store DIR FILE -o doc.txt       > reading-key
  groundgate admit    DOC SCHEMA CANDIDATES             > receipt.json
  groundgate admit    --store DIR DOC SCHEMA CANDIDATES > packet-key
  groundgate admit    --docs D --candidates C --schema S --out R [--store DIR]
  groundgate verify   RECEIPT DOC SCHEMA CANDIDATES [--pack-dir DIR]
  groundgate verify   --store DIR PACKET
  groundgate report   RECEIPT DOC SCHEMA CANDIDATES [--pack-dir DIR] -o report.html
  groundgate report   --store DIR PACKET -o report.html
  groundgate review   tasks --store DIR PACKET          > task keys
  groundgate review   resolve --store DIR PACKET --reviewer NAME
  groundgate review   serve --store DIR --reviewer NAME  (the review page on 127.0.0.1)
  groundgate review   measures --store DIR [--json]     (the measures of the answers)
  groundgate schema   SCHEMA                            > extractor.schema.json
  groundgate schema check SCHEMA
  groundgate store    check   --store DIR [--repair]
  groundgate store    rebuild --store DIR
  groundgate store    forget  --store DIR PACKET --reason TEXT [--all]
  groundgate calibrate STEP ...                         (experimental; calibrate --help)

DOC may be "-" to read the document from standard input. Exit codes: 0 success, 1 the receipt
does not match its inputs (or schema check has a finding), 2 invalid input, or an input that is
not in the store ("input deleted" or "input missing").
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .admit import admit, verify
from .fold import fold, fold_text
from .model import PacketError, Schema, extractor_schema
from .pack import load_pack
from .text import KEY_DASHES, key_mentions, normalize_ws

if TYPE_CHECKING:
    from .store import FolderStore


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


def store_option(p: argparse.ArgumentParser, text: str) -> None:
    p.add_argument("--store", metavar="DIR", help=f"a store folder (docs/design/store.md): {text}")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="groundgate", description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = ap.add_subparsers(dest="command", required=True)

    x = sub.add_parser("read", help="turn a PDF, HTML, XML or text file into NFC text")
    x.add_argument("file")
    x.add_argument("-o", "--output", help="write the text here instead of stdout")
    x.add_argument("--layout", help="also write page and word boxes (PDF only) as JSON")
    x.add_argument("--pages", type=_pages, help="PDF pages to read, e.g. 1-12,15")
    store_option(x, "write the source, the text, the layout and a reading; print the reading key")

    s = sub.add_parser(
        "schema",
        help="write the JSON Schema for an extractor's output (or: schema check SCHEMA)",
    )
    s.add_argument("schema", help="schema JSON")
    s.add_argument("--references", help="JSON array of references; their ids become refs")
    s.add_argument(
        "--pack",
        action="append",
        default=[],
        metavar="FILE",
        help="a vocabulary pack that the schema names (SPEC §4.8); repeat for each pack",
    )
    s.add_argument("-o", "--output", help="write the JSON Schema here instead of stdout")

    def inputs(p: argparse.ArgumentParser, *, batch: bool = False) -> None:
        nargs = "?"  # main() checks the inputs of each mode
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
        p.add_argument(
            "--pack",
            action="append",
            default=[],
            metavar="FILE",
            help="a vocabulary pack that the schema names (SPEC §4.8); repeat for each pack",
        )

    a = sub.add_parser("admit", help="decide candidates and write a receipt")
    inputs(a, batch=True)
    a.add_argument("--document-id")
    a.add_argument("-o", "--output", help="write the receipt here instead of stdout")
    a.add_argument("--docs", help="folder of <doc>.txt files")
    a.add_argument("--schema", dest="batch_schema", help="schema JSON for batch mode")
    a.add_argument("--candidates", dest="batch_candidates", help="folder of <doc>.json files")
    a.add_argument("--out", help="folder for batch receipts and summary.json")
    store_option(
        a,
        "write the inputs, the receipt and a packet; print the packet key "
        "(in batch mode, summary.json names the packet key of each document)",
    )
    a.add_argument(
        "--reading", metavar="KEY", help="with --store: the key of the reading of DOC from read"
    )

    def pack_dir(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--pack-dir",
            metavar="DIR",
            help="a folder of pack files: verify takes each pack that the receipt names by its "
            "digest",
        )

    v = sub.add_parser("verify", help="re-derive a receipt from its inputs and compare")
    v.add_argument("receipt", help="the receipt JSON, or the packet key with --store")
    inputs(v)
    pack_dir(v)
    store_option(v, "get the receipt and each input of the packet PACKET")

    r = sub.add_parser("report", help="verify a receipt, then render an HTML review page")
    r.add_argument("receipt", help="the receipt JSON, or the packet key with --store")
    inputs(r)
    pack_dir(r)
    store_option(r, "get the receipt, each input and the layout of the packet PACKET")
    r.add_argument("--layout", help="layout JSON from read, to show page numbers")
    r.add_argument("--title")
    r.add_argument("-o", "--output", help="write the HTML here instead of stdout")
    rv = sub.add_parser("review", help="the review step (docs/design/review.md)")
    steps = rv.add_subparsers(dest="step", required=True)
    t = steps.add_parser(
        "tasks",
        help="write the review tasks of one packet to the store; print each task key",
        description="Decide the packet again, then write a task@1 object for each slot that "
        "docs/design/review.md section 5.2 selects. Print each task key, one on each line, in "
        "slot order. Exit codes: 0 success, 1 the receipt does not match its inputs, 2 invalid "
        "input, or an input that is not in the store.",
    )
    t.add_argument("packet", metavar="PACKET", help="the packet key from admit --store")
    t.add_argument("--store", metavar="DIR", required=True, help="the store folder")
    t.add_argument(
        "--policy",
        metavar="FILE",
        help="a review-policy@1 JSON file; without it, no audit and no task for a rejected slot",
    )
    rs = steps.add_parser(
        "resolve",
        help="resolve the answers to the tasks of one packet; print one line for each field",
        description="Decide the packet again, read the answer log of each reviewer, and run "
        "admit for each correction (docs/design/review.md section 6). Write each correction "
        "packet and a resolution@1 object to the store. Print the resolution key, then one "
        "line for each slot: the final value, or the reason that there is none. Exit codes: 0 "
        "success, 1 the receipt does not match its inputs, 2 invalid input, an answer that "
        "breaks its task, or an input that is not in the store.",
    )
    rs.add_argument("packet", metavar="PACKET", help="the packet key from admit --store")
    rs.add_argument("--store", metavar="DIR", required=True, help="the store folder")
    rs.add_argument(
        "--policy",
        metavar="FILE",
        help="a review-policy@1 JSON file; without it, agree 1, no lead and no audit",
    )
    rs.add_argument(
        "--reviewer",
        action="append",
        default=[],
        metavar="NAME",
        help="read the answer log of this reviewer; repeat for each reviewer",
    )
    sv = steps.add_parser(
        "serve",
        help="answer the review tasks of a store in the browser, on 127.0.0.1",
        description="Serve the review page of docs/design/review.md section 8 on 127.0.0.1, and "
        "print its start URL. The page shows each task@1 object of the store whose packet "
        "matches its receipt, and writes each answer to the answer log of the reviewer. The "
        "server is for one local user: a holder of the URL can answer as the reviewer, and a "
        "lead answer is not an authenticated act. Press Ctrl-C to stop. Exit codes: 0 stopped, "
        "2 invalid input.",
    )
    sv.add_argument("--store", metavar="DIR", required=True, help="the store folder")
    sv.add_argument("--reviewer", metavar="NAME", required=True, help="the name of the reviewer")
    sv.add_argument(
        "--policy",
        metavar="FILE",
        help="a review-policy@1 JSON file for agree and leads; without it, agree 1 and no lead",
    )
    sv.add_argument(
        "--port", type=int, default=0, help="the port; 0 (the default) takes a free one"
    )
    ms = steps.add_parser(
        "measures",
        help="print the measures of the answers in a store, for each item kind and field",
        description="Read each answer log of the store, resolve each packet, and print the "
        "measures of docs/design/review.md section 10 for each item kind and for each field: "
        "the median time, the answers given with one key, the agreement with blind labels and "
        "the escapes that the audit finds. Write nothing to the store. A packet whose receipt "
        "does not match its inputs, or whose answers break their tasks, is left out and named "
        "on stderr. Exit codes: 0 success, 1 a packet is left out, 2 invalid input.",
    )
    ms.add_argument("--store", metavar="DIR", required=True, help="the store folder")
    ms.add_argument(
        "--policy",
        metavar="FILE",
        help="a review-policy@1 JSON file for agree and leads; without it, agree 1 and no lead",
    )
    ms.add_argument("--set", metavar="NAME", help="the set of the splits log; needs --split")
    ms.add_argument(
        "--split",
        metavar="NAME",
        help="measure only the documents in this split of --set, for example development",
    )
    ms.add_argument("--json", action="store_true", help="print the measures as JSON")
    # main() sends `store` to its own parser before this parser runs; the entry is here so that
    # --help names the command
    sub.add_parser(
        "store", help="check, rebuild and forget in a store folder (store --help)", add_help=False
    )
    # main() sends `calibrate` to groundgate.calibrate before this parser runs; the entry is here
    # so that --help names the command
    sub.add_parser(
        "calibrate",
        help="experimental: measure a judge's thresholds on your own documents",
        add_help=False,
    )
    return ap


def _check_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="groundgate schema check",
        description="Print the schema settings that docs/schema.md lists under 'Check a schema'. "
        "Exit codes: 0 no finding, 1 a finding, 2 invalid schema.",
    )
    ap.add_argument("schema", help="schema JSON")
    ap.add_argument(
        "--pack",
        action="append",
        default=[],
        metavar="FILE",
        help="a vocabulary pack that the schema names (SPEC §4.8); repeat for each pack",
    )
    return ap


def _store_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="groundgate store",
        description="Check, rebuild and forget in a store folder (docs/design/store.md). Exit "
        "codes: 0 success, 1 check has a finding or forget could not read an object, 2 invalid "
        "input or a store error.",
    )
    sub = ap.add_subparsers(dest="action", required=True)
    c = sub.add_parser("check", help="check each object, each chain and each packet")
    c.add_argument("--store", metavar="DIR", required=True, help="the store folder")
    c.add_argument("--repair", action="store_true", help="cut a torn last line, and print it")
    b = sub.add_parser("rebuild", help="build the views again from the objects and logs")
    b.add_argument("--store", metavar="DIR", required=True, help="the store folder")
    f = sub.add_parser(
        "forget",
        help="remove the document data of a packet and record each deletion",
        description="Remove the objects of PACKET that hold document data, and record each "
        "deletion in logs/deleted.jsonl. An object that two packets share goes for both. "
        "The packet, the receipt and the other kept objects stay, and verify then reports "
        "'input deleted'. The run record goes too if a line holds document text: a string of "
        "8 or more characters that is in the text. That check is not a proof. If forget "
        "cannot read an object, it prints 'unchecked', removes the rest and exits 1.",
    )
    f.add_argument("--store", metavar="DIR", required=True, help="the store folder")
    f.add_argument("packet", metavar="PACKET", help="the packet key")
    f.add_argument("--reason", required=True, help="the reason, for the deleted log")
    f.add_argument(
        "--all",
        action="store_true",
        help="remove each object and answer log of the packet, and the packet. A kept object "
        "that another packet names stays. Run store check first: a packet that cannot be read "
        "names nothing.",
    )
    return ap


def _store_command(args: argparse.Namespace) -> int:
    from .store.maintain import check, forget_packet, rebuild
    from .store.packets import printable

    with _store(args.store, make=False) as store:
        if args.action == "rebuild":
            for path in rebuild(store):
                print(f"wrote {path}")
            return 0
        if args.action == "forget":
            done = forget_packet(store, args.packet, args.reason, everything=args.all)
            for kind, name, state, shared in done:
                line = f"{state} {kind} {name}" if kind != "log" else f"{state} {name}"
                if shared:
                    line += f" ({shared} other packet{'s' if shared > 1 else ''} name"
                    line += "s it)" if shared == 1 else " it)"
                print(line)
            return 1 if any(state == "unchecked" for _, _, state, _ in done) else 0
        report = check(store, repair=args.repair)
    for path, cut in report.cut:
        text = cut.decode("utf-8", errors="backslashreplace")
        print(f"cut from {path}: {printable(text, limit=None)}")
    for entry in report.deleted:
        print(f"input deleted: {entry}")
    for run in report.unchecked:
        print(f"not checked: the run record {run}, because its text is not in the store")
    for finding in report.findings:
        print(f"finding: {printable(finding, limit=None)}")
    print(
        f"checked {report.objects} objects and {report.logs} logs: {len(report.findings)} findings"
    )
    return 1 if report.findings else 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["extract"]:  # 0.9 moved the reader to `read`, with any old options
        print(
            "groundgate: to turn a file into text, use `groundgate read FILE` "
            "(`groundgate extract` was renamed to `groundgate read` in 0.9)",
            file=sys.stderr,
        )
        return 2
    if argv[:1] == ["calibrate"]:
        from .calibrate.cli import main as calibrate

        calibrate(argv[1:])
        return 0
    if argv[:1] == ["store"]:
        store_args = _store_parser().parse_args(argv[1:])
        try:
            return _store_command(store_args)
        except (ValueError, OSError) as e:
            print(f"groundgate: {e}", file=sys.stderr)
            return 2
    check = argv[:2] == ["schema", "check"]
    parser = _check_parser() if check else _parser()
    args = parser.parse_args(argv[2:] if check else argv)
    if not check and args.command == "admit":
        _admit_inputs(parser, args)
    if not check and args.command in ("verify", "report"):
        _verify_inputs(parser, args)
    try:
        if check:
            return _check(args)
        if args.command == "read":
            return _read(args)
        if args.command == "schema":
            return _schema(args)
        if args.command == "review" and args.step == "resolve":
            return _review_resolve(args)
        if args.command == "review" and args.step == "serve":
            return _review_serve(args)
        if args.command == "review" and args.step == "measures":
            return _review_measures(args)
        if args.command == "review":
            return _review_tasks(args)
        if args.command == "admit" and args.docs is not None:
            return _batch_admit(args)
        if args.command in ("verify", "report") and args.store is not None:
            return _from_store(args)
        policy = _json(args.policy) if args.policy else None
        text = _text(args.document)
        schema, candidates = _json(args.schema), _json(args.candidates)
        judgments = _json(args.judgments) if args.judgments else None
        extra = {
            "references": _json(args.references) if args.references else None,
            "document_source": args.document_source,
            "packs": [load_pack(f) for f in args.pack],
        }
        if args.command == "admit" and args.store is not None:
            return _admit_store(args, text, schema, candidates, policy, judgments, extra)
        if args.command == "admit":
            receipt = admit(text, schema, candidates, policy, args.document_id, judgments, **extra)
            _write(_dumps(receipt.to_dict()), args.output)
            return 0
        stored = _json(args.receipt)
        extra["pack_dir"] = args.pack_dir  # verify and report read the folder in the same way
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
        title = Path(args.document).name if args.document != "-" else None
        layout = _json(args.layout) if args.layout else None
        schema, policy = _json(args.schema), _json(args.policy) if args.policy else None
        extra.update(schema=schema, policy=policy, judgments=judgments)
        return _report(args, stored, text, candidates, extra, layout, title)
    except (PacketError, ValueError, OSError, ImportError) as e:  # JSON, UTF-8: ValueError
        print(f"groundgate: {e}", file=sys.stderr)
        return 2


def _admit_inputs(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    batch = (args.docs, args.batch_candidates, args.batch_schema, args.out)
    single = (args.document, args.schema, args.candidates)
    if args.reading is not None and args.store is None:
        parser.error("--reading needs --store")
    if any(value is not None for value in batch):
        if not all(batch):
            parser.error("batch admit requires --docs, --candidates, --schema and --out")
        if any(value is not None for value in (*single, args.output, args.document_id)):
            parser.error("batch admit cannot use positional inputs, --output or --document-id")
        if args.reading is not None:
            parser.error("batch admit cannot use --reading")
    elif not all(value is not None for value in single):
        parser.error("admit requires DOC SCHEMA CANDIDATES, or the batch options")


def _verify_inputs(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    single = (args.document, args.schema, args.candidates)
    if args.store is None:
        if not all(value is not None for value in single):
            parser.error(
                f"{args.command} requires RECEIPT DOC SCHEMA CANDIDATES, or --store DIR PACKET"
            )
        return
    given = [
        option
        for option, value in (
            ("DOC SCHEMA CANDIDATES", any(v is not None for v in single)),
            ("--policy", args.policy is not None),
            ("--judgments", args.judgments is not None),
            ("--references", args.references is not None),
            ("--document-source", args.document_source is not None),
            ("--pack", bool(args.pack)),
        )
        if value
    ]
    if given:
        parser.error(
            f"with --store, {args.command} gets each input from the packet: remove "
            + ", ".join(given)
        )


@contextlib.contextmanager
def _store(folder: str, *, make: bool) -> Iterator[FolderStore]:
    """A folder store. A store error becomes a ``ValueError``, so it exits 2. The core and this
    module do not import the store until a command takes ``--store``."""
    from .store import FolderStore, StoreError

    path = Path(folder)
    if not make and not path.is_dir():
        raise ValueError(f"{folder}: the store folder is not there")
    try:
        with FolderStore(path) as store:
            yield store
    except StoreError as exc:
        raise ValueError(str(exc)) from exc


def _admit_store(
    args: argparse.Namespace,
    text: str,
    schema: Any,
    candidates: Any,
    policy: Any,
    judgments: Any,
    extra: dict[str, Any],
) -> int:
    from .store.packets import admit_packet

    with _store(args.store, make=True) as store:
        packet, receipt = admit_packet(
            store,
            text,
            schema,
            candidates,
            policy,
            args.document_id,
            judgments,
            reading=args.reading,
            **extra,
        )
    if args.output:
        _write(_dumps(receipt.to_dict()), args.output)
    print(packet)
    return 0


def _from_store(args: argparse.Namespace) -> int:
    from .store.packets import load_packet

    with _store(args.store, make=False) as store:
        packet = load_packet(store, args.receipt, layout=args.command == "report")
    extra = {**packet.inputs(), "pack_dir": args.pack_dir}
    result = verify(packet.receipt, packet.text, packet.schema, packet.candidates, **extra)
    for problem in result.problems:
        print(f"mismatch: {problem}", file=sys.stderr)
    if args.command == "verify":
        if result.ok:
            print("receipt verified")
        return 0 if result.ok else 1
    if not result.ok:
        print("groundgate: not rendering a receipt that does not match", file=sys.stderr)
        return 1
    layout = _json(args.layout) if args.layout else packet.layout
    extra["schema"] = packet.schema
    return _report(args, packet.receipt, packet.text, packet.candidates, extra, layout, None)


def _review_tasks(args: argparse.Namespace) -> int:
    from .escape import escape
    from .review.tasks import write_tasks

    policy = _json(args.policy) if args.policy else None
    with _store(args.store, make=False) as store:
        written = write_tasks(store, args.packet, policy)
    for problem in written.problems:  # a problem can quote store data: escape each control
        shown = escape(problem)
        print(f"mismatch: {shown}", file=sys.stderr)
    if written.problems:
        print("groundgate: no task for a receipt that does not match", file=sys.stderr)
        return 1
    for k, _ in written.tasks:
        print(k)
    return 0


def _review_serve(args: argparse.Namespace) -> int:
    from .review.serve import Review, server

    policy = _json(args.policy) if args.policy else None
    if not 0 <= args.port <= 65535:
        raise ValueError("the port must be from 0 to 65535")
    with _store(args.store, make=False) as store:
        review = Review(store, args.reviewer, policy)
        for line in review.skipped:
            print(f"skipped: {line}", file=sys.stderr)
        httpd, url = server(review, args.port)
        print(f"Open {url} and press Ctrl-C here when you finish.", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()
    return 0


def _review_measures(args: argparse.Namespace) -> int:
    from .review.measures import lines, measures

    policy = _json(args.policy) if args.policy else None
    with _store(args.store, make=False) as store:
        measured = measures(store, policy, set_name=args.set, split=args.split)
    for line in measured.skipped:  # each line escapes the control characters of store data
        print(f"skipped: {line}", file=sys.stderr)
    if args.json:
        print(json.dumps(measured.to_dict(), indent=2, sort_keys=True, ensure_ascii=True))
    else:
        for line in lines(measured):
            print(line)
    return 1 if measured.skipped else 0


def _review_resolve(args: argparse.Namespace) -> int:
    from .escape import escape
    from .review.resolve import lines, write_resolution

    policy = _json(args.policy) if args.policy else None
    with _store(args.store, make=False) as store:
        resolved = write_resolution(store, args.packet, policy, args.reviewer)
    for problem in resolved.problems:  # a problem can quote store data: escape each control
        shown = escape(problem)
        print(f"mismatch: {shown}", file=sys.stderr)
    if resolved.resolution is None:
        print("groundgate: no resolution for a receipt that does not match", file=sys.stderr)
        return 1
    print(resolved.key)
    for line in lines(resolved.resolution):
        print(line)
    return 0


def _check_packet() -> Any:
    """``check_packet``, imported only when batch admit takes ``--store``."""
    from .store.packets import check_packet

    return check_packet


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
    if args.store is not None and resolved_output == Path(args.store).resolve():
        raise ValueError(f"--out must not be the same folder as --store: {resolved_output}")
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
    packs = [load_pack(f) for f in args.pack]
    receipts: dict[str, Any] = {}
    inputs: dict[str, tuple[str, Any, Any]] = {}
    documents: dict[str, Any] = {}
    outcomes = Counter({"admitted": 0, "needs_verification": 0, "rejected": 0})
    codes: Counter[str] = Counter()
    decide = admit if args.store is None else _check_packet()  # with --store, the store checks too
    for path in paths:
        doc = path.stem
        try:
            candidates = _json(str(Path(args.batch_candidates) / f"{doc}.json"))
            judgments = _json(str(Path(args.judgments) / f"{doc}.json")) if args.judgments else None
            text = _text(str(path))
            receipt = decide(
                text,
                schema,
                candidates,
                policy,
                doc,
                judgments,
                references=references,
                document_source=args.document_source,
                packs=packs,
            )
        except (PacketError, ValueError, OSError) as e:
            raise ValueError(f"{path.name}: {e}") from e
        doc_codes = Counter(code for decision in receipt.decisions for code in decision.codes)
        doc_codes.update(code for _, code in receipt.coverage)
        body = receipt.to_dict()
        receipts[doc] = body
        inputs[doc] = (text, candidates, judgments)
        documents[doc] = {"outcomes": body["summary"], "codes": dict(sorted(doc_codes.items()))}
        outcomes.update(body["summary"])
        codes.update(doc_codes)

    if args.store is not None:
        # check_packet passed for each document, so no packet is written before an input error.
        from .store.packets import admit_packet

        with _store(args.store, make=True) as store:
            for doc, (text, candidates, judgments) in inputs.items():
                try:
                    packet, _ = admit_packet(
                        store,
                        text,
                        schema,
                        candidates,
                        policy,
                        doc,
                        judgments,
                        references=references,
                        document_source=args.document_source,
                        packs=packs,
                    )
                except ValueError as e:  # PacketError is a ValueError
                    raise ValueError(f"{doc}.txt: {e}") from e
                documents[doc]["packet"] = packet
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
    packs = [load_pack(f) for f in args.pack]
    _write(_dumps(extractor_schema(_json(args.schema), ids, packs)), args.output)
    return 0


def _findings(schema: Schema) -> list[str]:
    """The settings of a valid schema that make a check fail every time, or pass for the wrong
    key or field. Step 1 already refuses blank and repeated keys and aliases of one field."""
    out: list[str] = []
    owners: dict[str, tuple[str, list[str]]] = {}  # normalized alias: (as written, fields)
    for name, f in schema.fields.items():
        formless = f.unit is not None and not any(schema.units.get(f.unit, ([], [])))
        if formless:
            out.append(
                f"field {name!r} has a unit with no forms: "
                "a value is admitted with no unit check, and a unit item never passes"
            )
        if f.aliases is None:
            if f.unit is not None and not formless:
                out.append(
                    f"field {name!r} has a unit and no aliases: "
                    "a unit item passes only for a unit next to the number"
                )
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
                names = owners.setdefault(_norm(alias), (alias, []))[1]
                if name not in names:  # two spellings of one alias on one field
                    names.append(name)
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
    # in each other alias, with each letter folded as SPEC §4 says (Aho-Corasick). key_mentions
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


_DASH_FOLD = str.maketrans(dict.fromkeys(KEY_DASHES, "-"))


def _norm(word: str) -> str:
    """The alias as key_mentions compares it: letters (SPEC §4), whitespace runs and dashes folded
    (SPEC §4.5)."""
    return fold_text(normalize_ws(word)).translate(_DASH_FOLD)


def _folded(text: str) -> tuple[str, list[int]]:
    """The text with each letter folded as SPEC §4 says, each run of whitespace as one space
    and each dash as "-", as key_mentions reads a key, and the place in the text of each
    character."""
    out: list[str] = []
    places: list[int] = []
    for i, c in enumerate(text):
        if _SPACE.match(c):
            if out and out[-1] != " ":
                out.append(" ")
                places.append(i)
            continue
        out.append("-" if c in KEY_DASHES else fold(c))
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


def _check(args: argparse.Namespace) -> int:
    found = _findings(Schema.from_dict(_json(args.schema), [load_pack(f) for f in args.pack]))
    for line in found:
        print(line)
    return 1 if found else 0


def _read(args: argparse.Namespace) -> int:
    from .read import read

    if args.store is not None:
        if args.layout and Path(args.file).suffix.lower() != ".pdf":  # before a store write
            print("groundgate: --layout needs a PDF", file=sys.stderr)
            return 2
        from .store.packets import put_reading

        with _store(args.store, make=True) as store:
            reading, doc = put_reading(store, args.file, args.pages)
    else:
        doc = read(args.file, pages=args.pages)
    for w in doc.warnings:
        print(f"groundgate: warning: {w}", file=sys.stderr)
    if args.layout:
        if doc.layout is None:
            print("groundgate: --layout needs a PDF", file=sys.stderr)
            return 2
        Path(args.layout).write_text(json.dumps(doc.layout.to_dict()) + "\n", encoding="utf-8")
    if args.store is not None:
        if args.output:
            _write(doc.text, args.output)
        print(reading)
        return 0
    _write(doc.text, args.output)
    return 0


def _report(
    args: argparse.Namespace,
    receipt: Any,
    text: str,
    candidates: Any,
    extra: dict[str, Any],
    layout_dict: Any,
    file_title: str | None,
) -> int:
    from .canonical import digest
    from .read import Layout
    from .report import render

    layout = None
    if layout_dict is not None:
        layout = Layout.from_dict(layout_dict)
        if layout.document_sha256 != digest("document", {"text": text}):
            raise PacketError("the layout was extracted from a different document")
    doc_id = receipt.get("document", {}).get("id") if isinstance(receipt, dict) else None
    title = args.title or doc_id or file_title
    page = render(receipt, text, candidates, layout=layout, title=title, **extra)
    _write(page, args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
