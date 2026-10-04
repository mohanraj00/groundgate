# Caps set: U.S. and No. before an uppercase letter

This set measures one rule of spec 0.3 (#77, SPEC §4.2). In the qualifier window, the dot of
`U.S.` does not end a sentence, and the dot of `No.` or `Nos.` does not end one before a code
such as `DEA-1086`. The dots set (`bench/dots`) is where these cuts were found, so it can't
measure the rule (#80).

These rules were fixed before anyone read a document of this set. `caps.py` is the same rules as
code. Its `pick` step looks only at titles, page counts and dot counts, and prints no text.

```bash
uv run python bench/caps/caps.py pick --count     # how many dots each kind finds
uv run python bench/caps/caps.py pick             # write sources.json, selection-log.json
uv run python bench/fetch.py --set bench/caps     # download, verify, write docs/
uv run python bench/caps/caps.py items            # write items.json from docs/
uv run python bench/caps/caps.py label            # label them in the terminal
uv run python bench/caps/caps.py score            # RESULTS.md: spec 0.3 before and after #77
```

## A dot

`U.S.`, `No.` or `Nos.`, as a whole word, whose dot is followed by whitespace and an uppercase
letter, with at most one line break between. These are the dots that spec 0.3 with the #63 rule
keeps as sentence ends. A dot inside a Federal Register running head does not count, as in the
dots set.

## What is excluded

Every IRS publication and Federal Register rule that v0.1, set 2, the pattern set or the dots set
used, by number. FDA labels are not in this set, because sections 1 and 2 of a label rarely hold
these abbreviations.

## Order

Each kind takes documents in a fixed order until it has 50 dots. The first 5 dots of a document
count.

- **IRS:** publications in numeric order. The text is the pages that hold the first 5 dots.
- **Federal Register:** final rules of at most 20 pages, published 2024-07-01 to 2024-12-31,
  newest first. Set 2 took 2026, the pattern set 2025-07-01 to 2025-12-31 and the dots set
  2025-01-01 to 2025-06-30.

## Labels

`caps.py label` shows each abbreviation in its text and asks one question: does the sentence end
at its dot (`end`), or does it go on (`goes on`)? It never shows how a spec reads the dot. The
labels go in `labels.json`.
