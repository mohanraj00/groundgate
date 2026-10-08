# Changelog

Versions follow [SemVer](https://semver.org). groundgate-calibrate is released apart from
groundgate, with tags `calibrate-v*`.

## 0.1.0 (2026-10-08)

The first version on PyPI ([#122](https://github.com/mohanraj00/groundgate/issues/122)). It
measures a judge's thresholds for groundgate on your own documents, as hybrid design §9 describes.
[Measure a judge's thresholds](https://github.com/mohanraj00/groundgate/blob/main/docs/howto/calibrate.md)
runs it from start to end.

- `sample`, `split`, `label`, `ask`, `report`: from the candidates to a threshold, with blind
  labels in the browser before any model answers.
- `judge` writes recorded judgments that spec 0.4 and later read.
- One judge is built in, and a package adds more with an entry point.
- It needs `groundgate>=0.4`. A work directory holds the spec it was sampled under, and the tool
  refuses one from another spec.
