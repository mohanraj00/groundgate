"""Download, check and pin the 90 members of the 1.0 release set (#748).

The script reads ``members.json``, downloads the PDF of each member into ``--out`` (local work
storage, not the repository), checks it, reads its text with ``groundgate.read``, and writes
``manifest.json`` and ``source_checks.json`` here:

    uv run python bench/release1/sources.py --out DIR --meta CACHE --fetch   # download first
    uv run python bench/release1/sources.py --out DIR --meta CACHE           # use the files

``--meta`` is the metadata cache of ``select.py``. The MODS record of a govinfo package gives
its PDF address and its page count. The script refuses a list whose download the owner has not
approved. If ``manifest.json`` already pins a member, a changed PDF or a changed reader text
fails the run before it writes a file. ``--repin`` is only for a new freeze that the owner
approves.

The checks are the identity, the page count, the text, the language and the printed notices.
A member with a problem goes on hold. The split comes from a seed that is the SHA-256 of the
source digests in member order, so nobody chooses it after the download. The script makes no
model call, reads no label and draws no slot.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KINDS = ("minerals", "opinions", "reports")
CALIBRATION = 5  # members of each kind for the operating point; the others are held-out
NS = {"m": "http://www.loc.gov/mods/v3"}
NOTICE = re.compile(r"copyright|©|all rights reserved|reproduc|permission of", re.I)
ENGLISH = ("the", "of", "and", "to", "for")
SERIES = "U.S. Geological Survey, Mineral Commodity Summaries, February 2026"
LICENSE = {
    "minerals": "USGS-authored or produced information: US public domain (USGS copyrights and "
    "credits page). A notice match marks material of another owner.",
    "opinions": "A US court opinion: a government edict, with no copyright.",
    "reports": "A report of a committee of Congress: a US government work (17 U.S.C. 105).",
}

_spec = importlib.util.spec_from_file_location("reg_sources", HERE.parent / "regulatory/sources.py")
assert _spec and _spec.loader
regulatory = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = regulatory
_spec.loader.exec_module(regulatory)
sha, split_seed, split, reader_code = (
    regulatory.sha, regulatory.split_seed, regulatory.split, regulatory.reader_code
)  # fmt: skip


def pdf_url(kind: str, member: dict[str, Any], meta: Path) -> str:
    if kind == "minerals":
        return str(member["url"])
    root = ET.fromstring((meta / f"{member['package']}.mods.xml").read_bytes())
    for url in root.iterfind(".//m:location/m:url", NS):  # in the granule for an opinion
        if url.get("displayLabel") == "PDF rendition" and url.text:
            return url.text.strip()
    raise ValueError(f"{member['package']}: the MODS record has no PDF rendition")


def fetch(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "groundgate-bench/1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read(), r.headers.get("ETag", "")


def identity(kind: str, member: dict[str, Any], head: str, text: str = "") -> str | None:
    """A problem if the first page does not name this member, else None.

    A USGS chapter names the series in the line at the end of its last page."""
    flat = " ".join(head.split()).casefold()
    if kind == "minerals":
        if SERIES not in " ".join(text.split()):
            return f"the text does not name the series ({SERIES})"
        if not all(w in flat for w in member["commodity"].split("-")):
            return f"the first page does not name {member['commodity']}"
    elif kind == "opinions":
        year, number = member["case"].split("-")
        if not re.search(rf"\b{year}\s*-\s*0*{int(number)}\b", flat):
            return f"the first page does not give the docket {member['case']}"
    else:
        congress, number = re.fullmatch(r"CRPT-(\d+)[hs]rpt(\d+)", member["package"]).groups()  # type: ignore[union-attr]
        if not re.search(rf"\b{congress}\s*[-\u2013\u2014]\s*{number}\b", flat):
            return f"the first page does not give the report number {congress}-{number}"
    return None


def check(kind: str, member: dict[str, Any], raw: bytes, etag: str | None) -> dict[str, Any]:
    from groundgate.read import read

    got = read(f"{member['package'].removesuffix('.pdf')}.pdf", data=raw)
    text = got.text
    layout = got.layout
    pages = len(layout.pages) if layout else 0
    # The page offsets count UTF-8 bytes.
    first = layout.pages[0] if layout and layout.pages else None
    head = text.encode()[first.start : first.end].decode() if first else ""
    tokens = re.findall(r"[a-z]+", text.lower())
    english = {w: tokens.count(w) for w in ENGLISH}
    # A match is a place for a person to read: a source can name copyright in its own text.
    notices = [" ".join(text[max(0, m.start() - 60) : m.end() + 60].split())
               for m in NOTICE.finditer(text)]  # fmt: skip
    problems = []
    if not raw.startswith(b"%PDF-"):
        problems.append("not a PDF")
    if kind == "minerals":
        if len(raw) != member["bytes"]:
            problems.append(f"{len(raw)} bytes, not the {member['bytes']} of the selection")
        if etag is not None and etag != member["etag"]:
            problems.append(f"the entity tag is {etag}, not {member['etag']}")
    elif pages != member["pages"]:
        problems.append(f"{pages} pages, not the {member['pages']} of the MODS record")
    if why := identity(kind, member, head, text):
        problems.append(why)
    if not text.strip():
        problems.append("no text")
    if min(english.values()) == 0:
        problems.append("not English text")
    return {
        "pages": pages,
        "text_characters": len(text),
        "text_sha256": sha(text.encode()),
        "warnings": len(got.warnings),
        "language": {"language": "English", "word_counts": english},
        "notice": {"matches": len(notices), "examples": notices[:5]},
        "problems": problems,
        "text": text,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True, help="local work storage for the PDFs")
    ap.add_argument("--meta", type=Path, required=True, help="the metadata cache of select.py")
    ap.add_argument("--fetch", action="store_true", help="download each member first")
    ap.add_argument("--repin", action="store_true", help="replace the pins of manifest.json")
    args = ap.parse_args(argv)
    if args.out.resolve().is_relative_to(ROOT):
        ap.error("--out must be outside the repository")
    body = json.loads((HERE / "members.json").read_text())
    if not body.get("download_approved"):
        ap.error("the owner has not approved the download of this member list")
    review = body.get("notice_review", {})
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = HERE / "manifest.json"
    old_manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    pinned = {d["id"]: d for d in old_manifest.get("documents", [])}
    docs, checks, files, changed = [], [], {}, []
    for kind in KINDS:
        for member in body["kinds"][kind]["members"]:
            ident = member["package"].removesuffix(".pdf")
            path = args.out / kind / f"{ident}.pdf"
            url = pdf_url(kind, member, args.meta)
            etag = None
            if args.fetch:
                raw, etag = fetch(url)
                time.sleep(1)
            else:
                raw = path.read_bytes()
            c = check(kind, member, raw, etag)
            text = c.pop("text")
            old = pinned.get(ident)
            if old and (old["source_sha256"], old["text_sha256"]) != (sha(raw), c["text_sha256"]):
                changed.append(ident)
            files[path] = raw
            files[path.with_suffix(".txt")] = text.encode()
            c["notice"]["review"] = review.get(ident) if c["notice"]["matches"] else None
            checks.append({"id": ident, "kind": kind, "source": url, **c})
            docs.append({
                "id": ident,
                "kind": kind,
                "split": None,
                "selection_status": "frozen_member" if not c["problems"] else "on_hold",
                "source": url,
                "source_bytes": len(raw),
                "source_sha256": sha(raw),
                "pages": c["pages"],
                "download_approved": body["download_approved"],
                "source_retention": "original PDF in local work storage; not committed",
                "license": LICENSE[kind],
                "text_sha256": c["text_sha256"],
            })  # fmt: skip
    if changed and not args.repin:
        print(f"the source or the reader text is not the pinned one: {' '.join(changed)}")
        print("nothing was written; give --repin only for a new freeze that the owner approved")
        return 1
    for path, raw in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    members = [d for d in docs if d["selection_status"] == "frozen_member"]
    seed = split_seed([d["source_sha256"] for d in members])
    for kind in KINDS:
        sides = split([d["id"] for d in members if d["kind"] == kind], seed, CALIBRATION)
        for d in members:
            d["split"] = sides.get(d["id"], d["split"])
    manifest = {
        "format": "release1-sources/1",
        "claim": "#748",
        "selection_complete": len(members) == len(docs),
        "split_rule": {
            "seed": seed,
            "seed_method": "sha256 over the source_sha256 of the members in member order "
            "(minerals, opinions, reports), one a line with LF",
            "rule": f"in each kind, the {CALIBRATION} ids with the lowest sha256(seed LF id) in "
            "hex are calibration; the others are heldout",
        },
        "reader_text": {
            "reader": "groundgate.read, PDF",
            "code_sha256": reader_code(),
            "code_digest_method": 'sha256 over sorted src/groundgate/read/*.py lines "name NUL '
            'sha256(file) LF"',
            "note": "Text files stay in local work storage with the PDFs. Only their hashes are "
            "published.",
        },
        "documents": docs,
    }
    # a rerun keeps the pins of labels.py and passes.py
    manifest.update({k: v for k, v in old_manifest.items() if k in ("slots", "labels")})
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    out = {"format": "release1-source-checks/1", "documents": checks}
    (HERE / "source_checks.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    held = [d["id"] for d in docs if d["selection_status"] != "frozen_member"]
    unread = [c["id"] for c in checks if c["notice"]["matches"] and not c["notice"]["review"]]
    print(f"{len(members)} members, {len(held)} on hold {held}, seed {seed}")
    print(f"{len(unread)} members with notice matches and no review {unread}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
