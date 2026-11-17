"""Download, check and pin the 14 CFR parts of the regulatory family (#641, #686).

Each member is one CFR part at one point in time: the XML of the eCFR versioner API for the
date ``DATE``. The script downloads each part into ``--out`` (local work storage, not the
repository), checks it, reads its text with ``groundgate.read``, and writes the members of
``manifest.json`` and ``source_checks.json``:

    uv run python bench/regulatory/sources.py --out DIR            # use the files in DIR
    uv run python bench/regulatory/sources.py --out DIR --fetch    # download them first

If ``manifest.json`` already pins a part, a changed XML or a changed reader text fails the run
before it writes a file, so a rerun cannot change the members or the split. ``--repin`` is only
for a new freeze that the owner approves. The script also writes the reader text of each part
next to its XML, as ``<id>.txt``.

The checks are the identity (the part number and the title in the XML), the section count,
the text, the language and the printed notices. The split comes from a seed that is the
SHA-256 of the source digests in member order, so nobody chooses it after the download. The
script makes no model call and reads no label.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DATE = "2026-11-12"
API = "https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{title}.xml?part={part}"
PAGE = "https://www.ecfr.gov/current/title-{title}/part-{part}"
CALIBRATION = 5  # parts for profile calibration; the others are held-out

# (title, part, the words that the part heading must hold, the section count of the list
# that the owner approved on 2026-11-17 in #641)
MEMBERS: tuple[tuple[int, int, str, int], ...] = (
    (7, 800, "GENERAL REGULATIONS", 119),
    (8, 106, "USCIS FEE SCHEDULE", 6),
    (9, 391, "FEES AND CHARGES FOR INSPECTION SERVICES", 5),
    (10, 170, "FEES FOR FACILITIES, MATERIALS", 15),
    (10, 171, "ANNUAL FEES FOR REACTOR LICENSES", 16),
    (14, 187, "FEES", 9),
    (19, 24, "CUSTOMS FINANCIAL AND ACCOUNTING PROCEDURE", 28),
    (33, 402, "TARIFF OF TOLLS", 14),
    (36, 71, "RECREATION FEES", 15),
    (37, 201, "GENERAL PROVISIONS", 38),
    (46, 401, "GREAT LAKES PILOTAGE REGULATIONS", 48),
    (46, 404, "GREAT LAKES PILOTAGE RATEMAKING", 13),
    (49, 107, "HAZARDOUS MATERIALS PROGRAM PROCEDURES", 76),
    (49, 1002, "FEES", 3),
)

_NOTICE = re.compile(r"copyright|©|all rights reserved|reproduc|permission of", re.I)
# I read each match on 2026-11-17 (all of them, except the first 40 of the 789 in 37 CFR 201,
# the rules of the Copyright Office).
NOTICE_REVIEW = (
    "No notice of the publisher in the source. Each match is regulation text, for example a "
    "rule on copies of certificates or the address of the Copyright Office."
)
_ENGLISH = ("the", "of", "and", "to", "for")


def member_id(title: int, part: int) -> str:
    return f"cfr-{title}-{part}"


def sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def fetch(title: int, part: int) -> bytes:
    url = API.format(date=DATE, title=title, part=part)
    req = urllib.request.Request(
        url, headers={"User-Agent": "groundgate-bench/1", "Accept-Encoding": "gzip"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return raw


def split_seed(digests: list[str]) -> str:
    """The seed of the split: the SHA-256 of the source digests in member order, one a line."""
    return sha("".join(d + "\n" for d in digests).encode())


def split(ids: list[str], seed: str) -> dict[str, str]:
    """``calibration`` for the CALIBRATION ids with the lowest SHA-256 of seed and id, else
    ``heldout``."""
    order = sorted(ids, key=lambda i: hashlib.sha256(f"{seed}\n{i}".encode()).hexdigest())
    return {i: "calibration" if n < CALIBRATION else "heldout" for n, i in enumerate(order)}


def reader_code() -> str:
    lines = []
    for f in sorted((ROOT / "src/groundgate/read").glob("*.py")):
        lines.append(f"{f.name}\0{hashlib.sha256(f.read_bytes()).hexdigest()}\n")
    return sha("".join(lines).encode())


def check(title: int, part: int, words: str, listed: int, raw: bytes) -> dict:
    from groundgate.read import read

    root = ET.fromstring(raw)
    head = " ".join("".join(root.find("HEAD").itertext()).split())  # type: ignore[union-attr]
    meta = root.get("hierarchy_metadata", "{}")
    while "&" in meta:  # the eCFR escapes this attribute one or two times
        meta = html.unescape(meta)
    citation = json.loads(meta).get("citation")
    sections = [d for d in root.iter() if d.get("TYPE") == "SECTION"]
    tables = sum(1 for _ in root.iter("TABLE")) + sum(1 for _ in root.iter("GPOTABLE"))
    text = read(f"{member_id(title, part)}.xml", data=raw).text
    tokens = re.findall(r"[a-z]+", text.lower())
    english = {w: tokens.count(w) for w in _ENGLISH}
    # A match is a place for a person to read: CFR text often names copyright or reproduction.
    notices = [" ".join(text[max(0, m.start() - 60) : m.end() + 60].split())
               for m in _NOTICE.finditer(text)]  # fmt: skip
    problems = []
    if root.tag != "DIV5" or root.get("TYPE") != "PART" or root.get("N") != str(part):
        problems.append("the root is not this part")
    if citation != f"{title} CFR Part {part}":
        problems.append(f"the citation is {citation}")
    if not head.startswith(f"PART {part}—") or words not in head:
        problems.append(f"the heading is {head}")
    if len(sections) != listed:
        problems.append(f"{len(sections)} sections, not {listed}")
    if not text.strip():
        problems.append("no text")
    if min(english.values()) == 0:
        problems.append("not English text")
    return {
        "identity": {"citation": citation, "heading": head, "date": DATE},
        "sections": len(sections),
        "sections_listed": listed,
        "tables": tables,
        "text_characters": len(text),
        "text_sha256": sha(text.encode()),
        "language": {"language": "English", "word_counts": english},
        "notice": {"matches": len(notices), "examples": notices[:3], "review": NOTICE_REVIEW},
        "problems": problems,
        "text": text,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True, help="local work storage for the XML")
    ap.add_argument("--fetch", action="store_true", help="download each part first")
    ap.add_argument(
        "--repin",
        action="store_true",
        help="replace the pins of manifest.json; without it a changed source or text fails",
    )
    args = ap.parse_args(argv)
    if args.out.resolve().is_relative_to(ROOT) and ".cache" not in args.out.parts:
        ap.error("--out must be outside the repository or under an ignored .cache folder")
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = HERE / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    pinned = {d["id"]: d for d in manifest.get("documents", [])}
    docs, checks, files, changed = [], [], {}, []
    for title, part, words, listed in MEMBERS:
        path = args.out / f"{member_id(title, part)}.xml"
        if args.fetch:
            raw = fetch(title, part)
            time.sleep(1)
        else:
            raw = path.read_bytes()
        c = check(title, part, words, listed, raw)
        text = c.pop("text")
        old = pinned.get(member_id(title, part))
        if old and (old["source_sha256"], old["text_sha256"]) != (sha(raw), c["text_sha256"]):
            changed.append(member_id(title, part))
        files[path] = raw
        files[path.with_suffix(".txt")] = text.encode()
        url = API.format(date=DATE, title=title, part=part)
        checks.append({"id": member_id(title, part), "source": url, **c})
        docs.append({
            "id": member_id(title, part),
            "kind": "regulatory",
            "split": None,
            "selection_status": "frozen_member" if not c["problems"] else "on_hold",
            "citation": c["identity"]["citation"],
            "heading": c["identity"]["heading"],
            "source": url,
            "page": PAGE.format(title=title, part=part),
            "point_in_time": DATE,
            "source_bytes": len(raw),
            "source_sha256": sha(raw),
            "download_approved": "2026-11-17",
            "source_retention": "original XML in local work storage; not committed",
            "terms_group": "A",
            "license": "US government work (17 U.S.C. 105): no copyright in the United States.",
            "text_sha256": c["text_sha256"],
        })  # fmt: skip
    if changed and not args.repin:
        print(f"the source or the reader text is not the pinned one: {' '.join(changed)}")
        print("nothing was written; give --repin only for a new freeze that the owner approved")
        return 1
    for path, raw in files.items():
        path.write_bytes(raw)
    members = [d for d in docs if d["selection_status"] == "frozen_member"]
    seed = split_seed([d["source_sha256"] for d in members])
    sides = split([d["id"] for d in members], seed)
    for d in members:
        d["split"] = sides[d["id"]]
    manifest["split_rule"] = {
        "seed": seed,
        "seed_method": "sha256 over the source_sha256 of the members in member order, "
        "one a line with LF",
        "rule": f"the {CALIBRATION} ids with the lowest sha256(seed LF id) in hex are "
        "calibration; the others are heldout",
    }
    manifest["reader_text"] = {
        "reader": "groundgate.read (spec 0.12), XML",
        "code_sha256": reader_code(),
        "code_digest_method": 'sha256 over sorted src/groundgate/read/*.py lines "name NUL '
        'sha256(file) LF"',
        "note": "Text files stay in local work storage with the XML. Only their hashes are "
        "published.",
    }
    manifest["documents"] = docs
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    (HERE / "source_checks.json").write_text(
        json.dumps(
            {"format": "regulatory-source-checks/1", "date": DATE, "documents": checks},
            indent=1,
            ensure_ascii=False,
        )
        + "\n"
    )
    held = [d["id"] for d in docs if d["selection_status"] != "frozen_member"]
    print(f"{len(members)} members, {len(held)} on hold {held}, seed {seed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
