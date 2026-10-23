# Codex judge on the review fields: development split

This file comes from `results.json` through `bench/judges/codex/score.py`.

Items: 69 fields of the `runner` arm that end in review with at least one candidate (annual 15, component 20, sbc 23, sds 11). 6 of them have an unclear label and are left out of the scores.

## Judges

| Judge | Calls | Scored items | Right candidate | Right choices | Wrong choices | None, right | None, wrong |
|---|---:|---:|---:|---:|---:|---:|---:|
| gpt-6-luna medium run 1 | 69 | 63 | 60 | 51 | 1 | 2 | 9 |
| gpt-6-luna medium run 2 | 69 | 63 | 60 | 49 | 3 | 0 | 11 |
| gpt-6.1-sol medium run 1 | 70 | 63 | 60 | 51 | 2 | 1 | 9 |
| gpt-6.1-sol medium run 2 | 70 | 63 | 60 | 51 | 1 | 2 | 9 |

"Right candidate" counts the items where a candidate matches the label. "None, right" is a none choice on an item with no right candidate.

## Threshold at each ceiling

The threshold is the lowest t whose one-sided 95% upper bound on escapes among clears is below the ceiling, pooled over the kinds.

| Judge | Ceiling | t | Right values cleared | Escapes | Upper 95% | Runner miss rate | Miss rate with the clears | Escapes with the clears |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| gpt-6-luna medium run 1 | 0.05 | none | | | | | | |
| gpt-6-luna medium run 1 | 0.1 | 0.5 | 51 | 1 | 0.0880 | 61.48% (75 of 122) | 19.67% (24 of 122) | 3 |
| gpt-6-luna medium run 1 | 0.2 | 0.5 | 51 | 1 | 0.0880 | 61.48% (75 of 122) | 19.67% (24 of 122) | 3 |
| gpt-6-luna medium run 2 | 0.05 | none | | | | | | |
| gpt-6-luna medium run 2 | 0.1 | none | | | | | | |
| gpt-6-luna medium run 2 | 0.2 | 0.5 | 49 | 3 | 0.1424 | 61.48% (75 of 122) | 21.31% (26 of 122) | 5 |
| gpt-6.1-sol medium run 1 | 0.05 | none | | | | | | |
| gpt-6.1-sol medium run 1 | 0.1 | 0.9 | 51 | 1 | 0.0880 | 61.48% (75 of 122) | 19.67% (24 of 122) | 3 |
| gpt-6.1-sol medium run 1 | 0.2 | 0.5 | 51 | 2 | 0.1141 | 61.48% (75 of 122) | 19.67% (24 of 122) | 4 |
| gpt-6.1-sol medium run 2 | 0.05 | none | | | | | | |
| gpt-6.1-sol medium run 2 | 0.1 | 0.5 | 51 | 1 | 0.0880 | 61.48% (75 of 122) | 19.67% (24 of 122) | 3 |
| gpt-6.1-sol medium run 2 | 0.2 | 0.5 | 51 | 1 | 0.0880 | 61.48% (75 of 122) | 19.67% (24 of 122) | 3 |

## Each kind at the threshold

| Judge | Ceiling | t | Kind | Items | Right values cleared | Escapes | Runner miss rate | Miss rate with the clears |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| gpt-6-luna medium run 1 | 0.1 | 0.5 | annual | 15 | 14 | 1 | 62.22% (28 of 45) | 31.11% (14 of 45) |
| gpt-6-luna medium run 1 | 0.1 | 0.5 | component | 16 | 13 | 0 | 57.69% (15 of 26) | 7.69% (2 of 26) |
| gpt-6-luna medium run 1 | 0.1 | 0.5 | sbc | 21 | 15 | 0 | 60.00% (21 of 35) | 17.14% (6 of 35) |
| gpt-6-luna medium run 1 | 0.1 | 0.5 | sds | 11 | 9 | 0 | 68.75% (11 of 16) | 12.50% (2 of 16) |
| gpt-6-luna medium run 1 | 0.2 | 0.5 | annual | 15 | 14 | 1 | 62.22% (28 of 45) | 31.11% (14 of 45) |
| gpt-6-luna medium run 1 | 0.2 | 0.5 | component | 16 | 13 | 0 | 57.69% (15 of 26) | 7.69% (2 of 26) |
| gpt-6-luna medium run 1 | 0.2 | 0.5 | sbc | 21 | 15 | 0 | 60.00% (21 of 35) | 17.14% (6 of 35) |
| gpt-6-luna medium run 1 | 0.2 | 0.5 | sds | 11 | 9 | 0 | 68.75% (11 of 16) | 12.50% (2 of 16) |
| gpt-6-luna medium run 2 | 0.2 | 0.5 | annual | 15 | 14 | 1 | 62.22% (28 of 45) | 31.11% (14 of 45) |
| gpt-6-luna medium run 2 | 0.2 | 0.5 | component | 16 | 13 | 2 | 57.69% (15 of 26) | 7.69% (2 of 26) |
| gpt-6-luna medium run 2 | 0.2 | 0.5 | sbc | 21 | 15 | 0 | 60.00% (21 of 35) | 17.14% (6 of 35) |
| gpt-6-luna medium run 2 | 0.2 | 0.5 | sds | 11 | 7 | 0 | 68.75% (11 of 16) | 25.00% (4 of 16) |
| gpt-6.1-sol medium run 1 | 0.1 | 0.9 | annual | 15 | 14 | 1 | 62.22% (28 of 45) | 31.11% (14 of 45) |
| gpt-6.1-sol medium run 1 | 0.1 | 0.9 | component | 16 | 14 | 0 | 57.69% (15 of 26) | 3.85% (1 of 26) |
| gpt-6.1-sol medium run 1 | 0.1 | 0.9 | sbc | 21 | 13 | 0 | 60.00% (21 of 35) | 22.86% (8 of 35) |
| gpt-6.1-sol medium run 1 | 0.1 | 0.9 | sds | 11 | 10 | 0 | 68.75% (11 of 16) | 6.25% (1 of 16) |
| gpt-6.1-sol medium run 1 | 0.2 | 0.5 | annual | 15 | 14 | 1 | 62.22% (28 of 45) | 31.11% (14 of 45) |
| gpt-6.1-sol medium run 1 | 0.2 | 0.5 | component | 16 | 14 | 1 | 57.69% (15 of 26) | 3.85% (1 of 26) |
| gpt-6.1-sol medium run 1 | 0.2 | 0.5 | sbc | 21 | 13 | 0 | 60.00% (21 of 35) | 22.86% (8 of 35) |
| gpt-6.1-sol medium run 1 | 0.2 | 0.5 | sds | 11 | 10 | 0 | 68.75% (11 of 16) | 6.25% (1 of 16) |
| gpt-6.1-sol medium run 2 | 0.1 | 0.5 | annual | 15 | 14 | 1 | 62.22% (28 of 45) | 31.11% (14 of 45) |
| gpt-6.1-sol medium run 2 | 0.1 | 0.5 | component | 16 | 14 | 0 | 57.69% (15 of 26) | 3.85% (1 of 26) |
| gpt-6.1-sol medium run 2 | 0.1 | 0.5 | sbc | 21 | 13 | 0 | 60.00% (21 of 35) | 22.86% (8 of 35) |
| gpt-6.1-sol medium run 2 | 0.1 | 0.5 | sds | 11 | 10 | 0 | 68.75% (11 of 16) | 6.25% (1 of 16) |
| gpt-6.1-sol medium run 2 | 0.2 | 0.5 | annual | 15 | 14 | 1 | 62.22% (28 of 45) | 31.11% (14 of 45) |
| gpt-6.1-sol medium run 2 | 0.2 | 0.5 | component | 16 | 14 | 0 | 57.69% (15 of 26) | 3.85% (1 of 26) |
| gpt-6.1-sol medium run 2 | 0.2 | 0.5 | sbc | 21 | 13 | 0 | 60.00% (21 of 35) | 22.86% (8 of 35) |
| gpt-6.1-sol medium run 2 | 0.2 | 0.5 | sds | 11 | 10 | 0 | 68.75% (11 of 16) | 6.25% (1 of 16) |

## All thresholds

| Judge | t | Right values cleared | Escapes | Upper 95% |
|---|---:|---:|---:|---:|
| gpt-6-luna medium run 1 | 0.5 | 51 | 1 | 0.0880 |
| gpt-6-luna medium run 1 | 0.7 | 51 | 1 | 0.0880 |
| gpt-6-luna medium run 1 | 0.8 | 51 | 1 | 0.0880 |
| gpt-6-luna medium run 1 | 0.9 | 51 | 1 | 0.0880 |
| gpt-6-luna medium run 1 | 0.95 | 51 | 1 | 0.0880 |
| gpt-6-luna medium run 1 | 0.99 | 50 | 1 | 0.0897 |
| gpt-6-luna medium run 2 | 0.5 | 49 | 3 | 0.1424 |
| gpt-6-luna medium run 2 | 0.7 | 49 | 3 | 0.1424 |
| gpt-6-luna medium run 2 | 0.8 | 49 | 3 | 0.1424 |
| gpt-6-luna medium run 2 | 0.9 | 49 | 3 | 0.1424 |
| gpt-6-luna medium run 2 | 0.95 | 49 | 3 | 0.1424 |
| gpt-6-luna medium run 2 | 0.99 | 47 | 2 | 0.1230 |
| gpt-6.1-sol medium run 1 | 0.5 | 51 | 2 | 0.1141 |
| gpt-6.1-sol medium run 1 | 0.7 | 51 | 2 | 0.1141 |
| gpt-6.1-sol medium run 1 | 0.8 | 51 | 2 | 0.1141 |
| gpt-6.1-sol medium run 1 | 0.9 | 51 | 1 | 0.0880 |
| gpt-6.1-sol medium run 1 | 0.95 | 50 | 1 | 0.0897 |
| gpt-6.1-sol medium run 1 | 0.99 | 47 | 0 | 0.0618 |
| gpt-6.1-sol medium run 2 | 0.5 | 51 | 1 | 0.0880 |
| gpt-6.1-sol medium run 2 | 0.7 | 51 | 1 | 0.0880 |
| gpt-6.1-sol medium run 2 | 0.8 | 51 | 1 | 0.0880 |
| gpt-6.1-sol medium run 2 | 0.9 | 51 | 1 | 0.0880 |
| gpt-6.1-sol medium run 2 | 0.95 | 51 | 1 | 0.0880 |
| gpt-6.1-sol medium run 2 | 0.99 | 47 | 0 | 0.0618 |

## Calibration bins

A choice is correct when it names a right candidate, or none on an item with no right candidate.

| Judge | Confidence | Items | Correct |
|---|---|---:|---:|
| gpt-6-luna medium run 1 | 0.9 to 1 | 63 | 53 |
| gpt-6-luna medium run 2 | 0.9 to 1 | 63 | 49 |
| gpt-6.1-sol medium run 1 | 0.7 to 0.9 | 2 | 1 |
| gpt-6.1-sol medium run 1 | 0.9 to 1 | 61 | 51 |
| gpt-6.1-sol medium run 2 | 0.7 to 0.9 | 1 | 1 |
| gpt-6.1-sol medium run 2 | 0.9 to 1 | 62 | 52 |

## Pairs

Two runs of one model show the repeatability. Two models show the shared wrong choices. A wrong choice names a candidate that the label does not hold.

| First | Second | Items | Same option | Wrong, first | Wrong, second | Wrong, both | Same wrong candidate |
|---|---|---:|---:|---:|---:|---:|---:|
| gpt-6-luna medium run 1 | gpt-6-luna medium run 2 | 63 | 57 | 1 | 3 | 1 | 1 |
| gpt-6-luna medium run 1 | gpt-6.1-sol medium run 1 | 63 | 58 | 1 | 2 | 1 | 1 |
| gpt-6.1-sol medium run 1 | gpt-6.1-sol medium run 2 | 63 | 62 | 2 | 1 | 1 | 1 |
