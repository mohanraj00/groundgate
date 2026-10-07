# Status set: the key rules on IRS filing status

This set measures the two key rules of spec 0.3 on a kind that is not an FDA label (#113). Both
rules were written and measured on FDA labels: the label-line rule (#52, `bench/keys`) and the
table-sentence rule (#87, `bench/tables`). Here the keys are filing statuses, and the values are
dollar amounts in IRS publications.

These rules were fixed on #113 before anyone read a document of this set. `status.py` is the same
rules as code, on top of the keys-set tool. Its `pick` step looks only at counts and prints no
text.

```bash
uv run python bench/status/status.py pick --count     # how many amounts the walk finds
uv run python bench/status/status.py pick             # write sources.json, selection-log.json
uv run python bench/fetch.py --set bench/status       # download, verify, write docs/
uv run python bench/status/status.py items            # write items.json from docs/
uv run python bench/status/status.py label            # label them in the terminal
uv run python bench/status/web.py                     # or in a browser, at 127.0.0.1:8767
uv run python bench/status/status.py score            # RESULTS.md: spec 0.2 and 0.3
```

## Publications and keys

English IRS publications from the IRS list, in numeric order. Every publication that another set
or an example used is skipped. The keys are the same 5 for every publication, as IRS text writes
them: Single, Married filing jointly, Married filing separately, Head of household and Qualifying
surviving spouse.

"Single" also matches the plain word, as in "a single payment". It stays a key, because a user's
packet has the same key and the same hazard.

## An amount

A number token (SPEC §4.1) right after `$`. It counts only on a page that names 2 or more of the
keys. A publication gives its first 6 amounts, and the walk stops when the set has 100. A
publication whose pages have the same text as an earlier one is skipped. The walk found 100
amounts in 18 publications.

## Labels

`status.py label` shows each amount in its text, with the line breaks of the text, and lists the
5 keys. It asks one question: which filing statuses does the amount belong to? The answer is one
key, more than one when the amount holds for each of them, `0` when it belongs to none, or `?`
when the person can't tell. An amount that holds whatever the filing status holds for each key.
The publication's own text decides, not outside tax knowledge, because groundgate reads only the
document. An amount that the text does not limit to some statuses holds for each of them, even
when the law sets another amount for one status. Example: "taxpayers with MAGI more than $85,000"
holds for all 5, although the law gives married filing jointly a higher threshold.
`m` shows more of the text before the amount. IRS tables are hard to read as text, so
`web.py` shows the same question in a browser, next to the PDF page with the amount boxed. Both
write the same `labels.json`. The tool never shows which keys a spec puts at the
amount. The labels go in `labels.json`, and the amounts labeled `?` are left out of the counts.

## Scoring

```bash
uv run python bench/status/status.py score --check    # fail if the committed files differ
```

[RESULTS.md](RESULTS.md) reads the keys at each amount under spec 0.2, the released 0.2.0 wheel in
its own environment, and under spec 0.3, the core in this repository. Spec 0.4 keeps the key
rules of 0.3. For an amount with keys, it asks whether every labeled key reaches the amount and
whether a wrong key does. CI runs `score --check`.
