# Calibration report vectors

Each folder is one vector of `groundgate calibrate measure` (#640), report format 1. The files
do not depend on a programming language.

| File | Content |
|---|---|
| `profile.json` | The input profile (SPEC §4.10). |
| `gold/` | The gold set, format 1: `docs/`, `candidates/`, `judgments/` and `labels.json`. |
| `split.json` | The split file, format 1. |
| `args.json` | The `--target` and the `--date` of the run. |
| `expected-report.json` | The report that the command must write as `report.json`. |
| `expected-profile.json` | The draft profile change that the command must write as `profile.json`. |

An implementation passes a vector when both output files are equal to the expected files as
JSON data. [docs/calibrate.md](../../../docs/calibrate.md) defines the formats and each number.

I wrote the counts, the rates and the bounds of each expected report by hand, from the labels
and the decisions of the gate. `two-routes` has 4 calibration documents and 6 test documents. It
shows a threshold that fails, the threshold that the command picks, one measured route, an
admitted error on each route, one review and a label with no value.
