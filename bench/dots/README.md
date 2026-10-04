# Dots set: the abbreviation sentence-end rule

This set measures one rule of spec 0.3 (#63, SPEC §4.2): the dot of a listed abbreviation does
not end a sentence when the next word starts with no uppercase letter. The pattern set
(`bench/patterns`) is where the "p.m." case was found, so it can't measure the rule (#73).

These rules were fixed before anyone read a document of this set. `dots.py` is the same rules as
code. Its `pick` step looks only at titles, section codes, page counts and dot counts, and prints
no text.

```bash
uv run python bench/dots/dots.py pick --count     # how many dots each kind finds
uv run python bench/dots/dots.py pick             # write sources.json, selection-log.json
uv run python bench/fetch.py --set bench/dots     # download, verify, write docs/
uv run python bench/dots/dots.py items            # write items.json from docs/
uv run python bench/dots/dots.py label            # label them in the terminal
uv run python bench/dots/dots.py score            # RESULTS.md: spec 0.2 and 0.3
```

## A dot

A listed abbreviation, as a whole word, whose dot is followed by whitespace. The list is the one in
SPEC §4.2, written out in `dots.py`, so the pick does not run the rule it measures. A dot inside a
Federal Register running head ("Federal Register / Vol. 90, No. 123") does not count, because the
head repeats on every page. The head is matched across line breaks, because the extraction
sometimes splits it. Both kinds count: a dot before an uppercase word, which spec 0.3 keeps as a
sentence end, and a dot before any other character, which spec 0.3 does not.

## What is excluded

Every drug, IRS publication and Federal Register rule that v0.1, set 2 or the pattern set used,
by name and number.

## Order

Each kind takes documents in a fixed order until it has 50 dots. The first 5 dots of a document
count.

- **FDA:** the set-2 Part D ranking and label rules, up to rank 400, sections 1 and 2. These
  sections rarely hold a listed abbreviation, so FDA stops at a rank and not at a dot count.
- **IRS:** publications in numeric order. The text is the pages that hold the first 5 dots.
- **Federal Register:** final rules of at most 20 pages, published 2025-01-01 to 2025-06-30,
  newest first. Set 2 took 2026 and the pattern set 2025-07-01 to 2025-12-31.

The counts of dots and documents, for each kind, are in [RESULTS.md](RESULTS.md) once the dots are scored.

The first pick counted running heads, and a review of #74 found that most of the Federal Register
dots were `Vol.` and `No.` in them. The running-head rule was added, and then widened to a head
split over lines, which the second review found. The pick ran again each time before anyone read
the text.

## Labels

`dots.py label` shows each abbreviation in its text and asks one question: does the sentence end
at its dot (`end`), or does it go on (`goes on`)? It never shows how a spec reads the dot. The
labels go in `labels.json`.

## Scoring

```bash
uv run python bench/dots/dots.py score            # RESULTS.md and results.json
```

[RESULTS.md](RESULTS.md) reads each dot under spec 0.2, which ends a sentence at every `.`
followed by whitespace, and under spec 0.3 (the core in this repository), and counts each
reading against the label. The rule was fixed at the head of #72 before anyone read a dot. CI
runs `score --check`.

What it found:

- Of the 107 dots where the sentence goes on, spec 0.2 cuts all 107 and spec 0.3 cuts 10. A cut
  sentence can lose a qualifier that stands before the dot.
- Of the 9 real sentence ends, spec 0.3 joins none.
- With the #63 rule alone, spec 0.3 cut 53 of the 107. Most were `U.S.` and `No.` before a
  capitalized word, as in "U.S. Tax Court" and "Docket No. DEA-1086". The #77 rule joins those.
  This set found them, so it does not measure that rule: the caps set (`bench/caps`) does.
- The 10 cuts that remain are other abbreviations before an uppercase letter or a parenthesis,
  such as "Inc. Ora Plus" and "St. John's wort", and 3 `No.` before a blank line in a table.

The rule changed twice after the first scoring, both times from a security review of #72, not from
this set. It first joined before any character that was not an uppercase letter, and a join before
a parenthesis let the key of one sentence reach a value in the next. The join then needed a
lowercase letter, a digit or a currency sign, and with the first rule spec 0.3 had cut 51 of the
107 and joined 1 of the 9 real ends ("mL/min. ( 2.2)"). A second review showed that a real sentence
can start with a digit too, so the join now applies only to the qualifier window, where it can only
add a flag. Key scope and the unit search end at every dot, as in spec 0.2. This set measures the
qualifier window.

## Labels changed after scoring

The labels were made blind. Three changed from "goes on" to "end" after the first scoring
showed the dots: `irs-p556:17116` ("inter- est. This period", the word "interest" broken over a
line), and `irs-p529:12011` and `irs-p547:8951` ("1040-SR." before a heading).
