# Benchmark set 2: how the documents are picked

Set 2 measures spec 0.2 (#1). These rules were fixed before anyone read a set-2 document, and
this file is frozen at the commit recorded in #1. `bench/pick.py` is the same rules as code.
It only looks at titles, section codes, page counts and pattern matches, and prints no text.

```bash
uv run python bench/pick.py --count   # how many documents each group finds
uv run python bench/pick.py           # write sources.json and selection-log.json
```

`selection-log.json` lists every candidate the walk looked at, and why it was taken or skipped.

## What is excluded

Nothing from v0.1 or from building groundgate. That is excluded by drug and by publication
number, not by file, because generic labels copy the reference label's text and a new revision
of a publication keeps most of the old one.

- Drugs: amlodipine, atorvastatin, escitalopram, gabapentin, levothyroxine, lisinopril,
  losartan, metformin, metoprolol (succinate and tartrate), sertraline, simvastatin.
- IRS publications 15, 15-B, 463, 501, 505, 554, 560, 571, 590-A, 596, 970.
- NTSB report ids up to 192717.

## FDA drug labels

**Order.** Generic names from CMS "Medicare Part D Spending by Drug", data year 2024
([file](https://data.cms.gov/sites/default/files/2026-06/98218f98-166c-4723-8438-c344a4ef96a6/DSD_PTD_RY26_P04_V10_DY24_BGM.csv),
SHA-256 `5dcc9d7b…c2a55`). Total 2024 claims are summed over each brand's "Overall" row, per
generic name, highest first. The walk stops at rank 150. It skips combinations (a `/` in the
name), the excluded drugs, and a name whose first word was already taken, so each drug is
used once.

**Label.** DailyMed search for the generic name, with HCl and HBr spelled out, newest first. The
first result that meets all of these is the label:

- its title starts with the name's first word and names a tablet or capsule;
- its title has no " AND " or "/", so it has one ingredient;
- it has section 1 (LOINC 34067-9), section 2 (34068-7) and section 3 (43678-2).

At most 10 matching results are tried. A drug with none is skipped; older labels without the
numbered sections are the usual reason. DailyMed's order changes as labels are republished, so
the pinned hash, not the search, defines the document.

**Groups.** A label can be in more than one.

| Group | Takes | Until |
|---|---|---|
| general | every label, in rank order | 10 labels |
| keyed (#2) | labels whose section 1 has at least 2 titled subsections | 15 labels, counting general ones |
| weight-based (#3) | labels whose section 2 matches the pattern below at least 3 times | 12 labels, counting the others |

```
(?<![A-Za-z])(?:mg|mcg)\s*(?:/|per)\s*(?:kg|kilogram|m2|m²)(?![A-Za-z])   (case-insensitive)
```

A single match is usually a passing mention, not a dosing table, so it takes 3.

**Text.** Sections 2 and 3, as in v0.1. The key list for keyed fields is the section 1
subsection titles without their numbers. It is stored in `sources.json`, not in the text.

## NTSB aviation reports

Report ids from 192718 up, the v0.1 rule: the first 10 whose PDF starts with "Aviation
Investigation Final Report" and has 8 pages or fewer. A 404 means there is no report. Any other
download failure is retried and then stops the walk, so a report is never skipped because a
server was slow. Text: the whole report.

NTSB is the negative control. No 0.2 rule should change a decision on it.

## IRS publications

**Order.** English publications from the IRS forms and publications list, in numeric order
(1, 3, 5, 15-A, 15-T, 16, 17, ...). Language versions, marked "(SP)", "(ko)" and so on, are
left out. Circulars such as "Publication 15 (Circular E)" are in.

**General.** The first 10 with at least 8 dollar amounts (`\$\s?\d`) on pages 1 and 2, the v0.1
rule. Text: pages 1 and 2.

**Targeted.** The other publications, in the same order. Each page is matched against three
patterns, all case-insensitive, and each wider than the rule it tests:

| Group | Tests | Pattern |
|---|---|---|
| change | #4 | `\bfrom\s+\$?\d[\d,.]*(?:\s*(?:million\|billion\|percent\|%))?\s+(?:to\|through)\s+\$?\d` |
| negation | #5 | `\b(?:not\|no\|cannot\|can't\|never)\s+(?:be\s+)?(?:more\|greater\|less\|fewer)\s+than\b[^;]{0,20}?\d`, or `\b(?:not\|cannot\|can't)\s+exceed\b[^;]{0,20}?\d` |
| scale | #6 | `\$\s?\d[\d,.]*\s+(?:thousand\|million\|billion\|trillion)\b` |

The change pattern matches any "from N to N", so real ranges that must still be flagged are
in the set too.

A group is open until its counted matches reach 40. A publication joins when a page matches an
open group. Its text is the first 3 such pages. Matches of every group on those pages count,
but at most 5 per group from one document, so no single document fills a group. The walk stops
when all three groups are closed or 25 publications have joined.

## Federal Register

The fallback for a group the IRS walk leaves open. CBO cost estimates were the first choice,
but cbo.gov refuses scripted downloads.

Final rules (type RULE) from the Federal Register API, published 2026-01-01 to 2026-09-30, at most
20 pages long, newest first, ties by document number. Federal Register documents are US
government works. The PDF comes from govinfo.gov. The same patterns and counting apply, with
one page per document, the first that matches an open group, because a Federal Register page
holds about 7,000 characters. The walk stops when every group is closed or 25 documents have
joined.

Short rules share printed pages, so two rules can select the same page. A document whose
selected text is identical to one already taken is skipped. That rule holds for the IRS walk
too, where it never fires.

## Fields

Fields are drafted per document after spec 0.2 is frozen (#10), under these rules:

- FDA: `starting_dose` (mg, eq) and `max_daily_dose` (mg, le), keyed by indication from the key
  list; `pediatric_min_age` (years, ge); `hepatic_starting_dose` (mg); `strengths` (mg,
  multiple, tablets and capsules only). Weight-based labels add a per-kg dose field in the
  label's own unit.
- NTSB: the twelve v0.1 fields.
- IRS, general: v0.1-style fields, with one absent field per document.
- IRS and Federal Register, targeted: one field for every amount in a matched sentence (for
  "from X to Y", both X and Y), and one absent field per document.
- The comparator follows what the field means, not the wording: a limit is `le`, a threshold
  to reach is `ge`, anything else is `eq`.

## Feasibility pass

`pick.py --count` ran on 2026-09-30, before the rules were frozen, and reported only counts.
Four rules changed because of it:

- Keyed labels need titled subsections. One label had untitled ones and would have had no key
  list.
- Weight-based labels need 3 matches. 5 of the first 12 had only 1 or 2, which reads as a
  passing mention, not weight-based dosing.
- No document counts more than 5 matches per group. Without the cap, one publication supplied 48
  of the 49 scale matches.
- The fallback is the Federal Register. CBO refuses scripted downloads, and after 25 IRS
  publications the change group had 11 counted matches.

What the rules pick:

| Group | Documents | Notes |
|---|---:|---|
| FDA general | 10 | |
| FDA keyed | 15 | quota met at Part D rank 145 of 150 |
| FDA weight-based | 12 | 31 FDA labels in all, the groups overlap |
| NTSB | 10 | ids 192719 to 192731 |
| IRS general | 10 | |
| IRS targeted | 25 | change 11, negation 42, scale 33 counted matches |
| Federal Register | 25 | brings change to 38, negation to 50, scale to 60 |

Change closes at 38, two short of 40, because the Federal Register walk reached its cap. Its
38 matches come from 27 documents, negation's 50 from 26 and scale's 60 from 19.

101 documents, about 855,000 characters of text: 3.9 times v0.1.

## Changes after the freeze

Each change here is noted on #1.

- #29: the first walk took three pairs of Federal Register rules whose selected page was the
  same printed page: 20036 and 19963, 19173 and 19143, 18911 and 18830. The rule above was
  added and the walk ran again from cached downloads. It dropped 19963, 19143 and 18830 and took
  17116, 17400 and 17429. Nothing outside the Federal Register changed.
- #29: `fetch.py` took a label section a second time when it was nested inside a section already
  taken with the same LOINC code. The texts of apixaban, potassium and lamotrigine lost the
  repeat. The selection did not change: the weight-based counts are the same either way, and
  the v0.1 label texts are byte-identical.
