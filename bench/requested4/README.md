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
are absent. No model output existed when I made this change.

## Arms

The frozen manifest names the three arms of requested3:

| Arm | `drop_rounded` | Model calls |
|---|---|---|
| `baseline` | not used | new calls on each split |
| `runner` | off, the default (main arm) | new calls on each split |
| `runner_drop_rounded` | on | none: it replays the recorded calls of `runner` |

## What comes next

The learning loop runs on the development split only (`bench/requested/loop.py`). It writes one
record for each iteration in `loop/`, and it never opens a held-out output. The code freezes
before the first held-out model call. One PR writes the commit, the `code_sha256`, the last loop
record and the held-out configuration digest into the manifest. A code change after the freeze
voids it.
