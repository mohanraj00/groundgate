# Regulatory texts: a held-out family

Status: the members, their source pins, the split and the slots are frozen (#641). The labels
come from two blind passes and the owner's decisions. The claim on this family is #686.

The set has 14 CFR parts: fee rules, rate tables, definitions and numbered method steps. Today
the other bench sets have business documents. This family measures the gate on the texts of a
knowledge source.

| Split | Parts |
|---|---|
| calibration | 10 CFR 171, 19 CFR 24, 36 CFR 71, 46 CFR 401, 46 CFR 404 |
| heldout | 7 CFR 800, 8 CFR 106, 9 CFR 391, 10 CFR 170, 14 CFR 187, 33 CFR 402, 37 CFR 201, 49 CFR 107, 49 CFR 1002 |

The family profile is calibrated on the 5 calibration parts only. No rule and no threshold is
tuned on the 9 held-out parts.

## Selection

The owner approved all 14 parts of the candidate list in #641 on 2026-11-17. I selected them from
publisher metadata only: the eCFR title list, the eCFR structure API of 2026-11-12, and the
Federal Register API. None of the 84 Federal Register final rules in set 2, `bench/caps`,
`bench/dots` and `bench/patterns` amends one of the 14 parts.

## Sources

Each member is the XML of one part at 2026-11-12 from the eCFR versioner API.
`manifest.json` records the URL, the byte size, the SHA-256 of the XML and of the reader text,
and the citation and the heading of the part. The parts are US government works (17 U.S.C. 105).
The XML and the reader text stay in local work storage.

```bash
WORK=/path/outside/the/repo/regulatory-686
uv run python bench/regulatory/sources.py --out "$WORK/sources" --fetch
```

This command downloads the parts again, does the checks, and writes `manifest.json`,
`source_checks.json` and the reader text of each part as `<id>.txt` next to its XML. If the XML
or the reader text of a part is not the pinned one, the command fails before it writes a file,
so a rerun cannot change the members or the split. Two downloads on 2026-11-17 gave the same
bytes. The reader text comes
from `groundgate.read` at the code digest in `reader_text`.

## Source checks

`source_checks.json` has the checks of each part:

- The identity: the root is the part, and the citation and the heading match the approved list.
- The section count: it is equal to the count of the list for all 14 parts.
- The text and the language: the reader text is not empty, and it is English.
- The notices: the script finds each place that says copyright, reproduction or permission. I
  read them. Each one is regulation text, for example a rule on copies of certificates. No part
  has a notice of the publisher, so no part is on hold.

## Split

The seed is the SHA-256 of the source digests in member order, one on each line. The 5 ids with
the lowest SHA-256 of the seed, a line feed and the id are the calibration parts. Nobody can
choose the seed after the download, and the seed came before any label.

## Slots

The owner approved five fields on 2026-11-17. `slots.py` draws the slots of each part from its
structure only: section headings, the defined terms of a definitions section, table captions,
row positions and column headers. The draw uses the split seed. One layout test reads a cell: a
`table_value` cell must hold a digit.

| Field | Kind | Slots for each part | Calibration | Held-out |
|---|---|---|---:|---:|
| `section_text` | passage | 2 | 10 | 18 |
| `definition` | passage | 1, if the part has a definitions section | 2 | 4 |
| `table_value` | number | 2, if the part has a table | 6 | 14 |
| `table_rows` | record | 1, if the part has a table with 2 to 30 body rows | 3 | 5 |
| `effective_date` | date | 1 | 5 | 9 |

That is 76 slots: 26 calibration and 50 held-out. `slots.json` holds each request and the
field rules.

```bash
uv run python bench/regulatory/slots.py --sources "$WORK/sources"
```

## Labels

The owner approved this method on 2026-11-17. `passes.py` runs it:

1. Pass a is Claude Code (`claude -p` with no tools). Pass b is Codex (`codex exec` in a
   read-only sandbox, in an empty folder). Each pass gets the slots of one part and the reader
   text and the XML of each named section, and nothing else.
2. Each slot that a pass marks absent gets a second blind check by a new agent of the other
   harness.
3. A pass keeps a reply only when each answer has the shape of the answer rules. A number is
   a string of digits, a date is a real `YYYY-MM-DD` date, and a record is a list of rows.
4. `passes.py compare` gives the agreements: the same normal form in both passes and in each
   absence check. An absence with no second check is missing, not an agreement. A cached
   answer with a bad shape is invalid. The owner decides each other slot on the page of
   `bench/label/decide.py`, and the page refuses a choice with a bad shape.
5. `passes.py seal` writes `labels.json` and its digest into the manifest. It refuses while a
   slot is open. The labels are sealed before any benchmark model output on this set.

The labels were sealed on 2026-11-17. 71 of the 76 slots are agreements, and the owner decided
the other 5. 58 labels have a value and 18 are absent. The manifest records the digest of
`labels.json`.

The answers of the passes stay in local work storage.

## Run the claim

I run these commands from the repository root after the source and label seals are in place.
`$WORK/sources` has the pinned XML and reader text. The other directory holds the call cache.
Keep both directories outside the repository.

```bash
WORK=/path/outside/the/repo/regulatory-686
uv run python -m bench.regulatory.run calibrate --sources "$WORK/sources" --cache "$WORK/calls" --model gpt-6.2-sol --effort medium
uv run python -m bench.regulatory.run freeze --sources "$WORK/sources" --cache "$WORK/calls"
uv run python -m bench.regulatory.run heldout --sources "$WORK/sources" --cache "$WORK/calls" --model gpt-6.2-sol --effort medium
```

The calibration command caches one reply per calibration part. The freeze replays the
cache and seeks to the pinned calibration label ranges in `labels.json`. It measures the
scalar routes with `groundgate calibrate measure` and scores each passage and table as a whole
from its receipt. The local calibration report has both measures. The manifest records the
profile, the code and profile digests, and the transport version, model and effort.

Each request includes the named section of the pinned reader text. I use the headings and
defined terms in the XML to form the passage outline. The scorer strips the heading and
the trailing source note from an admitted passage. A table counts as one value and keeps
its row order, column names and empty cells.

The held-out command checks the freeze before any model call. It reserves one run in
`heldout-run.json` and records each reply before admission. A repeat command can reuse
completed calls from the same cache while the run is incomplete. A pending call or a
recorded transport error stops the run. A malformed answer counts as invalid and supplies
no admitted value. The command opens the full label seal after admission, writes
`results.json` and renders `RESULTS.md` from it. Once the result exists the command refuses
another run. If the report is missing, I can render it again from the existing result with
`uv run python -m bench.regulatory.run report`.

## Escapes

[ESCAPES.md](ESCAPES.md) has the cause of each of the 6 escapes of the held-out run (#709) and
the fix issues. `RESULTS.md` has no link to it, because `run report` refuses a report that is
not the exact render of `results.json`.
