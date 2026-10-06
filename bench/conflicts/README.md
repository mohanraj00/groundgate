# Conflicts set: the conflict question

Spec 0.3 flags `CONFLICTING_CANDIDATES` when two candidates for one field have different values.
The hybrid design (#66) lets a System 1 model choose among them. To measure that (#67), each FDA
label here is labeled by a person with the dose that the text states as each of three set-2
fields, or none.

`conflicts.py` is the pick of the keys set (`bench/keys/keys.py`) with its own documents. The
pick looks only at label metadata and dose counts, and prints no text. The label tool shows
sections 2 and 3 as the pinned SPL formats them, marks every dose, and never shows what spec 0.3
or a model reads.

```bash
uv run python bench/conflicts/conflicts.py pick --count   # how many labels the walk finds
uv run python bench/conflicts/conflicts.py pick           # write sources.json, selection-log.json
uv run python bench/fetch.py --set bench/conflicts        # download, verify, write docs/
uv run python bench/conflicts/conflicts.py items          # write items.json from docs/
uv run python bench/conflicts/conflicts.py web            # label at http://127.0.0.1:8771
```

## Labels

40 FDA labels in the set-2 Part D ranking, up to rank 3000, with the set-2 label rules: the first
search result that is a single-ingredient tablet or capsule label with sections 1, 2 and 3. The
text is sections 2 and 3. A label with more than 30 doses there is skipped, so that one person
can read each label in full.

## What is excluded

Every drug that v0.1, set 2, the pattern set, the dots set, the keys set, the tables set, the
relations set or the fields set used.

## Doses and fields

A dose is a number token followed by mg or mcg, as in the keys set, or by a hyphen and the unit
("a 5-mg dose"). The lower end of a range or a list is a dose too: a number that "to", "or",
"and", a comma or a dash joins to a dose ("20 to 30 mg", "5 or 10 mg"). `items.json` holds every
dose of each label. The fields are the three set-2 FDA fields in mg that take one value, with
the set-2 schemas and descriptions for a label without keys (`FIELDS` in `conflicts.py`):
`starting_dose`, `max_daily_dose` and `hepatic_starting_dose`.

The first `items.json` had only the doses with a unit after them. The labeler found that the
lower end of "20 to 30 mg" could not be clicked, so I added the two other kinds during
labeling. Every dose of the first file kept its id, so no label changed.

## A label

For each label and field, the dose that the text states as the field (its item id), `none` when
the text states no dose as the field, or `null` for not sure, which is left out of the gold.
When the text states the value more than once, any of those doses is the label.

Rules that the labeling settled, for the cases that the field descriptions leave open:

- A field stated, but not as a number in mg or mcg, is not sure: a dose in grams, a count of
  tablets or capsules, or a dose for each kg or m² of body. A dose here is in mg or mcg, so no
  candidate can hold it.
- A fixed daily dose with no stated maximum is not a maximum, as in set 2: azithromycin's "500 mg
  once daily" has no `max_daily_dose` there. The upper end of a recommended daily range is the
  maximum, as in set 2.
- The maximum rule came after the labeler had labeled five labels with the fixed dose as the
  maximum. At the labeler's request, I read those five texts (budesonide, cilostazol, mesalamine,
  raloxifene, terbinafine) and set their `max_daily_dose` to none. Each gives one fixed adult dose
  and no adult maximum. No model or spec 0.3 reading of this set existed then.
