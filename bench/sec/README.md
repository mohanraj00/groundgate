# 10-K demo of the calibration tool

The first run of `groundgate-calibrate` (#112) from start to end, on a document kind that no #67
set used: Item 7 (Management's Discussion and Analysis) of 10-K annual reports. The plan and the
walk rule were posted on #112 before the walk, and the labels were made before any model answered.
[RESULTS.md](RESULTS.md) has every number.

```bash
SEC_USER_AGENT="name email" uv run python bench/sec/sec.py pick    # sources.json, log
SEC_USER_AGENT="name email" uv run python bench/sec/sec.py docs    # docs/, from the cache
uv run python bench/sec/sec.py fields                              # schema, descriptions, gold/
uv run --group langextract python bench/propose.py --set bench/sec --provider claude-cli \
    --model claude-haiku-4-5-20251001 --label "Claude Haiku 4.5" --buffer 4000
uv run --group langextract python bench/sec/sec.py cands Claude_Haiku_4.5/4000
groundgate-calibrate sample --work bench/sec/work-field --docs bench/sec/docs \
    --candidates bench/sec/cands --schema bench/sec/schema.json \
    --descriptions bench/sec/descriptions.json --question field \
    --context "The text is from Item 7 (Management's Discussion and Analysis) of a 10-K annual report."
groundgate-calibrate split  --work bench/sec/work-field
groundgate-calibrate label  --work bench/sec/work-field
TYPESAFE_API_KEY=... groundgate-calibrate ask --work bench/sec/work-field --judge jev
groundgate-calibrate report --work bench/sec/work-field
# the same five steps for the key question, in bench/sec/work-key
uv run python bench/sec/sec.py results                             # results.json, RESULTS.md
```

## Filings and text

The EDGAR full index of 2026 Q1, form type `10-K` exactly, in the order of sha256 of the
accession number. A filing passes when its primary document is HTML, it has an "Item 7." heading
and a later "Item 7A." or "Item 8." heading, and Item 7 (the longest text between such a pair)
has 5,000 to 150,000 code points. The walk takes the first 40 that pass and logs each skip in
`selection-log.json`. The text is groundgate's own HTML extraction, cut to Item 7.

10-K filings are not public-domain works. Only their pins are committed: `sources.json` has each
URL and sha256, and `sec.py docs` rebuilds the text from them. The text, the extraction runs and
the candidates stay out of git. EDGAR asks every client to name itself with a contact, which
comes from `SEC_USER_AGENT` only.

## Schema and candidates

Five fields in USD, each keyed by fiscal year (`2025`, `2024`, `2023`): `revenue`, `net_income`,
`operating_income`, `cash_and_equivalents` and `total_debt` (`schema.json`, `descriptions.json`).
One extraction run made the candidates: Claude Haiku 4.5 through `bench/propose.py`, with the
set-2 keyed prompt and a made-up 10-K example. I did not change the prompt after I saw the
filings.

Haiku scales table numbers: a table "in thousands" with "18,789" comes back as 18789000. Spec
0.3 rejects such a value as `VALUE_NOT_IN_EVIDENCE`, as it should, so most candidates never reach
a question.

## Labels

The maintainer labeled the field items in the tool, blind: does the text state the marked value
as the field? A value is right when it is the field as its description says, for the whole
company and for a fiscal year (or at the fiscal year end for cash and debt). A part (a segment, a
product, a quarter), a change, another measure or another period is wrong. "Cash" alone is
`cash_and_equivalents` when it is the company's whole cash balance at the year end, and wrong
when it is one account or a part, such as "cash in our operating account" or cash held in trust.

The maintainer then labeled the key items too, blind, in a second pass: which of the fiscal
years 2025, 2024 and 2023 the marked value belongs to, or none. Where extraction flattened a
table to one cell on each line, the tool linked to the filing on EDGAR (`links.json`).

## What it shows

- The tool works on a new kind from start to end: sample, split, label, ask, report, and a policy
  block for each ceiling with a threshold.
- The key clear helps on real extractor output. Almost every `KEY_NOT_AT_VALUE` flag here is a
  false alarm, and Jev clears most of the right ones on the test part with no escape. The FDA threshold gives the same result here. The
  test part has few wrong flags, so the escape side rests on little data.
- On these filings, the admitted values are almost all right already, so the field doubt has
  little to catch. The thresholds of the FDA and NTSB sets, applied unchanged, catch no wrong
  test value here, and the FDA threshold sends right values to review. A threshold does not travel
  between kinds of documents, and a user measures their own.
