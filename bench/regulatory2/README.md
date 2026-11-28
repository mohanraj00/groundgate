# Regulatory texts: a second held-out split

Status: the owner approved the member list on 2026-11-27 (#750). The 14 sources pass their
checks. The 65 slots are drawn and pinned. The label passes come next.

The held-out split of [`bench/regulatory`](../regulatory/README.md) is spent: the 0.17 claim
(#686) and the escape analysis (#709) used it. #735 changed how the bench ends a section
passage, and #736 (cause 1) changed how a table goes to review. Each fix needs a measure on
parts that no rule was written from. This folder is that split.

## Members

All 14 members are held-out. The fields, the field rules, the slot draw and the label method
are the same as in `bench/regulatory`. The profile comes from the 5 calibration parts of
`bench/regulatory`, so this split has no calibration part.

| Part | Heading | Sections | Size | Reason |
|---|---|---:|---:|---|
| 9 CFR 130 | User Fees | 7 | 38 KB | Definitions, and hourly rate and minimum user fees |
| 10 CFR 903 | Power and Transmission Rates | 12 | 24 KB | Definitions, and numbered procedure steps for rate adjustments |
| 12 CFR 8 | Assessment of Fees | 5 | 31 KB | Semiannual assessment and fees for special examinations |
| 14 CFR 389 | Fees and Charges for Special Services | 13 | 23 KB | Fees for services and a schedule of processing fees |
| 18 CFR 381 | Fees | 20 | 24 KB | Definitions, annual adjustment of fees, and fees by filing type |
| 21 CFR 1150 | User Fees | 9 | 16 KB | Definitions, class allocation and assessment sections |
| 22 CFR 22 | Schedule of Fees for Consular Services | 7 | 40 KB | One long schedule of fees |
| 25 CFR 514 | Fees | 17 | 17 KB | Fee rates, a maximum fee rate and the calculation of the annual fee |
| 29 CFR 4006 | Premium Rates | 7 | 30 KB | Definitions, premium rates and the method for unfunded vested benefits |
| 36 CFR 1258 | Fees | 9 | 17 KB | Definitions and the calculation of fees for products |
| 40 CFR 1027 | Fees for Vehicle and Engine Compliance Programs | 11 | 37 KB | Fee amounts by certification type, and definitions |
| 43 CFR 3834 | Required Fees for Mining Claims or Sites | 9 | 6 KB | Maintenance and location fees and their adjustment |
| 49 CFR 594 | Schedule of Fees Authorized by 49 U.S.C. 30141 | 10 | 19 KB | Definitions and one fee for each section |
| 49 CFR 1510 | Passenger Civil Aviation Security Service Fees | 11 | 15 KB | Definitions and security service fees |

The spares are 7 CFR 354 (user fees for import and export services) and 8 CFR 286
(immigration user fee). If the source check puts a member on hold, the first spare takes its
place, and the owner approves the change on #750 before the split.

The section count includes the reserved sections, as the XML counts them. The size is the
eCFR structure size on 2026-11-24.

## Selection

I selected the members on 2026-11-27 from publisher metadata only:

- the eCFR title list, up to date as of 2026-11-24;
- the eCFR structure API of 2026-11-24, for the part headings, the section headings, the
  section counts and the sizes;
- the Federal Register API, for the `cfr_references` of the 462 Federal Register documents
  that a file under `bench/` names.

The rule: a part heading about fees, rates or charges, 2 to 150 sections that are not
reserved, and section headings that name fees, rates, schedules, definitions or method steps.
I keep one part for each agency where possible. No member is a part of `bench/regulatory`,
no file under `bench/` names a member, and none of the 462 Federal Register documents amends
a member. I read no document body. A HEAD request on the versioner URL of each member and
spare gave HTTP 200 with an XML type.

[`members.json`](members.json) holds the list, the metadata URLs and the rule. Its
`download_approved` is the date of the owner approval, 2026-11-27. `sources.py` refuses a set
with no approval.

## Sources

Each member is the XML of one part at 2026-11-24 from the eCFR versioner API. The parts are US
government works (17 U.S.C. 105). The XML and the reader text stay in local work storage.

```bash
WORK=/path/outside/the/repo/regulatory-750
uv run python bench/regulatory/sources.py --set bench/regulatory2 --out "$WORK/sources" --fetch
```

The command does the checks of `bench/regulatory`: the identity, the section count, the text,
the language and the printed notices. It writes `manifest.json` and `source_checks.json`
here. I read each notice match and write the review into `notice_review` of `members.json`
before the slots. `selection_complete` becomes true only when no member is on hold.

I downloaded the 14 parts on 2026-11-27. All 14 pass the checks, so no spare comes in, and
`selection_complete` is true. 13 parts have no notice match. 36 CFR 1258 has 41 matches. I
read each of them: each is regulation text about the fees for records reproductions of NARA.
No source has a notice of the publisher.

## Split and seed

The seed is the SHA-256 of the source digests in member order, one on each line, as in
`bench/regulatory`. All members are held-out, so the seed only draws the slots. Nobody can
choose the seed after the download, and the seed comes before any label.

## Slots

```bash
uv run python bench/regulatory/slots.py --set bench/regulatory2 --sources "$WORK/sources"
```

`slots.py` draws the slots with the field counts of `bench/regulatory` and writes their pin
into `manifest.json`. A draw reads the structure only: section headings, defined terms,
table captions, row positions and column headers. The upper limit is 98 slots: 28
`section_text`, 14 `definition`, 28 `table_value`, 14 `table_rows` and 14 `effective_date`.
A part with no definitions section or no table gets fewer slots.

I drew the slots on 2026-11-28 with no model call. The draw gave 65 slots: 28
`section_text`, 7 `definition`, 12 `table_value`, 4 `table_rows` and 14 `effective_date`. 7
parts have no definitions section with a defined term in italics. 8 parts have no table with
a number cell, and 2 more have no table with 2 to 30 body rows. The manifest pins
[`slots.json`](slots.json) with its digest.

## Labels

The labels use the method of `bench/regulatory` with `--set bench/regulatory2` on each
command of `passes.py` and `bench/label/decide.py`. `passes.py seal` writes `labels.json` and
its digest into the manifest before any benchmark model output on this set, and it refuses a
second seal.

## The planned run

The run uses the current main and the cache folder of this split. The calibration parts and
labels come from `bench/regulatory`, so `--sources` must hold the XML and the reader text of
both sets.

```bash
uv run python -m bench.regulatory.run calibrate --set bench/regulatory2 --sources "$WORK/sources" --cache "$WORK/calls" --model gpt-6.2-sol --effort medium
uv run python -m bench.regulatory.run freeze --set bench/regulatory2 --sources "$WORK/sources" --cache "$WORK/calls"
uv run python -m bench.regulatory.run heldout --set bench/regulatory2 --sources "$WORK/sources" --cache "$WORK/calls" --model gpt-6.2-sol --effort medium
```

The freeze goes into `manifest.json` of this folder. The manifest of `bench/regulatory` does
not change. The run record binds the set, slot and label digests of `bench/regulatory`, so a
change there stops the run.
