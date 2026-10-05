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
A user sets a ceiling on the escape rate among cleared flags. For each ceiling, the threshold
is the lowest of 0.5, 0.7, 0.8, 0.9, 0.95 and 0.99 whose 95% upper bound on the calibration part
is below it, as in `docs/design/hybrid-decisions.md` §9, or none. [REPORT.md](REPORT.md) gives the
test part at that threshold for ceilings of 0.05, 0.1 and 0.2. CI runs `report --check` on the
committed answers.

The plan on #67 first said "the lowest threshold with no escape on the calibration part". A
review of #100 showed that this differs from §9 and is weaker: one cleared flag with no escape
passes it. The rule changed to §9 after the first report. It changes how a threshold is chosen,
not the answers, the gold or the split.

## Notes

- Jeff Gemma4 E2B did well on the probe sentences of `bench/judges` (#67), but it does much worse
  here, and it is often confident when it is wrong. The probe sentences are short and clean, and
  these doses are in long text with up to 15 options. A probe is not a measure.
- Jev does not answer twice the same way (#71), so a second run can differ.
- One label changed after a model run. Jev's only escape on the test part was
  `fda-lansoprazole:801`, and the labeler read the text again and changed the label (see the keys
  set README). A label that changed because of a model answer can't score that model, so this dose
  is left out of the gold (`RELABELED_AFTER_A_RUN` in `judge.py`).
- A stopped run goes on from a partial file, but only with the same engine, model and prompts
  (a digest of every state and question), so one answers file never mixes two runs. Each answers
  file keeps that digest, and the report refuses a file whose prompts are not the gold's. I added
  the digest to the two files after the runs. No text, span, key or question changed since then.
