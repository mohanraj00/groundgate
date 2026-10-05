# Tables set: the table-sentence rule

This set measures one rule of spec 0.3 (#87, SPEC §4.5). A table sentence is a sentence with 3 or
more line breaks that mentions 2 or more keys. A value in it is at the keys mentioned on its own
line, or at no key. The keys set (`bench/keys`) is where the gap was found, so it can't measure
the rule (#90).

These rules were fixed before anyone read a document of this set. `tables.py` is the same rules as
code. It is the keys-set tool (`bench/keys/keys.py`) with its own documents and its own items.
Its `pick` step looks only at label metadata and dose counts, and prints no text.

```bash
uv run python bench/tables/tables.py pick --count     # how many doses the walk finds
uv run python bench/tables/tables.py pick             # write sources.json, selection-log.json
uv run python bench/fetch.py --set bench/tables       # download, verify, write docs/
uv run python bench/tables/tables.py items            # write items.json from docs/
uv run python bench/tables/tables.py label            # label them in the terminal
uv run python bench/tables/tables.py score            # RESULTS.md: spec 0.2 and 0.3
```

## Labels and keys

As in the keys set: FDA labels in the set-2 Part D ranking, with the set-2 label rules and at
least 2 subsections in section 1. The keys are the subsection titles, and the text is sections 2
and 3. The walk goes through the whole ranking, because table sentences are rare.

## What is excluded

Every drug that v0.1, set 2, the pattern set, the dots set or the keys set used.

## A dose

A dose of the keys set (a number token followed by `mg` or `mcg`) that lies in a table sentence
of its label. The pick finds table sentences with the sentence rule and the key mentions of SPEC
§4.2 and §4.5, which this rule does not change.

The set holds every such dose of every label in the ranking, not a sample. The plan on #90 was
the first 6 doses of a label up to 100, but the first walk of the whole ranking found fewer, so
the cap went before anyone read the text.

## Labels

As in the keys set: `tables.py label` shows each dose in its text and lists the label's keys, and
the answer is one key, more than one when the dose holds for each of them, `0` when it belongs to
none, or `?` when the person can't tell. `m` shows more text, `s` shows section 1 of the label,
and `label --recheck` shows the doses labeled `0` or `?` again. The labels go in `labels.json`.

## Scoring

```bash
uv run python bench/tables/tables.py score --check    # fail if the committed files differ
```

[RESULTS.md](RESULTS.md) reads the keys at each dose under spec 0.2, the released 0.2.0 wheel in
its own environment, and under spec 0.3, the core in this repository, as in the keys set. The
rule was fixed on #87 before the pick. CI runs `score --check`.

What it found:

- Under spec 0.2, a wrong key reaches almost every dose of these tables, because each table is
  one sentence that mentions two or more keys.
- Under spec 0.3, no wrong key reaches a dose. The price is that almost every right key goes to
  review too: in these labels a table puts one cell on each line, so the value's own line rarely
  names its condition. That is the trade that #87 chose: a swapped key in a table is silent, and a
  right key in review costs a look.
- No label changed after scoring.
