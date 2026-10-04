# Pattern set: the change rule

This set measures one rule, the change rule of SPEC §4.2 that #51 widens (#58). The rule decides
one thing: whether Y in "from X to Y" is the new value of a change or the end of a range. So
this set has no gold facts and no model runs. It has every "from X to Y" pair in documents that
v0.1 and set 2 did not use, each labeled by a person as a change, a range or neither.

These rules were fixed before anyone read a document of this set. `pairs.py` is the same rules
as code. Its `pick` step looks only at titles, section codes, page counts and pair counts, and
prints no text.

```bash
uv run python bench/patterns/pairs.py pick --count     # how many pairs each kind finds
uv run python bench/patterns/pairs.py pick             # write sources.json, selection-log.json
uv run python bench/fetch.py --set bench/patterns      # download, verify, write docs/
uv run python bench/patterns/pairs.py pairs            # write pairs.json from docs/
uv run python bench/patterns/pairs.py label            # label them in the terminal
```

## A pair

`from`, a number, at most one word of up to 12 characters with no digits, a range connector
(`to`, `through`, `thru`, `-` or `–`) and a number. Each number may have up to 4 characters
before it, such as `$`. This is the range pair of SPEC §4.2 with its first number after `from`.
It has no change word in it, so the pick does not depend on the rule it measures.

## What is excluded

Every drug, IRS publication and Federal Register rule that v0.1 or set 2 used. The drugs and
publications are excluded by name and number, as in set 2, so a newer revision of a used
document is not taken either.

## Order

IRS and the Federal Register take documents in a fixed order until each has 70 pairs. The first
5 pairs of a document count, so no one document fills a kind.

- **FDA:** generic names in the order of the set-2 Part D ranking, with the set-2 label rules
  ([SELECTION.md](../set2/SELECTION.md)), up to rank 400. The text is sections 1 and 2
  (indications, dosage). These sections rarely hold a pair: the first count found 5 pairs in
  the first 336 ranks, so FDA stops at a rank and not at a pair count.
- **IRS:** publications in numeric order. The text is the pages that hold the first 5 pairs.
- **Federal Register:** final rules of at most 20 pages, published 2025-07-01 to 2025-12-31,
  newest first. Set 2 took rules from 2026. The text is the pages that hold the first 5 pairs,
  and a rule whose pages are the same text as a rule taken before is skipped.

## Labels

`pairs.py label` shows each pair in its sentence, with X and Y marked, and asks one question: is
Y the new value that replaces X (`change`), the end of a range (`range`), or neither (`neither`:
a form number, a phone number)? It never shows how a spec reads the pair. The labels go
in `labels.json`.

A clock time is two numbers: in "8:30 p.m. to 10 p.m.", the pattern can take 30 (minutes) as X
and 10 (hours) as Y. Such a pair is `neither`, because X and Y are not two values of one
quantity. A pair of whole hours, "6 p.m. to 7 p.m.", is a `range`.

## Scoring

```bash
uv run python bench/patterns/pairs.py score            # RESULTS.md and results.json
```

[RESULTS.md](RESULTS.md) reads each Y under spec 0.2 (the released 0.2.0 wheel) and spec 0.3 (the
core in this repository), and counts each reading against the label. Y is read as a range end
or not. A range end goes to review with `QUALIFIED_VALUE`. The change rule was fixed at 470a2e6
(#62) before anyone read a pair. CI runs `score --check`.

What it found:

- Spec 0.3 reads 9 pairs differently from 0.2, and all 9 are changes. The wider rule moves no
  range to a change. Of the 31 changes that 0.2 sends to review, 22 still go to review.
- Causes of the 22: "extend" (6), "going from" (3) and "expand" (1), which are not change words;
  a digit (2), a parenthesis (2) or "for" (1) between the change word and `from`; a list that
  continues after a comma (2); the change word in an earlier clause (2); a word broken by a line
  end ("in- creased", 1); a period of years (1); and a chain of three values (1).
- The 15 ranges that both specs read as changes are all clock times. "p.m." ends the sentence,
  so Y is in a sentence of its own (#69).

Some pairs are the same text in two documents: IRS publications 2104 and 2104-C share a
paragraph, and so do several Federal Register rules about the same safety zone. Each pair counts
once for each document that holds it.

## Typed-decision models (#65)

```bash
uv run python bench/patterns/triage.py report   # TRIAGE.md from triage-laya.json, triage-jev.json
```

[TRIAGE.md](TRIAGE.md) asks two typed-decision models the same Choice question about each pair
(change, range or neither), with the text the label tool showed: Laya 0.3.26 on the CPU, and
Jev (`jev-1.13.0`) through the TypeSafe API. `triage.py` has the commands that ask them. The core
never calls a model, so this only asks whether a model could sort the reviews. The question was
written once, before the first run.

- Jev matches 134 of 147 labels. As a review aid at confidence 0.99, it marks 14 of the 22
  changes that spec 0.3 sends to review and no other pair. It is not deterministic: on a second
  run, 2 choices changed.
- Laya matches 74 of 147 labels, and at 0.99 it marks none. Its checkpoint ships confidences
  that Laya itself calls uncalibrated. It gives the same answers on a second run.

The labels were re-checked because of Jev (below), so Jev's match count is not blind. Its
answers did not change after the re-check.

## Labels changed after scoring

The labels were made blind. They changed three times after that, and `recheck.json` records the
second and third rounds.

1. After the first scoring showed the pairs, 5 labels: `irs-p1187:1426` and `irs-p1187:3094`
   ("increase amounts from 50 to 99 cents to the next dollar") from change to range, and
   `irs-p926:1855`, `fr-2025-23920:3361` and `fr-2025-23860:3725` from range to neither, because
   X is the minutes of a clock time.
2. Jev disagreed with 22 labels, and 5 of them looked like label errors ("extends ... from 18
   months to 24 months"). So the 22 pairs and 22 pairs where Jev agreed, drawn with a fixed seed,
   were labeled again in a shuffled order, without the first label or any model answer. 16
   labels changed: 12 of the 22 where Jev disagreed, and 4 of the 22 where it agreed.
3. 5 labels from the re-check were slips, and were set back: `irs-p946:2177` ("is reduced from
   $180,000 to $135,000") and `fr-2025-23837:10822` to change, `irs-p1187:1426` and
   `irs-p1187:3094` to range, and `fr-2025-22545:7860` to change, so it matches the same sentence
   at `:199`.

So a person labeling this one question is not consistent: the re-check changed 4 of the 22
labels that a model had confirmed, and all 4 went back on review. No label change moves the 9
pairs that 0.2 and 0.3 read differently: all 9 were labeled change every time.
