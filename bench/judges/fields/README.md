# Finding wrong fields with a typed-decision model

Spec 0.3 admits a dose as a field when the number and its unit are in the text and no check
flags it. It can't tell if the text states that dose as the field: a starting dose, a maximum
daily dose and a tablet strength all look the same to it. This experiment asks whether a
typed-decision model can find the doses that spec 0.3 admits as the wrong field, without doubting
too many right ones (#67). The core never calls a model: a model answer would be a recorded
input that a later spec may read, as the hybrid design describes.

```bash
uv run python bench/judges/fields/judge.py split    # split.json, before any model run
TYPESAFE_API_KEY=... uv run python bench/judges/fields/judge.py run jev
uv run python bench/judges/fields/judge.py report   # REPORT.md, report.json
uv run python bench/judges/fields/judge.py report --check
```

The judge reuses the run, the split, the engine and the resume rules of the key judge
(`bench/judges/keys`). [REPORT.md](REPORT.md) has every number.

## Gold and split

The gold is the fields set (`bench/fields`): doses in FDA dosage text, each labeled by the
maintainer with the set-2 fields that the text states as that dose. For each dose and each of
the four fields, spec 0.3 decides one extraction alone: the number, in mg, with the number and
its unit as evidence. A pair is a dose and a field that spec 0.3 admits. It is right when the
label holds the field, and wrong when it does not. Doses labeled `?` are left out, and so are
doses where spec 0.3 admits no field. The split is by label, on the first hex digit of
sha256(label id), and it was committed before any model answered.

## Question

One noul question for each admitted field of a dose, all in one request, written once before the
first run: does the text state that dose as this value? The value is the set-2 description of
the field. The state is 400 code points before the dose and 150 after, with the dose in
brackets, as in the other judges. A noul answer is the probability that the answer is yes.

## Scoring

The model doubts a pair when the probability is below a threshold t: 0.01, 0.05, 0.1, 0.2, 0.3
or 0.5. A doubted wrong pair is caught, and goes to review. A doubted right pair costs a review.
A user sets a ceiling on the share of right pairs doubted. For each ceiling, the threshold is the
highest whose 95% upper bound on the calibration part is below it, as in
`docs/design/hybrid-decisions.md` §9, or none. [REPORT.md](REPORT.md) gives the test part at that
threshold for ceilings of 0.05, 0.1 and 0.2, and the share of right pairs in bins of probability.
CI runs `report --check` on the committed answers.

## Notes

- Jev's probabilities are seldom near 0 or 1 here, so the two lowest thresholds catch nothing
  (the bins in [REPORT.md](REPORT.md)). The thresholds were fixed before the run and are not changed after it.
- Jev only. Jeff did much worse than Jev on the key question, so it is not run here.
- FDA labels are the only document kind here.
