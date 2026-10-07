# Outside knowledge: rejected values that the document does not state

This measures how often groundgate rejects a value that the document does not state, and how
often that value is right (#132). It is measurement only, with no spec change and no new model
runs. The plan was fixed on #132 before counting.

```bash
uv run --group langextract python bench/outside/outside.py items   # items.json
uv run --group langextract python bench/outside/outside.py web     # label at 127.0.0.1:8768
uv run python bench/outside/outside.py results                     # results.json, RESULTS.md
uv run python bench/outside/outside.py results --check             # fail if they differ
```

## Items

An item is a rejected candidate from an existing run: every run of set 2 (`bench/set2/runs`), and
the #120 run of the 10-K set (`bench/sec/runs`, kept out of git). It counts when all of these hold:

- its field is in the set's gold;
- it was rejected `VALUE_NOT_IN_EVIDENCE`, or `NO_EVIDENCE` because LangExtract did not find the
  quote;
- no number token of the document equals the value, as written or scaled (for a string field, the
  text does not hold the value).

Candidates with the same document, field, key, value and unit are one item. `items.json` holds
no document text.

## Labels

A person labels each item in `web.py`, which shows the source link, the field and its
description, the value, the extractor's quote, and the text around the cited span. It never
shows which model proposed the value. The labels are:

- **right**: the value is true for the field and the document's subject. A right label also
  gives a source and a basis:
  - **from the document**: the document's own numbers give it, such as a loss in brackets, a
    table "in thousands", or two numbers added;
  - **from outside**: it needs knowledge from outside the document.
- **wrong**;
- **not sure**.

The plan on #132 has right, wrong and not sure. The basis was added before any label, because
most 10-K items are signs and table scales, not outside knowledge. Only "right, from outside"
answers the question of #125.

[RESULTS.md](RESULTS.md) has the counts by set and by kind, and each right value with its
source.
