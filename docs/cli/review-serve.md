# groundgate review serve

Release: main, before 1.0.0 (spec 0.13).

`groundgate review serve` serves the review page of a store on `127.0.0.1`. A person answers
each task in the browser, and the page writes each answer to the answer log of the reviewer.

## Command

```text
groundgate review serve --store DIR --reviewer NAME [--policy FILE] [--port N]
```

| Option | Default | Effect |
|---|---|---|
| `--store DIR` | required | The store folder. The folder must exist. |
| `--reviewer NAME` | required | The name of the reviewer. The name must be NFC text. |
| `--policy FILE` | none | A `review-policy@1` JSON file for `agree` and `leads`. Without it, `agree` is 1 and there is no lead. |
| `--port N` | 0 | The port, from 0 to 65535. With 0, the server takes a free port. |

The page shows each `task@1` object of the store whose packet matches its receipt. Write the
tasks first with [review tasks](review-tasks.md).

## Example

This example starts the server in the background, gets the page one time, and stops the
server. Run it in an interactive shell, because `%1` needs job control.

```bash
PACKET=$(uv run groundgate admit --store store docs/quickstart/doc.txt docs/quickstart/schema.json docs/quickstart/candidates.json)
uv run groundgate review tasks --store store "$PACKET" > /dev/null
uv run groundgate review serve --store store --reviewer ana --port 8648 &
sleep 2
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://127.0.0.1:8648/
kill -INT %1; wait
```

```text
Open http://127.0.0.1:8648/#MKV_jelYWcGbuf81Bi7hLfZnqdADI4z9wV_QiDIFo48 and press Ctrl-C here when you finish.
200 text/html; charset=utf-8
```

The token after `#` is new for each start. In normal use, open the start URL in a browser.

## Result

The command prints the start URL, then serves until Ctrl-C. Each request of the page must send
the token of the start URL. The server refuses a request with another `Host` header (HTTP 421).
A packet that the page cannot show gets a `skipped: ...` line on stderr.

The server is for one local user. Any holder of the URL can answer as the reviewer, so a lead
answer is not an authenticated act. Keep the URL private.

Exit codes: 0 stopped with Ctrl-C, 2 invalid input.

## Errors

| Exit | Message | Cause |
|---|---|---|
| 2 | `groundgate: --reviewer must be NFC text; normalize the name to NFC and try again` | The reviewer name is not NFC. |
| 2 | `groundgate: the port must be from 0 to 65535` | `--port` is out of range. |
| 2 | `groundgate: [Errno 48] Address already in use` | Another process has the port (an `OSError`; the number differs by system). |
| 2 | `groundgate: nostore: the store folder is not there` | The `--store` folder does not exist. |
| 2 | `groundgate: the review policy format must be review-policy@1` | The policy file is not valid. |

## See also

- [Review flagged facts](../howto/review.md#9-answer-the-tasks-on-the-review-page) gives the
  keys of the page and its checks.
- [The review note](../design/review.md), sections 8 and 9, gives the page and its security.
- [groundgate review api](review-api.md) gives the same tasks to a program.
