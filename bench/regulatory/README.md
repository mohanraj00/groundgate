# Regulatory texts: a held-out family

Status: the members, their source pins and the split are frozen (#641). No label exists yet, and
no model call has run on this set. The claim on this family is #686.

The set has 14 CFR parts: fee rules, rate tables, definitions and numbered method steps. Today
the other bench sets have business documents. This family measures the gate on the texts of a
knowledge source.

| Split | Parts |
|---|---|
| calibration | 10 CFR 171, 19 CFR 24, 36 CFR 71, 46 CFR 401, 46 CFR 404 |
| heldout | 7 CFR 800, 8 CFR 106, 9 CFR 391, 10 CFR 170, 14 CFR 187, 33 CFR 402, 37 CFR 201, 49 CFR 107, 49 CFR 1002 |

The family profile is calibrated on the 5 calibration parts only. No rule and no threshold is
tuned on the 9 held-out parts.

## Selection

The owner approved all 14 parts of the candidate list in #641 on 2026-11-17. I selected them from
publisher metadata only: the eCFR title list, the eCFR structure API of 2026-11-12, and the
Federal Register API. None of the 84 Federal Register final rules in set 2, `bench/caps`,
`bench/dots` and `bench/patterns` amends one of the 14 parts.

## Sources

Each member is the XML of one part at 2026-11-12 from the eCFR versioner API.
`manifest.json` records the URL, the byte size, the SHA-256 of the XML and of the reader text,
and the citation and the heading of the part. The parts are US government works (17 U.S.C. 105).
The XML and the reader text stay in local work storage.

```bash
uv run python bench/regulatory/sources.py --out bench/regulatory/.cache/sources --fetch
```

This command downloads the parts again, does the checks, and writes `manifest.json` and
`source_checks.json`. Two downloads on 2026-11-17 gave the same bytes. The reader text comes
from `groundgate.read` at the code digest in `reader_text`.

## Source checks

`source_checks.json` has the checks of each part:

- The identity: the root is the part, and the citation and the heading match the approved list.
- The section count: it is equal to the count of the list for all 14 parts.
- The text and the language: the reader text is not empty, and it is English.
- The notices: the script finds each place that says copyright, reproduction or permission. I
  read them. Each one is regulation text, for example a rule on copies of certificates. No part
  has a notice of the publisher, so no part is on hold.

## Split

The seed is the SHA-256 of the source digests in member order, one on each line. The 5 ids with
the lowest SHA-256 of the seed, a line feed and the id are the calibration parts. Nobody can
choose the seed after the download, and the seed came before any label.

## Labels

Not started. Two blind label passes come from two different agent harnesses. A second blind
check reads each absence again. The owner decides each disagreement in `bench/label`. All labels
are sealed before any model output on this set.
