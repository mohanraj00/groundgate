# Requested fields: the 0.10 confirmation set

Status: I selected the members on 2026-10-18 and froze the manifest on 2026-10-20, before any
model output on this set (#323). I sealed the labels on 2026-10-20. The set has 115 documents:
4 development pilots and 111 held-out (18 component datasheets, 23 SBCs, 20 annual reports and
50 safety data sheets). No benchmark arm has run on this set.

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

`manifest.json` records each source URL, byte size, PDF hash, reader text hash, terms group and
license note. The originals and the reader texts stay in local work storage and are not published.
One datasheet download URL holds a session token, so its source is the catalog page that links it.
Its SHA-256 identifies the file. Its HEAD request gave no size, so its approved size is the size of
the downloaded file.

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

Pass B ran again for the 4 component datasheets of one batch (component-c23 to c26). While the
first pass B of that batch ran, the label script of pass A for the same batch was in a shared
scratch directory that pass B could read. I moved the first output out of reach and ran a new
pass B that could not read pass A, the first output or the label files. The new pass B gave the
same label as pass A on 20 of 20 slots, and no label changed. The agreement above
uses the new pass B.

Three reports print income in brackets in a statement of net expenditure. The statement adds the
bracketed amount as a negative, so the check kept the printed sign, as requested2 did for a
bracketed total liabilities line. Revenue is negative in these three reports.

## Code freeze and arms

The code freeze is origin/main 8290450, where the 0.10 rules, the runner and the replay arm of
the harness (#376) are merged. Its `code_sha256` is
`sha256:0e6c6b2606db02e6e04ef79ea858afb35a885519b4912f78c9f83dd5852f0403`. The run
configuration pins this digest, and a code change after the freeze voids it. The reader code is
the same as at c5ba774, where `groundgate.read` made the reader texts. The frozen manifest names
three arms:

| Arm | `drop_rounded` | Model calls |
|---|---|---|
| `baseline` | not used | new calls on the held-out split |
| `runner` | off, the 0.10 default (main arm) | new calls on the held-out split |
| `runner_drop_rounded` | on | none: it replays the recorded calls of `runner` |

The rounding step runs in `finish()`, after the last model call, and it calls only `admit`. So the
`runner_drop_rounded` arm sends the same prompts as `runner`. It takes no client. It reads the
recorded calls of `runner` in order and checks each prompt against its record. A missing, extra or
changed call stops the run.
