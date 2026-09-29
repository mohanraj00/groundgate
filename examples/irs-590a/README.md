# Example: IRS Publication 590-A, pages 1-2

The whole pipeline on a real public-domain document: PDF to text, two models proposing facts
through LangExtract, groundgate deciding, and a review page.

The two pages are the "What's New" section: IRA contribution limits and income phase-outs for
2025 and 2026. They are dense with similar dollar amounts, which is where extraction goes wrong.

## Result

Two models ran through LangExtract 1.7.0 with its default chunking, temperature 0 and one
invented few-shot example: Gemini 3.6 Flash (26 extractions) and GPT-OSS 120B (22). LangExtract
aligned all 48 as `MATCH_EXACT`. Every quote was found in the source.

| Outcome | Count |
|---|---:|
| Admitted | 44 |
| Needs verification | 3 |
| Rejected | 1 |
| Required fields missing | 1 |

I checked every decision against the source by hand.

**Rejected: a misprint read as a number.** Page 2 of the IRS PDF says:

> You can't make a Roth IRA contribution if your modified AGI is $252,0000 or more.

Gemini reported 2,520,000. groundgate rejected it with `VALUE_NOT_IN_EVIDENCE`: `252,0000` is
not a well-formed number, so no value can be read from it. (In an earlier run on the same pages,
both models made this mistake.)

**Needs verification: the right number from the wrong rule.** GPT-OSS filled two Roth IRA fields
with numbers from the *spousal* deduction sentence, "more than $236,000 ... but less than
$246,000". The Roth sentence has the same amounts, so the values happen to be right, but the
evidence is for a different rule. The schema declares both Roth fields as "at least" (`ge`), so
groundgate saw "more than" and "less than" at the cited spot and flagged them. The third flag is
noise: a correct spousal limit cited from "$252,000 or more", where the schema expects "less than".

**Missing: a field neither model extracted.** Both skipped the 2025 single-filer Roth limit
("$165,000 or more"). Coverage lists it, so the gap is visible instead of silent.

**Admitted: 44, all with the right value.** One of them cites the wrong rule and got through:
GPT-OSS put the spousal "$252,000 or more" into the 2026 joint Roth field. The number is what the
IRS meant for that field, and the comparator matches, so every check passes. This is the class
span checks cannot see, and the one the benchmark will measure.

Two rule changes came out of building this example, both in SPEC §4.2. A bare `from` no longer
counts as a range qualifier, because it flagged three correct "up from $236,000" facts in the first
run. `through` now counts as a range connector, which a reviewer pointed out `from` had been
covering. The tables above are from a second run on the final text; model output varies between
runs even at temperature 0.

Open `report.html` in a browser to see every decision next to its source text.

## Files

| File | What it is |
|---|---|
| `document.txt` | pages 1-2, from `groundgate extract` |
| `layout.json` | page and word boxes for the same text |
| `schema.json` | 25 fields, all required, each with its comparator ("more than" is `gt`) |
| `propose.py` | runs LangExtract; the only step that calls a model |
| `runs/*.json` | cached LangExtract output, one record per model |
| `build.py` | cached runs to `candidates.json`, `receipt.json` and `report.html` |

## Reproduce

From the cache, with no API key:

```bash
uv run python examples/irs-590a/build.py
uv run groundgate verify examples/irs-590a/receipt.json examples/irs-590a/document.txt \
  examples/irs-590a/schema.json examples/irs-590a/candidates.json
```

CI runs `build.py` and fails if any output file changes.

From scratch:

```bash
curl -LO https://www.irs.gov/pub/irs-pdf/p590a.pdf
shasum -a 256 p590a.pdf   # ca0e42873cfd66d2d9bfd082125d381f8a0c2f3b0a441d7d65ab5ccc06a0e1c7
groundgate extract p590a.pdf --pages 1-2 -o document.txt --layout layout.json
python propose.py --provider gemini --model gemini-2.5-flash    # needs GEMINI_API_KEY
python build.py
```

The IRS revises its publications, so a fresh download may not match the pinned text. The runs
here used the Antigravity CLI (`--provider agy`) rather than a raw API call; see `propose.py`.
