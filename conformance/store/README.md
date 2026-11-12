# Store contract vectors

`vectors.json` is the store contract (docs/design/store.md §6) as language-agnostic vectors. A
store backend in any language runs them to prove that it meets the contract. A Python backend
can run `groundgate.store.contract.CHECKS` instead: these checks run the same vectors.

The vectors are written by hand in `groundgate.store.contract.vectors`. `build.py` gives that
function its own SHA-256 and JCS functions from the standard library, so the keys and log heads
in the file do not come from the store code. After you edit a vector, run the script and commit
the JSON:

```bash
uv run python conformance/store/build.py
```

`tests/test_store_contract.py` fails if the committed JSON differs, and it runs the file on the
folder store and on an in-memory store.

## The file

```json
{"format": "groundgate-store-vectors@1", "vectors": [VECTOR, ...]}
```

Each vector is an object:

- `id`: a unique name, for example `put-refuses/schema-a-space`;
- `check`: the Python check in `CHECKS` that runs it;
- `about`: one sentence on the rule;
- `steps`: a list of operations.

Each step has `op`, its inputs, and `result` or `error`, never both:

| `op` | Inputs | `result` |
|---|---|---|
| `put` | `kind`, `data` | the key, a string |
| `get` | `kind`, `key` | the data |
| `append` | `log`, `record` | the head (`entry_sha256` of the new record), a string |
| `read` | `log` | the list of records, in order |
| `forget` | `key`, `reason` | `null` |

- `data`, and the `result` of `get`, is `{"utf8": "..."}` or `{"hex": "..."}`. Bytes that are
  not valid UTF-8 use `hex`. Give the backend the bytes, not the JSON string.
- `log` is a JSON array, for example `["answers", "sha256:...", "sha256:..."]`. A step that tests
  a bad log can have any JSON value, for example the string `"answers"` or a nested array.
- `kind`, `key` and `reason` are strings. A bad kind or key is still a string.
- `record` is a JSON value. A bad record can be an array.
- `error` names one of three error classes:
  - `invalid`: bad input (Python `ValueError`);
  - `not-found`: an absent object (Python `NotFound`);
  - `store-error`: any store error (Python `StoreError`). `not-found` is a kind of
    `store-error`, so a `not-found` error also passes a step that wants `store-error`.
- In a `read` result, the value `{"$": "string"}` matches any string. No record body of a vector
  uses the member `$`. Only the `time` and `entry_sha256` of a deletion record use it, because
  the time changes.
- A `result` comparison is exact: an object has the same members, an array has the same items
  in the same order, and a number is an integer of the same value.

## The runner

Write a runner in the language of the backend. Do these steps:

1. Read `vectors.json`. Stop if `format` is not `groundgate-store-vectors@1`.
2. For each vector, make a new, empty store.
3. Run each step in order on that store. Decode `data` to bytes before the call.
4. If the step has `result`, the call must succeed and give that result.
5. If the step has `error`, the call must fail with an error of that class.
6. If a step fails, stop that vector, record the step number (1 is the first step) and go to the
   next vector. A failure to make the new store is step 0.

Map each error of the backend to one of the three classes. An error that maps to no class fails
the step.

The vectors test only the five operations. Locks, torn logs, `run_keys` and the folder layout
are rules of the folder store, not of the contract.

## The report

The runner writes one JSON object, and exits 0 only if each vector passes:

```json
{
  "format": "store-report@1",
  "vectors_sha256": "<the SHA-256 hex digest of the bytes of vectors.json>",
  "backend": "<free text, for example the name and version of the backend>",
  "passed": 43,
  "failed": 0,
  "results": [
    {"id": "put-get/three-kinds", "passed": true},
    {"id": "chain/two-reviewers", "passed": false, "step": 2, "detail": "..."}
  ]
}
```

`results` has one item for each vector, in file order. `detail` is free text. In Python,
`groundgate.store.contract.report(make, backend)` gives this object.
