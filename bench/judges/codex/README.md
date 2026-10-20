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

`ITEMS.json` has the format `codex-judge-items/1`. Each item is one review field: its id, the
document id in the set's manifest, its split (`development` or `heldout`), the document kind, the field name and description, the text,
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
- web search is off (`web_search="disabled"`), and so are apps, browser use and computer use;
- the CLI gets only `PATH`, `HOME` and `CODEX_HOME` from the environment, and no other variable,
  such as a token;
- the prompt goes on stdin;
- never with a flag that bypasses approvals or the sandbox.

If a reply used a tool, or is not a valid answer, the judge asks again, at most 3 times for each
item. `--max-calls` caps the calls of a run, failed calls included. The plan allows at most 1,700
development calls.

## Held-out gate

The items file states a split, but `run` does not trust it. `run` reads the set's manifest
(`--manifest`, by default `bench/requested4/manifest.json`) and finds the document of each item
there. It refuses an item whose document is not in the manifest, or whose split is not the
manifest split. It refuses a held-out item unless it gets `--allow-heldout`, because the held-out
run needs the maintainer's approval after the freeze. If the manifest is not there, `run` refuses
every item, held-out or not. The answers file records the manifest digest.

## Records

The cache keeps one file for each answered prompt. Its key binds the template, the model, the
effort, the run number and the prompt, so a second pass with the same inputs makes no call. Each
entry also records the Codex CLI version that answered. `--run 2` asks again, for the repeat run.

The judge refuses a cache file that is not valid JSON, that differs from its digest, or whose
model, effort, run or template is not the one of the current call. The digest finds a corrupt or
changed file. It is not a secret, so it does not find a forged file: keep the cache folder
writable only by you.

The answers file (`codex-judge-answers/1`) has, for each item, the option, the candidate it
names, the confidence, the prompt digest and the Codex CLI version that answered. Its `meta` has
the model, the effort, all Codex CLI versions of the answers, the template digest, the digest of
all prompts and the manifest digest. The freeze records the model, the prompt digest and the
threshold.

## Limits

The document text can hold instructions to the model. The JSON framing and the strict reply format
limit the effect to a wrong choice, but a document can still move the choice. The numbers of this
judge hold for documents that do not attack the model.

No model runs inside a groundgate decision. An answer can enter a decision only as a recorded
input.
