# Requested fields: the 0.10 confirmation set

Status: draft. I selected the members on 2026-10-18, before any model output on this set (#323).
The labels are a draft and `manifest.json` is not frozen. Both freeze at the code freeze. No
benchmark arm has run on this set.

This set measures the 0.10 rules on documents that no 0.10 rule came from. It uses the three kinds
of [bench/requested2](../requested2) with the same schemas and the same fixed requests, and it
adds a fourth kind, safety data sheets. A document schema changes only the reporting currency of
an annual report. No requested2 document is a member.

## Safety data sheet schema

| Field | Type | Unit | Aliases |
|---|---|---|---|
| `flash_point` | number | C | Flash point |
| `initial_boiling_point` | number | C | Initial boiling point; Initial boiling point and boiling range; Boiling point |
| `ph` | number | none | pH |
| `relative_density` | number | none | Relative density; Specific gravity |
| `un_number` | string | none | UN number; UN No. |

The unit C reads the suffixes "°C" and "Celsius". The request takes each value as Section 9 or
Section 14 of the sheet states it. It does not convert a unit and it does not calculate a value.
A bound, a range or a value in °F only is unclear. A density with a unit is a different quantity
from relative density. The UN number is "UN" and four digits.

## Selection

On 2026-10-18 the maintainer approved 130 downloads in chat. Before that I read only catalog
pages and terms pages, and I sent HEAD requests for the sizes. Terms group A gives no use limit
that applies to a private copy. Terms group B allows only personal, noncommercial or internal use.
A group B member is a member only for local, internal measurement, and I infer no broader right.

After each download I checked the identity, the period or revision, the text layer and the printed
notices. 15 downloads are not members (`source_checks.json` gives each reason):

- 4 downloads failed: the server answered 403 or 406 (sbc-c11, sbc-c12, sbc-c14, annual-c18).
- 10 sources are on hold because their own notice limits reproduction or use:
  8 component datasheets, 1 annual report and 1 safety data sheet.
- 1 SBC is a scanned carrier summary, not the SBC form (sbc-c13).

| Kind | Approved | Members | Held-out | Pilot | Group B members |
|---|---:|---:|---:|---:|---:|
| component | 27 | 19 | 18 | 1 | 18 |
| sbc | 28 | 24 | 23 | 1 | 3 |
| annual | 23 | 21 | 20 | 1 | 13 |
| sds | 52 | 51 | 50 | 1 | 36 |

Every other download is a member. I made no subsample. The development pilot of each kind is the
lowest ID whose source family has one member: component-c05, sbc-c05, annual-c01, sds-c09.
The documents of one family or one employer stay in one split. Selection uses publisher metadata, notices and layout eligibility. It
never uses a requested value or a model output.

`manifest.json` records each source URL, byte size, PDF hash, terms group and license note. The
originals stay in local work storage and are not published. One datasheet download URL holds a
session token, so its source is the catalog page that links it. Its SHA-256 identifies the file.

## Labels

Two blind passes labeled all 596 slots from the original PDFs, with the rules of requested2.
Each pass confirmed each present value on a render of its PDF page. The passes gave the same
label on 589 slots (98.8%). An independent check of the original PDF decided the other 7. Each absence has a second blind check: both passes gave all 173 absences.

| Kind | Slots | Present | Absent | Unclear |
|---|---:|---:|---:|---:|
| component | 95 | 68 | 2 | 25 |
| sbc | 120 | 100 | 8 | 12 |
| annual | 126 | 72 | 51 | 3 |
| sds | 255 | 77 | 112 | 66 |

Three reports print income in brackets in a statement of net expenditure. The statement adds the
bracketed amount as a negative, so the check kept the printed sign, as requested2 did for a
bracketed total liabilities line. Revenue is negative in these three reports.
