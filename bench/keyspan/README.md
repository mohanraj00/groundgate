# Keyed claims

This measures spec 0.5 key citations (#131). A candidate can cite the span that names its key
(#129), and the extractor gives that span when the prompt asks for it (#130). The question: does a
cited key admit more right keys without more escapes?

## Sets and runs

Two sets that the rule was not written from:

- The status set (`bench/status`): IRS publications, one keyed field `amount` [USD] with the 5
  filing statuses as keys.
- The 10-K key labels (`bench/sec/work-key`): the fiscal year of a reported value.

Each set has two runs of Claude Haiku 4.5 at buffer 4000: the plain keyed prompt, and the same
prompt with `--key-span`.

Spec 0.4 is the same candidates without `key_evidence`. SPEC §4.5 says that this is the 0.4
decision, and vectors 19 and 19b check it. So each run gets a 0.4 and a 0.5 decision.

## Commands

```bash
uv run python bench/keyspan/keyspan.py gold          # the one keyed field, in bench/status/gold/
uv run python bench/keyspan/keyspan.py decide        # decisions.json; --set status or --set sec
uv run python bench/keyspan/keyspan.py results       # results.json and RESULTS.md
uv run python bench/keyspan/keyspan.py results --check
uv run python bench/keyspan/web.py                   # label page at http://127.0.0.1:8769
```

`decide` stops if a run does not cover every document in the set's `sources.json`.

## Population

The population is the labeled amounts: the status labels in `bench/status/labels.json` and the
10-K labels in `bench/sec/work-key/labels.json`. A candidate counts for an amount when its value
token is the labeled one. A value token is the first number token that holds the value, as the
core reads it, scale words included. An amount's position is the start of the first number token
in its labeled span, so "$35.1 million" sits at "35.1".

A status amount labeled "not sure" is in the population but no score counts it. An amount labeled
with no key counts as right only when no key is admitted for it.

The 10-K population is biased. Its items come from the review queue of the #120 plain run, so on
the plain run spec 0.4 admits 0 right keys there by construction. Compare the two specs on the
key-span run.

## Ship rule

The escapes for the ship rule are the wrong keys admitted in the population, plus the `KEY_CITED`
escapes outside it, on the key-span run. If they rise from 0.4 to 0.5 on either set, keyed claims
do not ship in 0.5.

## Blind labeling

Every `KEY_CITED` admit is listed, also outside the population. Where no set labels the amount, I
label it on the web page. The page shows the PDF page with the value boxed for an IRS document,
the text around the value, and the field's keys. It never shows the extractor's key, its key span
or a decision. Labels go to `bench/keyspan/labels.json`.

Until an amount has a label, `results.json` and `RESULTS.md` show "hidden until labeled" in place
of its key. The results never print a key the labeler has not judged.

## What is committed

`decisions.json` holds offsets, keys, values and codes for each decision, and the position of each
labeled amount. It holds no 10-K text, so `results --check` runs without the 10-K documents. The
status runs are committed, as IRS text is public. The 10-K runs and documents stay out of git, as
in `bench/sec`.
