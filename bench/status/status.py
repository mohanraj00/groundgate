"""The status set for #113: the key rules of spec 0.3 on a kind that is not an FDA label. Dollar
amounts in IRS publications that no other set used, each labeled by a person with the filing
statuses it belongs to.

    uv run python bench/status/status.py pick --count     # how many amounts the walk finds
    uv run python bench/status/status.py pick             # write sources.json, selection-log.json
    uv run python bench/fetch.py --set bench/status       # download, verify, write docs/
    uv run python bench/status/status.py items            # write items.json from docs/
    uv run python bench/status/status.py label            # label them in the terminal
    uv run python bench/status/status.py score            # RESULTS.md: spec 0.2 and 0.3
    uv run python bench/status/status.py score --check    # fail if the committed files differ

This is the keys-set tool (bench/keys/keys.py) with its own documents, keys and items. The pick
looks only at counts and prints no text, and the label tool never shows which keys a spec puts
at an amount.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE.parent / "keys")]

import keys  # noqa: E402  (bench/keys/keys.py)
import pairs  # noqa: E402  (bench/patterns/pairs.py)

walk = keys.walk  # bench/pick.py

PER_SET, PER_DOC, PAGE_KEYS = 100, 6, 2
# the filing statuses, as IRS text writes them; every publication has the same keys
KEYS = [
    "Single",
    "Married filing jointly",
    "Married filing separately",
    "Head of household",
    "Qualifying surviving spouse",
]
EXAMPLES = {"irs-p590a"}  # examples/irs-590a


def amounts_in(text: str) -> list[tuple[int, int]]:
    """(start, end) of each number token right after a dollar sign."""
    from groundgate.text import tokens

    return [(t.start, t.end) for t in tokens(text) if t.start and text[t.start - 1] == "$"]


def page_amounts(page: str) -> list[tuple[int, int]]:
    """The amounts of a page that names PAGE_KEYS or more of the filing statuses, else none."""
    from groundgate.text import key_mentions

    named = {k for _, _, k in key_mentions(page, tuple(KEYS))}
    return amounts_in(page) if len(named) >= PAGE_KEYS else []


def items_in(text: str, label_keys: list[str]) -> list[tuple[int, int]]:
    """The items of a publication: its amounts. docs/ holds only the pages that the pick took,
    and each of them names PAGE_KEYS or more filing statuses."""
    return amounts_in(text)


def excluded() -> set[str]:
    """IRS publication ids that another set or an example used."""
    _, pubs, _ = keys.dots.excluded()
    for path in HERE.parent.glob("*/sources.json"):
        if path.parent != HERE:
            pubs |= {
                s["id"]
                for s in json.loads(path.read_text())["sources"]
                if s["id"].startswith("irs-")
            }
    return pubs | EXAMPLES


def pick(count_only: bool) -> None:
    walk.CACHE = HERE / ".cache"
    walk.CACHE.mkdir(parents=True, exist_ok=True)
    used = excluded()
    log: list[dict] = []
    irs = [(f"irs-p{n.lower()}", u) for n, u in walk.irs_publications()]
    for doc_id, _ in irs:
        if doc_id in used:
            log.append({"kind": "irs", "id": doc_id, "skip": "used by another set or an example"})
    fresh = [(i, u) for i, u in irs if i not in used]
    sources = pairs.pick_pdfs(
        "irs", fresh, log, {}, find=page_amounts, per_kind=PER_SET, per_doc=PER_DOC, group="status"
    )
    for s in sources:
        s["keys"] = KEYS
    total = sum(min(e["pairs"], PER_DOC) for e in log if "skip" not in e)
    skips: dict[str, int] = {}
    for e in log:
        if "skip" in e:
            skips[e["skip"]] = skips.get(e["skip"], 0) + 1
    print(f"irs: {len(sources)} publications, {total} amounts")
    for why, c in sorted(skips.items()):
        print(f"  skipped, {why}: {c}")
    if count_only:
        return
    lock = {"retrieved": datetime.date.today().isoformat(), "sources": sources}
    (HERE / "sources.json").write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
    (HERE / "selection-log.json").write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n")
    print("wrote bench/status/sources.json and selection-log.json")


keys.HERE, keys.NAME, keys.TITLE = HERE, "status", "Status set: the key rules on IRS filing status"
keys.PER_SET, keys.PER_DOC = PER_SET, PER_DOC
keys.ITEM, keys.ITEMS, keys.DOCS, keys.DOCS_KEY = "amount", "amounts", "IRS publications", "docs"
keys.THEIR_KEYS = "the filing statuses"
keys.SECTION_1 = False
keys.INTRO = (
    "For each marked dollar amount: which filing statuses does it belong to?",
    "Type a number, or several numbers with commas (1,3) when the amount holds for each of",
    "those statuses. An amount that holds whatever the filing status holds for each of them.",
    "Type 0 only when the amount belongs to none of them, and ? when you can't tell.",
    "Type m to see more of the text before the amount, with its heading.\n",
)
keys.items_in = items_in
keys.pick = pick
keys.SPEC02 = [
    *("uv", "run", "--isolated", "--no-project", "--quiet", "--python", "3.12"),
    *("--with", "groundgate[pdf]==0.2.0", "python", str(HERE / "status.py"), "read"),
]

if __name__ == "__main__":
    keys.main()
