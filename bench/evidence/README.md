# The spec 0.5 evidence list, measured

The measure of #141 on two sets that the 0.5 rules did not come from. The roles came from the
10-K items of #132. The plan was posted on #141 before any new document was fetched.
[RESULTS.md](RESULTS.md) has every number, from `results.json`.

```bash
SEC_USER_AGENT="name email" uv run python bench/sec2/sec2.py pick    # the 20 filings
SEC_USER_AGENT="name email" uv run python bench/sec2/sec2.py docs
uv run python bench/sec2/sec2.py fields
uv run --group langextract python bench/propose.py --set bench/sec2 --provider claude-cli \
    --model claude-haiku-4-5-20251001 --label "Claude Haiku 4.5" --buffer 4000 --roles
uv run --group langextract python bench/propose.py --set bench/status --provider claude-cli \
    --model claude-haiku-4-5-20251001 --label "Claude Haiku 4.5" --buffer 4000 --roles
uv run --isolated --no-project --no-sources --python 3.12 --with groundgate==0.4.0 \
    python bench/evidence/measure.py decide04
uv run python bench/evidence/measure.py decide
uv run python bench/evidence/measure.py web       # blind labels
uv run python bench/evidence/measure.py results   # results.json, RESULTS.md
```

## Sets

- **bench/sec2**: the next 20 filings of the `bench/sec` walk (EDGAR 2026 Q1, `10-K`), after
  every filing that the first walk looked at, each accession number once. The five fields are
  keyed by fiscal year and have the aliases that I posted on #141 before the walk. The filings
  are not public-domain works, so only their pins are committed. The run and its candidates stay
  out of git, but the decisions and the labels are here.
- **bench/status**: the IRS filing-status set, with its gold and its own labels from #128.

## Runs and decisions

One run of Claude Haiku 4.5 with the `--roles` prompt of `bench/propose.py`. The prompt asks for
`sign_text`, `scale_text`, `unit_text`, `field_text` and `key_text`, and a made-up 10-K table
shows them. I wrote the note and the example before the run, and did not change them after.

Each run is decided seven ways: spec 0.4 on the 0.4.0 wheel, spec 0.5, and spec 0.5 with the
items of one role removed. The 0.4 adapter reads only the value span, so the 0.4 decision sees
the same extraction without its parts.

## Labels

The maintainer labeled every value that any decision admits, blind: the page showed the value,
the field, the key and the document, and never a spec, an outcome or a code. A value is right
when it is the field for that key, for the company's whole fiscal year, with its sign and scale.
On the status set, its own labels decided the amounts that they cover first.

## What it shows

- Spec 0.5 admits more right values on the new 10-K set than spec 0.4, with no escape. Spec 0.4
  admits one escape there, a value that re-anchoring moved to another occurrence of its quote.
- On the status set, the two specs admit the same right values, with no escape. Values with a
  missing part move from rejected to review.
- Two rules cost right values, and neither adds an escape:
  - A unit item fails when a unit form is already next to the number. The model often cites the
    `$` that is next to the number, so a right value goes to review. The ablation without unit
    items shows the cost.
  - A scale quote must be in the text as written, and the quote search counts case. Many scale
    quotes change the case or the brackets of the header.
