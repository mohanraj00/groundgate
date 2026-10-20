# Codex judge

This judge asks a Codex model about the fields that the 0.11 runner sends to review (#67). For
each field with at least one candidate, it asks one choice: which candidate does the document
state as the field, or none. The plan is on #67. This folder has the code only. The development
answers come in a later PR, after `bench/requested4` has its development labels.

```bash
uv run python bench/judges/codex/judge.py prompt --items ITEMS.json --id ID
uv run python bench/judges/codex/judge.py run --items ITEMS.json --model MODEL \
    --max-calls 1700 --cache DIR --out answers.json [--effort low] [--run 2]
```

## Items

`ITEMS.json` has the format `codex-judge-items/1`. Each item is one review field: its id, its
split (`development` or `heldout`), the document kind, the field name and description, the text,
and the candidates. A candidate has a value, a scale, a unit and its spans, in code points of the
text. `code_point_span` changes a UTF-8 byte span, such as the evidence of a decision, into code
points.

## Question

The options are the candidates, one for each different (value, scale, unit), and "none". Each
option shows each cited span with 400 code points of text before it and 150 after it. The
document text goes into the prompt as JSON strings, and the instructions tell the model to treat
it as data. The model returns `{"choice", "confidence"}`. A reply in any other form is refused.

## Calls

The judge runs the model only through the installed Codex CLI and its logged-in account:

- `codex exec` in an empty directory, with the `read-only` sandbox;
- the user config, the rules and AGENTS.md are not loaded, and no session is saved;
- the prompt goes on stdin;
- never with a flag that bypasses approvals or the sandbox.

If a reply used a tool, or is not a valid answer, the judge asks again, at most 3 times for each
item. `--max-calls` caps the calls of a run, failed calls included. The plan allows at most 1,700
development calls. `run` refuses a held-out item unless it gets `--allow-heldout`, because the
held-out run needs the maintainer's approval after the freeze.

## Records

The cache keeps one file for each answered prompt. Its key binds the template, the model, the
effort, the run number and the prompt, so a second pass with the same inputs makes no call. A
cache file that differs from its digest is refused. `--run 2` asks again, for the repeat run.

The answers file (`codex-judge-answers/1`) has, for each item, the option, the candidate it
names, the confidence and the prompt digest. Its `meta` has the model, the effort, the Codex CLI
version, the template digest and the digest of all prompts. The freeze records the model, the
prompt digest and the threshold.

No model runs inside a groundgate decision. An answer can enter a decision only as a recorded
input.
