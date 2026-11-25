# Escapes of the regulatory held-out run

The held-out run of 0.17.0 (#686) admitted 34 values on 50 slots. 6 of them are escapes: an
admitted value that does not equal its label ([results.json](results.json)). All 6 are in the
value kinds `passage` and `record`. This file records each escape and its cause (#709).

## Method

I replayed the admission from the cached replies of the run, with `parse_reply` and `admit` of
[run.py](run.py) and the frozen profile of [manifest.json](manifest.json). I made no new model
call. Each cached prompt has the digest that [heldout-run.json](heldout-run.json) records. The
replay gives the same counts as `results.json`: 28 right admitted values, 6 escapes and 4
reviews. Then I compared each admitted value with its label in [labels.json](labels.json), and
the text of the section or the table in the pinned XML.

The cache and the XML stay in local work storage, as the [README](README.md) says. I did not
change the split, the labels or the slots.

## The 6 escapes

| Slot | Part | Field | Admitted value | Label | Cause |
|---|---|---|---|---|---|
| r014 | 10 CFR 170 | `section_text` of § 170.21 | the body, then the source note and an editorial note | the body | boundary |
| r049 | 37 CFR 201 | `section_text` of § 201.13 | the body, then the authority note | the body | boundary |
| r072 | 49 CFR 1002 | `section_text` of § 1002.1 | the body, then the source note and an editorial note | the body | boundary |
| r073 | 49 CFR 1002 | `section_text` of § 1002.2 | the body, then the source note and an editorial note | the body | boundary |
| r006 | 7 CFR 800 | `table_rows` of Table 21 | 4 records | 5 rows | row: a missing row |
| r044 | 33 CFR 402 | `table_rows` of Table 1 to § 402.12 | 22 records, 3 of them with a null member | 22 rows, with `n/a` in those 3 cells | row: a null cell |

| Cause | Passage | Record |
|---|---:|---:|
| A wrong passage or table | 0 | 0 |
| A boundary error | 4 | 0 |
| A row error | 0 | 2 |
| A label error | 0 | 0 |

Each of the 6 cites the right section or the right table. Each admitted member value of the two
tables is right. The errors are at the end of a section, in the set of rows, and in the
meaning of a null member.

## Cause 1: the notes at the end of a section (4 passages)

In each of the 4 passages, the admitted text is the label with more text at the end. The body
is equal to the label. The extra text is the notes of the section:

- r014, r072 and r073 end with a source note in brackets, for example
  `[53 FR 52648, Dec. 29, 1988]`, and then an editorial note: "For Federal Register citations
  affecting § 170.21, see the List of CFR Sections Affected".
- r049 ends with the authority note `(Pub. L. 94-553; 17 U.S.C. 110(4), 702)`. The source note
  after it is removed.

The gate did what SPEC §4.17 says. The outline of the bench has the section headings only. So
the section of a heading runs to the next heading, and the notes are in it. A quote of the body
only gets `PASSAGE_CUT_SHORT`. After admission, the bench removes one source note in brackets at
the very end of the text (`SOURCE_NOTE` in [extract.py](extract.py)). That rule does not remove
an editorial note after the source note, and it does not remove an authority note before it.

In the eCFR XML, each note is its own element: `SECAUTH` for the authority, `CITA` for the
source and `EDNOTE` for an editorial note. So a reader can find the end of the body from the
structure.

The field rule of `section_text` says "without the source note in brackets at its end". The
owner decided all 4 labels, and the labels also leave out the editorial note and the authority
note. So the rule text is narrower than the labels. I do not count this as a label error,
because the labels follow the purpose of the field: the text of the section.

**Fix: #735.** The family reader gives an outline entry at the first trailing note of a
section, at the level of the section heading. Then the section of §4.17 ends at the end of the
body, and no core rule changes. The field rule names the three notes, and the bench removes no
note after admission.

## Cause 2: a missing row (r006)

Table 21 of 7 CFR 800 has 5 body rows. The first body row has the marks `GL BP` under each
column header, and an empty grade cell. The model left out this row. The 4 admitted records are
the other 4 rows, in their order, and each member value is right.

SPEC §4.12 reads only the records that the candidates name. No rule compares the records with
the rows of the table. So the 4 admitted records are true rows, but the set of rows is not the
table.

A reader can say that the `GL BP` row is a second header row. The XML has it in `TBODY`, the
field rule says "the body rows", and the two blind passes agree on it. So I do not count it as a
label error.

**Fix: #736.** The record id of a model row is the position of its row in the table of the
structure. The structure reader proposes the cells of the table as a `corroborate` proposer
(§2.4). A row that only the structure reader gives gets `NOT_CORROBORATED`, so the table goes
to review.

## Cause 3: a null member at a cell with text (r044)

Table 1 to § 402.12 of 33 CFR 402 has `n/a` in column 2 of three rows. The model gave null for
these three cells, so the bench made no candidate for them. The members of `table_rows` are not
required, because a table can have empty cells. So §4.12 admits each of the three records. The
other 19 rows are equal to the label.

In §4.12, a null member says that no value of that member passed. The bench, and the field rule
"An empty cell is null", read it as "the cell is empty". The two meanings are different, and
the gate cannot see the difference without the cells of the table.

**Fix: #736.** The structure reader proposes `n/a` for these cells. No model candidate agrees,
so each one gets `NOT_CORROBORATED`, and the table goes to review. A cell that is empty in the
structure gets no candidate, so a true empty cell stays null.

## What an admitted value means today

- An admitted `passage` is the whole section of the outline that the reader gives. It includes
  each note that the outline does not mark as a heading.
- Each member value of an admitted `record` that is not null passed its own checks. The gate
  does not check that these values come from one row. A null member does not say that the cell
  is empty. The admitted records are not always all the rows of the table.
- `number` had 0 escapes in this run, on 7 admitted values.

The bounds of this run are in [RESULTS.md](RESULTS.md). The fixes of #735 and #736 change the
outcomes, so they get a measure on a new held-out split of this family or on new parts. These 6
escapes are not a measure of the fixes.
