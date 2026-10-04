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
is one key, more than one when the dose holds for each of them, `0` when it belongs to none, or
`?` when the person can't tell. `m` shows more of the text before the dose, and `s` shows section
1 of the label, which says what each key covers. The tool never shows which keys a spec puts at
the dose. The labels go in `labels.json`.

The labeling showed two gaps in the tool, and both were fixed before scoring:

- Some short forms need medical knowledge: "ALL" (acute lymphoblastic leukemia) is one of the
  neoplastic diseases of methotrexate. `s` and `m` were added so that the label's own text
  settles them.
- My first instructions said to type `0` for a dose that holds for every patient. That is wrong:
  such a dose holds for each key. `?` and `label --recheck` were added, and every dose labeled
  `0` was labeled again with the corrected instructions.

The doses labeled `?` are listed in `results.json` and left out of the counts.

## Scoring

```bash
uv run python bench/keys/keys.py score --check    # fail if the committed files differ
```

[RESULTS.md](RESULTS.md) reads the keys at each dose under spec 0.2, the released 0.2.0 wheel in
its own environment, and under spec 0.3, the core in this repository. For a dose with keys, it
asks whether every labeled key reaches the dose (a candidate with it is admitted) and whether a
wrong key does (a candidate with it is admitted too). The rule was fixed on #52 before the pick.
CI runs `score --check`.

What it found:

- The label-line rule stops a wrong key at short forms and headings that are not keys, such as
  "Cold Sores", "Benign Gastric Ulcer" and "2.1 Dosing Information".
- It also sends right keys to review, in the same number of doses as it fixes. Half of those are
  a bullet that the text puts on a line of its own, which the rule reads as a label line (#86).
  The rest are under headings that are not keys, such as "2.1 General Considerations".
- A wrong key still reaches many doses under both specs, most of them where one sentence or a
  flattened table mentions two or more keys (#87).
- No label changed after scoring.
