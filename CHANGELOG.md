# Changelog

Versions follow [SemVer](https://semver.org). A change to how any candidate is decided is a new
spec version, and receipts name the spec version they were decided under.

## Unreleased

Spec 0.2, in progress. Receipts name `"groundgate": "0.2"` and every digest uses the
`groundgate/0.2:` prefix, so all hashes differ from 0.1.0. The decision changes are tracked in
milestone 0.2.

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
