# Review answers against blind labels (#234)

`bench/requested/review_items.py report` wrote this file from `results.json`, for the
reviewer `maintainer`.
The bar is a 95% upper bound below 0.05 for the rate of wrong answers. The result does not pass.

| Group | Items | Scored | Agree | Label wrong | Wrong | Pending | Unsure | Unclear | Followed, not the label | Median ms | Upper 95% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| total | 147 | 132 | 122 | 0 | 10 | 0 | 11 | 4 | 7 of 126 | 13044 | 0.1251 |
| audit | 30 | 29 | 28 | 0 | 1 | 0 | 0 | 1 | 0 of 27 | 5911.5 | 0.1534 |
| audit number | 29 | 28 | 27 | 0 | 1 | 0 | 0 | 1 | 0 of 26 | 6104 | 0.1585 |
| audit text | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 of 1 | 5420 | 0.9500 |
| number | 145 | 130 | 120 | 0 | 10 | 0 | 11 | 4 | 7 of 124 | 13044 | 0.1270 |
| review | 117 | 103 | 94 | 0 | 9 | 0 | 11 | 3 | 7 of 99 | 15254 | 0.1475 |
| review number | 116 | 102 | 93 | 0 | 9 | 0 | 11 | 3 | 7 of 98 | 15151 | 0.1489 |
| review text | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 of 1 | 30909 | 0.9500 |
| text | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 of 2 | 18164.5 | 0.7764 |

`report` does not write the sections below. I wrote them from `results.json`, `checks.json`
and the answer store with a script, and I compared each number with its output.

## The result

The bar of #234: the 95% upper bound of the rate of wrong answers is below 0.05.
Of 147 items, 132 are scored: 122 agree with the label and 10 are wrong. The
blind check gave the label on each of the 10 disagreements, so 0 labels are wrong.
11 answers are `unsure` and 4 labels are `unclear`. The upper bound is
0.1251, so the result does not pass.

The issue says that a pass opens a new issue to let calibrate take review answers as labels.
This result does not pass. So review answers do not count as labels for these kinds, and
calibrate takes labels only from its blind label page.

Before the checks, 7 of 126 answers that take a value of groundgate (`confirm` or `choose`)
are not the label. The median time for each item is 13044 ms.

## The two corrections of cost_of_sales

2 wrong answers are corrections that give the number as written, not the amount in full. I
asked the agent that runs the milestone how to use the correction step. Its instruction was
wrong: it said to leave the typed box empty, to type the number as the text writes it, and to
cite the scale as a part. SPEC section 2.5 needs the scaled value in `value`. My first attempt
typed the scaled value, which was the right form. #460 makes the page explain the typed value
and each part.

The gate keeps the value of a candidate as it is, and flagged both corrections. So the score
counts them as wrong, with the code of #458. The first score showed the 10 disagreements.
After that, I checked if the score caused these two. It did not, and the score did not change.

Without the 2 corrections, 8 answers of 130 scored are wrong. The upper bound is
0.1083 (`upper95` of `bench/requested/metrics.py` for 8 of 130; this number is not in
`results.json`). This also does not pass the bar.

## The wrong answers

The check value comes from `checks.json`. An independent checker labeled each disagreement
blind from the original PDF. The reason is the checker's reason, in short.

| Document | Field | Task | Answer | Answer value | Check value | Reason |
|---|---|---|---|---|---|---|
| annual-c01 | cost_of_sales | review | `correct` | 9776 EUR | 9776000000 EUR | The correction gives the number as written. The statement is in millions of EUR. |
| annual-c01 | total_assets | review | `choose` | 27000000000 EUR | 26944000000 EUR | The balance sheet gives 26,944 million at 31 December 2025. The answer is a rounded figure. |
| annual-c03 | cost_of_sales | review | `correct` | 2885 USD | 2885000000 USD | The correction gives the number as written. The statement is in $m. |
| annual-c09 | revenue | review | `choose` | 2561000000 AUD | 2626000000 AUD | The answer is net sales revenue (2,561.0). The statutory total revenue is 2,626.0. |
| annual-c09 | total_liabilities | review | `choose` | -2949800000 AUD | 2949800000 AUD | The answer has a minus sign. The statement prints total liabilities as a positive amount. |
| annual-c09 | gross_profit | review | `choose` | 1170300000 AUD | 1041100000 AUD | The answer is the management measure of the profit report (1,170.3). The consolidated statement gives 1,041.1. |
| component-c04 | supply_current_typ | review | `confirm` | 4 mA | absent | The 4 mA is in the Maximum column. The document gives no typical supply current. |
| component-c21 | supply_voltage_max | audit | `not_in_document` | not in the document | 1.9 V | Page 3 gives a maximum operating supply voltage of 1.90 V. |
| sbc-c05 | specialist_copay | review | `choose` | 10 USD | 50 USD | The $10 is the telehealth copay. An office visit is "All other": $50. |
| sbc-c06 | specialist_copay | review | `choose` | 10 USD | 20 USD | The $10 is the telehealth copay. An office visit is "All other": $20. |
