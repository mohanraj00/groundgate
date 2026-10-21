# Codex judge on the review fields: heldout split

This file comes from `results.json` through `bench/judges/codex/score.py`.

Items: 104 fields of the `runner` arm that end in review with at least one candidate (annual 43, component 19, sbc 33, sds 9). 6 of them have an unclear label and are left out of the scores.

## Judges

| Judge | Calls | Scored items | Right candidate | Right choices | Wrong choices | None, right | None, wrong |
|---|---:|---:|---:|---:|---:|---:|---:|
| gpt-6.1-sol medium run 1 | 103 | 98 | 97 | 91 | 0 | 1 | 6 |
| gpt-6.1-sol medium run 2 | 103 | 98 | 97 | 94 | 0 | 1 | 3 |

"Right candidate" counts the items where a candidate matches the label. "None, right" is a none choice on an item with no right candidate.

## All thresholds

| Judge | t | Right values cleared | Escapes | Upper 95% |
|---|---:|---:|---:|---:|
| gpt-6.1-sol medium run 1 | 0.5 | 91 | 0 | 0.0324 |
| gpt-6.1-sol medium run 1 | 0.7 | 91 | 0 | 0.0324 |
| gpt-6.1-sol medium run 1 | 0.8 | 91 | 0 | 0.0324 |
| gpt-6.1-sol medium run 1 | 0.9 | 91 | 0 | 0.0324 |
| gpt-6.1-sol medium run 1 | 0.95 | 91 | 0 | 0.0324 |
| gpt-6.1-sol medium run 1 | 0.99 | 85 | 0 | 0.0346 |
| gpt-6.1-sol medium run 2 | 0.5 | 94 | 0 | 0.0314 |
| gpt-6.1-sol medium run 2 | 0.7 | 94 | 0 | 0.0314 |
| gpt-6.1-sol medium run 2 | 0.8 | 94 | 0 | 0.0314 |
| gpt-6.1-sol medium run 2 | 0.9 | 94 | 0 | 0.0314 |
| gpt-6.1-sol medium run 2 | 0.95 | 91 | 0 | 0.0324 |
| gpt-6.1-sol medium run 2 | 0.99 | 87 | 0 | 0.0338 |

## Calibration bins

A choice is correct when it names a right candidate, or none on an item with no right candidate.

| Judge | Confidence | Items | Correct |
|---|---|---:|---:|
| gpt-6.1-sol medium run 1 | 0.7 to 0.9 | 3 | 0 |
| gpt-6.1-sol medium run 1 | 0.9 to 1 | 95 | 92 |
| gpt-6.1-sol medium run 2 | 0.7 to 0.9 | 1 | 0 |
| gpt-6.1-sol medium run 2 | 0.9 to 1 | 97 | 95 |

## Frozen threshold

The freeze (`bench/requested4/judge/freeze.json`) names gpt-6.1-sol at effort medium, ceiling 0.1 and threshold 0.9 for all kinds.

| Judge | Kind | Right values cleared | Escapes | Upper 95% | Runner miss rate | Miss rate with the clears | Runner escapes | Escapes with the clears |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| gpt-6.1-sol medium run 1 | total | 91 | 0 | 0.0324 | 61.27% (125 of 204) | 16.67% (34 of 204) | 1 | 1 |
| gpt-6.1-sol medium run 1 | annual | 43 | 0 | 0.0673 | 72.09% (62 of 86) | 22.09% (19 of 86) | 0 | 0 |
| gpt-6.1-sol medium run 1 | component | 12 | 0 | 0.2209 | 66.67% (20 of 30) | 26.67% (8 of 30) | 1 | 1 |
| gpt-6.1-sol medium run 1 | sbc | 28 | 0 | 0.1015 | 41.67% (30 of 72) | 2.78% (2 of 72) | 0 | 0 |
| gpt-6.1-sol medium run 1 | sds | 8 | 0 | 0.3123 | 81.25% (13 of 16) | 31.25% (5 of 16) | 0 | 0 |
| gpt-6.1-sol medium run 2 | total | 94 | 0 | 0.0314 | 61.27% (125 of 204) | 15.20% (31 of 204) | 1 | 1 |
| gpt-6.1-sol medium run 2 | annual | 43 | 0 | 0.0673 | 72.09% (62 of 86) | 22.09% (19 of 86) | 0 | 0 |
| gpt-6.1-sol medium run 2 | component | 14 | 0 | 0.1926 | 66.67% (20 of 30) | 20.00% (6 of 30) | 1 | 1 |
| gpt-6.1-sol medium run 2 | sbc | 29 | 0 | 0.0981 | 41.67% (30 of 72) | 1.39% (1 of 72) | 0 | 0 |
| gpt-6.1-sol medium run 2 | sds | 8 | 0 | 0.3123 | 81.25% (13 of 16) | 31.25% (5 of 16) | 0 | 0 |

Agreement of the runs at the frozen threshold:

| First | Second | Kind | Items | Same option | Cleared by both | First only | Second only |
|---|---|---|---:|---:|---:|---:|---:|
| gpt-6.1-sol medium run 1 | gpt-6.1-sol medium run 2 | total | 98 | 93 | 90 | 1 | 4 |
| gpt-6.1-sol medium run 1 | gpt-6.1-sol medium run 2 | annual | 43 | 43 | 43 | 0 | 0 |
| gpt-6.1-sol medium run 1 | gpt-6.1-sol medium run 2 | component | 16 | 14 | 12 | 0 | 2 |
| gpt-6.1-sol medium run 1 | gpt-6.1-sol medium run 2 | sbc | 30 | 29 | 28 | 0 | 1 |
| gpt-6.1-sol medium run 1 | gpt-6.1-sol medium run 2 | sds | 9 | 7 | 7 | 1 | 1 |

## Pairs

Two runs of one model show the repeatability. Two models show the shared wrong choices. A wrong choice names a candidate that the label does not hold.

| First | Second | Items | Same option | Wrong, first | Wrong, second | Wrong, both | Same wrong candidate |
|---|---|---:|---:|---:|---:|---:|---:|
| gpt-6.1-sol medium run 1 | gpt-6.1-sol medium run 2 | 98 | 93 | 0 | 0 | 0 | 0 |
