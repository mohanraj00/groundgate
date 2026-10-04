# Changelog

Versions follow [SemVer](https://semver.org). A change to how any candidate is decided is a new
spec version, and receipts name the spec version they were decided under.

## Unreleased

Spec 0.3, in progress. Receipts name `"groundgate": "0.3"` and every digest uses the
`groundgate/0.3:` prefix, so all hashes differ from 0.2.0. The decision changes are tracked in
milestone 0.3.

- Set 2 is rescored on the released 0.2.0 wheel, the way the v0.1 set is rescored on 0.1.0, so
  its published numbers stay spec 0.2's.
- Changes (#51): a change word may stand up to six words before `from`, and every form of it
  counts. "reducing the annual fee from $1,200 to $950" and "the limit increases from $70,000 to
  $72,000" are now changes, so the new value is no longer flagged as a range end. The words
  between must start with a determiner and hold no digit, punctuation, preposition or range word,
  so "increased body weight from 20 to 40 kg" stays a range. Vector `07e-change-at-a-distance`.
- Sentence ends (#63): the dot of a listed abbreviation such as `Rs.`, `approx.`, `p.m.` or
  `U.S.` no longer ends a sentence when the next word starts with no uppercase letter. "up to
  Rs. 50,000" is now qualified, and in "from 6 p.m. to 8 p.m." 8 is a range end. `approx` joins
  the `approx` qualifiers, so "approx. 5 mg" is flagged. Vector `07f-abbreviation-dots`.

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
