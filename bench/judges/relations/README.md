# Clearing qualifier flags with a typed-decision model

Spec 0.3 flags a value `QUALIFIED_VALUE` when a qualifier near it (SPEC §4.2) has a comparator
that is not the field's. This experiment asks whether a typed-decision model can clear those
flags without letting a wrong relation through (#67). The core never calls a model: a model
answer would be a recorded input that a later spec may read, as the hybrid design describes.

```bash
uv run python bench/judges/relations/judge.py split    # split.json, before any model run
TYPESAFE_API_KEY=... uv run python bench/judges/relations/judge.py run jev
JEFF_MODEL="..." uv run python bench/judges/relations/judge.py run jeff
uv run python bench/judges/relations/judge.py report   # REPORT.md, report.json
uv run python bench/judges/relations/judge.py report --check
```

The judge reuses the run, the split, the engines and the resume rules of the key judge
(`bench/judges/keys`). [REPORT.md](REPORT.md) has every number.

## The plan

The plan is on #67, fixed before anyone read the gold. The gold is the relations set
(`bench/relations`): values in FDA dosage text for which spec 0.3 finds a qualifier, each
labeled by the maintainer with the relation that the text states. The split is by label, on the
first hex digit of sha256(label id).

The question is a choice among seven relations, on 400 code points before the value and 150
after, with the value in brackets. For a field with comparator c, spec 0.3 flags a value when its
qualifiers hold a comparator other than c. A model clears the flag when it answers c with
confidence t or more. The clear is right when the label is c, and an escape when it is not. A
threshold is chosen as hybrid design §9 says, at three ceilings.

The plan first measured only `eq`. The labels hold almost no `eq` value, so the report gives
every comparator. This addition was made after the labels and before any model answered, and it
is on #67.

## Notes

- Spec 0.3 already holds the labeled relation for most values, so there are few right flags to
  clear, and no comparator gets a threshold. The report gives the accuracy of each model too,
  because a question that a model answers well can still have nothing to clear.
- A review of #103 questioned three labels after the first model runs. The maintainer read the
  text again, without any model answer, and changed them. One of them made a value a fact, so it
  joined the gold. The first runs were for the old gold, so I ran both models again on the
  corrected gold, and the answers here are from those runs. No model answer led to a label
  change.
- FDA labels are the only document kind here.
