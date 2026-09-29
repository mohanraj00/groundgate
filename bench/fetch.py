"""Download the benchmark sources, check their pinned hashes, and write bench/docs/<id>.txt.

    uv run python bench/fetch.py          # verify and regenerate the text
    uv run python bench/fetch.py --pin    # record hashes for sources that have none

All sources are US government works in the public domain. The extracted text is committed, so
the benchmark scores offline even after a publisher revises or removes a document. Raw
downloads are cached in bench/.cache (not committed).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from groundgate.extract import extract
from groundgate.extract.markup import xml_text

HERE = Path(__file__).parent
CACHE = HERE / ".cache"
DOCS = HERE / "docs"
HL7 = "{urn:hl7-org:v3}"


def download(url: str, path: Path) -> bytes:
    if not path.exists():
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            path.write_bytes(r.read())
        time.sleep(1)  # be polite to the publishers
    return path.read_bytes()


def spl_sections(data: bytes, codes: list[str]) -> str:
    """Text of the SPL sections with the given LOINC codes, in document order."""
    root = ET.fromstring(data)
    parts = []
    for sec in root.iter(f"{HL7}section"):
        code = sec.find(f"{HL7}code")
        if code is not None and code.get("code") in codes:
            parts.append(xml_text(ET.tostring(sec)))
    if not parts:
        raise SystemExit(f"no sections {codes} found")
    return "\n\n".join(parts)


def text_of(src: dict, path: Path, data: bytes) -> str:
    if src["kind"] == "fda":
        return spl_sections(data, src["select"]["sections"])
    doc = extract(path, pages=src["select"].get("pages"))
    return doc.text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", action="store_true", help="record missing hashes")
    args = ap.parse_args()
    lock_path = HERE / "sources.json"
    lock = json.loads(lock_path.read_text())
    CACHE.mkdir(exist_ok=True)
    DOCS.mkdir(exist_ok=True)
    failed = False
    for src in lock["sources"]:
        suffix = ".xml" if src["kind"] == "fda" else ".pdf"
        path = CACHE / f"{src['id']}{suffix}"
        data = download(src["url"], path)
        sha = hashlib.sha256(data).hexdigest()
        if src["sha256"] is None and args.pin:
            src["sha256"] = sha
        elif sha != src["sha256"]:
            print(f"{src['id']}: sha256 {sha} != pinned {src['sha256']}", file=sys.stderr)
            print("  the publisher revised it; the committed text stays", file=sys.stderr)
            failed = True
            continue
        (DOCS / f"{src['id']}.txt").write_text(text_of(src, path, data), encoding="utf-8")
    if args.pin:
        lock_path.write_text(json.dumps(lock, indent=2) + "\n")
    if failed:
        raise SystemExit(1)
    print(f"{len(lock['sources'])} sources verified; text in {DOCS.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
