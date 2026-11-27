"""Choose the members of the 1.0 release set from publisher metadata only (#748).

The script reads the govinfo sitemaps, the MODS record of each package that it examines, the
file index of the USGS Mineral Commodity Summaries 2026 and the HTTP headers (HEAD) of its
chapter files. It never reads a document body. The order of the candidates is a SHA-256 of a
fixed tag and the package id, so the rule, not a person, picks each member. The rule is in this
file before the choice, and ``members.json`` records it with each member and each rejected
candidate.

    uv run python bench/release1/select.py --cache /path/outside/the/repo/release1-metadata
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

Row = dict[str, Any]

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SITEMAP = "https://www.govinfo.gov/sitemap/{name}_sitemap.xml"
MODS = "https://www.govinfo.gov/metadata/pkg/{package}/mods.xml"
NS = {"m": "http://www.loc.gov/mods/v3", "s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
YEAR = 2025

# The 11 regional circuits and the Federal Circuit (ca13). govinfo has no 2025 sitemap of the
# DC Circuit.
COURTS = ("ca1", "ca2", "ca3", "ca4", "ca5", "ca6", "ca7", "ca8", "ca9", "ca10", "ca11", "ca13")
OPINION_PAGES = (6, 60)
OPINIONS = 30
OPINIONS_EACH_COURT = 2
COURT_READS = 40  # candidates examined for each court at most
REPORT_PAGES = (8, 150)
REPORTS_EACH_CHAMBER = 15
RULES_COMMITTEE = {"hsru00", "ssra00"}
TITLE_OUT = re.compile(r"^PROVIDING FOR|CONFERENCE REPORT|ACTIVIT|ALLOCATION|OVERSIGHT PLAN", re.I)
MAX_READS = 800
MCS = "https://pubs.usgs.gov/periodicals/mcs2026/"
MINERALS = 30
NOT_A_CHAPTER = {"mcs2026-appendixes.pdf"}


def order(tag: str, package: str) -> str:
    return hashlib.sha256(f"groundgate #748 {tag}\n{package}".encode()).hexdigest()


class Metadata:
    def __init__(self, cache: Path) -> None:
        self.cache = cache
        self.reads = 0
        cache.mkdir(parents=True, exist_ok=True)

    def get(self, url: str, name: str) -> bytes:
        path = self.cache / name
        if path.exists():
            return path.read_bytes()
        if self.reads >= MAX_READS:
            raise SystemExit(f"more than {MAX_READS} metadata reads")
        self.reads += 1
        req = urllib.request.Request(url, headers={"User-Agent": "groundgate-bench/1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw: bytes = r.read()
        path.write_bytes(raw)
        time.sleep(0.5)
        return raw

    def packages(self, name: str) -> list[str]:
        raw = self.get(SITEMAP.format(name=name), f"{name.replace('/', '_')}.xml")
        locs = [e.text or "" for e in ET.fromstring(raw).iterfind("s:url/s:loc", NS)]
        return sorted({loc.rsplit("/", 1)[1] for loc in locs})

    def head(self, url: str, name: str) -> Row:
        """The size, the entity tag and the date of change of a file, from a HEAD request."""
        path = self.cache / name
        if path.exists():
            cached: Row = json.loads(path.read_text())
            return cached
        if self.reads >= MAX_READS:
            raise SystemExit(f"more than {MAX_READS} metadata reads")
        self.reads += 1
        req = urllib.request.Request(
            url, method="HEAD", headers={"User-Agent": "groundgate-bench/1"}
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            row = {
                "bytes": int(r.headers.get("Content-Length") or 0),
                "etag": r.headers.get("ETag") or "",
                "last_modified": r.headers.get("Last-Modified") or "",
            }
        path.write_text(json.dumps(row))
        time.sleep(0.5)
        return row

    def mods(self, package: str) -> ET.Element:
        return ET.fromstring(self.get(MODS.format(package=package), f"{package}.mods.xml"))


def text(root: ET.Element, path: str) -> str:
    e = root.find(path, NS)
    return " ".join((e.text or "").split()) if e is not None else ""


def pages(root: ET.Element) -> int:
    m = re.match(r"(\d+) digital object pages?", text(root, "m:physicalDescription/m:extent"))
    return int(m.group(1)) if m else 0


def opinion(root: ET.Element) -> Row:
    ext = "m:extension/m:"
    granules = root.findall("m:relatedItem[@type='constituent']", NS)
    return {
        "court": text(root, ext + "courtCode"),
        "court_type": text(root, ext + "courtType"),
        "case": text(root, ext + "caseNumber"),
        "title": text(root, "m:titleInfo/m:title"),
        "date_issued": text(root, "m:originInfo/m:dateIssued"),
        "pages": pages(root),
        "granules": len(granules),
        "entry": entry(granules),
    }


def entry(granules: list[ET.Element]) -> str:
    """The docket entry number of the opinion file, as the granule subtitle states it."""
    sub = text(granules[0], "m:titleInfo/m:subTitle") if granules else ""
    m = re.search(r"\[(\d+)\]", sub)
    return m.group(1) if m else ""


class Twins:
    """One document can be filed in two packages: two dockets, or two report numbers.

    A package is a twin of an earlier member if it has the same docket entry in the same court,
    or the same title, date of issue and page count. Only the first member stays.

    One bill gives at most one member: a report on the same primary bill as an earlier member
    is out, also if a committee of the other chamber wrote it.
    """

    def __init__(self) -> None:
        self.first: dict[tuple[str, ...], str] = {}

    @staticmethod
    def keys(m: Row) -> list[tuple[str, ...]]:
        out: list[tuple[str, ...]] = [
            ("same", m["title"].casefold(), m["date_issued"], str(m["pages"]))
        ]
        if m.get("entry"):
            out.append(("entry", m["court"], m["entry"]))
        if m.get("bill"):
            out.append(("bill", m["bill"]))
        return out

    def problem(self, m: Row) -> str | None:
        for key in self.keys(m):
            if key in self.first:
                if key[0] == "bill":
                    return f"the same bill as {self.first[key]}"
                return f"the same document as {self.first[key]}"
        return None

    def add(self, package: str, m: Row) -> None:
        for key in self.keys(m):
            self.first.setdefault(key, package)


def opinion_problem(m: Row) -> str | None:
    if m["court_type"] != "Appellate":
        return "not an appellate court"
    if m["granules"] != 1:
        return f"{m['granules']} documents in the package, not 1"
    if not OPINION_PAGES[0] <= m["pages"] <= OPINION_PAGES[1]:
        return f"{m['pages']} pages"
    if not m["date_issued"].startswith(str(YEAR)):
        return f"issued {m['date_issued']}"
    return None


def report(root: ET.Element) -> Row:
    ext = "m:extension/m:"
    committee = root.find(ext + "congCommittee", NS)
    primary = root.find(ext + "bill[@context='PRIMARY']", NS)
    return {
        "chamber": text(root, ext + "chamber"),
        "doc_class": text(root, ext + "docClass"),
        "committee": committee.get("authorityId", "") if committee is not None else "",
        "committee_name": text(committee, "m:name") if committee is not None else "",
        "bill": f"{primary.get('type')} {primary.get('number')}" if primary is not None else "",
        "title": text(root, "m:titleInfo/m:title"),
        "date_issued": text(root, "m:originInfo/m:dateIssued"),
        "pages": pages(root),
    }


def report_problem(m: Row) -> str | None:
    if m["doc_class"] not in ("HRPT", "SRPT"):
        return f"class {m['doc_class']}"
    if not m["bill"]:
        return "no primary bill"
    if not m["committee"]:
        return "no committee"
    if m["committee"] in RULES_COMMITTEE:
        return "a rule for floor consideration"
    if TITLE_OUT.search(m["title"]):
        return "not a report on one bill"
    if not REPORT_PAGES[0] <= m["pages"] <= REPORT_PAGES[1]:
        return f"{m['pages']} pages"
    return None


def opinions(meta: Metadata, named: set[str], rejected: list[Row]) -> list[Row]:
    lists = {c: [p for p in meta.packages(f"USCOURTS/USCOURTS_{c}_{YEAR}") if p not in named]
             for c in COURTS}  # fmt: skip
    queue = {c: iter(sorted(lists[c], key=lambda p: order("opinion", p))) for c in COURTS}
    seen = dict.fromkeys(COURTS, 0)
    got: dict[str, list[Row]] = {c: [] for c in COURTS}
    twins = Twins()

    def one_more(court: str) -> bool:
        for package in queue[court]:
            if seen[court] == COURT_READS:
                return False
            seen[court] += 1
            m = opinion(meta.mods(package))
            why = opinion_problem(m) or twins.problem(m)
            if why:
                rejected.append({"package": package, "reason": why})
                continue
            twins.add(package, m)
            got[court].append({"package": package, **m})
            return True
        return False

    # Two members for each court first. Then one more at a time for the courts with the most
    # 2025 packages, until there are OPINIONS members or no court has a candidate left.
    for court in COURTS:
        for _ in range(OPINIONS_EACH_COURT):
            one_more(court)
    by_size = sorted(COURTS, key=lambda c: (-len(lists[c]), COURTS.index(c)))
    total = sum(map(len, got.values()))
    progress = True
    while total < OPINIONS and progress:
        progress = False
        for court in by_size:
            if total < OPINIONS and one_more(court):
                total += 1
                progress = True
    return [m for c in COURTS for m in got[c]]


def reports(meta: Metadata, named: set[str], rejected: list[Row]) -> list[Row]:
    pkgs = [p for p in meta.packages(f"CRPT_{YEAR}") if p not in named]
    out = []
    twins = Twins()
    for tag in ("hrpt", "srpt"):
        cands = sorted((p for p in pkgs if tag in p), key=lambda p: order("report", p))
        got: list[Row] = []
        used: set[str] = set()
        # First one report for each committee, in candidate order; then a second pass.
        for one_each in (True, False):
            for package in cands:
                if len(got) == REPORTS_EACH_CHAMBER:
                    break
                if any(g["package"] == package for g in got):
                    continue
                m = report(meta.mods(package))
                why = report_problem(m) or twins.problem(m)
                if why:
                    if one_each:
                        rejected.append({"package": package, "reason": why})
                    continue
                if one_each and m["committee"] in used:
                    continue
                used.add(m["committee"])
                twins.add(package, m)
                got.append({"package": package, **m})
        out += got
    return out


def minerals(meta: Metadata, named: set[str], rejected: list[Row]) -> list[Row]:
    index = meta.get(MCS, "mcs2026-index.html").decode()
    files = sorted(set(re.findall(r'href="(mcs2026-[a-z0-9_.-]+\.pdf)"', index)))
    cands = sorted((f for f in files if f not in named), key=lambda f: order("mineral", f))
    got: list[Row] = []
    first: dict[str, str] = {}
    for name in cands:
        if len(got) == MINERALS:
            break
        if name in NOT_A_CHAPTER:
            rejected.append({"package": name, "reason": "not a commodity chapter"})
            continue
        # The index keeps an earlier version of a revised chapter as NAME_ver.N.pdf.
        if "_ver." in name:
            current = name.split("_ver.")[0] + ".pdf"
            rejected.append({"package": name, "reason": f"an earlier version of {current}"})
            continue
        h = meta.head(MCS + name, name + ".head.json")
        if h["etag"] and h["etag"] in first:
            rejected.append({"package": name, "reason": f"the same file as {first[h['etag']]}"})
            continue
        if h["etag"]:
            first[h["etag"]] = name
        commodity = name.removeprefix("mcs2026-").removesuffix(".pdf")
        got.append({"package": name, "commodity": commodity, "url": MCS + name, **h})
    return got


def named_in_bench() -> set[str]:
    pat = re.compile(
        r"(?:USCOURTS-[a-z0-9]+-[0-9-]+|CRPT-[0-9]+[hs]rpt[0-9]+|mcs2026-[a-z0-9_.-]+\.pdf)"
    )
    found: set[str] = set()
    for f in (ROOT / "bench").rglob("*"):
        if f.is_relative_to(HERE):  # this set names its own members
            continue
        if f.is_file() and f.suffix in (".json", ".md", ".py", ".jsonl", ".txt"):
            found |= set(pat.findall(f.read_text(errors="ignore")))
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, required=True, help="local storage for the metadata")
    args = ap.parse_args(argv)
    if args.cache.resolve().is_relative_to(ROOT):
        ap.error("--cache must be outside the repository")
    meta = Metadata(args.cache)
    named = named_in_bench()
    rejected: dict[str, list[Row]] = {"minerals": [], "opinions": [], "reports": []}
    chosen = {
        "minerals": minerals(meta, named, rejected["minerals"]),
        "opinions": opinions(meta, named, rejected["opinions"]),
        "reports": reports(meta, named, rejected["reports"]),
    }
    path = HERE / "members.json"
    body = json.loads(path.read_text()) if path.exists() else {}
    old = body.get("kinds", {})
    body["kinds"] = {}
    for kind in ("minerals", "opinions", "reports"):
        body["kinds"][kind] = {
            **old.get(kind, {}),
            "members": chosen[kind],
            "rejected": rejected[kind],
        }
    path.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n")
    for kind, ms in chosen.items():
        print(f"{kind}: {len(ms)} members, {len(rejected[kind])} rejected")
    print(f"{meta.reads} metadata reads")
    return 0


if __name__ == "__main__":
    sys.exit(main())
