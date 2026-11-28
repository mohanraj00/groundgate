# groundgate review api

Release: main, before 1.0.0 (spec 0.13).

`groundgate review api` serves the review API `groundgate-review/1` of a store on `127.0.0.1`.
A program lists the open tasks, reads a task and its document, and sends an answer.

## Command

```text
groundgate review api --store DIR (--token-file FILE --reviewer NAME | --issuers FILE)
                      [--policy FILE] [--first-agree N] [--port N]
```

| Option | Default | Effect |
|---|---|---|
| `--store DIR` | required | The store folder. The folder must exist. |
| `--token-file FILE` | none | A file with a static token: 32 to 512 characters from `A-Z`, `a-z`, `0-9`, `-`, `.`, `_` and `~`. Use it with `--reviewer`. |
| `--reviewer NAME` | none | The reviewer name of the holder of the static token. |
| `--issuers FILE` | none | A JSON file of issuers with HMAC-SHA-256 secrets of 32 bytes or more. The `sub` of a signed claim is the reviewer. |
| `--policy FILE` | none | A `review-policy@1` JSON file for `agree` and `leads`. Without it, `agree` is 1 and there is no lead. |
| `--first-agree N` | none | Record the previous `agree` for a store that has answers and no record. `N` must equal `agree` of the policy. |
| `--port N` | 0 | The port, from 0 to 65535. With 0, the server takes a free port. |

Give `--issuers`, or `--token-file` with `--reviewer`. Each path starts with `/v1/`.

## Example

This example answers the one task of the quickstart packet. Run it in an interactive shell,
because `%1` needs job control.

```bash
PACKET=$(uv run groundgate admit --store store docs/quickstart/doc.txt docs/quickstart/schema.json docs/quickstart/candidates.json)
uv run groundgate review tasks --store store "$PACKET" > /dev/null
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > token.txt
uv run groundgate review api --store store --token-file token.txt --reviewer ana --port 8649 &
sleep 2
AUTH="Authorization: Bearer $(cat token.txt)"
curl -s -H "$AUTH" http://127.0.0.1:8649/v1/tasks; echo
TASK=$(curl -s -H "$AUTH" http://127.0.0.1:8649/v1/tasks | python3 -c "import json, sys; print(json.load(sys.stdin)['tasks'][0]['task'])")
curl -s -H "$AUTH" -H "Content-Type: application/json" -d "{\"task\": \"$TASK\", \"verdict\": \"confirm\"}" http://127.0.0.1:8649/v1/answers; echo
kill -INT %1; wait
```

```text
The review API groundgate-review/1 is on http://127.0.0.1:8649/v1/. Press Ctrl-C to stop.
{"api": "groundgate-review/1", "actor": "ana", "tasks": [{"task": "task:3dd22b4f2785a4bb236119c380b0cb51a6447a8a1b24505b4173c88ea8827992", "document": "", "mode": "review", "field": "phaseout_start", "key": null}], "next": null}
{"api": "groundgate-review/1", "actor": "ana", "task": "task:3dd22b4f2785a4bb236119c380b0cb51a6447a8a1b24505b4173c88ea8827992", "record": {"format": "answer@1", "reviewer": "ana", "verdict": "confirm", "candidate": null, "codes_kept": [], "statements": null, "nodes": null, "reason_seen": false, "keys": 0, "ms": 0, "time": "2026-11-28T11:51:50Z", "choice": null}}
```

The task ID is new for each server start. Then `groundgate review resolve --store store
"$PACKET" --reviewer ana` gives `phaseout_start: 79000 USD (confirmed)`.

## Result

The command prints the line with the base URL, then serves until Ctrl-C. Each answer goes
through the same check as an answer from the review page. A packet that the API cannot show
gets a `skipped: ...` line on stderr. A request with no `Authorization` header gets HTTP 401
and the error code `no_claim`.

The server records `agree` in `state/review-api` and holds `state/review-api.lock` while it
runs. Stop it with Ctrl-C: the server then removes the lock. A `kill` with another signal
leaves the lock, and the next start stops.

Exit codes: 0 stopped with Ctrl-C, 2 invalid input.

## Errors

| Exit | Message | Cause |
|---|---|---|
| 2 | `groundgate: give --issuers, or --token-file with --reviewer` | The options give no claim check, or two. |
| 2 | `groundgate: the static token must have 32 to 512 characters from A-Z, a-z, 0-9, '-', '.', '_' and '~'` | The token file has a bad token. |
| 2 | `groundgate: store/state/review-api.lock exists. Delete this file only when no review API server runs on this store.` | Another server runs on the store, or an earlier server did not stop with Ctrl-C. |
| 2 | `groundgate: the store has answers and no recorded agree. Use --first-agree N with the previous value.` | The store has an answer log from before the record of `agree`. |
| 2 | `groundgate: the store has an answer log. Recorded agree is 1. New agree is 2. Use a new store to increase agree.` | The policy increases `agree` on a store with answers. |
| 2 | `groundgate: the port must be from 0 to 65535` | `--port` is out of range. |

The HTTP errors of each operation are in [SPEC §4.20](../../SPEC.md).

## See also

- [Read tasks and send answers over HTTP](../howto/review-api.md) gives each operation, the
  blind audit and signed claims.
- [groundgate review serve](review-serve.md) gives the same tasks to a person.
