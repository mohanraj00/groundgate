# Outside knowledge: rejected values that the document does not state

This measures how often groundgate rejects a value that the document does not state, and how
often that value is right (#132). It is measurement only, with no spec change and no new model
runs. The plan was fixed on #132 before counting.

```bash
uv export --only-group langextract --no-emit-project --no-hashes -o /tmp/lx.txt
uv run --isolated --no-project --no-sources --python 3.12 --with groundgate==0.4.0 \
    --with-requirements /tmp/lx.txt python bench/outside/outside.py items   # items.json
uv run --isolated --no-project --no-sources --python 3.12 --with groundgate==0.6.1 \
    --with-requirements /tmp/lx.txt python bench/outside/outside.py still   # still.json
uv run --group langextract python bench/outside/outside.py web     # label at 127.0.0.1:8768
uv run python bench/outside/outside.py results                     # results.json, RESULTS.md
uv run python bench/outside/outside.py results --check             # fail if they differ
```

The 10-K items need `bench/sec/runs` and `bench/sec/docs`, and the page needs the pinned
originals in `bench/sec/.cache` and `bench/set2/.cache`. All four are kept out of git.

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

The 229 items were fixed on #132 with a groundgate before spec 0.5, and the 0.4.0 wheel gives the
same 229. Spec 0.5 sends most 10-K values with a missing sign or scale to review, so spec 0.6.1
still rejects only 45 of them. `still.json` lists these 45, on the 0.6.1 wheel. They answer #125,
and the label page shows them. The other items stay unlabeled unless a later question needs them.

## Labels

A person labels each item in `web.py`. The page shows the original document with the cited text
boxed: the pinned 10-K filing HTML with its inline XBRL tag, or the PDF page. An FDA label is
XML, so it shows only the text and a link. Beside it are the field and its description, the
value, the extractor's quote, and the text around the cited span that groundgate reads. It never
shows which model proposed the value, a spec, a decision or a code. The labels are:

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
