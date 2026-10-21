# Changelog

Versions follow [SemVer](https://semver.org). groundgate-calibrate is released apart from
groundgate, with tags `calibrate-v*`.

## 0.4.0 (2026-10-21)

The last release ([#385](https://github.com/mohanraj00/groundgate/issues/385)). The tool moved
into groundgate 0.11 as the command `groundgate calibrate`, with the same steps and options.

- It requires `groundgate>=0.11`.
- `groundgate-calibrate` prints one line that tells you to change, then runs
  `groundgate calibrate` with your arguments.
- The modules `groundgate_calibrate.judges`, `questions`, `label` and `stats` are gone. Import
  them from `groundgate.calibrate`.

## 0.3.0 (2026-10-20)

Checked against groundgate 0.10.0 and spec 0.10
([#325](https://github.com/mohanraj00/groundgate/issues/325)).

- A field that takes a kind pack's template gets its description from the template (spec 0.10,
  [#335](https://github.com/mohanraj00/groundgate/issues/335)). Before, `sample` and `judge`
  read only the `description` that the schema field gives. So a templated field's question used
  the field name, and `judge` did not see a change of the template's description. Both now read
  each description after the field takes its template. `--descriptions` still replaces it.
- The tests compare the spec version as numbers. As strings, `"0.10"` is less than `"0.6"`, so
  under spec 0.10 six tests of descriptions and recorded judgments were skipped. They run again
  and pass.
- It still needs `groundgate>=0.5`.

## 0.2.0 (2026-10-09)

- `sample` reads each field's `description` from the schema, for the field question and the
  label page ([#174](https://github.com/mohanraj00/groundgate/issues/174)). Each entry of
  `--descriptions` replaces one of them. `judge` refuses a schema that gives a field another
  description than the field calibration had.
- A built-in `chat` judge for servers that accept chat requests, such as a local model server
  ([#124](https://github.com/mohanraj00/groundgate/issues/124)). Its URL, model, version and
  optional key come from the environment. It sends the text only over https, or over http to
  this machine with no proxy, and it refuses redirects.
- [Measure a judge's thresholds](https://github.com/mohanraj00/groundgate/blob/main/docs/howto/calibrate.md#a-local-model-as-the-judge)
  has a section for a local model
  ([#175](https://github.com/mohanraj00/groundgate/issues/175)). On 79 candidates of the IRS
  filing-status set that spec 0.6 flags `KEY_NOT_AT_VALUE`, `qwen2.5:7b` clears 12 right keys
  and no wrong key in the calibration part. The upper bound on the escape rate is 0.2209, so the
  report gives no threshold at the 0.05, 0.1 or 0.2 ceiling. In the test part, it clears 6
  right keys and no wrong key.
- It needs `groundgate>=0.5`. Schemas of spec 0.6 have field descriptions, and `--descriptions`
  stays for schemas of spec 0.5. A work directory of spec 0.4 needs calibrate 0.1.0.

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
