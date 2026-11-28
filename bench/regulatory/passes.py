"""The blind label passes of the regulatory family (#641).

The owner approved this method on 2026-11-17:

- Pass ``a`` is Claude Code (``claude -p``, no tools). Pass ``b`` is Codex (``codex exec``,
  read-only sandbox, in an empty folder). Each pass gets, for each part, the slots and the
  reader text and the XML of each section that a slot names. Nothing else goes in.
- Each slot that a pass marks absent gets a second blind check by a new agent of the other
  harness. The check asks only for that slot, and says nothing of the passes.
- ``compare`` writes the agreements and the disagreements. The owner decides each
  disagreement in ``bench/label``.

    uv run python bench/regulatory/passes.py run --pass a --sources DIR --work WORK
    uv run python bench/regulatory/passes.py run --pass b --sources DIR --work WORK
    uv run python bench/regulatory/passes.py run --pass absence --sources DIR --work WORK
    uv run python bench/regulatory/passes.py compare --work WORK
    uv run python bench/label/decide.py --sources DIR --work WORK
    uv run python bench/regulatory/passes.py seal --work WORK

Each command takes ``--set DIR`` for another set folder of the family, for example
``bench/regulatory2``. WORK is local work storage. The answers stay there until the owner
decides the disagreements; then the labels are sealed in the set folder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CLAUDE_MODEL = "claude-opus-5-5"
CODEX_MODEL = "gpt-6.1-sol"
TIMEOUT = 1800
SYSTEM = "You label values in regulation texts. Answer only from the text you are given."

ANSWER = """\
Answer with one JSON object and nothing else:

{"slots": [{"slot": "r001", "status": "value" or "absent", "value": ..., "unit": ...,
  "quote": "...", "note": "..."}]}

Give one entry for each slot, in the order of the slots.

- "absent": the named section does not state the value. Then "value", "unit" and "quote"
  are null. Never guess and never calculate a value.
- A passage: "value" is the exact text from the reader text of the section, with the same
  words and the same punctuation. "quote" is null.
- A number: "value" is a string of digits with an optional "-" and ".", with no thousands
  separators and no currency sign. "unit" is the unit or the currency that the column
  header or the cell states (for example "USD", "percent", "hours"), or null.
  "quote" is the exact cell text.
- A date: "value" is "YYYY-MM-DD". "quote" is the exact text that states the date.
- A record: "value" is a list with one object for each body row, in table order. Each
  object has one member for each named column header, with the exact cell text, or null
  for an empty cell. "quote" is null.
- "note" is a short reason when the request is not clear, or null.
"""


def section_map(raw: bytes) -> dict[str, ET.Element]:
    """Each section of a part by its heading, as slots.py names it."""
    sys.path.insert(0, str(HERE))
    from slots import head, sections

    return {head(sec): sec for sec in sections(ET.fromstring(raw))}


def section_block(sec: ET.Element) -> str:
    from groundgate.read.markup import xml_text

    xml = ET.tostring(sec, encoding="unicode")
    text = xml_text(xml.encode())
    return f"Reader text:\n<<<\n{text}\n>>>\n\nXML:\n<<<\n{xml}\n>>>"


def slot_line(s: dict[str, Any], schema: dict[str, Any]) -> str:
    desc = schema[s["field"]]["description"]
    return f"- {s['slot']} ({s['kind']}): {s['request_text']}\n  Field rule: {desc}"


def prompt(slots: list[dict[str, Any]], raw: bytes, schema: dict[str, Any], citation: str) -> str:
    secs = section_map(raw)
    names: list[str] = []
    for s in slots:
        name = s["request"]["section"]
        if name not in names:
            names.append(name)
    parts = [
        f"The slots below ask for values in {citation}, "
        "one regulation text. Each slot names one section. Read only the text of that section "
        "below.",
        "Slots:\n" + "\n".join(slot_line(s, schema) for s in slots),
        ANSWER,
    ]
    for name in names:
        parts.append(f"=== Section: {name}\n\n{section_block(secs[name])}")
    return "\n\n".join(parts)


class NotPinned(Exception):
    """A source file that is not the pinned source."""


def xml_prompt(
    sources: Path, slots: list[dict[str, Any]], schema: dict[str, Any], doc: dict[str, Any]
) -> str:
    """The prompt for the slots of one part, from the pinned XML of the part."""
    raw = (sources / f"{slots[0]['id']}.xml").read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != doc["source_sha256"]:
        raise NotPinned("the XML is not the pinned source")
    return prompt(slots, raw, schema, doc["citation"])


def claude(text: str, system: str = SYSTEM) -> str:
    cmd = [
        "claude", "-p", "--model", CLAUDE_MODEL, "--tools", "", "--strict-mcp-config",
        "--disable-slash-commands", "--setting-sources", "", "--no-session-persistence",
        "--system-prompt", system, "--output-format", "json",
    ]  # fmt: skip
    proc = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=TIMEOUT)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-300:] or proc.stdout[-300:])
    return str(json.loads(proc.stdout)["result"])


def codex(text: str, system: str = SYSTEM) -> str:
    with tempfile.TemporaryDirectory(prefix="groundgate-label-") as empty:
        out = Path(empty) / "answer.txt"
        cmd = [
            "codex", "exec", "-m", CODEX_MODEL, "--ephemeral", "--ignore-user-config",
            "--ignore-rules", "--skip-git-repo-check", "-s", "read-only", "-C", empty,
            "-c", "project_doc_max_bytes=0", "-c", 'model_reasoning_effort="high"',
            "-o", str(out), "-",
        ]  # fmt: skip
        proc = subprocess.run(
            cmd,
            input=system + "\n\nDo not run commands and do not read files.\n\n" + text,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(proc.stderr[-300:])
        return out.read_text()


def parse(reply: str) -> dict[str, Any]:
    start, end = reply.find("{"), reply.rfind("}")
    got = json.loads(reply[start : end + 1])
    return {e["slot"]: e for e in got["slots"]}


DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def problem(kind: str, e: Any) -> str | None:
    """Why an answer does not have the shape of the answer rules, or None."""
    if not isinstance(e, dict) or e.get("status") not in ("value", "absent"):
        return "the status is not value or absent"
    if e["status"] == "absent":
        return None
    v = e.get("value")
    if kind == "passage" and not (isinstance(v, str) and v.strip()):
        return "a passage needs a text value"
    if kind == "number" and not (isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v.strip())):
        return "a number needs a string of digits"
    if kind == "date":
        try:
            ok = isinstance(v, str) and bool(DATE.fullmatch(v)) and bool(date.fromisoformat(v))
        except ValueError:
            ok = False
        if not ok:
            return "a date needs a real YYYY-MM-DD value"
    if kind == "record":
        if not isinstance(v, list) or not v:
            return "a record needs a list of rows"
        for r in v:
            if not isinstance(r, dict) or not r:
                return "each row of a record is an object"
            if any(not isinstance(c, (str, type(None))) for c in r.values()):
                return "each cell is text or null"
    return None


def load(work: Path, name: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in sorted((work / name).glob("*.json")):
        out.update(json.loads(f.read_text())["answers"])
    return out


def run(
    args: argparse.Namespace,
    prompt_of: Callable[..., str] = xml_prompt,
    system: str = SYSTEM,
) -> int:
    """Run a pass. Another set family gives its own ``prompt_of`` and ``system``."""
    here = getattr(args, "set", None) or HERE
    data = json.loads((here / "slots.json").read_text())
    manifest = {d["id"]: d for d in json.loads((here / "manifest.json").read_text())["documents"]}
    schema, slots = data["schema"], data["slots"]
    jobs: list[tuple[str, str, list[dict[str, Any]]]] = []  # (harness, out name, slots)
    if args.pass_ in ("a", "b"):
        by: dict[str, list[dict[str, Any]]] = {}
        for s in slots:
            by.setdefault(s["id"], []).append(s)
        harness = "claude" if args.pass_ == "a" else "codex"
        jobs = [(harness, f"pass-{args.pass_}/{i}", ss) for i, ss in by.items()]
    else:
        a, b = load(args.work, "pass-a"), load(args.work, "pass-b")
        for s in slots:
            # an absence of pass a goes to codex, an absence of pass b goes to claude
            if a.get(s["slot"], {}).get("status") == "absent":
                jobs.append(("codex", f"absence-codex/{s['slot']}", [s]))
            if b.get(s["slot"], {}).get("status") == "absent":
                jobs.append(("claude", f"absence-claude/{s['slot']}", [s]))
    if args.ids:
        jobs = [j for j in jobs if j[2][0]["id"] in args.ids]

    def one(job: tuple[str, str, list[dict[str, Any]]]) -> str:
        harness, name, ss = job
        path = args.work / f"{name}.json"
        if path.exists():
            return f"{name}: kept"
        try:
            text = prompt_of(args.sources, ss, schema, manifest[ss[0]["id"]])
        except NotPinned as e:
            return f"{name}: {e}"
        for attempt in range(2):
            try:
                reply = (claude if harness == "claude" else codex)(text, system)
                answers = parse(reply)
                if set(answers) != {s["slot"] for s in ss}:
                    raise ValueError("the reply does not answer each slot")
                for s in ss:
                    why = problem(s["kind"], answers[s["slot"]])
                    if why:
                        raise ValueError(f"{s['slot']}: {why}")
                break
            except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as e:
                if attempt == 1:
                    return f"{name}: failed ({str(e)[:200]})"
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"harness": harness, "model": CLAUDE_MODEL if harness == "claude" else CODEX_MODEL}
        path.write_text(json.dumps({**rec, "answers": answers, "reply": reply}, indent=1) + "\n")
        return f"{name}: {len(answers)} answers"

    with ThreadPoolExecutor(args.workers) as pool:
        for line in pool.map(one, jobs):
            print(line, flush=True)
    return 0


def norm(kind: str, e: dict[str, Any] | None) -> Any:
    """The normal form that two answers must share to agree."""
    if e is None:
        return ("missing",)
    if e.get("status") == "absent":
        return ("absent",)
    v = e.get("value")
    if kind == "passage":
        return " ".join(str(v).split())
    if kind == "number":
        try:
            n = Decimal(str(v).replace(",", ""))
        except InvalidOperation:
            return ("bad", str(v))
        unit = str(e.get("unit") or "").casefold().strip()
        unit = {"$": "usd", "dollars": "usd", "%": "percent"}.get(unit, unit)
        return (n.normalize(), unit)
    if kind == "date":
        return str(v)
    if isinstance(v, list):
        return [
            {k: None if c is None else " ".join(str(c).split()) for k, c in r.items()}
            if isinstance(r, dict)
            else r
            for r in v
        ]
    return ("bad", str(v))


def compare(args: argparse.Namespace) -> int:
    here = getattr(args, "set", None) or HERE
    slots = json.loads((here / "slots.json").read_text())["slots"]
    a, b = load(args.work, "pass-a"), load(args.work, "pass-b")
    ca, cb = load(args.work, "absence-claude"), load(args.work, "absence-codex")
    rows, counts = [], {"agree": 0, "disagree": 0, "invalid": 0, "missing": 0}
    for s in slots:
        k, x, y = s["kind"], a.get(s["slot"]), b.get(s["slot"])
        na, nb = norm(k, x), norm(k, y)
        # an absence of pass a needs the codex check, an absence of pass b the claude check
        need = [cb.get(s["slot"])] if na == ("absent",) else []
        need += [ca.get(s["slot"])] if nb == ("absent",) else []
        checks = [c for c in need if c is not None]
        if ("missing",) in (na, nb) or len(checks) < len(need):
            state = "missing"
        elif any(problem(k, e) for e in (x, y, *checks)):
            state = "invalid"
        elif na == nb and all(norm(k, c) == na for c in checks):
            state = "agree"
        else:
            state = "disagree"
        counts[state] += 1
        rows.append({"slot": s["slot"], "state": state, "a": x, "b": y, "absence_checks": checks})
    (args.work / "compare.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(counts))
    for r in rows:
        if r["state"] != "agree":
            print(r["slot"], r["state"])
    return 0


def chosen(row: dict[str, Any], d: dict[str, Any]) -> Any:
    """The answer that an owner decision picks."""
    if d["choice"] in ("a", "b"):
        return row[d["choice"]]
    if d["choice"] == "absent":
        return {"status": "absent"}
    return {"status": "value", "value": d["value"], "unit": d["unit"]}


def seal(args: argparse.Namespace) -> int:
    """Write labels.json from the agreements and the owner decisions, and its digest to the
    manifest. Refuses while a slot has no answer or no decision, and refuses a second seal of a
    set with a ``members.json``."""
    here = getattr(args, "set", None) or HERE
    mpath = here / "manifest.json"
    if (here / "members.json").exists() and "labels" in json.loads(mpath.read_text()):
        print(f"{here}: the labels are already sealed")
        return 1
    slots = json.loads((here / "slots.json").read_text())["slots"]
    rows = {r["slot"]: r for r in json.loads((args.work / "compare.json").read_text())}
    path = args.work / "decisions.json"
    decided = json.loads(path.read_text()) if path.exists() else {}
    labels, open_ = [], []
    for s in slots:
        row = rows.get(s["slot"])
        if row is None or row["state"] == "missing":
            open_.append(s["slot"])
            continue
        if row["state"] == "agree":
            got, how = row["a"], "agree"
        elif s["slot"] in decided:
            got, how = chosen(row, decided[s["slot"]]), "owner"
            if problem(s["kind"], got):
                open_.append(s["slot"])
                continue
        else:
            open_.append(s["slot"])
            continue
        absent = got.get("status") == "absent"
        labels.append({
            "slot": s["slot"], "id": s["id"], "split": s["split"], "field": s["field"],
            "status": "absent" if absent else "value",
            "value": None if absent else got.get("value"),
            "unit": None if absent else got.get("unit"), "decided_by": how,
        })  # fmt: skip
    if open_:
        print(f"{len(open_)} slots are open: {' '.join(open_)}")
        return 1
    raw = (json.dumps({"format": "regulatory-labels/1", "labels": labels}, indent=1,
                      ensure_ascii=False) + "\n").encode()  # fmt: skip
    (here / "labels.json").write_bytes(raw)
    manifest = json.loads(mpath.read_text())
    manifest["labels"] = {
        "file": "labels.json",
        "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "sealed": time.strftime("%Y-%m-%d"),
        "agree": sum(x["decided_by"] == "agree" for x in labels),
        "owner": sum(x["decided_by"] == "owner" for x in labels),
    }
    mpath.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(manifest["labels"]))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--pass", dest="pass_", choices=["a", "b", "absence"], required=True)
    r.add_argument("--sources", type=Path, required=True)
    r.add_argument("--work", type=Path, required=True)
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--ids", nargs="*")
    r.add_argument("--set", type=Path, help="the set folder (default: this folder)")
    for name in ("compare", "seal"):
        c = sub.add_parser(name)
        c.add_argument("--work", type=Path, required=True)
        c.add_argument("--set", type=Path, help="the set folder (default: this folder)")
    args = ap.parse_args(argv)
    return {"run": run, "compare": compare, "seal": seal}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
