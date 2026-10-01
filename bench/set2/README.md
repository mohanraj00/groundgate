# Benchmark set 2

The documents spec 0.2 is measured on (#1). [SELECTION.md](SELECTION.md) has the rules that
picked them, frozen before anyone read one. The v0.1 set in `bench/` is unchanged.

| File | What it is |
|---|---|
| `sources.json` | 101 documents, each with its URL, SHA-256, groups and the pages or sections used |
| `selection-log.json` | every candidate the rules looked at, and why it was taken or skipped |
| `docs/` | the text of each document, written by `fetch.py` |
| `gold/` | the gold: model drafts in `drafts_*.py`, built by `build.py` into one file per document, then checked by a person (#10) |

```bash
uv run python bench/fetch.py --set bench/set2   # re-download, check the hashes, rewrite docs/
```

## Gold

A model (Claude) drafted the gold after spec 0.2 was frozen, from the rules in SELECTION.md
"Fields". The drafts are not ground truth: a person checks every fact in the labeling app, as for
v0.1, and only checked facts count.

```bash
uv run python bench/set2/gold/build.py              # write gold files for new drafts only
uv run python bench/set2/gold/matches.py            # the matched sentences of targeted documents
uv run python bench/label/app.py --set bench/set2   # check them
```

## Licenses

- FDA drug labels (DailyMed SPL): openFDA publishes drug label content as public domain under
  [CC0](https://open.fda.gov/license/). The labels are written by manufacturers and approved by
  FDA.
- NTSB reports, IRS publications and Federal Register documents: works of the US government,
  not subject to copyright in the United States (17 U.S.C. 105).
- The FDA order comes from CMS "Medicare Part D Spending by Drug" (2024), used only to rank
  drug names.
