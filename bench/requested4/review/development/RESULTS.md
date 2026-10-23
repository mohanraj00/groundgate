# Review answers against blind labels (#463)

`bench/requested/review_items.py report` wrote this file from `results.json`, for the
reviewer `maintainer`. The items are of the development split.
The bar is a 95% upper bound below 0.05 for the rate of wrong answers. The result does not pass.

| Group | Items | Scored | Agree | Label wrong | Wrong | Pending | Unsure | Unclear | Followed, not the label | Median ms | Upper 95% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| total | 107 | 92 | 88 | 0 | 4 | 0 | 10 | 5 | 1 of 85 | 7758 | 0.0967 |
| audit | 30 | 30 | 30 | 0 | 0 | 0 | 0 | 0 | 0 of 29 | 6098.5 | 0.0950 |
| audit number | 27 | 27 | 27 | 0 | 0 | 0 | 0 | 0 | 0 of 26 | 6328 | 0.1050 |
| audit text | 3 | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 of 3 | 4789 | 0.6316 |
| number | 103 | 88 | 84 | 0 | 4 | 0 | 10 | 5 | 1 of 81 | 7758 | 0.1010 |
| review | 77 | 62 | 58 | 0 | 4 | 0 | 10 | 5 | 1 of 56 | 8159 | 0.1416 |
| review number | 76 | 61 | 57 | 0 | 4 | 0 | 10 | 5 | 1 of 55 | 8046 | 0.1438 |
| review text | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 of 1 | 10067 | 0.9500 |
| text | 4 | 4 | 4 | 0 | 0 | 0 | 0 | 0 | 0 of 4 | 6531 | 0.5271 |
`report` does not write the sections below. I wrote them from `results.json`, `checks.json`,
`items.json`, the answer store and the output of `review measures`, with a script. I compared
each number with that output.

## The result

The bar of #234: the 95% upper bound of the rate of wrong answers is below 0.05. Of 107 items,
92 are scored: 88 agree with the label and 4 are wrong. The blind check gave the label on each
of the 4 disagreements, so 0 labels are wrong. The upper bound is 0.0967, so the result does not
pass. On the held-out split (#234), the bound was 0.1251.

10 answers are `unsure`, on sbc-c25, sbc-c26 and sbc-c27. On these SBCs, two in-network tiers
apply equally, and the request context says not to choose among tiers. So I pressed `u`. 8 of
the 10 have a present label and 2 have an unclear label. 5 labels are `unclear`.

Before the checks, 1 of 85 answers that take a value of groundgate (`confirm` or `choose`) is not
the label. The median time for each item is 7758 ms. 104 of 107 answers use one key.

## The word-box view and the PDF renders

#463 asks if the word-box view of the review page gives less agreement than the bench pages.

- The 30 audit tasks are blind: the page shows no reason, and I pressed `r` on none of them.
  30 of 30 audit answers agree with the label.
- All scored answers: 88 of 92 agree with the label (95.65%).
- The two blind passes of the labels read renders of the original PDF pages. They gave the same
  label on 470 of 480 slots (97.92%, `README.md`, section Labels).

The audit answers give no sign that the word-box view gives less agreement. The 4 wrong answers
are review tasks. 2 of them come from the reading of a number, not from the view (see below). The
other 2 say that a datasheet gives no typical current, but its Table 1 gives a nominal value. 30 audit
items are too few to show a small difference: the upper bound of the audit group is 0.0950.

## The wrong answers

The check value comes from `checks.json`. An independent checker labeled each disagreement
blind from the original PDF.

| Document | Field | Task | Answer | Answer value | Check value | Reason |
|---|---|---|---|---|---|---|
| annual-c28 | cost_of_sales | review | `correct` | -3266.2 EUR | 3266200000 EUR | The correction gives the number as written, with its sign. The statement is in EUR million, and cost of sales is a positive amount. |
| annual-c28 | revenue | review | `choose` | 3960000000 EUR | 3960200000 EUR | The answer is a rounded figure. The income statement gives net sales of 3,960.2 million. |
| component-c09 | supply_current_typ | review | `not_in_document` | not in the document | 1.2 mA | Table 1 on page 4 gives a nominal current of 1.2 mA for standard operation. |
| component-c12 | supply_current_typ | review | `not_in_document` | not in the document | 2.1 mA | Table 1 on page 4 gives a nominal current of 2.1 mA. The page showed page 2, the table of contents. |

The correction of cost_of_sales is the same error as the 2 corrections of the held-out
measure, after #460. The page explains the typed value, but it accepted a value that is not
in full and has the wrong sign.

## The measures of the page

`groundgate review measures --set requested4 --split development` gives these numbers. 29 of
the 32 packets have tasks: annual-c12, sds-c05 and sds-c22 have none.

| Kind | Answers | Median ms | One key | Escapes that the audit finds |
|---|---:|---:|---:|---:|
| number | 103 | 7758 | 100 of 103 | 1 of 27 audit slots |
| text | 4 | 6531 | 4 of 4 | 0 of 3 audit slots |

The escape is the `supply_current_typ` audit slot of component-c19: the run admitted a value,
the label is absent, and I answered `not_in_document`. The runner has 1 escape on this split, on
`supply_current_typ` (`development/results.json`).

The measures give 0 agreement pairs for each kind, because a pair needs a blind label of
another reviewer. The agreement with the sealed labels is in the sections above.
