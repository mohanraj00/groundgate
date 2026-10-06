# Changelog

Versions follow [SemVer](https://semver.org). A change to how any candidate is decided is a new
spec version, and receipts name the spec version they were decided under.

## 0.4.0 (2026-10-06)

Spec 0.4. Receipts name `"groundgate": "0.4"` and every digest uses the `groundgate/0.4:` prefix, so all
hashes differ from 0.3.0. With no `judge` in the policy, every decision is the 0.3 decision: all
earlier vectors and every bench set rescore unchanged.

- Recorded judgments (#116). A packet can carry `judgments`: answers that a judge gave about one
  candidate, recorded before the decision. The policy's new `judge` block names the one judge and
  model version whose answers apply, and their thresholds. groundgate never calls the judge.
  - `key`: on a candidate flagged `KEY_NOT_AT_VALUE`, the candidate's key at or above
    `clear.KEY_NOT_AT_VALUE` removes the flag and records `MODEL_CLEARED`; another key or none at
    that probability adds `MODEL_DOUBT`.
  - `field_match`: a probability below `doubt.field_match` adds `MODEL_DOUBT`.
  - A judgment never overturns a rejection and never admits a candidate with another flag. The
    receipt lists each judgment that applied, and `verify` takes the same judgments.
  - Vectors `18-judgments-key`, `18b-judgments-field`, `18c-judgments-both`, and 8 invalid
    packets.
- The judge block is experimental. Its one measure on real extractor output is the key clear on
  10-K filings (`bench/sec/results.json`, #120): of 51 right `KEY_NOT_AT_VALUE` flags on the test
  part, the built-in judge at 0.5 cleared 34 with 0 escapes, and 0.5 is also the threshold that
  the FDA labels gave (#100). The test part held only 2 wrong flags, so the escape side rests on
  little data. The field doubt caught no wrong value on the same filings. groundgate ships no
  thresholds: a threshold belongs to one model and one kind of document.
- `groundgate-calibrate` (#112, #115, #119) is a separate package in `calibrate/`. It measures a
  judge's thresholds on your own documents, writes the policy's `judge` block, and writes the
  recorded judgments for production. One judge is built in at this time. Other judges come in as
  plug-ins (entry point group `groundgate.judges`, #124). It is not on PyPI yet (#122).

## 0.3.0 (2026-10-05)

Spec 0.3. Receipts name `"groundgate": "0.3"` and every digest uses the `groundgate/0.3:` prefix,
so all hashes differ from 0.2.0. Each rule that changes how real text reads was measured on a new
set of documents that no rule was written from, labeled blind before scoring: the pattern, dots,
caps, India, keys and tables sets in `bench/`. The digit rule (#94) takes values away only, and
every set rescores unchanged under it. Every number below comes from the `results.json` of its
set.

- Set 2 is rescored on the released 0.2.0 wheel, the way the v0.1 set is rescored on 0.1.0, so
  its published numbers stay spec 0.2's.
- Changes (#51): a change word may stand up to six words before `from`, and every form of it
  counts. "reducing the annual fee from $1,200 to $950" and "the limit increases from $70,000 to
  $72,000" are now changes, so the new value is no longer flagged as a range end. The words
  between must start with a determiner and hold no digit, punctuation, preposition or range word,
  so "increased body weight from 20 to 40 kg" stays a range. Vector `07e-change-at-a-distance`.
- Sentence ends (#63): for the qualifier window, the dot of a listed abbreviation such as `Rs.`,
  `approx.`, `p.m.` or `U.S.` no longer ends a sentence when a lowercase letter, a digit or a
  currency sign follows. "up to Rs. 50,000" is now qualified, and in "from 6 p.m. to 8 p.m." 8 is a
  range end. A wider qualifier window can only add a flag. Key scope and the unit search still end
  at every such dot, so a join never lets a key or unit of one sentence reach a value in the next.
  `approx` joins the `approx` qualifiers, so "approx. 5 mg" is flagged. Vector
  `07f-abbreviation-dots`. Measured on 116 abbreviation dots in documents no rule was written from
  (`bench/dots`): of the 107 where the sentence goes on, spec 0.2 cuts all 107 and 0.3, with the
  #77 rule below, cuts 10. 0.3 joins none of the 9 real sentence ends.
- Sentence ends (#77): for the qualifier window, the dot of `U.S.` no longer ends a sentence, and
  the dot of `No.` or `Nos.` no longer ends one before a code such as `DEA-1086`. A blank line
  still ends the sentence. Vector `07g-us-and-number-dots`, and `07f-abbreviation-dots` a5 is now
  qualified. Measured on 105 such dots in documents no rule was written from (`bench/caps`): of
  the 102 where the sentence goes on, 0.3 before this rule cut all 102 and now cuts 3, and 0.3
  joins none of the 3 real sentence ends.
- Blank lines (#63): a blank line may hold a carriage return, so `\r\n\r\n` ends a sentence
  too.
- Keys (#52): when a value's sentence mentions no key, the key of the nearest earlier mention no
  longer reaches it past a label line: a short line of its own between blank lines, such as
  "Treatment of DVT and PE:" or "Adults". The value is at no key, so a keyed candidate goes to
  review. A heading that is a key mention still reaches past its blank line. Vector
  `17c-label-lines`. Measured on 100 doses in 17 FDA labels no rule was written from
  (`bench/keys`), 93 of them labeled: the rule stops a wrong key at as many doses as it sends a
  right key to review. Half of the right keys it loses are a bullet on a line of its own (#86).
  With the table rule below, a wrong key reaches 4 of those doses, down from 28 with spec 0.2, and
  every right key reaches 38, down from 58.
- Keys (#87): a sentence with 3 or more line breaks that mentions 2 or more keys is a table
  sentence. A value in it is at the keys mentioned on its own line, or at no key when the line
  mentions none, so a key swapped within a flattened table goes to review. Before, every value
  in such a table was at every key it mentioned. Vector `17d-table-sentences`, and in
  `17b-keyed-tables` 40 mg on the hypertension row is no longer at heart failure. Measured on all 62
  doses in such tables in the FDA labels of the Part D ranking that no rule was written from
  (`bench/tables`): a wrong key reaches 0 of them, down from 60 with spec 0.2, and every right key
  reaches 3, down from 55. In these tables a value's line rarely names its condition, so the right
  keys go to review with the wrong ones.
- Digits (#94): in the number rules a digit is an ASCII digit, 0 to 9. Python's `\d` matched
  every Unicode digit, so `२०००` was read as 2000, and an implementation in a language whose `\d`
  is ASCII decided the same document differently. A number in other digits now has no token, nor
  do ASCII digits next to it, and a candidate value in them is invalid. Where a digit only stops a
  reading or adds a flag, as in a per-unit, any Unicode digit still counts, so other digits can
  block a value but never make one. Vector `03c-ascii-digits`. The 322 benchmark documents
  hold no other digits, so every set rescores unchanged.
- Numbers (#59): a number grouped the Indian way, the last three digits and then pairs, has its
  value: `2,00,000` is 200000 and `1,00,00,000` is 10000000, in the document and in a candidate's
  `value`. A mix of the two groupings, such as `1,23,456,789`, still has none. Vector
  `03b-indian-grouping`. Measured on the India set (#76): 101 tokens with a comma in 41 SEBI
  circulars, labeled before scoring. Spec 0.2 rejects 14 of the 88 tokens that are one number,
  and spec 0.3 rejects 0. Both specs give a value to 1 of the 13 tokens that are not one
  number, the same token.

## 0.2.0 (2026-10-03)

Spec 0.2. Receipts name `"groundgate": "0.2"` and every digest uses the `groundgate/0.2:`
prefix, so all hashes differ from 0.1.0. The rules came from the v0.1 escapes, so they were
measured on a second set of 101 documents picked before anyone read them (`bench/set2`). Pooled
over 14 runs on the 74 documents checked in full, wrong extractions admitted without review fell
from 30.7% (253/823) under spec 0.1 to 8.8% (72/823), correct extractions rejected from 11.3%
(690/6080) to 0.5% (28/6080), and extractions sent to a person rose from 28.2% (1950/6903) to
39.6% (2730/6903).

- `verify` reports a receipt decided under another spec version as one problem, instead of a
  list of hash mismatches.
- Qualifiers (#5): where two overlap, only the longer applies, so "no more than" is `le` and no
  longer also `gt`. In 0.1 it flagged `le` fields on the spec's own `le` phrase. A negation
  directly before a `gt`, `lt`, `ge` or `le` qualifier inverts it: "must not be more than" and
  "may not exceed" are `le`, "cannot be less than" is `ge`. `exceed` joins `gt`, so an `eq` field
  is now flagged on "do not exceed". Vector `07b-negated-qualifiers`.
- Ranges (#14): one unit or scale word between the first number and `to`, `through`, `thru` or
  `and` no longer hides the upper end. In 0.1, "30 mg to 45 mg" flagged 30 as a range but
  admitted 45. Vector `07c-range-unit-words`.
- Changes (#4): after a change word such as "increased" or "reduced", "from X to Y" is a change.
  Y is the new value and no longer flagged as a range end; X keeps the range flag, so a field
  that takes the old value still goes to review. "run from 7 to 8 hours" is still a range.
  Vector `07d-change-not-range`.
- Scale words (#6): a number followed by a scale word also has its scaled value, so 1000000
  matches "$1 million" and is admitted with no flag. In 0.1 it was rejected. A candidate that
  gives the written value (1) keeps `SCALE_WORD`. Vector `08b-scaled-values`.
- Per-units (#3): the first suffix after a number decides its unit, and a suffix followed by a
  body-size or volume denominator (`/kg`, `/m2`, `per kilogram`, `/5 mL`) is not that unit. In
  0.1, "1.6 mcg/kg/day" passed as 1.6 mcg, and "10 mg/kg (maximum 500 mg)" passed as 10 mg
  through the later "500 mg". "200 mg/day" is still mg. A weight-based dose needs its own unit
  code, such as `mg/kg`. Vector `04b-per-units`.
- First unit (#26): the first suffix of any unit in the table, built-in or the schema's, decides
  a number's unit. In 0.1, "10 mcg (maximum 500 mg)" passed as 10 mg, because the `mg` of 500
  was within 24 code points, and "2 L in 4 hours" passed as 2 hours. "25 or 50 mg" still gives 25
  its mg. Vector `04c-first-unit`.
- Keyed fields (#2): a field can list `keys`, the conditions its values belong to (such as a
  drug's indications), and each candidate names one as `key`. A missing or unknown key rejects
  `KEY_INVALID`, a new step 7, so evidence checks are now steps 8 to 11. A key is at a value when
  the value's sentence mentions it, or, when the sentence mentions none, when it is the nearest
  key mentioned before the value, such as a heading. Otherwise the new flag `KEY_NOT_AT_VALUE`
  applies. `CONFLICTING_CANDIDATES` works per field and key, decisions echo the `key`, and the
  LangExtract adapter passes a `key` attribute through. In 0.1, a dose that differs by
  indication was one field, where the doses conflicted, or one field per indication, where
  nothing checked the indication. Vectors `17-keyed-fields` and `17b-keyed-tables`.
- `extract` (#30): the same PDF always gives the same text. pdfminer broke ties between equally
  distant text boxes by memory address, so a chart on one IRS page came out in two orders. All 90
  PDF texts in both benchmark sets are unchanged.
- A second benchmark set (#1): 101 public-domain FDA labels, NTSB reports, IRS publications and
  Federal Register rules, picked by rules frozen before anyone read them, with person-checked
  gold and the same seven models. `bench/score.py --set bench/set2` decides every candidate under
  spec 0.2 and, through `bench/decide.py`, under the released 0.1.0 wheel, side by side. Tables
  and every escape are in `bench/set2/RESULTS.md`.

## 0.1.0 (2026-09-29)

First release. Implements spec v0.1.

- `admit` and `verify`: deterministic admission with ten rejection codes, five flags, required
  field coverage and re-anchoring, and receipts hashed over RFC 8785 canonical JSON.
- `groundgate extract`: PDF (with `[pdf]`), HTML, XML and text to NFC text, with page and word
  boxes for PDFs. Text a reader can't see is dropped, and superscripts are marked.
- A LangExtract adapter that checks each extraction's value and unit at the place LangExtract
  aligned it.
- `groundgate report`: a self-contained HTML review page that re-derives the receipt before it
  renders.
- 16 conformance vectors and 6 invalid packets, language-neutral, so another implementation can
  prove it agrees.
- A benchmark on 30 public-domain FDA, NTSB and IRS documents with person-checked gold and seven
  models: [bench/RESULTS.md](https://github.com/mohanraj00/groundgate/blob/main/bench/RESULTS.md).
