# Benchmark set 2

The documents spec 0.2 is measured on (#1). [SELECTION.md](SELECTION.md) has the rules that
picked them, frozen before anyone read one. The v0.1 set in `bench/` is unchanged.

| File | What it is |
|---|---|
| `sources.json` | 101 documents, each with its URL, SHA-256, groups and the pages or sections used |
| `selection-log.json` | every candidate the rules looked at, and why it was taken or skipped |
| `docs/` | the text of each document, written by `fetch.py` |
| `gold/` | the gold: model drafts in `drafts_*.py`, built by `build.py` into one file per document, then checked by a person (#10) |

```bash
uv run python bench/fetch.py --set bench/set2   # re-download, check the hashes, rewrite docs/
```

## Gold

A model (Claude) drafted the gold after spec 0.2 was frozen, from the rules in SELECTION.md
"Fields". The drafts are not ground truth: a person checks every fact in the labeling app, as for
v0.1, and only checked facts count. Targeted fields are capped at the matches the walk counted,
and control documents are judged only where spec 0.1 and 0.2 disagree (SELECTION.md "Fields").

```bash
uv run python bench/set2/gold/build.py              # write gold files for new drafts only
uv run python bench/set2/gold/matches.py            # the matched sentences of targeted documents
uv run python bench/label/app.py --set bench/set2   # check them
```

## Runs

`runs/<model>/<buffer>/<id>.json` holds each model's extractions from `bench/propose.py`, the same
roster and flags as v0.1, at buffers 1,000 and 4,000 (#11). Every model saw the same prompts:
947 chunks at 1,000 and 262 at 4,000. Each record keeps the raw reply and the SHA-256 of the
prompt for every chunk, plus the CLI version.

```bash
uv run --group langextract python bench/propose.py --set bench/set2 --provider claude-cli \
  --model claude-sonnet-5-5 --label "Claude Sonnet 5.5" --buffer 1000
```

A rerun skips documents that already have a file, so delete one to run it again.

## Scoring

```bash
uv export --only-group langextract --no-emit-project --no-hashes -o /tmp/bench-req.txt
uv run --isolated --no-project --with groundgate==0.2.0 --with-requirements /tmp/bench-req.txt \
    python bench/score.py --set bench/set2 --controls                         # list the controls
uv run python bench/label/app.py --set bench/set2 --controls                  # judge them
uv run --isolated --no-project --with groundgate==0.2.0 --with-requirements /tmp/bench-req.txt \
    python bench/score.py --set bench/set2                                    # RESULTS.md
```

[RESULTS.md](RESULTS.md) scores every run under spec 0.1 and spec 0.2, side by side (#12). Spec 0.2
is the released 0.2.0 wheel, not the code in `src/`, which moves on to the next spec. Spec 0.1 is
the released 0.1.0 wheel, which `score.py` runs in a separate process through `bench/decide.py`.
Both decide the same candidates, built by the current LangExtract adapter, so a candidate carries
its key under both.

- **Keyed facts** are judged on field, key and value. The key comes from the model's extraction
  and is compared the way SPEC §4.5 compares keys. A right value under another key is `wrong_key`.
- **Spec 0.1 has no keyed fields.** The 0.1.0 wheel refuses a schema with `keys`, so `decide.py`
  drops them and makes the field `multiple`: what a 0.1 user would write for a field with one
  value per condition.
- **Controls** are judged only where the two specs decide differently. `--controls` writes
  those candidates to `controls.json`, without either decision, and a person judges each one in
  the labeling app. The other control candidates are not scored. The pooled rates cover the
  documents checked in full only.
- **Every rate carries its document count**, and every wrong candidate admitted without review
  is listed one by one, under each spec.
- **`--drafts` is refused.** Set 2 is scored on checked gold only.

Track A plants the v0.1 classes and three new ones: `key_swap` (#2), the right value under the
first other key that does not hold it; `per_kg_as_absolute` (#3), a weight-based dose given to
the first field with the absolute unit, under the key whose title appears last before the value
(the first key when none does);
and `from_value` (#4), the old value of "from X to Y" for a field that means Y. The clean
extraction is also scored on its own for each gold fact whose evidence overlaps a match of the
`change`, `negation` or `scale` pattern in `bench/pick.py` (#4, #5, #6).

### Gold changes after scoring

The gold was checked blind (#10). After the first scoring, spec 0.2 admitted model claims on
fields the gold called absent, so I looked at the three that read most like real values. That
look came with model output in view, so every change is listed here.

- The rule for a recommended daily range ("200 mg to 400 mg daily") is that its upper end is the
  maximum, as the blind check already decided for amoxicillin and valsartan. Applied everywhere:
  - `fda-topiramate`, `max_daily_dose`, Adjunctive Therapy Epilepsy: absent, now 400 ("200 mg to
    400 mg orally once daily", adults).
  - `fda-hydroxychloroquine`, `max_daily_dose`: absent, now excluded. Rheumatoid arthritis has an
    initial and a chronic range, so its maximum is not one value.
  - `fda-spironolactone`, `max_daily_dose`: absent, now excluded. Its ranges do not map clearly to
    its indications.
- Looked at and left as they were: topiramate's "should not exceed 400 mg/day" is in the
  pediatric paragraph; `irs-p54`'s $120,000 is from a worked example, not the stated maximum;
  lamotrigine's Epilepsy key has several ranges that depend on other drugs, so it keeps no value.

### Caveats

- `scale_word_in_text` skips a value that is already written with a scale word, because the plant
  would read "183 million million". The v0.1 scorer planted one such fact (`irs-p15b`); the v0.1
  numbers stay as published.
- A scorer bug found after scoring is fixed and noted here. A spec fix waits for 0.3.

## Licenses

- FDA drug labels (DailyMed SPL): openFDA publishes drug label content as public domain under
  [CC0](https://open.fda.gov/license/). The labels are written by manufacturers and approved by
  FDA.
- NTSB reports, IRS publications and Federal Register documents: works of the US government,
  not subject to copyright in the United States (17 U.S.C. 105).
- The FDA order comes from CMS "Medicare Part D Spending by Drug" (2024), used only to rank
  drug names.
