# The changed-value test (#322)

The models of the bench make few errors, so most checks have few or no catches to count. This
test makes the errors. It takes values that a person approved, changes each one the way that real
errors occur, and counts which check stops each changed value and how many get through. No model
runs. The plan is on #322, and gap 3 of #277 asks for it.

```bash
uv run python bench/changed/changed.py changes            # changes.json, the fixed list
uv run python bench/changed/changed.py results            # results.json and RESULTS.md
uv run python bench/changed/changed.py results --check    # fail if a file differs
```

The numbers are in [RESULTS.md](RESULTS.md).

## The source set

The values come from `bench/afr`, the held-out set of 20 agency financial reports (#229). I use
this set for three reasons:

- It is frozen and published, and a person labeled each value blind (`bench/afr/labels.json`).
  I use only the values with the label `right`.
- No rule of the 0.10 draft came from it, and it is not `bench/requested2` or `bench/requested3`.
- Its fields make a relation: total assets equal total liabilities plus total net position. So
  the test can count what the relation check of spec 0.10 stops.

The text is the text with table rows (`bench/afr/tabs/docs`, #230), which the reader of this
groundgate writes.

## The base

A label approves a value, not a citation. So each right value starts from a proposal of that
value from the runs of `bench/afr/tabs.py`: the first one, in the order of its runs, that this
groundgate admits. That proposal is the **base**. Its value item is pinned at the place where
groundgate found it, and its other items stay as the model gave them. A right value with no
admitted proposal has no base, and RESULTS.md gives the count.

`changes.json` is the fixed list: the bases and each change. `changes` writes it once. `results`
reads only `changes.json` and the texts, so a later rule cannot change the list.

## The changes

| Change | What changes | Evidence |
|---|---|---|
| next row | the number in the same column on the next row that holds a number | at the new number |
| next column | the next number on the same row, or the one before it in the last column | at the new number |
| wrong scale | the value times 1000, and the value divided by 1000 (two changes) | of the base |
| sign | a negative value loses its sign, and another value gets one | of the base |
| digit swap | two adjacent digits of the written number change places | of the base |
| other field | the value of each other field at the same year | at that value |
| rounded | the written number rounded to 3 significant digits | of the base |

The number cells of a row are the numbers after the first tab of its line. A value from the next
row, the next column or another field keeps the scale of the base, and takes the sign of the new
number: negative when it has a minus or brackets around it. So it is the value that a model gives
when it reads the wrong cell correctly. The other changes keep the sign of the base, except the
sign change itself.
The seed `322` chooses the two digits of a digit swap. All other changes have no random part. A
change that gives the right value again is left out.

## The decision

Each change replaces its base in the packet of its document, next to the other bases. So the
relation reads the right values of the other fields. Each packet is decided twice in process:
with the relation `balance` and without it. The schema is the schema of `bench/afr` with
`multiple` false, because a relation needs one value for each field and year (SPEC 2.3). Each
packet has one candidate for each field and year, so this changes no other decision. The clean
packets are the control: each base must be admitted in them.

## The counts

For each change, RESULTS.md gives:

- how many changed values are rejected, sent to review, and admitted;
- the check that stops each one: a rejected value under its code, a value sent to review under
  each of its flags;
- how many values the relation checks, how many of those it stops, how many only the relation
  stops, and how many right values a failed relation sends to review with the changed value;
- each admitted change.

Each count has one-sided 95% Clopper-Pearson bounds, lower and upper. The changes of one
document are not separate trials, so the bounds allow for clusters by document, as
`docs/design/extensions.md` (section 10) says. The design effect is the largest number of
changes of one document for that change. The trials are divided by it and rounded down, and the
count is divided by it and rounded toward the side of each bound. The admitted changes also have
the exact upper bound on documents with at least one admitted change.

## Limits

- One kind of document. The reports are financial statements with one year on most lines, so
  the next column applies to few values.
- The changes keep the role items of the base. A model that reads the wrong cell can also cite
  other items, so a changed value can pass or fail other checks than here.
- The relation checks a value only when the two other fields of the balance sheet have a base at
  that year. A field outside the relation, such as total budgetary resources, has no relation.
- The relation stops every changed value that it checks, because each change of a total or a
  part breaks the sum. So its count is not a detection rate: it shows how many changed values
  reach the relation, and what it adds to the other checks. A failed relation cannot name the
  wrong value, so it sends the right values of the other fields to review too. That is its cost.
- A rule that changes a decision changes `results.json`. Then `results --check` fails until the
  results are written again with that rule.
