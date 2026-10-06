# Finding wrong fields in NTSB reports with a typed-decision model

The field question (`bench/judges/fields`) on a second document kind. Spec 0.3 admits a number as
a field when the number and its unit are in the text and no check flags it. In an NTSB report, it
can't tell total time from time in make and model, or airport elevation from runway length. This
experiment asks whether a typed-decision model can find the numbers that spec 0.3 admits as the
wrong field (#67).

```bash
uv run python bench/judges/aviation/judge.py split    # split.json, before any model run
TYPESAFE_API_KEY=... uv run python bench/judges/aviation/judge.py run jev
uv run python bench/judges/aviation/judge.py report   # REPORT.md, report.json
uv run python bench/judges/aviation/judge.py report --check
```

The judge is the field judge with the aviation set as its gold. It reuses the run, the split and
the resume rules of the key judge, and the scoring and the report of the field judge.
[REPORT.md](REPORT.md) has every number.

## Gold and split

The gold is the aviation set (`bench/aviation`): numbers in hours or feet in NTSB reports, each
labeled by the maintainer with the set-2 NTSB fields that the report states as that number. For
each number and each of the six fields, spec 0.3 decides one extraction alone: the number, in the
field's unit, with the number and its unit suffix as evidence, and the set-2 unit table. A pair
is a number and a field that spec 0.3 admits. It is right when the label holds the field. Numbers
labeled `?` are left out, and so are numbers where spec 0.3 admits no field. The split is by
report, on the first hex digit of sha256(report id), and it was committed before any model
answered.

## Question and scoring

The field judge's: one noul question for each admitted field of a number, all in one request.
The question names an NTSB report in place of a drug label. The state is 400 code points before
the number and 150 after, with the number in brackets, as on the FDA labels. A pair below the
threshold is doubted. For each ceiling on the share of right pairs doubted, the threshold is the
highest whose 95% upper bound on the calibration part is below it (hybrid design §9). CI runs
`report --check` on the committed answers.

## Notes

- 11 reports, so each part has few reports. One report with an odd layout moves the numbers.
- The state does not hold the PDF's table layout. The maintainer labeled with the PDF page in
  view; the model sees only the text.
- Jev only, one run.
