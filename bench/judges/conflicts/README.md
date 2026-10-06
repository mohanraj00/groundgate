# Choosing among conflicting values with a typed-decision model

Spec 0.3 flags `CONFLICTING_CANDIDATES` when two candidates for one single-value field pass every
check with different values. Both go to review. This experiment asks whether a typed-decision
model can choose the right one, or say that none is right, without letting a wrong value
through (#67). The core never calls a model: a model answer would be a recorded input that a
later spec may read, as the hybrid design describes.

```bash
uv run python bench/judges/conflicts/judge.py split    # split.json, before any model run
TYPESAFE_API_KEY=... uv run python bench/judges/conflicts/judge.py run jev
uv run python bench/judges/conflicts/judge.py report   # REPORT.md, report.json
uv run python bench/judges/conflicts/judge.py report --check
```

The judge reuses the run, the split, the engine and the resume rules of the key judge
(`bench/judges/keys`). [REPORT.md](REPORT.md) has every number.

## Gold and split

The gold is the conflicts set (`bench/conflicts`): FDA labels, each labeled by the maintainer
with the dose that the text states as each of three set-2 fields, or none. For each label and
field, spec 0.3 decides each dose alone as an extraction of the field: the number, in mg, with
evidence from the number to the end of its unit. A conflict is a field at which spec 0.3 admits
two values or more. Fields labeled `?` are left out. The split is by label, on the first hex digit
of sha256(label id), and it was committed before any model answered.

## Question

One choice for each conflict, written once before the first run: which dose does the text state
as this value? The value is the set-2 description of the field. The options are the values that
spec 0.3 admits, and none. The state is all of sections 2 and 3, because a conflict spans the
label.

## Scoring

A model clears a conflict when it chooses a value with confidence t or more: that value is
admitted, and the others are not. The clear is right when the value is the labeled one, and an
escape when it is not, which includes a field labeled none. An answer of none clears nothing.
An answer is right when it is the labeled value, or none when no admitted value is the labeled
one. For each ceiling on the escape rate among cleared conflicts, the threshold is the lowest of
0.5, 0.7, 0.8, 0.9, 0.95 and 0.99 whose 95% upper bound on the calibration part is below it, as
in `docs/design/hybrid-decisions.md` §9, or none. CI runs `report --check` on the committed
answers.

## Notes

- Jev only, one run. The key question showed that Jev does not answer twice the same way.
- FDA labels are the only document kind here.
