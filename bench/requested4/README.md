# Requested fields: the 0.11 measure

Status: I selected the members and froze the manifest on 2026-10-20, before any model output on
this set (#395). I sealed the labels of both splits on 2026-10-20. The set has 91 documents: 32
in the development split and 59 in the held-out split. No model call has run on this set.

This set is the first with a development split and a held-out split (#383). It answers one
question: does a change that the learning loop finds on the development split lower the miss rate
on documents that no rule came from, with no new escape? The held-out split answers it once, on
the frozen code.

The kinds, the schemas and the fixed requests are the same as in [bench/requested3](../requested3).
A document schema changes only the reporting currency of an annual report. No publisher or
employer of bench/requested, bench/requested2 or bench/requested3 is a member.

## Split rule

`manifest.json` records `split_rule`:

- `method`: `family-hash/1`
- `salt`: `01b7a9400553fd883fbff30d7e5295d3`
- `development_share`: 1/3 (a first byte of 0 to 85 is development)
- `fixed_on`: 2026-10-20

A document is in the development split if the first byte of `sha256(salt + source_family_group)`
is less than `development_share x 256`. Else it is held-out. I fixed the salt in #395 before any
download. A component datasheet or a safety data sheet has the family of its publisher and its
product family. An SBC or an annual report has one family for each employer or organization. So
all documents of one family are in one split. `bench/requested/metrics.py` calculates each split
again and refuses a mismatch.

The hash decides each split, so the sizes are not the targets of #395 (10 and 20 for each kind).
I made no subsample and I moved no document.

| Kind | Approved | Members | Development | Held-out | Group B members |
|---|---:|---:|---:|---:|---:|
| component | 25 | 16 | 7 | 9 | 12 |
| sbc | 30 | 24 | 8 | 16 | 8 |
| annual | 26 | 25 | 9 | 16 | 21 |
| sds | 27 | 26 | 8 | 18 | 21 |

## Selection

The maintainer approved 108 downloads with their sources and sizes. Before that I read only
catalog pages and terms pages, and I sent HEAD requests for the sizes. Terms group A gives no use
limit that applies to a private copy. Terms group B allows only personal, noncommercial or
internal use. A group B member is a member only for local, internal measurement, and I infer no
broader right.

After each download I checked the identity, the period or revision, the text layer and the printed
notices. 17 downloads are not members (`source_checks.json` gives each reason):

- 1 download failed: the server answered 403 (annual-c11).
- 6 component datasheets are on hold because their own notice limits reproduction.
- 6 sources have no usable text layer: 1 component datasheet, 2 SBCs whose font encoding gives
  unreadable text, 2 scanned plan schedules that are also not the SBC form, and 1 safety data
  sheet. 2 more SBCs are a carrier benefit summary, not the SBC form.
- 1 component datasheet is not in English, and 1 has a different printed publisher.

Every other download is a member. Selection used publisher metadata, notices and layout
eligibility. It never used a requested value or a model output.

`manifest.json` records each source URL, byte size, PDF hash, reader text hash, terms group and
license note. The originals and the reader texts stay in local work storage and are not published.

## Labels

Two blind passes labeled all 480 slots from the original PDFs, with the rules of requested3. Each
pass confirmed each present value on a render of its PDF page. The passes gave the same label on
470 slots (97.9%). An independent check of the original PDF decided the other 10. Each absence
has a second blind check: both passes gave 101 of the 108 absences. The independent check decided
3 more.

| Kind | Slots | Present | Absent | Unclear |
|---|---:|---:|---:|---:|
| component | 80 | 56 | 7 | 17 |
| sbc | 120 | 107 | 8 | 5 |
| annual | 150 | 131 | 16 | 3 |
| sds | 130 | 32 | 77 | 21 |

| Split | Slots | Present | Absent | Unclear |
|---|---:|---:|---:|---:|
| development | 169 | 122 | 31 | 16 |
| held-out | 311 | 204 | 77 | 30 |

The independent check used the requested3 precedent for a typical current that has only a Max
value: no typical value is stated, so the slot is absent. Both passes had labeled 4 such slots
unclear (component-c01 to c04, `supply_current_typ`). I applied the same rule to them, so they
are absent. No model output existed when I made this change. So the 108 absences are 101 from
both blind passes, 3 from the independent check and 4 from this rule.

## Arms

The frozen manifest names the three arms of requested3:

| Arm | `drop_rounded` | Model calls |
|---|---|---|
| `baseline` | not used | new calls on each split |
| `runner` | off, the default (main arm) | new calls on each split |
| `runner_drop_rounded` | on | none: it replays the recorded calls of `runner` |

## Learning loop

Loop 01 ran all three arms on the 32 development documents on 2026-10-20, on origin/main
ccaf944 (`loop/01.json`, `loop/01/results.json`, `loop/01/RESULTS.md`). The model, transport and
run limits are the same as in requested3, with codex-cli 0.162.1. The baseline made 152 calls and
the runner made 271. `runner_drop_rounded` replayed the runner calls. No document was incomplete,
had a transport error or stopped at `search_limit`.

| Arm | Miss rate | Escapes |
|---|---:|---:|
| baseline | 72.95% (89 of 122) | 1 |
| runner | 72.95% (89 of 122) | 2 |
| runner_drop_rounded | 72.95% (89 of 122) | 2 |

The annual miss rate is 91.11% for the baseline and 93.33% for the runner. The record proposes one
change: #423. The scale check fails on a header such as "(in € million)", and the unit check fails
on items such as "Canadian dollars". This is a decision change, so it needs a new spec version.

Loop 02 ran the three arms on the same 32 documents on origin/main 671c0fb (`loop/02.json`,
`loop/02/results.json`, `loop/02/RESULTS.md`, `loop/02/COMPARE.md`). This code has spec 0.11 with
#423 (74c1a1e) and the runner prompt change #428 (32f2b0e). The configuration is the same as in
loop 01 except the code. The baseline made 149 calls and the runner made 249. No document was
incomplete, had a transport error or stopped at `search_limit`.

| Arm | Kind | Miss rate, loop 01 | Miss rate, loop 02 | Escapes, loop 01 | Escapes, loop 02 |
|---|---|---:|---:|---:|---:|
| baseline | total | 72.95% (89 of 122) | 62.30% (76 of 122) | 1 | 1 |
| baseline | annual | 91.11% (41 of 45) | 66.67% (30 of 45) | 0 | 0 |
| baseline | component | 61.54% (16 of 26) | 61.54% (16 of 26) | 1 | 1 |
| baseline | sbc | 60.00% (21 of 35) | 54.29% (19 of 35) | 0 | 0 |
| baseline | sds | 68.75% (11 of 16) | 68.75% (11 of 16) | 0 | 0 |
| runner | total | 72.95% (89 of 122) | 58.20% (71 of 122) | 2 | 2 |
| runner | annual | 93.33% (42 of 45) | 60.00% (27 of 45) | 0 | 0 |
| runner | component | 61.54% (16 of 26) | 57.69% (15 of 26) | 2 | 2 |
| runner | sbc | 57.14% (20 of 35) | 51.43% (18 of 35) | 0 | 0 |
| runner | sds | 68.75% (11 of 16) | 68.75% (11 of 16) | 0 | 0 |
| runner_drop_rounded | total | 72.95% (89 of 122) | 57.38% (70 of 122) | 2 | 2 |

The table gives only the total for `runner_drop_rounded`; `loop/02/COMPARE.md` has each kind.
The changes lower the miss rate in each arm and add no escape, so loop 02 keeps them. The
most frequent review code of the runner is now `FIELD_CITATION_INVALID`: `diagnose.review_codes`
in `loop/02.json` counts 68 review decisions with this code that carry a right value.

Loop 03 ran the three arms on the same 32 documents on origin/main 7967dde (`loop/03.json`,
`loop/03/results.json`, `loop/03/RESULTS.md`, `loop/03/COMPARE.md`). The one change is the runner
prompt of #441: a field item holds one of the field's aliases, and a repair names the cause
`no_alias`. 840db78 changed only the review tasks. The configuration is the same as in loop 02
except the code. No document was incomplete, had a transport error or stopped at
`search_limit`.

| Arm | Kind | Miss rate, loop 02 | Miss rate, loop 03 | Escapes, loop 02 | Escapes, loop 03 |
|---|---|---:|---:|---:|---:|
| baseline | total | 62.30% (76 of 122) | 59.84% (73 of 122) | 1 | 1 |
| baseline | annual | 66.67% (30 of 45) | 68.89% (31 of 45) | 0 | 0 |
| baseline | component | 61.54% (16 of 26) | 53.85% (14 of 26) | 1 | 1 |
| baseline | sbc | 54.29% (19 of 35) | 48.57% (17 of 35) | 0 | 0 |
| baseline | sds | 68.75% (11 of 16) | 68.75% (11 of 16) | 0 | 0 |
| runner | total | 58.20% (71 of 122) | 55.74% (68 of 122) | 2 | 2 |
| runner | annual | 60.00% (27 of 45) | 64.44% (29 of 45) | 0 | 0 |
| runner | component | 57.69% (15 of 26) | 80.77% (21 of 26) | 2 | 2 |
| runner | sbc | 51.43% (18 of 35) | 17.14% (6 of 35) | 0 | 0 |
| runner | sds | 68.75% (11 of 16) | 75.00% (12 of 16) | 0 | 0 |
| runner_drop_rounded | total | 57.38% (70 of 122) | 55.74% (68 of 122) | 2 | 2 |

The table gives only the total for `runner_drop_rounded`; `loop/03/COMPARE.md` has each kind.
The baseline prompt did not change, so its move from 76 to 73 misses is run noise. The runner
moves by the same 3 misses, but the kinds move apart. `diagnose.review_codes` in `loop/03.json`
counts 22 runner review decisions with `FIELD_CITATION_INVALID` that carry a right value, down
from 68.

The sbc misses of the runner fall from 18 to 6. This is not a gain in field items. Most runner
sbc admits of loop 03 cite no field item, and no runner admit of loop 02 did. I counted this in
the local run cache of the candidates. The repo does not hold that cache, so this count cannot be
checked from the repo.
SPEC §4.6 checks the field only when a candidate cites a field item, so these candidates pass
without one. The other three kinds get worse: annual from 27 to 29 misses, component from 15 to
21 and sds from 11 to 12. In component, the model quotes only the alias, such as "Supply
voltage", and that quote can match a place far from the value.

Loop 03 drops the change (`decide` is `drop` in `loop/03.json`), and #449 reverts #441. The
runner gain of 3 misses is the same size as the baseline noise of 3 misses. Annual, component
and sds get worse, and the sbc gain comes from candidates that cite no field item. The
question of a required field item is in #450.

Loop 04 ran the three arms on the same 32 documents on origin/main c0d2705 (`loop/04.json`,
`loop/04/results.json`, `loop/04/RESULTS.md`, `loop/04/COMPARE.md`). It has no change: #449
reverted #441, so the extraction code is the same as in loop 02. The later merges changed only
the review and store code. Loop 04 records the code that the held-out run freezes. The
configuration is the same as in loop 02 except the code digest. No document was incomplete,
had a transport error or stopped at `search_limit`.

| Arm | Kind | Miss rate, loop 02 | Miss rate, loop 04 | Escapes, loop 02 | Escapes, loop 04 |
|---|---|---:|---:|---:|---:|
| baseline | total | 62.30% (76 of 122) | 62.30% (76 of 122) | 1 | 0 |
| baseline | annual | 66.67% (30 of 45) | 66.67% (30 of 45) | 0 | 0 |
| baseline | component | 61.54% (16 of 26) | 61.54% (16 of 26) | 1 | 0 |
| baseline | sbc | 54.29% (19 of 35) | 54.29% (19 of 35) | 0 | 0 |
| baseline | sds | 68.75% (11 of 16) | 68.75% (11 of 16) | 0 | 0 |
| runner | total | 58.20% (71 of 122) | 61.48% (75 of 122) | 2 | 2 |
| runner | annual | 60.00% (27 of 45) | 62.22% (28 of 45) | 0 | 0 |
| runner | component | 57.69% (15 of 26) | 57.69% (15 of 26) | 2 | 2 |
| runner | sbc | 51.43% (18 of 35) | 60.00% (21 of 35) | 0 | 0 |
| runner | sds | 68.75% (11 of 16) | 68.75% (11 of 16) | 0 | 0 |
| runner_drop_rounded | total | 57.38% (70 of 122) | 60.66% (74 of 122) | 2 | 2 |

The table gives only the total for `runner_drop_rounded`. `loop/04/COMPARE.md` compares each
kind with loop 03. The runner extraction code is the same as in loop 02, so the move from 71 to
75 misses is run noise. Loop 04 keeps the decision of loop 03: `decide` is `drop`.

## Held-out results

The manifest `code_freeze` names b27d3d2, its code digest and `loop/04.json`. Then the three arms
ran one time on the 59 held-out documents on 2026-10-21 (`runs/`, `results.json`, `RESULTS.md`).
The model, transport and run limits are the same as in loop 04, with the installed Codex
account. The held-out run had a limit of 1,500 model calls for all arms together.
`runner_drop_rounded` replayed the runner calls. No document was incomplete, had a transport
error or stopped at `search_limit`.

`COMPARE.md` puts these numbers beside the 0.10 held-out results of `bench/requested3`. The two
sets have different documents, so the comparison is not of the same documents.

| Arm | Kind | Miss rate, 0.10 | Miss rate, 0.11 | Escapes, 0.10 | Escapes, 0.11 | Incomplete, 0.10 | Incomplete, 0.11 |
|---|---|---:|---:|---:|---:|---:|---:|
| baseline | total | 62.30% (190 of 305) | 62.75% (128 of 204) | 2 | 1 | 0 of 111 | 0 of 59 |
| baseline | annual | 73.53% (50 of 68) | 65.12% (56 of 86) | 2 | 1 | 0 of 20 | 0 of 16 |
| baseline | component | 89.39% (59 of 66) | 83.33% (25 of 30) | 0 | 0 | 0 of 18 | 0 of 9 |
| baseline | sbc | 42.11% (40 of 95) | 45.83% (33 of 72) | 0 | 0 | 0 of 23 | 0 of 16 |
| baseline | sds | 53.95% (41 of 76) | 87.50% (14 of 16) | 0 | 0 | 0 of 50 | 0 of 18 |
| runner | total | 68.20% (208 of 305) | 61.27% (125 of 204) | 0 | 1 | 19 of 111 | 0 of 59 |
| runner | annual | 97.06% (66 of 68) | 72.09% (62 of 86) | 0 | 0 | 15 of 20 | 0 of 16 |
| runner | component | 92.42% (61 of 66) | 66.67% (20 of 30) | 0 | 1 | 4 of 18 | 0 of 9 |
| runner | sbc | 43.16% (41 of 95) | 41.67% (30 of 72) | 0 | 0 | 0 of 23 | 0 of 16 |
| runner | sds | 52.63% (40 of 76) | 81.25% (13 of 16) | 0 | 0 | 0 of 50 | 0 of 18 |
| runner_drop_rounded | total | 67.54% (206 of 305) | 60.29% (123 of 204) | 0 | 1 | 19 of 111 | 0 of 59 |

The table gives only the total for `runner_drop_rounded`; `COMPARE.md` has each kind and the
`search_limit` counts. In 0.10, 19 runner documents stopped at `search_limit` (56 fields). In
0.11, none did. In 0.11, the runner misses 125 values and the baseline 128 of 204, and each arm
has 1 escape. The gap of 3 misses is inside the run noise that loop 04 shows, so I do not claim
a difference between the arms.

## Judge calibration (#67)

The Codex judge of `bench/judges/codex` asks one choice for each field of the `runner` arm that
ends in review with at least one candidate. The development split is the calibration part. The
items come from the loop 04 runner output, the code that the held-out run froze.

Two models of the installed Codex account answered each development item two times, at effort
medium: `gpt-6.1-sol`, the runner's model, and `gpt-6-luna`. The answers are in
`judge/answers/`. `judge/results.json` and `judge/RESULTS.md` come from them through
`bench/judges/codex/score.py`. No held-out item, label or output was read. The held-out judge
run needs the maintainer's approval.

The maintainer approved the held-out judge run on 2026-10-21. `judge/freeze.json` freezes
`gpt-6.1-sol` at effort medium, ceiling 0.1 and threshold 0.9 for all kinds, with the digest of
the judge code. I committed it before the first held-out judge call. Then the frozen judge
answered each held-out item two times (`judge/heldout/answers/`). `judge/heldout/results.json`
and `judge/heldout/RESULTS.md` score them at the frozen threshold only, through
`bench/judges/codex/score.py --freeze`. No threshold, prompt or code changed after a held-out
answer.

## Review answers (#234)

#234 asks if a person who sees an item for the first time, with groundgate's reading, gives
answers as good as blind labels. The items come from the held-out run of the `runner` arm. That
run is frozen: `bench/requested/review_items.py` reads its cached results and changes no rule,
prompt or code of the run. No model runs in these steps.

`build` wrote one packet for each of the 59 held-out documents to the store
`.cache/review/store2`. The receipt of each packet must be the recorded receipt of the run, or
`build` stops. Each packet names a reading of its PDF, so the page shows the PDF page with the
value in a box. The store has two kinds of task, and `review/items.json` counts them:

- a review task for each field with a flagged value;
- an audit task for a sample of the admitted values. The sample is the slots with the smallest
  audit hash for the seed in `review/policy.json`. The audit rate of that policy picks the same
  slots.

An audit task looks the same as a review task with one value. The page shows no code and no
outcome until you press `r`. The store holds no label.

I stopped my first session in `.cache/review/store` and started again in
`.cache/review/store2`, without model help. The score reads only `store2`. The answers of the
first session are not scored.

The result is in `review/RESULTS.md`, and the checker's reasons for each disagreement are there
too.

### The steps for the maintainer

Run each command from the root of the repository.

1. Do not open `labels.json`, `loop/` or `review/results.json` before the last answer.
2. Start the page:

   ```bash
   uv run groundgate review serve --store bench/requested4/.cache/review/store2 --reviewer maintainer
   ```

3. Open the URL that the command prints, and answer each item. Press `r` only when you need the
   codes, because the answer records that you saw them. The page records the time and the keys
   of each answer. To stop, press Ctrl-C. The same command shows only the items that have no
   answer.
4. After the last answer, score the answers against the sealed labels:

   ```bash
   PYTHONPATH=bench uv run python -m requested.review_items score --set bench/requested4 \
       --store bench/requested4/.cache/review/store2 --reviewer maintainer
   ```

   If an item has no answer, the command stops before it reads a label. It writes
   `review/results.json` and `review/checks-needed.json`.
5. Give `review/checks-needed.json` to an independent checker. For each disagreement, the file
   names the document, the field and the page, with no answer and no label. The checker labels
   each item blind from the original PDF, and writes `review/checks.json`:

   ```json
   {"checks": [{"task": "sha256:...", "status": "present", "values": [{"value": "85", "unit": "C"}]}]}
   ```

   `status` is `present`, `absent` or `unclear`, as in `labels.json`.
6. Score again with the checks, then write `review/RESULTS.md` from `review/results.json`:

   ```bash
   PYTHONPATH=bench uv run python -m requested.review_items score --set bench/requested4 \
       --store bench/requested4/.cache/review/store2 --reviewer maintainer \
       --checks bench/requested4/review/checks.json
   PYTHONPATH=bench uv run python -m requested.review_items report --set bench/requested4
   ```

An answer agrees with its label when it gives the labeled value and unit, or `not_in_document`
for an absent label. An `unsure` answer and an `unclear` label are not scored. A disagreement is
a wrong answer when the check does not give the answer, and the item is not scored when the
check is `unclear`. The result passes the bar of #234 when the 95% upper bound of the rate of
wrong answers is below 0.05. The results also count the answers that take a value of groundgate
(`confirm` or `choose`) and are not the label, before the checks. They also give the median
time of each group.

This command gives the measures of the review page itself:

```bash
uv run groundgate review measures --store bench/requested4/.cache/review/store2 \
    --set requested4 --split heldout --policy bench/requested4/review/policy.json
```

Do not run `build` on another store or with another groundgate version, because the keys of the
packets and tasks change. A second `build` on the same store stops if it gives other items than
`review/items.json`.

## The development measure of the review page (#463)

#463 asks for a first measure of the review page on the development split, with blind labels.
The page must read the output of the current code, so I ran the three arms again on the 32
development documents on 2026-10-22, on origin/main 3273c30 (`development/runs/`,
`development/results.json`, `development/RESULTS.md`). This code has the stop words of #466
(`groundgate-run/4`) and the review page of #460. The model, transport and run limits are the
same as in loop 04. The baseline made 150 calls and the runner made 243. `runner_drop_rounded`
replayed the runner calls. No document was incomplete, had a transport error or stopped at
`search_limit`.

This run is not a loop record. The code freeze names `loop/04.json` as the last record, and
`loop.py check` refuses a new one. `development/COMPARE.md` puts the run beside loop 04
(`bench/report.py --compare`).

| Arm | Miss rate, loop 04 | Miss rate, 3273c30 | Escapes, loop 04 | Escapes, 3273c30 | Absence hits, 3273c30 |
|---|---:|---:|---:|---:|---:|
| baseline | 62.30% (76 of 122) | 61.48% (75 of 122) | 0 | 0 | 0 |
| runner | 61.48% (75 of 122) | 62.30% (76 of 122) | 2 | 1 | 1 |
| runner_drop_rounded | 60.66% (74 of 122) | 61.48% (75 of 122) | 2 | 1 | 1 |

The miss rates move by 1 value in each arm, which is inside the run noise of loop 04. The runner
has 1 absence hit and 29 unreported absences. #466 alone does not give the absence hits that
#464 waits for.

`bench/requested/review_items.py --split development` builds the review items from this runner
run. It writes `review/development/items.json` and `review/development/policy.json`, with the
audit seed `requested4-463-audit`. The store has 32 packets, 77 review tasks and 30 audit tasks.
The store is not in the old cache: it is in `groundgate-cache-463/review/store-development`,
in the folder that holds the main checkout. An audit answer with no reason seen is a blind
label of the word-box view. The two blind passes labeled from renders of the original PDF pages
and gave the same label on 470 of 480 slots (section Labels). The result compares the agreement
of the review answers on the word-box view with that number.

The result is in `review/development/RESULTS.md`. Of 107 items, 92 are scored: 88 agree with
the label and 4 are wrong. The upper bound of the rate of wrong answers is 0.0967, so the result
does not pass the bar of #234. 30 of 30 blind audit answers agree with the label, so the audit
gives no sign that the word-box view gives less agreement. 10 answers are `unsure`.

### The steps for the maintainer

Run each command from the root of the main checkout, so that `../groundgate-cache-463` is the
store folder. From a worktree, give the store path in full. Do not open `labels.json`, `loop/`,
`development/` or `review/development/results.json` before the last answer.

1. Start the page, open the URL that the command prints, and answer each item:

   ```bash
   uv run groundgate review serve --reviewer maintainer \
       --store ../groundgate-cache-463/review/store-development
   ```

2. After the last answer, score the answers against the sealed labels:

   ```bash
   PYTHONPATH=bench uv run python -m requested.review_items score --set bench/requested4 \
       --split development --store ../groundgate-cache-463/review/store-development \
       --reviewer maintainer
   ```

3. Give `review/development/checks-needed.json` to an independent checker, as in step 5 of the
   held-out steps. The checker writes `review/development/checks.json`.
4. Score again with the checks, then write `review/development/RESULTS.md` from
   `review/development/results.json`. `report` writes the table again and keeps the sections
   from the line "`report` does not write the sections below." to the end of the file:

   ```bash
   PYTHONPATH=bench uv run python -m requested.review_items score --set bench/requested4 \
       --split development --store ../groundgate-cache-463/review/store-development \
       --reviewer maintainer --checks bench/requested4/review/development/checks.json
   PYTHONPATH=bench uv run python -m requested.review_items report --set bench/requested4 \
       --split development
   ```

5. Print the measures of the page:

   ```bash
   uv run groundgate review measures --set requested4 --split development \
       --store ../groundgate-cache-463/review/store-development \
       --policy bench/requested4/review/development/policy.json
   ```

   With one reviewer, `review measures` gives no agreement pair, because a pair needs a blind
   label of another reviewer. The agreement with the sealed labels comes from
   `review/development/results.json`.

## What comes next

The learning loop runs on the development split only (`bench/requested/loop.py`). It writes one
record for each iteration in `loop/`, and it never opens a held-out output. The code freezes
before the first held-out model call. One PR writes the commit, the `code_sha256`, the last loop
record and the held-out configuration digest into the manifest. A code change after the freeze
voids it.
