# Column words and marker words in the field check

Status: approved by the maintainer on 2026-10-24, with the recommendation of each open question
(section 12). On 2026-10-25 the maintainer renamed the qualifier words of this note to marker
words, because SPEC §4.2 already uses "qualifier" for words such as "up to". SPEC.md has the
rules as spec 0.12 (#542). Nothing in this file is built. The note proposes a decision change for spec 0.12
(milestone 0.14, #540). The vectors come by hand in `conformance/build.py` before the code.

## 1. The answers in short

| Question | My answer | Section |
|---|---|---|
| What fails | 29 reviews of right values where the cited field item holds an alias but its place fails SPEC §4.6, and 2 escapes where the row label is an alias but the value is in another column. | 2 |
| Text or nodes | The gate stays on the text. `groundgate read` writes a tab between the cells of a row, so the text already holds the cells. `admit` still never reads a node (document-model.md §5.2). | 3 |
| Column words | A new schema member `columns`. A new item role `column` puts the value in the column of a header cell, by the tab slots of the two lines. | 4, 5 |
| Marker words | A new schema member `markers`. A new item role `marker` binds a value to the field by the word next to it, as "family" in "$800 family". | 4, 6 |
| The escapes | A field with `columns` needs its column at the value, or the value goes to review. | 5.3 |
| Old packets | A schema with no `columns` and no `markers` decides as in 0.11. | 8 |
| The terms | Lane 1e of #539 proposes the words from the field description, and the user approves them. | 10 |

## 2. What fails today

Lane 0 of #539 read the cached records of the #534 run (runner arm, development split). Of the
58 reviews, 52 carry `FIELD_CITATION_INVALID`. In 23 of them, no cited field item holds an alias:
that is an alias gap, and lane 1e acts on it. In the other 29, a cited field item holds an alias,
and the place check fails. By kind, the 29 are 16 sbc, 9 sds, 3 component and 1 annual.

### 2.1 An answer cell with two values

```text
What is the overall deductible?\tIn-Network: $400 person/$800 family per calendar year. ...
```

The question cell is a label cell (SPEC §4.6) for a token in the answer slot. Rule 1 of label
cells says that no number token lies between the item and the token. For the family amount, "$400"
lies between, so the family deductible goes to review. #426 found this in loop 01. Rule 1 cannot
just go: both fields of the pair have the aliases "Overall deductible" and "Deductible", so
`deductible_individual` = 800 would pass too. The word "family" next to the value is the fact
that tells the two fields apart, and the schema does not hold it.

### 2.2 A table row with text columns

```text
Parameter\tSymbol\tConditions\tMin.\tTyp.\tMax.\tUnit
Supply Voltage Range\tVCC\t\t6\t\t35\tV
```

The field item "Supply Voltage Range" is not at the row (the letters "VCC" stand between), it is
not a label cell (35 is not in the first answer slot), and the sentence rule finds the number 6
between. The column rule of §4.5 does not help: it reads keys, and the slot "VCC" is a nonempty
slot with no cell, so rule 6 makes the line ambiguous. The text has the cells. The gate reads them
only by number cells, not by slots.

### 2.3 The escapes

```text
\t0.4\t1.4\t2.4\t\tVDD > 2.3V
Supply current 2 mA At maximum VDD 2
```

On component-c17 and component-c19, `supply_current_typ` admitted 2. The labels say that the
document prints only a Max value, so the field is absent. The row label "Supply current" is an
alias of the field, and the value is at the row, so the field check passes. The row has no tab,
so its columns are lost in the text. No rule of today can see that 2 is a maximum.

### 2.4 Not a gate problem

The 9 sds cases cite the right label, but the value lines hold only values, one for each line,
as in "-188 °C (-306.4 °F)\n-42.2 °C (-44 °F)". The reader wrote the label column and the value
column of the page as separate runs of lines. No safe text rule pairs them. The fix belongs in
the PDF reader: one row for each line, with a tab between the cells. Section 9 lists it.

## 3. Text or nodes

**Option A: the text slots.** The gate reads the tab slots of a line. A header slot and a value
slot with the same index are in one column. The structure stays in the text that `admit` checks
today.

**Option B: the nodes.** The packet gives the table cells of `document@1`, and the core reads
their rows and columns.

I recommend option A, for three reasons:

1. The approved document model (#285) says that `admit` never reads a node (§5.2). Option B
   reverses that decision and adds an input format to the core.
2. The structure reader (#510) proposes values from the grid of the nodes. If the gate checks the
   same grid, it repeats the work of the reader and never finds its errors (document-model.md §8).
   Option A checks the text, so the two stay independent.
3. `groundgate read` already writes HTML and PDF table rows with a tab between the cells, as
   SPEC §4.5 rule 3 says. All the cases of section 2.1 and 2.2 have tabs.

Option A fails where the text lost the cells, as in section 2.3. There it sends the value to
review (section 5.3). It does not guess.

## 4. The schema members

```text
{"fields": {"supply_current_typ": {"aliases": ["Supply current"], "columns": ["Typ", "Typical"]},
            "deductible_family": {"aliases": ["Overall deductible"], "markers": ["family", "FAM"]},
            "deductible_individual": {"aliases": ["Overall deductible"],
                                      "markers": ["individual", "person", "member", "IND"]}}}
```

- `columns`: the words of a column header that name the column of the field, such as "Typ" or
  "Max.". Null (default) or a non-empty list of strings, with the rules of `keys` and `aliases`:
  none blank, and no two equal after whitespace normalisation (§4.4) and the fold of each letter.
- `markers`: the words next to a value that name the field, such as "family". The same rules.
- A column word or a marker word is matched as a key mention is (§4.5): case-insensitively,
  with whitespace and dash folding, and with no letter or digit directly before or after.
- Both members are part of the schema digest. They do not change `field_keys` or the receipt
  shape.

## 5. Column words

### 5.1 The slots of a line

The **slots** of a line are the parts between its tabs. Slot 0 is the text before the first tab.
A line with no tab has one slot. This is the label slot and the answer slot of §4.6 with an index.

### 5.2 The column item

A `column` item passes when all of these hold:

1. It holds a mention of a column word of the field, and it lies wholly in slot n of its line,
   the **header line**, with n of 1 or more.
2. The value's token lies wholly in slot n of the value's line. That slot holds only the token,
   whitespace and forms of the field's unit (§4.3), so "35" and "35 V" pass, and "6...35" fails.
3. The header line comes before the value's line. The two lines have the same number of slots.
   Each line between them is not blank, has that number of slots, and no page break (`\f`)
   stands between them.
4. No other slot of the header line holds a column word of the field.
5. No line between them holds a column word of any field of the schema. Slot n of each line
   between holds a number token or no letter. So a second header stops the rule, as a key
   mention does in §4.5 rule 2, also when its column words are not in the schema, as "Nom.".
   A dash for an empty cell does not stop it.

A field item **reaches** the token as a **row label** when it lies wholly in slot 0 of the
value's line, it holds an alias of the field, and a column item of the candidate passes. This is
a fourth way for the field check of §4.6 to pass, next to the row, the label cell and the
sentence. Text and numbers in the other slots of the row then do not stop it. So section 2.2
passes with the field item "Supply Voltage Range" and the column item "Max.".

### 5.3 A field with columns needs its column

When the field has `columns`, the value must be in its column. This holds when a column item
passes, or a passing field item holds a column word of the field, as "typical supply current"
holds "Typical". When neither holds, the decision gets the new flag `COLUMN_NOT_AT_VALUE`, and
the outcome is at best `needs_verification`.

A candidate with no field item and no column item gets the flag too. So on a field with
`columns`, #450 has its answer: the candidate cannot pass by leaving the items out.

In section 2.3 the row has no tab, so no column item can pass, and "Supply current" holds no
column word. Both escapes go to review. A right value in a row that lost its tabs goes to review
too. That is the cost, and the measure (section 10) counts it.

## 6. Marker words

### 6.1 Next to the value

A marker mention is **next to** the token when one of these holds:

1. **Before.** It ends before the token, on the same line and in the same slot, and only
   whitespace, `(`, `)` and prefixes of the field's unit stand between its end and the token. So
   "Family $0" and "IND $1,500" have the marker before the value.
2. **After.** It starts after the token, on the same line and in the same slot, and only
   whitespace and suffixes of the field's unit stand between the token and its start. So
   "$800 family" and "$500 member" have the marker after the value.

A `/`, a `;` or a word between them breaks it. So in "$400 person/$800 family", "person" is next
to $400 only, and "family" is next to $800 only.

### 6.2 The marker item

A **competing word** of a field is a marker word of another field of the schema that is not
also a marker word of this field, after whitespace normalisation and the fold of each letter.
So when `deductible_family` and `out_of_pocket_family` both list "family", "family" is not a
competing word of either. The aliases tell those two fields apart, not the marker.

A `marker` item passes when it holds a marker word of the field, that mention is next to
the token, and no competing word of the field is next to the token.

When a marker item passes, a field item that is a label cell for the token passes without
rule 1 of label cells: number tokens can lie between the item and the token. Rules 2, 3 and 4
stay, and one more rule holds. After the first number token of the answer slot, each run of
letters before the token lies in a marker word of a field of the schema, or in a form of the
field's unit.
So "In-Network: $400 person/$800 family" passes for $800: "person" is the only word between.
A later part of the cell is a **boundary**: in "In-Network: $800 family Out-of-Network: $1600
family", the word "Out-of-Network:" stands between, so $1600 stays out of reach. The rule does
not depend on the limit of 4 words.

### 6.3 Another field's word at the value

When the field has `markers`, and a competing word of the field is next to the token while no
marker word of this field is, the decision gets the new flag
`MARKER_OTHER_FIELD`. This holds also for a candidate with no marker item. So a model that
gives $800 of "$800 family" as `deductible_individual` goes to review.

## 7. Roles, codes and the receipt

- §2.5: the roles `column` and `marker`, on a document or reference item, with offsets or a
  quote, as the other role items have. On a field without `columns`, a column item fails and has
  no effect. The same holds for a marker item on a field without `markers`.
- §3.3, two new flags, each with the outcome at best `needs_verification`:

| Code | Text |
|---|---|
| `COLUMN_NOT_AT_VALUE` | The field has `columns`, no column item puts the value in a column of the field, and no passing field item holds a column word of the field (§4.6). |
| `MARKER_OTHER_FIELD` | The field has `markers`, a competing word (a marker word of another field that this field does not list) is next to the value, and no marker word of this field is (§4.6). |

- The receipt gets no new member. A decision records the codes as today.

## 8. What stays the same for 0.11 packets

- A schema with no `columns` and no `markers` decides as in 0.11: the same outcome, codes,
  `missing`, `parts` and relations in each vector of 0.11. A column item or a marker item on
  such a field fails and changes nothing.
- The default policy has no new member. Only the `groundgate/0.12:` prefix changes the digests.
- The row label way of section 5.2 needs a passing column item, so it adds nothing for a field
  without `columns`.

## 9. Not in this note

1. **The 9 sds cases.** A reader issue: the PDF reader writes the label and the value of a two
   column table as one line with a tab. That changes the text, so it is a new reader version and
   a cache miss. It is not a decision change.
2. **Ranges.** "VCC = 6...35V" and "–40°C...+85°C" have a minimum and a maximum in one token run.
   2 of the 3 component cases are ranges. A range rule needs its own note.
3. **The alias gaps.** 23 reviews. Lane 1e adds the aliases. No rule change.
4. **A long answer cell.** "For each Plan Year, In-Network: Individual $0 / Family $0." has more
   than 4 words before each value, so rule 2 of label cells stops it. I keep rule 2. Such a cell
   stays in review.
5. **Networks and tiers.** "In-Network" and "Tier 1" choose among several family amounts. Today
   the 4-word limit keeps the later parts out. A key rule for networks is a separate question.
6. **#450 for other fields.** Section 5.3 answers #450 only for a field with `columns`. The
   general question stays open.

## 10. The measure

1. **The terms.** Lane 1e proposes `columns`, `markers` and aliases from the name and the
   description of each field, with no document, and the maintainer approves the diff. Words that
   I choose by hand from the development documents are tuning, so they never count as a result.
2. **A replay on the development split.** The rules run on the recorded candidates of the #534
   run, with the approved terms, and with no model call. I count the right values that move from
   review to admitted, the wrong values that get in, and the right values that the column rule
   sends to review. This shows if a rule does what this note says, before the vectors.
3. **The claim.** Only the new held-out set of lane 2 gives the 0.14 number. The runner prompt
   asks for column and marker items before that run.

## 11. Vectors I write by hand, after approval

- `column-slot-max`: section 2.2. `supply_voltage_max` = 35 with the field item and the column
  item "Max.": admitted.
- `column-slot-other`: the same row, 6 with the column item "Max.": the column item fails,
  `COLUMN_NOT_AT_VALUE`.
- `column-slot-count`: the header has 7 slots and the row 6: the column item fails.
- `column-reordered-header`: "Parameter\tMin.\tTyp.\tMax.\nSupply voltage\t6\t12\t35\nParameter\tMin.\tMax.\tTyp.\nSupply current\t1\t3\t2". `supply_current_typ` = 3
  with the first "Typ." and the row label "Supply current": the column item fails (rule 5),
  `COLUMN_NOT_AT_VALUE`. The same value with the second "Typ." fails rule 2.
- `column-slot-two-words`: a header with "Typ." in 2 slots: the column item fails (rule 4).
- `column-plain-row`: section 2.3 with a field that has `columns`: review, `COLUMN_NOT_AT_VALUE`.
- `column-field-word`: "Typical supply current 2 mA" with the column word "Typical": admitted.
- `column-no-items`: a candidate with no field item and no column item on a field with
  `columns`: review, `COLUMN_NOT_AT_VALUE`.
- `marker-after`: section 2.1, `deductible_family` = 800 with the marker item "family":
  admitted.
- `marker-before`: "Individual $0 / Family $0" with the marker item "Family": admitted.
- `marker-other`: `deductible_individual` = 800 at "$800 family": review,
  `MARKER_OTHER_FIELD`, also with no marker item.
- `marker-shared`: `deductible_family` and `out_of_pocket_family` both list "family".
  `deductible_family` = 800 at "Overall deductible\tIn-Network: $400 person/$800 family" with
  the marker item "family": admitted, and no `MARKER_OTHER_FIELD`.
- `marker-boundary`: `deductible_family` = 1600 at "Overall deductible\tIn-Network: $800
  family Out-of-Network: $1600 family" with the marker item on the second "family": the
  label cell fails, as in 0.11. The same cell with 800 and the first "family": admitted.
- `marker-slash`: "$400 person/$800 family": "person" is not next to $800.
- `marker-four-words`: a fifth word before the token: the label cell fails, as in 0.11.
- `marker-sentence`: the later part after a sentence end: the label cell fails, as in 0.11.
- `columns-absent`: each case above with no `columns` and no `markers`: the 0.11 outcome.
- Invalid packets: a blank column word, two equal marker words after the fold.

## 12. Open questions

The maintainer chose the recommendation for each question on 2026-10-24.

1. **Text or nodes.** Option A or option B of section 3? I recommend A. It keeps the approved
   rule that `admit` never reads a node, and the independence of the structure reader.
2. **Flags or rejects.** Do the two new codes give review or reject? I recommend review. The
   escapes become reviews, and a person sees the value.
3. **The column requirement.** Does a field with `columns` need its column (section 5.3)? I
   recommend yes. Without it, the escapes of section 2.3 stay.
4. **Rule 2 of label cells.** Keep the 4-word limit with a marker item? I recommend yes, also
   though some cells stay in review (section 9, point 4). It is the rule that keeps a later
   network or tier out.
5. **Abbreviations.** Must "FAM" and "IND" be in the schema, or does the gate know them? I
   recommend the schema. The gate knows no domain words, and lane 1e can propose them.
6. **Slot equality.** Does a column item need the same number of slots in the header and the
   row (section 5.2, rule 3)? I recommend yes. A row with a spanned cell then goes to review. A
   wrong column is worse than no column.

## 13. Code issues, after approval

1. The spec text and the vectors of section 11, by hand, before the code.
2. `admit`: the members, the roles, the slot rule, the marker rule and the two flags.
3. The runner prompt: ask for a column item in a table and a marker item in an answer cell.
   The instruction text changes, so the prompt digests change.
4. The PDF reader: one line for each row of a two-column table (section 9, point 1).
5. The replay of section 10, point 2, with the terms of lane 1e.
