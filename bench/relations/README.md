# Relations set: the relation question

This set is the gold for the relation question of #67. Spec 0.3 flags a value
`QUALIFIED_VALUE` when it finds a qualifier near it (SPEC §4.2) whose comparator is not the
field's. A System 1 model can clear that flag when it reads that the text states the field's
relation. To measure that, each value here is labeled by a person with the relation that the text
states for it. The plan is on #67, and it was fixed before anyone read a document of this set.

`relations.py` is the pick of the keys set (`bench/keys/keys.py`) with its own items. The pick
looks only at label metadata and value counts, and prints no text. The label tool never shows
what spec 0.3 or a model reads.

```bash
uv run python bench/relations/relations.py pick --count   # how many values the walk finds
uv run python bench/relations/relations.py pick           # write sources.json, selection-log
uv run python bench/fetch.py --set bench/relations        # download, verify, write docs/
uv run python bench/relations/relations.py items          # write items.json from docs/
uv run python bench/relations/relations.py label          # label them in the terminal
```

## Labels

FDA labels in the set-2 Part D ranking, up to rank 1200, with the set-2 label rules: the first
search result that is a single-ingredient tablet or capsule label with sections 1, 2 and 3. The
text is sections 2 and 3, as in the keys set. A label does not need subsections in section 1,
because an item here has no key.

## What is excluded

Every drug that v0.1, set 2, the pattern set, the dots set, the keys set or the tables set used.

## An item

A number token with a value (SPEC §4.1) for which spec 0.3 finds a qualifier (`qualifiers()` is
not empty). These are the values that spec 0.3 flags for a field with the default comparator
`eq`. 6 items for each label at most, 150 in all, in label order.

## A label

The relation that the text states for the marked value: `eq`, `le`, `lt`, `ge`, `gt`, `approx`
or `range`. `x` is a value that is not a fact, such as a section number, and `?` is not sure.
Both are left out of the gold.
