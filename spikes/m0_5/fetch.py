"""Fetch the two spike sources, verify their pinned hashes, and regenerate the text files.

Both are US government works in the public domain. The derived .txt files are committed so the
spike reproduces offline even after the publishers revise the originals.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from pdfminer.high_level import extract_text
from pdfminer.layout import LAParams

SRC = Path(__file__).parent / "sources"
SOURCES = {
    "p590a.pdf": (
        "https://www.irs.gov/pub/irs-pdf/p590a.pdf",
        "ca0e42873cfd66d2d9bfd082125d381f8a0c2f3b0a441d7d65ab5ccc06a0e1c7",
    ),
    # DailyMed SPL, set id 0ef9de1a-b786-4b6c-a250-3f5ac532b16a, version 5
    "metformin-er.xml": (
        "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/0ef9de1a-b786-4b6c-a250-3f5ac532b16a.xml",
        "a19749660b332fbbe721cf84c455256b1616f726abe4a8e0c5b4873e23d410a6",
    ),
}


def fetch() -> None:
    for name, (url, sha) in SOURCES.items():
        path = SRC / name
        if not path.exists():
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            path.write_bytes(urllib.request.urlopen(req, timeout=60).read())
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != sha:
            raise SystemExit(f"{name}: sha256 {got} != pinned {sha} (the publisher revised it)")


def spl_text(path: Path) -> str:
    ns = {"v": "urn:hl7-org:v3"}

    def text(e: ET.Element) -> str:
        return re.sub(r"\s+", " ", "".join(e.itertext())).strip()

    out = []
    for sec in ET.parse(path).getroot().iter("{urn:hl7-org:v3}section"):
        title = sec.find("v:title", ns)
        if title is not None and text(title):
            out.append("\n## " + text(title) + "\n")
        for child in sec:
            if child.tag.endswith("}text"):
                out.extend(s for p in child if (s := text(p)))
    return unicodedata.normalize("NFC", "\n".join(out))


def main() -> None:
    fetch()
    pdf = extract_text(SRC / "p590a.pdf", page_numbers=range(12), laparams=LAParams())
    (SRC / "p590a.txt").write_text(unicodedata.normalize("NFC", pdf))
    (SRC / "metformin-er.txt").write_text(spl_text(SRC / "metformin-er.xml"))
    print("sources verified and text regenerated")


if __name__ == "__main__":
    main()
