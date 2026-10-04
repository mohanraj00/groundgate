# Dots set: the abbreviation sentence-end rule

This set measures one rule of spec 0.3 (#63, SPEC §4.2): the dot of a listed abbreviation does
not end a sentence when the next word starts with no uppercase letter. The pattern set
(`bench/patterns`) is where the "p.m." case was found, so it can't measure the rule (#73).

These rules were fixed before anyone read a document of this set. `dots.py` is the same rules as
code. Its `pick` step looks only at titles, section codes, page counts and dot counts, and prints
no text.

```bash
uv run python bench/dots/dots.py pick --count     # how many dots each kind finds
uv run python bench/dots/dots.py pick             # write sources.json, selection-log.json
uv run python bench/fetch.py --set bench/dots     # download, verify, write docs/
uv run python bench/dots/dots.py items            # write items.json from docs/
uv run python bench/dots/dots.py label            # label them in the terminal
uv run python bench/dots/dots.py score            # RESULTS.md: spec 0.2 and 0.3
```

## A dot

A listed abbreviation, as a whole word, whose dot is followed by whitespace. The list is the one
in SPEC §4.2, written out in `dots.py`, so the pick does not run the rule it measures. Both
kinds count: a dot before an uppercase word, which spec 0.3 keeps as a sentence end, and a dot
before any other character, which spec 0.3 does not.

## What is excluded

Every drug, IRS publication and Federal Register rule that v0.1, set 2 or the pattern set used,
by name and number.

## Order

Each kind takes documents in a fixed order until it has 50 dots. The first 5 dots of a document
count.

- **FDA:** the set-2 Part D ranking and label rules, up to rank 400, sections 1 and 2. These
  sections rarely hold a listed abbreviation, so FDA stops at a rank and not at a dot count.
- **IRS:** publications in numeric order. The text is the pages that hold the first 5 dots.
- **Federal Register:** final rules of at most 20 pages, published 2025-01-01 to 2025-06-30,
  newest first. Set 2 took 2026 and the pattern set 2025-07-01 to 2025-12-31.

113 dots in 29 documents: FDA 9 (7 labels), IRS 54 (12 publications), Federal Register 50 (10
rules).

## Labels

`dots.py label` shows each abbreviation in its text and asks one question: does the sentence end
at its dot (`end`), or does it go on (`goes on`)? It never shows how a spec reads the dot. The
labels go in `labels.json`.
