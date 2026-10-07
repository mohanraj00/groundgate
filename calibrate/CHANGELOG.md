# Changelog

Versions follow [SemVer](https://semver.org). groundgate-calibrate is released apart from
groundgate, with tags `calibrate-v*`.

## 0.1.0

The first release. It measures a judge's thresholds for groundgate on your own documents, as hybrid
design §9 describes.

- `sample`, `split`, `label`, `ask`, `report`: from the candidates to a threshold, with blind
  labels in the browser before any model answers.
- `judge` writes recorded judgments that spec 0.4 and later read.
- It needs `groundgate>=0.4`. A work directory holds the spec it was sampled under, and the tool
  refuses one from another spec.
