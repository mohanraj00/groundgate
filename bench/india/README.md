# India set: the Indian digit grouping

This set measures one rule of spec 0.3 (#59, SPEC §4.1): a number grouped the Indian way, the
last three digits and then pairs (`2,00,000`), has a value. Set 2, the pattern set and the dots
set hold US documents only, so none of them can measure it (#76).

These rules were fixed before anyone read a document of this set. `india.py` is the same rules
as code. Its `pick` step looks only at page and token counts, and prints no text.

```bash
uv run python bench/india/india.py pick --count     # how many tokens the walk finds
uv run python bench/india/india.py pick             # write sources.json, selection-log.json
uv run python bench/fetch.py --set bench/india      # download, verify, write docs/
uv run python bench/india/india.py items            # write items.json from docs/
uv run python bench/india/india.py label            # label them in the terminal
uv run python bench/india/india.py score            # RESULTS.md: spec 0.2 and 0.3
```

## Source

SEBI circulars, in the order of the circulars listing that `www.sebi.gov.in` returns from page
1, through its own pagination request with the session cookie that the listing page sets. A
circular counts when its page links a PDF. Reserve Bank of India notifications were the first
choice, but their PDFs are behind a CAPTCHA page.

## A token

A number token (SPEC §4.1) with a comma in it, valid or not under either grouping. The first 5
of a circular count, and the walk stops when the set has 100. The pages are the ones that hold
those tokens.

## Labels

`india.py label` shows each token in its text and asks one question: is the marked text one
number written with grouping commas (`one number`), or not one number, such as a list, two
values or a reference (`not one number`)? It never shows the value a spec reads. The labels go
in `labels.json`.
