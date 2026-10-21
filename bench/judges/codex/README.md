# Codex judge

This judge asks a Codex model about the fields that the 0.11 runner sends to review (#67). For
each field with at least one candidate, it asks one choice: which candidate does the document
state as the field, or none. The plan is on #67. The development answers and their scores are in
[bench/requested4/judge](../../requested4/judge/RESULTS.md).

```bash
uv run python bench/judges/codex/judge.py prompt --items ITEMS.json --id ID
uv run python bench/judges/codex/judge.py run --items ITEMS.json --model MODEL \
    --max-calls 1700 --cache DIR --out answers.json [--effort low] [--run 2]
```

## Items

`ITEMS.json` has the format `codex-judge-items/1`. Each item is one review field: its id, the
document id in the set's manifest, its split (`development` or `heldout`), the document kind,
the field name and description, the text, and the candidates. The text is the whole reader text
of the document, byte for byte the file that the manifest pins with `text_sha256`. A candidate
has a value, a scale, a unit and its spans, in code points of the text. `code_point_span`
changes a UTF-8 byte span, such as the evidence of a decision, into code points.

`items.py` makes the items of one split of `bench/requested4`:

```bash
uv run python bench/judges/codex/items.py --run bench/requested4/loop/04/runs/runner.json \
    --results CACHE/runs/loop04/BINDING/runner/development --texts CACHE/run_sources \
    --out CACHE/judge/items-development.json
```

An item is one field of the `runner` arm with no admitted value and at least one
`needs_verification` decision. Each review decision is a candidate. Its value already holds the
printed scale, so the candidate has no scale. Its spans are the evidence span and the cited parts
of the decision receipt. The committed run file selects the items, and the decisions of the run
cache must be the same. The reader text must have the manifest `text_sha256`. An items file holds
whole reader texts, so it stays in the ignored `bench/requested4/.cache/judge/`. `items.py`
refuses a held-out run file unless it gets `--allow-heldout`.

## Question

The options are the candidates, one for each different (value, scale, unit), and "none". Each
option shows each cited span with 400 code points of text before it and 150 after it. The
document text, the document kind and the field go into the prompt as JSON strings, and the
instructions tell the model to treat them as data. No item value goes into the instructions.
The model returns `{"choice", "confidence"}`. A reply in any other form is refused.

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

## Scores

`score.py` scores answer files against the sealed labels and writes `results.json` and
`RESULTS.md`:

```bash
uv run python bench/judges/codex/score.py \
    --answers bench/requested4/judge/answers/*.json --out bench/requested4/judge [--check]
```

It selects the items again from the committed run file, so it needs no cache. It takes from the
label file only the documents of the run file's split. A clear is a candidate choice at
confidence t or more, for t of 0.5, 0.7, 0.8, 0.9, 0.95 and 0.99. The clear is right when the
label holds the chosen value and unit by the match rule of `bench/requested/metrics.py`, and an
escape when it does not. An unclear slot is left out. For each ceiling of 0.05, 0.1 and 0.2, the
threshold is the lowest t whose one-sided 95% upper bound on escapes among clears is below the
ceiling (hybrid design §9), with one threshold for all kinds. "Miss rate with the clears" takes
the cleared right values from the runner misses of the loop results. A test checks that the
committed `results.json` and `RESULTS.md` come from the committed answers.

The freeze (`bench/requested4/judge/freeze.json`) names the model, the effort, the prompt
template, the ceiling, the threshold and `code_sha256`, the digest of `items.py`, `judge.py`
and `score.py`. `score.py --freeze` scores the held-out split at the frozen threshold only. It
refuses answers of another model, effort or template, and judge code that changed after the
freeze.

Only the frozen threshold is a held-out result. The held-out `RESULTS.md` also shows the other
thresholds and the calibration bins, but no threshold may be chosen from them. A test checks the
held-out results with `--freeze`, so any later change to `items.py`, `judge.py` or `score.py`
fails it. A change to the judge code needs a new freeze and a new held-out run, approved by the
maintainer. If the judge code must change for another reason, the test can drop the held-out
check, and the freeze commit stays the record of the code that scored the answers.

## Held-out gate

The items file states a split, but `run` does not trust it. `run` reads the set's manifest
(`--manifest`, by default `bench/requested4/manifest.json`) and finds the document of each item
there. It refuses an item when:

- its document is not in the manifest;
- the sha256 of its text is not the manifest `text_sha256` of that document, or the manifest
  has no `text_sha256` for it;
- its split is not the manifest split.

So held-out text cannot pass under the id of a development document. `run` also refuses a
held-out item unless it gets `--allow-heldout`, because the held-out run needs the maintainer's
approval after the freeze. If the manifest is not there, `run` refuses every item, held-out or
not. The answers file records the manifest digest.

The gate trusts the manifest file. `--manifest` can name any file, and the judge does not check
it against git. Use the committed `bench/requested4/manifest.json`, and check `manifest_sha256`
in the answers file against it.

## Records

The cache keeps one file for each answered prompt. Its key binds the template, the model, the
effort, the run number and the prompt, so a second pass with the same inputs makes no call. Each
entry also records the Codex CLI version that answered. `--run 2` asks again, for the repeat run.

The judge refuses a cache folder or a cache file that is a link, and a cache file that is not
valid JSON, that differs from its digest, or whose model, effort, run or template is not the one
of the current call. The digest finds a corrupt or changed file. It is not a secret, so it does
not find a forged file: keep the cache folder writable only by you.

The answers file (`codex-judge-answers/1`) has, for each item, the option, the candidate it
names, the confidence, the prompt digest and the Codex CLI version that answered. Its `meta` has
the model, the effort, all Codex CLI versions of the answers, the template digest, the digest of
all prompts and the manifest digest. The freeze records the model, the prompt digest and the
threshold.

## Limits

If a call fails, the judge keeps only the exit code and the first line of stderr or of the turn
error, cut to 120 characters. The rest of stderr can hold local paths or account details.

The document text can hold instructions to the model. The JSON framing and the strict reply format
limit the effect to a wrong choice, but a document can still move the choice. The numbers of this
judge hold for documents that do not attack the model.

A tool call runs before the judge sees it and discards the reply. I checked the read-only
sandbox of Codex CLI 0.162.1 on macOS with `codex sandbox -c sandbox_mode="read-only"`, which
runs a command under the same sandbox with no model call:

- an outbound TCP connection (`nc` to 1.1.1.1:443) and a DNS lookup fail;
- a write to the working folder fails;
- a read of `~/.codex/auth.json` succeeds.

So a tool can read local files, including the Codex login. The tool output goes back to the
model, so what a tool reads reaches the model provider. The sandbox stops every other network
path, and the judge keeps only an option name and a number from the reply. Check this again when
the CLI version changes. Web search runs on the model side, not in the sandbox, so the judge sets it
off.

No model runs inside a groundgate decision. An answer can enter a decision only as a recorded
input.
