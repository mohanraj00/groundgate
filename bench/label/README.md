# Checking the gold

Every fact in `bench/gold` starts as a model-written draft. A person checks each document in this
app before its facts count. The app never shows what the benchmarked models extracted.

```bash
uv run python bench/label/app.py
```

For set 2, add `--set bench/set2`. Set 2 lists its control documents last, marked "control":
they are not checked in full (SELECTION.md "Fields"), so start with the others. It opens `http://127.0.0.1:8765`. Pick a document from the list at the top. The document is on
the left and its fields are on the right.

Tables lose their layout in the text: an IRS table comes out as its row labels, then its
values. **Original ↗** in the header opens the source PDF, or the label on DailyMed (which may
be a newer version than the pinned one), so you can read the table as printed. Decide from the
original, then cite the place in the text.

When the original is a cached PDF, the app also shows it in a pane between the text and the
fields. The pane turns to the PDF page of the focused fact's evidence. `p` or **PDF pane** shows
or hides it. Chrome and Firefox open the right page; other browsers may open page 1.

## What to decide

For each field, the draft gives either one or more values or says the field is not in the
document. Your job is to make that true.

- **Each fact has a badge.** "in evidence" means its value is written in its evidence, in any
  form: `1000000` matches "1,000,000", "$1 million" and "$1.0 million". Then you only check what the value
  means. "not in evidence" or "no evidence" means the draft is probably wrong, so read it
  closely. The badge only shows where to look. You still decide every fact.
- **A draft value is right.** Press `y` (or click ✓). Check the evidence chip too: it should
  point at the place in the text that states the value. If the same number is stated for the
  same field somewhere else, click its `+` chip under the fact to add that place as evidence.
  An extraction that cites any listed place counts as citing the right place, and one that
  cites a place you did not list counts as citing the wrong one, so add every place that
  states this field's value. A dose that happens to equal the tablet strength is not a place
  that states the tablet strength.
- **A draft value is wrong.** Fix the number in the box if the right one is in the text, or
  press `n` (✗) to reject it. If you reject the only value of a field, either add the right one
  or click **Not in document**. A field left with neither is not scored.
- **A value is missing.** Select the number in the document (with its unit, if adjacent), focus
  the field, and press `+`. For list fields such as `tablet_strengths`, add each value.
- **The draft says the field is absent.** Search the text. If it really is absent, press `a`.
  If it is there, add it from the selection.
- **The field does not fit this document** (two readings are both defensible, or the text is
  garbled): click **Exclude as ambiguous** and give the reason. Excluded fields are not scored.

Values are plain numbers: `15750` or `15,750`, no `$` and no unit. Units come from the field.

- **The field is keyed** (set 2, FDA labels with indications): each fact has a key picker. Check
  that the value belongs to the indication shown, and change the key if it belongs to another
  one. A value you add from the selection starts with no key; pick one. The number keys pick a
  key by its number in the picker. With 10 or more keys, type both digits, `1` then `2` for 12.

When nothing on the page is still a draft, and every kept fact on a keyed field has a key, click
**Mark document checked**. The app refuses
until every draft fact and absence is decided.

## Keys

| Key | Action |
|---|---|
| `j` / `k` | next / previous item |
| `y` | fact is correct |
| `n` | fact is wrong |
| `a` | confirm the field is absent |
| `+` | add the selected text as a fact for the focused field |
| `1`-`9` | pick the key with this number for the focused fact |
| `p` | show or hide the PDF pane |
| `c` | mark the document checked |
| `[` / `]` | previous / next document |

## A second look at absences

An absence is easy to confirm too fast, because the value can sit in a part of the text you
did not read. After the check, look at the absences again:

```bash
uv run python bench/label/app.py --set bench/set2 --absent fda
```

`--absent` lists only the documents checked in full that have an absence, of one kind (`fda`,
`irs`, `fr`) or of all kinds without a value. `j` / `k` move between the absences only. Under
each absence, chips show the lines that name the field ("hepatic", "pediatric", "maximum" and
similar words) where that line or the next holds a number. Click a chip to read the line.

- **The value is there.** Select it, then press `+`. Pick the key if the field has keys, then
  press `c`. A changed document must be marked checked again.
- **The absence holds.** Press `]` for the next document. Nothing is saved.

The chips only show where to look. A field with no chip can still be in the text.

## Rules of thumb

- Read the field description, not just the name. `pilot_total_hours` is all aircraft;
  `pilot_make_model_hours` is this make and model.
- Take the value the text states. Do not compute one, and do not use outside knowledge.
- When the document states a value for a different year, a different filing status or a
  different population than the field asks for, that value is not the field's value.
- Saves are automatic. The timer counts time with the tab visible, and the total is written to
  the gold file so the benchmark can report the labeling cost.

The first check covered 276 draft facts and 34 absences across 30 documents and took 2.4 hours.
The NTSB reports are the fastest; the IRS pages take the most reading. One-hour sittings work
well.
