# Pattern set: the change rule

This set measures one rule, the change rule of SPEC §4.2 that #51 widens (#58). The rule decides
one thing: whether Y in "from X to Y" is the new value of a change or the end of a range. So
this set has no gold facts and no model runs. It has every "from X to Y" pair in documents that
v0.1 and set 2 did not use, each labeled by a person as a change, a range or neither.

These rules were fixed before anyone read a document of this set. `pairs.py` is the same rules
as code. Its `pick` step looks only at titles, section codes, page counts and pair counts, and
prints no text.

```bash
uv run python bench/patterns/pairs.py pick --count     # how many pairs each kind finds
uv run python bench/patterns/pairs.py pick             # write sources.json, selection-log.json
uv run python bench/fetch.py --set bench/patterns      # download, verify, write docs/
uv run python bench/patterns/pairs.py pairs            # write pairs.json from docs/
uv run python bench/patterns/pairs.py label            # label them in the terminal
```

## A pair

`from`, a number, at most one word of up to 12 characters with no digits, a range connector
(`to`, `through`, `thru`, `-` or `–`) and a number. Each number may have up to 4 characters
before it, such as `$`. This is the range pair of SPEC §4.2 with its first number after `from`.
It has no change word in it, so the pick does not depend on the rule it measures.

## What is excluded

Every drug, IRS publication and Federal Register rule that v0.1 or set 2 used. The drugs and
publications are excluded by name and number, as in set 2, so a newer revision of a used
document is not taken either.

## Order

IRS and the Federal Register take documents in a fixed order until each has 70 pairs. The first
5 pairs of a document count, so no one document fills a kind.

- **FDA:** generic names in the order of the set-2 Part D ranking, with the set-2 label rules
  ([SELECTION.md](../set2/SELECTION.md)), up to rank 400. The text is sections 1 and 2
  (indications, dosage). These sections rarely hold a pair: the first count found 5 pairs in
  the first 336 ranks, so FDA stops at a rank and not at a pair count.
- **IRS:** publications in numeric order. The text is the pages that hold the first 5 pairs.
- **Federal Register:** final rules of at most 20 pages, published 2025-07-01 to 2025-12-31,
  newest first. Set 2 took rules from 2026. The text is the pages that hold the first 5 pairs,
  and a rule whose pages are the same text as a rule taken before is skipped.

## Labels

`pairs.py label` shows each pair in its sentence, with X and Y marked, and asks one question: is
Y the new value that replaces X (`change`), the end of a range (`range`), or neither (`neither`:
a form number, a phone number)? It never shows how a spec reads the pair. The labels go
in `labels.json`.
