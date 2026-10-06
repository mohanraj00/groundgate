# Fields set: the field question

This set is the gold for the field question of #67: does the text state this field as this
value? A System 1 model would ask it about an admitted value, and a low probability would send
the value to review (hybrid design §5). To measure that, each dose here is labeled by a person
with the fields that the text states as that dose. The plan is on #67, and it was fixed before
anyone read a document of this set.

`fields.py` is the pick of the keys set (`bench/keys/keys.py`) with its own documents. The pick
looks only at label metadata and dose counts, and prints no text. The label tool never shows
what spec 0.3 or a model reads.

```bash
uv run python bench/fields/fields.py pick --count   # how many doses the walk finds
uv run python bench/fields/fields.py pick           # write sources.json, selection-log.json
uv run python bench/fetch.py --set bench/fields     # download, verify, write docs/
uv run python bench/fields/fields.py items          # write items.json from docs/
uv run python bench/fields/fields.py label          # label them in the terminal
```

## Labels

FDA labels in the set-2 Part D ranking, up to rank 2000, with the set-2 label rules: the first
search result that is a single-ingredient tablet or capsule label with sections 1, 2 and 3. The
text is sections 2 and 3. A label does not need subsections in section 1, because these fields
have no key.

## What is excluded

Every drug that v0.1, set 2, the pattern set, the dots set, the keys set, the tables set or the
relations set used.

## A dose and its fields

A dose is a number token followed by mg or mcg, as in the keys set, 6 for each label at most,
150 in all, in label order. The fields are four set-2 FDA fields in mg, with the schemas and the
descriptions that set 2 uses for a label without keys (`FIELDS` in `fields.py`):
`starting_dose`, `max_daily_dose`, `hepatic_starting_dose` and `strengths`.

## A label

The fields that the text states as the marked dose: one, several, or none. `?` is not sure, and
it is left out of the gold.
