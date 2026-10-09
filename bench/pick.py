"""Pick the documents of benchmark set 2 by the fixed rules in bench/set2/SELECTION.md.

    uv run python bench/pick.py --count   # how many documents each group finds; no text shown
    uv run python bench/pick.py           # write bench/set2/sources.json and selection-log.json

Since #230, groundgate writes a PDF table as rows with tabs, so its PDF text differs from the
committed text. Run it on the 0.7.0 wheel, which writes it:

    uv run --isolated --no-project --no-sources --python 3.12 --with 'groundgate[pdf]==0.7.0' \
        python bench/pick.py --count

The rules only look at titles, section codes, page counts and pattern matches. Nothing here
prints document text. Downloads are cached in bench/set2/.cache (not committed), so a rerun
walks the same search results. fetch.py --set bench/set2 then verifies the pinned hashes and
writes the text.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any

from fetch import HL7, download, spl_sections

from groundgate.extract import extract

HERE = Path(__file__).parent
SET = HERE / "set2"
CACHE = SET / ".cache"

# Documents used for v0.1 or while building groundgate. Excluded by drug and by publication.
V01_DRUGS = {
    "amlodipine", "atorvastatin", "escitalopram", "gabapentin", "levothyroxine", "lisinopril",
    "losartan", "metformin", "metoprolol", "sertraline", "simvastatin",
}  # fmt: skip
V01_PUBS = {"15", "15-B", "463", "501", "505", "554", "560", "571", "590-A", "596", "970"}
V01_LAST_NTSB = 192717

# FDA
PART_D = (
    "https://data.cms.gov/sites/default/files/2026-06/98218f98-166c-4723-8438-c344a4ef96a6/"
    "DSD_PTD_RY26_P04_V10_DY24_BGM.csv"
)
PART_D_SHA256 = "5dcc9d7bd7d7f88d9f6b24485c06d961ed6d70f9aa6deffa50dd47a6854c2a55"
CLAIMS = "Tot_Clms_2024"
FDA_GENERAL, FDA_KEYED, FDA_WEIGHT, FDA_MAX_RANK = 10, 15, 12, 150
LABELS_TRIED = 10  # search results checked per drug before it is skipped
MIN_KEYS, MIN_WEIGHT_MATCHES = 2, 3
INDICATIONS, DOSAGE, STRENGTHS = "34067-9", "34068-7", "43678-2"
WEIGHT_BASED = re.compile(
    r"(?<![A-Za-z])(?:mg|mcg)\s*(?:/|per)\s*(?:kg|kilogram|m2|m²)(?![A-Za-z])", re.I
)
SALTS = {"HCl": "Hydrochloride", "HBr": "Hydrobromide"}

# NTSB
NTSB = "https://data.ntsb.gov/carol-repgen/api/Aviation/ReportMain/GenerateNewestReport/{}/pdf"
NTSB_COUNT, NTSB_MAX_PAGES, NTSB_MAX_ID = 10, 8, V01_LAST_NTSB + 300

# Federal Register: the fallback for a pattern group IRS publications can't fill
FR_API = "https://www.federalregister.gov/api/v1/documents.json"
FR_FROM, FR_TO, FR_MAX_DOC_PAGES, FR_MAX_PAGES = "2026-01-01", "2026-09-30", 20, 1
FR_FIELDS = ("document_number", "publication_date", "page_length", "pdf_url")

# IRS
IRS_LIST = "https://www.irs.gov/forms-instructions-and-publications?find=Publication&page={}"
IRS_GENERAL, IRS_MIN_DOLLARS = 10, 8
DOLLAR = re.compile(r"\$\s?\d")
TARGET_MATCHES, TARGET_MAX_DOCS, TARGET_MAX_PAGES, TARGET_PER_DOC = 40, 25, 3, 5
NUM = r"\$?\d[\d,.]*"
PATTERNS = {
    "change": re.compile(
        rf"\bfrom\s+{NUM}(?:\s*(?:million|billion|percent|%))?\s+(?:to|through)\s+\$?\d", re.I
    ),
    "negation": re.compile(
        r"\b(?:not|no|cannot|can[\u2019']t|never)\s+(?:be\s+)?(?:more|greater|less|fewer)\s+than\b"
        r"[^;]{0,20}?\d|\b(?:not|cannot|can[\u2019']t)\s+exceed\b[^;]{0,20}?\d",
        re.I,
    ),
    "scale": re.compile(r"\$\s?\d[\d,.]*\s+(?:thousand|million|billion|trillion)\b", re.I),
}


def get(url: str, name: str) -> bytes:
    """Download into the cache. A 404 raises HTTPError. Any other failure is retried, and then
    stops the walk: a document that could not be read is never silently skipped."""
    err: OSError | None = None
    for wait in (0, 10, 30, 90):
        time.sleep(wait)
        try:
            return download(url, CACHE / name)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            err = e
        except OSError as e:
            err = e
    raise SystemExit(f"{url}: {err}; rerun later")


# --------------------------------------------------------------------------------- FDA


def ranked_generics() -> list[str]:
    """Generic names by total 2024 Part D claims, summed over each brand's "Overall" row."""
    data = get(PART_D, "part-d-2024.csv")
    if hashlib.sha256(data).hexdigest() != PART_D_SHA256:
        raise SystemExit("the Part D file changed; the ranking is pinned to its hash")
    claims: dict[str, float] = defaultdict(float)
    for row in csv.DictReader(data.decode("utf-8-sig").splitlines()):
        if row["Mftr_Name"] == "Overall" and row[CLAIMS]:
            claims[row["Gnrc_Name"].strip()] += float(row[CLAIMS])
    return sorted(claims, key=lambda n: (-claims[n], n))


def base_word(name: str) -> str:
    return re.split(r"[\s,]", name.strip(), maxsplit=1)[0].lower()


def search_name(name: str) -> str:
    return " ".join(SALTS.get(w, w) for w in name.split())


def find_label(name: str) -> tuple[dict[str, Any] | None, str]:
    """The first search result that is a single-ingredient tablet or capsule label with
    sections 1, 2 and 3, or None and why not."""
    q = urllib.parse.quote(search_name(name))
    url = f"https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json?drug_name={q}&pagesize=100"
    results = json.loads(get(url, f"search-{base_word(name)}.json"))["data"]
    base = base_word(name).upper()
    tried = 0
    for r in results:
        title = r["title"].upper()
        if not (title.startswith(base + " ") and re.search(r"TABLET|CAPSULE", title)):
            continue
        if " AND " in title or "/" in title:
            continue
        if tried == LABELS_TRIED:
            break
        tried += 1
        xml_url = f"https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{r['setid']}.xml"
        data = get(xml_url, f"spl-{r['setid']}.xml")
        root = ET.fromstring(data)
        sections = {
            code.get("code"): sec
            for sec in root.iter(f"{HL7}section")
            if (code := sec.find(f"{HL7}code")) is not None
        }
        if not {INDICATIONS, DOSAGE, STRENGTHS} <= set(sections):
            continue
        subsections = sections[INDICATIONS].findall(f"{HL7}component/{HL7}section")
        keys = [
            re.sub(r"^\s*\d+(\.\d+)*\s*", "", "".join(t.itertext())).strip()
            for s in subsections
            if (t := s.find(f"{HL7}title")) is not None
        ]
        dosage = spl_sections(data, [DOSAGE])
        return {
            "setid": r["setid"],
            "title": r["title"],
            "url": xml_url,
            "sha256": hashlib.sha256(data).hexdigest(),
            "keys": [k for k in keys if k],
            "keyed": len([k for k in keys if k]) >= MIN_KEYS,
            "weight_based": len(WEIGHT_BASED.findall(dosage)) >= MIN_WEIGHT_MATCHES,
        }, "ok"
    return None, "no single-ingredient tablet or capsule label with sections 1, 2 and 3"


def select_fda(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    quota = {"general": FDA_GENERAL, "keyed": FDA_KEYED, "weight_based": FDA_WEIGHT}
    n = dict.fromkeys(quota, 0)
    for rank, name in enumerate(ranked_generics()[:FDA_MAX_RANK], 1):
        if all(n[g] >= q for g, q in quota.items()):
            break
        base = base_word(name)
        entry: dict[str, Any] = {"kind": "fda", "rank": rank, "name": name}
        log.append(entry)
        if "/" in name:
            entry["skip"] = "combination"
        elif base in V01_DRUGS:
            entry["skip"] = "used in v0.1"
        elif base in seen:
            entry["skip"] = "same drug ranked higher"
        if "skip" in entry:
            continue
        seen.add(base)
        label, why = find_label(name)
        if label is None:
            entry["skip"] = why
            continue
        entry.update({k: label[k] for k in ("setid", "keyed", "weight_based")})
        groups = []
        if n["general"] < FDA_GENERAL:
            groups.append("general")
        if label["keyed"] and (groups or n["keyed"] < FDA_KEYED):
            groups.append("keyed")
        if label["weight_based"] and (groups or n["weight_based"] < FDA_WEIGHT):
            groups.append("weight_based")
        if not groups:
            entry["skip"] = "no group needs it"
            continue
        for g in groups:
            n[g] += 1
        entry["groups"] = groups
        chosen.append(
            {
                "id": f"fda-{base}",
                "kind": "fda",
                "groups": groups,
                "url": label["url"],
                "sha256": label["sha256"],
                "select": {"sections": [DOSAGE, STRENGTHS]},
                "keys": label["keys"],
                "source": f"{label['title']}; Part D 2024 claims rank {rank}",
            }
        )
    return chosen


# -------------------------------------------------------------------------------- NTSB


def select_ntsb(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    for rid in range(V01_LAST_NTSB + 1, NTSB_MAX_ID + 1):
        if len(chosen) == NTSB_COUNT:
            break
        entry: dict[str, Any] = {"kind": "ntsb", "id": rid}
        log.append(entry)
        try:
            data = get(NTSB.format(rid), f"ntsb-{rid}.pdf")
        except urllib.error.HTTPError:
            entry["skip"] = "no report (404)"
            continue
        if not data.startswith(b"%PDF"):
            entry["skip"] = "not a PDF"
            continue
        doc = extract(CACHE / f"ntsb-{rid}.pdf")
        pages = len(doc.layout.pages) if doc.layout else 0
        if not doc.text.lstrip().startswith("Aviation Investigation Final Report"):
            entry["skip"] = "not a final report"
        elif pages > NTSB_MAX_PAGES:
            entry["skip"] = f"{pages} pages"
        if "skip" in entry:
            continue
        chosen.append(
            {
                "id": f"ntsb-{rid}",
                "kind": "ntsb",
                "groups": ["control"],
                "url": NTSB.format(rid),
                "sha256": hashlib.sha256(data).hexdigest(),
                "select": {},
            }
        )
    return chosen


# --------------------------------------------------------------------------------- IRS


def irs_publications() -> list[tuple[str, str]]:
    """(number, pdf url) for every English publication, in numeric order."""
    found: dict[str, str] = {}
    for page in range(200):
        html = get(IRS_LIST.format(page), f"irs-list-{page}.html").decode("utf-8", "replace")
        rows = re.findall(r"<tr.*?</tr>", html, re.S)
        new = 0
        for row in rows:
            # English only: "Publication 15-B" or "Publication 15 (Circular E)", not "(SP)"
            m = re.search(
                r">\s*Publication\s+([0-9][0-9A-Za-z-]*)(?:\s*\(Circular [^)<]*\))?\s*<", row
            )
            link = re.search(r'href="(/pub/irs-pdf/[^"]+\.pdf)"', row)
            if m and link and m.group(1) not in found:
                found[m.group(1)] = "https://www.irs.gov" + link.group(1)
                new += 1
        if not new:
            break

    def order(num: str) -> tuple[int, str]:
        digits = re.match(r"\d+", num)
        return (int(digits.group()) if digits else 0, num)

    return [(n, found[n]) for n in sorted(found, key=order)]


def page_texts(doc_id: str, url: str) -> tuple[list[str], str]:
    """The text of each page and the file's SHA-256, cached after the first extraction."""
    pdf = CACHE / f"{doc_id}.pdf"
    data = get(url, pdf.name)
    sha = hashlib.sha256(data).hexdigest()
    cached = CACHE / f"{doc_id}.pages.json"
    if cached.exists():
        pages = json.loads(cached.read_text(encoding="utf-8"))
        if pages["sha256"] == sha:
            return pages["text"], sha
    doc = extract(pdf)
    raw = doc.text.encode()
    assert doc.layout is not None
    text = [raw[p.start : p.end].decode() for p in doc.layout.pages]
    cached.write_text(json.dumps({"sha256": sha, "text": text}), encoding="utf-8")
    return text, sha


def source(doc_id: str, kind: str, url: str, sha: str, groups: list[str], pages: list[int]) -> dict:
    return {
        "id": doc_id,
        "kind": kind,
        "groups": groups,
        "url": url,
        "sha256": sha,
        "select": {"pages": pages},
    }


def walk_targeted(
    docs: list[tuple[str, str]],
    kind: str,
    counts: dict[str, int],
    max_pages: int,
    log: list[dict[str, Any]],
    seen: dict[str, str],
) -> list[dict[str, Any]]:
    """Add documents (id, url), in order, while a pattern group is open. Updates ``counts``,
    and ``seen`` (the hash of each taken text: its id), so the same text is never taken twice."""
    chosen: list[dict[str, Any]] = []
    for doc_id, url in docs:
        open_groups = [g for g, c in counts.items() if c < TARGET_MATCHES]
        if not open_groups or len(chosen) == TARGET_MAX_DOCS:
            break
        entry: dict[str, Any] = {"kind": kind, "group": "targeted", "id": doc_id}
        log.append(entry)
        try:
            pages, sha = page_texts(doc_id, url)
        except Exception as e:  # an unreadable file is skipped, and the log says why
            entry["skip"] = f"unreadable: {type(e).__name__}"
            continue
        hits = [{g: len(rx.findall(t)) for g, rx in PATTERNS.items()} for t in pages]
        idx = [i for i, h in enumerate(hits) if any(h[g] for g in open_groups)][:max_pages]
        if not idx:
            entry["skip"] = "no page matches a group that is still open"
            continue
        text_sha = hashlib.sha256("\f".join(pages[i] for i in idx).encode()).hexdigest()
        if text_sha in seen:  # Federal Register rules share printed pages
            entry["skip"] = f"same text as {seen[text_sha]}"
            continue
        seen[text_sha] = doc_id
        added = {g: min(TARGET_PER_DOC, sum(hits[i][g] for i in idx)) for g in PATTERNS}
        for g, c in added.items():
            counts[g] += c
        groups = [g for g in PATTERNS if added[g]]
        entry.update({"pages": [i + 1 for i in idx], "matches": added})
        chosen.append(source(doc_id, kind, url, sha, groups, [i + 1 for i in idx]))
    return chosen


def select_irs(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pubs = [(n, u) for n, u in irs_publications() if n.upper() not in V01_PUBS]
    general: list[dict[str, Any]] = []
    for num, url in pubs:
        if len(general) == IRS_GENERAL:
            break
        doc_id = f"irs-p{num.lower()}"
        entry: dict[str, Any] = {"kind": "irs", "group": "general", "id": doc_id}
        log.append(entry)
        try:
            pages, sha = page_texts(doc_id, url)
        except Exception as e:
            entry["skip"] = f"unreadable: {type(e).__name__}"
            continue
        dollars = sum(len(DOLLAR.findall(t)) for t in pages[:2])
        entry["dollar_amounts_pages_1_2"] = dollars
        if dollars < IRS_MIN_DOLLARS:
            entry["skip"] = "fewer than 8 dollar amounts on pages 1 and 2"
            continue
        general.append(source(doc_id, "irs", url, sha, ["general"], [1, 2]))
    taken = {s["id"] for s in general}
    rest = [(f"irs-p{n.lower()}", u) for n, u in pubs if f"irs-p{n.lower()}" not in taken]
    counts = dict.fromkeys(PATTERNS, 0)
    seen: dict[str, str] = {}
    targeted = walk_targeted(rest, "irs", counts, TARGET_MAX_PAGES, log, seen)
    log.append({"kind": "irs", "targeted_matches": dict(counts)})
    if any(c < TARGET_MATCHES for c in counts.values()):
        targeted += walk_targeted(federal_register_rules(), "fr", counts, FR_MAX_PAGES, log, seen)
        log.append({"kind": "fr", "targeted_matches": dict(counts)})
    return general + targeted


# -------------------------------------------------------------------------- Federal Register


def federal_register_rules() -> list[tuple[str, str]]:
    """(id, pdf url) for final rules of at most FR_MAX_DOC_PAGES pages published in the window,
    newest first, ties by document number."""
    rules = []
    for page in range(1, 200):
        q = urllib.parse.urlencode(
            [
                ("conditions[type][]", "RULE"),
                ("conditions[publication_date][gte]", FR_FROM),
                ("conditions[publication_date][lte]", FR_TO),
                ("order", "oldest"),
                ("per_page", "100"),
                ("page", str(page)),
                *[("fields[]", f) for f in FR_FIELDS],
            ]
        )
        data = json.loads(get(f"{FR_API}?{q}", f"fr-list-{page}.json"))
        rules += data.get("results", [])
        if page >= data.get("total_pages", 0):
            break
    rules = [
        r for r in rules if r.get("pdf_url") and (r.get("page_length") or 0) <= FR_MAX_DOC_PAGES
    ]
    rules.sort(key=lambda r: (r["publication_date"], r["document_number"]), reverse=True)
    return [(f"fr-{r['document_number']}", r["pdf_url"]) for r in rules]


# -------------------------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", action="store_true", help="report group sizes; write nothing")
    ap.add_argument("--only", choices=["fda", "ntsb", "irs"], help="walk one source")
    args = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    log: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for kind, walk in (("fda", select_fda), ("ntsb", select_ntsb), ("irs", select_irs)):
        if args.only in (None, kind):
            sources += walk(log)
    groups: dict[str, int] = defaultdict(int)
    for s in sources:
        for g in s["groups"]:
            groups[f"{s['kind']} {g}"] += 1
    print(f"{len(sources)} documents")
    for g, c in sorted(groups.items()):
        print(f"  {g}: {c}")
    for entry in log:
        if "targeted_matches" in entry:
            print(f"  {entry['kind']} pattern matches so far: {entry['targeted_matches']}")
    skips: dict[str, int] = defaultdict(int)
    for entry in log:
        if "skip" in entry:
            skips[f"{entry['kind']}: {entry['skip']}"] += 1
    print("skipped:")
    for why, c in sorted(skips.items()):
        print(f"  {why}: {c}")
    if args.count:
        return
    today = datetime.date.today().isoformat()
    lock = {"retrieved": today, "sources": sources}
    (SET / "sources.json").write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
    (SET / "selection-log.json").write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {SET.relative_to(HERE.parent)}/sources.json and selection-log.json")


if __name__ == "__main__":
    main()
