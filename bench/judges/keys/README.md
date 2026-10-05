# Clearing key flags with a typed-decision model

Spec 0.3 sends a right key to review when its sentence or table line does not name it (#52,
#87). This experiment asks whether a typed-decision model can clear those `KEY_NOT_AT_VALUE`
flags without letting a wrong key through (#67). The core never calls a model: a model answer
would be a recorded input that a later spec may read, as the hybrid design describes.

```bash
uv run python bench/judges/keys/judge.py split       # split.json, before any model run
TYPESAFE_API_KEY=... uv run python bench/judges/keys/judge.py run jev
JEFF_MODEL="..." uv run python bench/judges/keys/judge.py run jeff   # a local jeff-serve
uv run python bench/judges/keys/judge.py report      # REPORT.md, report.json
```

## Gold and split

The labeled doses of the keys set and the tables set, with the label's keys and the keys that spec
0.3 puts at each dose, from those sets' files. Doses labeled `?` are left out. The split is by
label, on the first hex digit of sha256(label id), so one label's text is never on both sides. It
was committed before any model answered.

## Question

One choice for each dose, written once before the first run: which of the drug's conditions does
the marked dose belong to? The options are the label's keys and "none". The state is the text the
label tool showed, with the dose in brackets.

## Scoring

A model clears a flag when spec 0.3 does not put key K at the dose, the model chooses K, and its
confidence is at least t. The clear is right when K is a labeled key, and an escape when it is not.
The threshold is the lowest of 0.5, 0.7, 0.8, 0.9, 0.95 and 0.99 with no escape on the
calibration part. [REPORT.md](REPORT.md) gives the test part at that threshold, with a 95% upper
bound on the escape rate among cleared flags. CI runs `report --check` on the committed answers.

## Notes

- Jeff Gemma4 E2B answered 31 of the 32 probe sentences of `bench/judges` right, but it does much
  worse here, and it is often confident when it is wrong. The probe sentences are short and clean,
  and these doses are in long text with up to 15 options. A probe is not a measure.
- Jev does not answer twice the same way (#71), so a second run can differ.
- One label changed after a model run. Jev's only escape on the test part was
  `fda-lansoprazole:801`, and the labeler read the text again and changed the label (see the keys
  set README). With the first label, Jev cleared 47 right flags and 1 wrong one at 0.5.
