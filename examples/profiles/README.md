# Two document-family profiles, one gate

A profile (SPEC §4.10) holds the terms, the policy and the route status of one document family.
These two profiles run through the same `gg.admit` with different terms and thresholds.

| Profile | Documents | Terms | Thresholds | Routes |
|---|---|---|---|---|
| [`invoice-v1`](invoice-v1/profile.json) | 60 synthetic invoices that `build.py` makes | the kind pack `invoice-x-example`: `total`, `subtotal`, `tax`, `invoice_number` | `unit_window` 24, judge clear `KEY_NOT_AT_VALUE` at 0.95 | `total`/`checked` is `measured` |
| [`fee-schedule-v1`](fee-schedule-v1/profile.json) | the NOAA schedule of user fees, Appendix A to 15 CFR part 950 (Federal Register 2026-07250, a US government work) | three keyed fees, with the keys `Current fee` and `New fee` | `unit_window` 40, judge doubt `field_match` at 0.3 | `certification_fee`/`checked` is `draft` |

Rebuild every output:

```bash
uv run python examples/profiles/build.py
```

No model is called, and each output rebuilds byte for byte. `tests/test_profile.py` fails if it
does not.

## The measured route of invoice-v1

`build.py` makes 60 invoices with known labels in [`invoice-v1/gold.json`](invoice-v1/gold.json).
A simulated extractor proposes each field. On `total` it makes three known errors: it gives the
subtotal as the total, it changes a digit, or it misses the field. The gate gives these results
for `total`:

| Outcome | Count |
|---|---|
| admitted, right value | 48 |
| admitted, wrong value | 0 |
| needs verification (`FIELD_CITATION_INVALID`: the subtotal cited as the total) | 5 |
| rejected (`VALUE_NOT_IN_EVIDENCE`: a wrong digit) | 4 |
| missed by the extractor | 3 |

0 wrong of 48 admitted gives the one-sided 95% upper bound 0.0605. The route row records it with
the day and the 60 documents, and `gold_sha256` is the SHA-256 of the bytes of `gold.json`.

This bound is a claim about these synthetic invoices and this simulated extractor only. It is
not a claim about real invoices. Measure your own family on documents that you did not use to
write its terms.

## The receipts

`invoice-v1/receipt.json` is the receipt of the first invoice, and `fee-schedule-v1/receipt.json`
is the receipt of the fee table. Each one names its profile in the member `profile`, with the
digest. In the fee table, the gate admits the three new fees. The current fee of the
certification goes to review with `KEY_NOT_AT_VALUE`: in this layout, the key check does not
put that value under its heading, so a person checks it. A layout need such as this one goes
into a profile term, not into a core reading rule.
