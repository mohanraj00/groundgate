"""The held-out set of #140: FDA drug labels whose Dosage and Administration section has a
subsection for adults and one for pediatric patients, for a keyed string field. The plan is on
#140, made before anyone read the set.

    uv run python bench/strings/strings.py pick   # sources.json, selection-log.json
    uv run python bench/strings/strings.py text   # docs/<id>.txt

The walk reuses the rules of set 2 (bench/pick.py): the generic names of its pinned Part D file,
here in alphabetical order, and its label rule. It skips each drug that a bench set already holds.
A label counts when a section 2 subsection title, at any depth, holds "adult" and another holds
"pediatric". It stops at 10 labels. Labels and searches are cached in .cache, out of git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
BENCH = HERE.parent
sys.path.insert(0, str(BENCH))
import fetch  # noqa: E402  (bench/fetch.py)
import pick  # noqa: E402  (bench/pick.py)

COUNT = 10
pick.CACHE = HERE / ".cache"  # pick.get downloads here, not into set 2's cache


def held() -> set[str]:
    """The drugs that a bench set already holds: the v0.1 drugs, and each "fda-<drug>" id in a
    file of bench/ that git tracks."""
    import subprocess

    files = subprocess.run(
        ["git", "ls-files", "*.json", "*.py", "*.md"],
        cwd=BENCH,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    out = set(pick.V01_DRUGS)
    for name in files:
        path = BENCH / name
        if path.is_relative_to(HERE):
            continue
        out |= set(re.findall(r"\bfda-([a-z]+)", path.read_text(encoding="utf-8", errors="ignore")))
    return out


def titles(data: bytes) -> list[str]:
    """The subsection titles of section 2, at any depth."""
    root = ET.fromstring(data)
    for sec in root.iter(f"{fetch.HL7}section"):
        code = sec.find(f"{fetch.HL7}code")
        if code is not None and code.get("code") == pick.DOSAGE:
            return [
                " ".join("".join(t.itertext()).split())
                for sub in sec.iter(f"{fetch.HL7}section")
                if sub is not sec and (t := sub.find(f"{fetch.HL7}title")) is not None
            ]
    return []


def select() -> None:
    skip = held()
    log: list[dict[str, Any]] = []
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in sorted(pick.ranked_generics(), key=str.lower):
        if len(chosen) == COUNT:
            break
        base = pick.base_word(name)
        entry: dict[str, Any] = {"name": name}
        log.append(entry)
        if "/" in name:
            entry["skip"] = "combination"
        elif base in skip:
            entry["skip"] = "a bench set holds it"
        elif base in seen:
            entry["skip"] = "same first word taken"
        if "skip" in entry:
            continue
        seen.add(base)
        label, why = pick.find_label(name)
        if label is None:
            entry["skip"] = why
            continue
        data = (pick.CACHE / f"spl-{label['setid']}.xml").read_bytes()
        found = titles(data)
        adult = any("adult" in t.lower() for t in found)
        child = any("pediatric" in t.lower() for t in found)
        entry["setid"] = label["setid"]
        if not (adult and child):
            entry["skip"] = "section 2 has no adult and pediatric subsections"
            continue
        chosen.append(
            {
                "id": f"strings-{base}",
                "kind": "fda",
                "url": label["url"],
                "sha256": label["sha256"],
                "select": {"sections": [pick.DOSAGE, pick.STRENGTHS]},
                "source": label["title"],
            }
        )
        entry["taken"] = True
    if len(chosen) < COUNT:
        raise SystemExit(f"only {len(chosen)} labels found")
    (HERE / "sources.json").write_text(json.dumps({"sources": chosen}, indent=1) + "\n")
    (HERE / "selection-log.json").write_text(json.dumps(log, indent=1) + "\n")
    print(f"{len(chosen)} labels from {len(log)} names")


def text() -> None:
    """docs/<id>.txt from each pinned label, sections 2 and 3, as set 2 writes them."""
    (HERE / "docs").mkdir(exist_ok=True)
    for src in json.loads((HERE / "sources.json").read_text())["sources"]:
        setid = src["url"].rsplit("/", 1)[1].removesuffix(".xml")
        data = (pick.CACHE / f"spl-{setid}.xml").read_bytes()
        if hashlib.sha256(data).hexdigest() != src["sha256"]:
            raise SystemExit(f"{src['id']}: the cached label is not the pinned one")
        body = fetch.spl_sections(data, src["select"]["sections"])
        (HERE / "docs" / f"{src['id']}.txt").write_text(body, encoding="utf-8")
    print("wrote docs")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pick")
    sub.add_parser("text")
    args = ap.parse_args()
    select() if args.cmd == "pick" else text()


if __name__ == "__main__":
    main()
