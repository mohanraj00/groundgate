# The quote question: too few natural flags

Spec 0.3 flags `NON_VERBATIM_EVIDENCE` when a candidate's `evidence.text` differs from the text
at its span after the §4.4 normalisation. The plan on #67 asks a typed-decision model whether
the quote states the same fact as the span. Before I label a set for it, I counted how often the
flag occurs in the extraction runs that are already recorded.

```bash
uv run --group langextract python bench/judges/quotes/count.py           # COUNTS.md, counts.json
uv run --group langextract python bench/judges/quotes/count.py --check
```

The script runs spec 0.3 on every recorded candidate of the v0.1 set and set 2, on the documents
that are not controls. It counts the flags, and the different (document, span, quote) pairs that
they come from. For each pair it records how the quote differs from the span text, after the §4.4
normalisation for the verbatim comparison: case only, the quote adds text, the quote drops text,
or the quote changes text. It prints no document text and asks no model. CI runs `--check`.
[COUNTS.md](COUNTS.md) has every number.

## What the counts show

Most quotes that differ add text: usually the unit or the word after the number, for example "12"
as "12 years". A quote that changes text usually drops one end of a range.

## Why I stop here

The other judges choose a threshold for each escape ceiling from a calibration part, with the
one-sided 95% upper bound of the key judge. COUNTS.md gives the right clears that each ceiling
needs with no escape, next to the different pairs of both sets. At 0.05 the two numbers are
equal, and a split puts only about half of the pairs in the calibration part. So no label of
these pairs can give a threshold at 0.05, and 0.1 needs every calibration pair to be a right
clear.

More pairs need new extraction runs on new documents. At these rates, each 100 more flags need
thousands of new candidates. A flag this rare also sends few candidates to review, so a model
that clears it saves little review work. I leave the quote question here and go to the
missing-field question.
