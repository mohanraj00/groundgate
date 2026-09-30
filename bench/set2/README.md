# Benchmark set 2

The documents spec 0.2 is measured on (#1). [SELECTION.md](SELECTION.md) has the rules that
picked them, frozen before anyone read one. The v0.1 set in `bench/` is unchanged.

| File | What it is |
|---|---|
| `sources.json` | 101 documents, each with its URL, SHA-256, groups and the pages or sections used |
| `selection-log.json` | every candidate the rules looked at, and why it was taken or skipped |
| `docs/` | the text of each document, written by `fetch.py` |

```bash
uv run python bench/fetch.py --set bench/set2   # re-download, check the hashes, rewrite docs/
```

## Licenses

- FDA drug labels (DailyMed SPL): openFDA publishes drug label content as public domain under
  [CC0](https://open.fda.gov/license/). The labels are written by manufacturers and approved by
  FDA.
- NTSB reports, IRS publications and Federal Register documents: works of the US government,
  not subject to copyright in the United States (17 U.S.C. 105).
- The FDA order comes from CMS "Medicare Part D Spending by Drug" (2024), used only to rank
  drug names.
