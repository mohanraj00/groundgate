# groundgate docs

groundgate checks the values that an extractor pulls from a document, and returns one decision for
each value with the reason. Start with the [quickstart](../README.md#quickstart), then pick the
page for your task.

## How-to guides

| Task | Page |
|---|---|
| Write a schema for your documents | [schema.md](schema.md) |
| Check your own model's extractions, end to end | [howto/own-model.md](howto/own-model.md) |
| Send the reasons back to the extractor and decide again | [howto/feedback.md](howto/feedback.md) |
| Check values in financial tables | [howto/tables.md](howto/tables.md) |
| Use references, web sources and the model's knowledge | [howto/outside-sources.md](howto/outside-sources.md) |
| Review flagged facts, and keep and verify receipts | [howto/review.md](howto/review.md) |
| Check LangExtract output | [guide.md#langextract](guide.md#langextract) |
| Measure a judge's thresholds on your documents | [howto/calibrate.md](howto/calibrate.md) |

## Reference

- [guide.md](guide.md): every input, policy key, code, function and command, with defaults.
- [SPEC.md](../SPEC.md): the normative rules of every decision. Another implementation conforms
  when it passes the vectors in [conformance/](../conformance).
- [CONTEXT.md](../CONTEXT.md): the terms that the docs use.
- [CHANGELOG.md](../CHANGELOG.md): what each version changes, with its measure.

## Decisions and designs

- [adr/0001-admit-by-policy.md](adr/0001-admit-by-policy.md): why the app's policy, not
  groundgate, decides whether to trust evidence from outside the document.
- [design/hybrid-decisions.md](design/hybrid-decisions.md): recorded judgments from a model or a
  person. Partly built.
- [design/locale-packs.md](design/locale-packs.md): number formats outside English. A design.

## The benchmark

[bench/README.md](../bench/README.md) has every measure behind the numbers in the README, and each
set's `results.json`.
