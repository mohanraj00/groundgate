"""One feedback round on the held-out 10-K set (#209). The replies of run.py are decided with
the current groundgate (spec 0.6, all rules on). For each document with a decision that
gg.feedback_message gives a message for, the same model gets the prompt of run.py once more,
then the messages. Its new candidates are decided alone, as in docs/howto/feedback.md.

    uv run python bench/sec3/feedback.py ask --provider claude-cli --model claude-haiku-5-5
    uv run python bench/sec3/feedback.py ask --provider codex --model gpt-6-luna
    uv run python bench/sec3/feedback.py decide
    uv run python bench/sec3/feedback.py web            # blind labels, http://127.0.0.1:8775
    uv run python bench/sec3/feedback.py results [--check]

The CLIs run as in run.py, with the same flags, isolation and default effort. The new replies
go to runs/<model>-feedback/<id>.json, with the CLI version and the prompt hash. They quote the
filings, so runs/ stays out of git. A reply is stale when its prompt hash or its output schema
hash differs from those of the prompt and the schema now: decide stops on it, and ask asks again.

A fact is stored when a round admits it, except when the two rounds admit different values for
one field and key that is not multiple: then neither value is stored (the how-to's rule). A
person labels each fact that a round admits, on the page of measure.py, which never shows a
run, a spec, a round or an outcome. Labels are keyed by fact, in labels.json, so the labels of
measure.py stay valid.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import measure  # bench/sec3/measure.py
import run  # bench/sec3/run.py

from groundgate.codes import INFO

HERE = Path(__file__).parent
OUT = HERE / "feedback"
RUNS = measure.RUNS
PORT = 8775
INTRO = (
    "\n\ngroundgate checked your first answer and did not admit the candidates below. Give a "
    "new candidate for each one, and fix what the feedback says. Give only these candidates."
    "\n\n"
)


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidates(rec: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    reply = rec.get("reply")
    cands = [] if reply is None else reply["candidates"]
    return [{"id": f"{prefix}{i}", **c} for i, c in enumerate(cands)]


def _first(run_name: str, doc: str, text: str) -> tuple[list[Any], list[str | None]]:
    """The first round's decisions under the current groundgate, with the message of each."""
    import groundgate as gg

    schema = measure._schema()
    cands = _candidates(_read(HERE / "runs" / run_name / f"{doc}.json"), "c")
    by_id = {c["id"]: c for c in cands}
    decisions = sorted(
        gg.admit(text, schema, cands).decisions, key=lambda d: int(d.candidate_id[1:])
    )
    messages = [gg.feedback_message(d, by_id[d.candidate_id], schema, text) for d in decisions]
    return decisions, messages


def _prompt(text: str, messages: list[str | None]) -> str | None:
    sent = [m for m in messages if m is not None]
    return run.prompt_for(text) + INTRO + "\n".join(sent) if sent else None


def _docs() -> list[Path]:
    return sorted((HERE / "docs").glob("*.txt"))


def _stale(rec: dict[str, Any], prompt: str) -> str | None:
    """Why a recorded reply does not answer this prompt and the current output schema."""
    import groundgate as gg

    if rec["prompt_sha256"] != run.sha(prompt):
        return "answers other messages"
    shown = run.output_schema(rec["provider"], gg.extractor_schema(measure._schema()))
    if rec["output_schema_sha256"] != run.sha(json.dumps(shown, sort_keys=True)):
        return "answers another output schema"
    return None


def ask(provider: str, model: str, workers: int) -> None:
    import groundgate as gg

    schema = gg.extractor_schema(measure._schema())
    runner = run.Runner(provider, model, schema)
    folder = HERE / "runs" / f"{model}-feedback"
    folder.mkdir(parents=True, exist_ok=True)
    todo = []
    for doc in _docs():
        text = doc.read_text(encoding="utf-8")
        prompt = _prompt(text, _first(model, doc.stem, text)[1])
        path = folder / f"{doc.stem}.json"
        if prompt is None or (path.exists() and _stale(_read(path), prompt) is None):
            continue
        todo.append((doc, prompt))  # a stale reply is asked again
    print(f"{len(todo)} documents to ask", flush=True)
    with ThreadPoolExecutor(workers) as pool:
        jobs = [pool.submit(runner.one, d, folder / f"{d.stem}.json", p) for d, p in todo]
        for job in jobs:
            print(job.result(), flush=True)


def _rows(decisions: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": d.candidate_id,
            "field": d.field,
            "key": d.key,
            "value": d.value,
            "evidence": None if d.evidence is None else list(d.evidence),
            "outcome": d.outcome,
            "codes": list(d.codes),
        }
        for d in decisions
    ]


def decide() -> None:
    """feedback/decisions-<run>.json: for each document, the first round's decisions with a
    flag for each message, and the decisions of the feedback round."""
    import groundgate as gg
    from groundgate.canonical import SPEC_VERSION

    if SPEC_VERSION != "0.6":
        raise SystemExit(f"this measure decides with spec 0.6, not {SPEC_VERSION}")
    OUT.mkdir(exist_ok=True)
    schema = measure._schema()
    for run_name in RUNS:
        found: dict[str, Any] = {"spec": SPEC_VERSION, "docs": {}}
        for doc_path in _docs():
            doc = doc_path.stem
            text = doc_path.read_text(encoding="utf-8")
            decisions, messages = _first(run_name, doc, text)
            first = _rows(decisions)
            for row, m in zip(first, messages, strict=True):
                row["message"] = m is not None
            got: dict[str, Any] = {"first": first, "asked": False}
            prompt = _prompt(text, messages)
            if prompt is not None:
                path = HERE / "runs" / f"{run_name}-feedback" / f"{doc}.json"
                if not path.exists():
                    raise SystemExit(f"{path} is missing: run ask")
                rec = _read(path)
                stale = _stale(rec, prompt)
                if stale is not None:
                    raise SystemExit(f"{path} {stale}: run ask again")
                cands = _candidates(rec, "r")
                got.update(
                    asked=True,
                    reply=rec["reply"] is not None,
                    cli=rec["cli"],
                    prompt_sha256=rec["prompt_sha256"],
                    second=_rows(list(gg.admit(text, schema, cands).decisions)),
                )
            found["docs"][doc] = got
        measure._dump(OUT / f"decisions-{run_name}.json", found)
    print(f"wrote decisions for {', '.join(RUNS)}")


def _found() -> dict[str, Any]:
    return {run_name: _read(OUT / f"decisions-{run_name}.json") for run_name in RUNS}


def _admitted(doc: str, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        measure.item_id(doc, r["field"], r["key"], r["value"]): r
        for r in rows
        if r["outcome"] == "admitted"
    }


def facts() -> dict[str, dict[str, Any]]:
    """Each fact that a round admits, once."""
    out: dict[str, dict[str, Any]] = {}
    for found in _found().values():
        for doc, got in found["docs"].items():
            for fid, r in _admitted(doc, got["first"] + got.get("second", [])).items():
                if fid not in out or (out[fid]["evidence"] is None and r["evidence"] is not None):
                    out[fid] = {k: r[k] for k in ("field", "key", "value", "evidence")}
                    out[fid]["doc"] = doc
    return out


def _stored(doc: str, got: dict[str, Any]) -> tuple[set[str], set[str]]:
    """The facts stored after the first round, and after the feedback round."""
    multiple = {k: f.get("multiple", False) for k, f in measure._schema()["fields"].items()}
    first = _admitted(doc, got["first"])
    both = {**first, **_admitted(doc, got.get("second", []))}
    values: dict[tuple[str, str | None], set[str]] = {}
    for r in both.values():
        values.setdefault((r["field"], r["key"]), set()).add(r["value"])
    after = {
        fid
        for fid, r in both.items()
        if multiple[r["field"]] or len(values[r["field"], r["key"]]) == 1
    }
    return set(first), after


def score() -> dict[str, Any]:
    """For each run, the labels of the facts stored after the first round and after the
    feedback round, and the counts of the round: the messages, the documents asked, the
    decisions with no message and their codes, the new proposals and the replies."""
    given = measure.labels()
    verdict = {"right": "right", "wrong": "escapes", "not sure": "not sure"}
    res: dict[str, Any] = {"runs": {}}
    for run_name, found in _found().items():
        rounds = {
            name: {"right": 0, "escapes": 0, "not sure": 0, "unlabeled": 0}
            for name in ("first", "after")
        }
        codes: Counter[str] = Counter()
        count = {"messages": 0, "no message": 0, "asked": 0, "no reply": 0, "proposals": 0}
        cli = set()
        for doc, got in found["docs"].items():
            for name, stored in zip(("first", "after"), _stored(doc, got), strict=True):
                for fid in stored:
                    v = given.get(fid, {}).get("verdict")
                    rounds[name][verdict[v] if v else "unlabeled"] += 1
            for r in got["first"]:
                if r["message"]:
                    count["messages"] += 1
                elif r["outcome"] != "admitted":
                    count["no message"] += 1
                    codes.update(c for c in r["codes"] if c not in INFO)
            if got["asked"]:
                count["asked"] += 1
                count["no reply"] += not got["reply"]
                count["proposals"] += len(got["second"])
                cli.add(got["cli"])
        res["runs"][run_name] = {
            **rounds,
            **count,
            "no message codes": dict(sorted(codes.items(), key=lambda kv: (-kv[1], kv[0]))),
            "cli": sorted(cli),
        }
    return res


def render(res: dict[str, Any]) -> str:
    lines = [
        "# One feedback round on the held-out 10-K set (#209)",
        "",
        "Generated by `bench/sec3/feedback.py results` from `feedback/results.json`. Do not edit.",
        "",
        "The replies of `bench/sec3/run.py`, decided with spec 0.6. Each decision that "
        "`gg.feedback_message` gives a message for goes back to the same model once, with the "
        "prompt of the first round. A value counts once per document, field, key and value. An "
        "escape is a wrong value that is stored. After the round, a fact is stored when either "
        "round admits it.",
        "",
        "| Run | Stored | Right | Escapes | Not sure | Not labeled |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for run_name, c in res["runs"].items():
        for name, title in (("first", "first answer"), ("after", "after one feedback round")):
            r = c[name]
            lines.append(
                f"| {run_name} | {title} | {r['right']} | {r['escapes']} | {r['not sure']} | "
                f"{r['unlabeled']} |"
            )
    lines += [
        "",
        "| Run | Messages | Not admitted, no message | Documents asked | No reply | "
        "New proposals |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for run_name, c in res["runs"].items():
        lines.append(
            f"| {run_name} | {c['messages']} | {c['no message']} | {c['asked']} | "
            f"{c['no reply']} | {c['proposals']} |"
        )
    lines += [
        "",
        "The codes of the decisions with no message, without the codes that only inform:",
        "",
    ]
    for run_name, c in res["runs"].items():
        listed = ", ".join(f"`{k}` {n}" for k, n in c["no message codes"].items())
        lines.append(f"- {run_name}: {listed or 'none'}")
    lines += ["", "The CLI versions of the feedback replies:", ""]
    for run_name, c in res["runs"].items():
        lines.append(f"- {run_name}: {', '.join(c['cli']) or 'none'}")
    return "\n".join(lines)


def results(check: bool) -> None:
    res = score()
    body = json.dumps(res, indent=1) + "\n"
    md = render(res) + "\n"
    if check:
        old = (OUT / "results.json").read_text(), (OUT / "RESULTS.md").read_text()
        same = old == (body, md)
        print("results are up to date" if same else "out of date: run results")
        sys.exit(0 if same else 1)
    (OUT / "results.json").write_text(body)
    (OUT / "RESULTS.md").write_text(md)
    print(md)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    a = sub.add_parser("ask")
    a.add_argument("--provider", choices=["claude-cli", "codex"], required=True)
    a.add_argument("--model", choices=RUNS, required=True)
    a.add_argument("--workers", type=int, default=4)
    sub.add_parser("decide")
    w = sub.add_parser("web")
    w.add_argument("--port", type=int, default=PORT)
    r = sub.add_parser("results")
    r.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.command == "ask":
        ask(args.provider, args.model, args.workers)
    elif args.command == "decide":
        decide()
    elif args.command == "web":
        measure.serve(args.port, measure.cards(facts()))
    else:
        results(args.check)


if __name__ == "__main__":
    main()
