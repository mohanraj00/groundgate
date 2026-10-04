# Keys set: the label-line rule

This set measures one rule of spec 0.3 (#52, SPEC §4.5). When a value's sentence mentions no key,
the key of the nearest earlier mention no longer reaches it past a label line, a short line of its
own between blank lines. Set 2 is where the gap was found, so it can't measure the rule (#83).

These rules were fixed before anyone read a document of this set. `keys.py` is the same rules as
code. Its `pick` step looks only at label metadata and dose counts, and prints no text.

```bash
uv run python bench/keys/keys.py pick --count     # how many doses the walk finds
uv run python bench/keys/keys.py pick             # write sources.json, selection-log.json
uv run python bench/fetch.py --set bench/keys     # download, verify, write docs/
uv run python bench/keys/keys.py items            # write items.json from docs/
uv run python bench/keys/keys.py label            # label them in the terminal
uv run python bench/keys/keys.py score            # RESULTS.md: spec 0.2 and 0.3
```

## Labels and keys

FDA labels in the set-2 Part D ranking, up to rank 600, with the set-2 label rules: the first
search result that is a single-ingredient tablet or capsule label with sections 1, 2 and 3. A
label counts when section 1 has at least 2 subsections. The keys are the titles of those
subsections without their numbers, and the text is sections 2 and 3, as in set 2.

## What is excluded

Every drug that v0.1, set 2, the pattern set or the dots set used.

## A dose

A number token (SPEC §4.1) followed by `mg` or `mcg`. The first 6 of a label count, and the walk
stops when the set has 100.

## Labels

`keys.py label` shows each dose in its text, with the line breaks of the text, and lists the
label's keys. It asks one question: which of these conditions does the dose belong to? The answer
is one key, more than one, or none of them. It never shows which keys a spec puts at the dose. The
labels go in `labels.json`.
