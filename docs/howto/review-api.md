# Read tasks and send answers over HTTP

Release: main, before 1.0.0 (spec 0.13).

`groundgate review serve` gives a person a page for the review tasks of a store
([review.md](review.md), part 9). The review API gives the same tasks to a program. A script, a
job or your own page lists the open tasks, reads a task with its document, and sends an answer.
The answer goes through the same check as an answer from the page, and it gives the same record
in the store.

[SPEC §4.20](../../SPEC.md) defines the API: the operations, the errors and the claim check. The
API is `groundgate-review/1`, and each path starts with `/v1/`. The invoice text on this page is
made up.

[examples/review-page](../../examples/review-page/README.md) has a page on this API: one command
starts the API and the page for a made-up invoice.

## 1. Start the server with a static token

For a local run, make a token file and start the server. The token has 32 to 512 characters from
`A-Z`, `a-z`, `0-9`, `-`, `.`, `_` and `~`.

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))" > token.txt
chmod 600 token.txt
groundgate review tasks --store work/store sha256:3e0c27fa...
groundgate review api --store work/store --token-file token.txt --reviewer ana --port 8649
```

The command prints `The review API groundgate-review/1 is on http://127.0.0.1:8649/v1/. Press
Ctrl-C to stop.` Each request sends the token in one header:

```bash
curl -H "Authorization: Bearer $(cat token.txt)" http://127.0.0.1:8649/v1/tasks
```

The server binds to `127.0.0.1` only. It is for one local user: each holder of the token answers
as the reviewer `ana`. Keep the token out of the store folder and out of your shell history.

At start, the server checks `agree` in the policy against the recorded value in the store.
You can keep or lower the recorded value. You can increase it only if the store has no answer
log. This check includes empty answer logs. If the store has no record and no answer log, the
server uses the policy value. When the check passes, the server records the value in a
`review-api-state@1` object and saves the object key in `state/review-api`.

If the store has an answer log and no record of `agree`, set `agree` in the policy to the
value the store used before. Use `--first-agree N` with that same value for N. In Python,
use `api.server(service, first_agree=N)`. Use the option only for the start that makes
the first record. The review page example also accepts `--first-agree N` and uses a policy
with `agree` set to 1.

The server uses `state/review-api.lock` to permit one review API server per store.
The server removes the file only when it stops on Ctrl-C (SIGINT). If a crash or a SIGTERM
leaves this file in the store, the next start stops with an error. Delete this file only when no
review API server runs on this store.

## 2. List the tasks, read one, and answer it

This example makes a store with one invoice, starts the server in the same process, and calls it
with `urllib`. The server is the one that `groundgate review api` starts. The invoice gives a
review task and a blind audit task. Each field goes in its own packet, because an actor who gets
a blind task of a packet gets no other task of that packet (section 3).

```python
import json
import tempfile
import threading
import urllib.request
from pathlib import Path

from groundgate.review import api
from groundgate.review.tasks import write_tasks
from groundgate.store import FolderStore
from groundgate.store.packets import admit_packet

text = "Invoice 0007\nTotal due: 4,200 thousand USD\nTax: 310 thousand USD\n"
schema = {
    "fields": {
        "total": {"type": "number", "description": "The total of the invoice."},
        "tax": {"type": "number"},
    }
}


def span(words):
    start = text.encode("utf-8").index(words.encode("utf-8"))
    return {"start": start, "end": start + len(words.encode("utf-8"))}


candidates = [
    {
        "id": "c1",
        "field": "total",
        "value": "4200000",
        "evidence": {**span("4,200 thousand"), "text": "4,200 thousand"},
    },
    {
        "id": "c2",
        "field": "total",
        "value": "4200",
        "evidence": {**span("4,200 thousand"), "text": "4,200 thousand"},
    },
    {
        "id": "c3",
        "field": "tax",
        "value": "310000",
        "evidence": {**span("310 thousand"), "text": "310 thousand"},
    },
]
policy = {
    "format": "review-policy@1",
    "audit": {"rate": "1", "seed": "s"},
    "agree": 1,
    "leads": [],
    "rejected": False,
}
root = Path(tempfile.mkdtemp()) / "store"
with FolderStore(root) as store:
    for field in ("total", "tax"):
        one = {"fields": {field: schema["fields"][field]}}
        given = [c for c in candidates if c["field"] == field]
        packet, _ = admit_packet(store, text, one, given, None, "inv-0007")
        write_tasks(store, packet, policy)

token = "a-local-token-of-32-characters-or-more"
service = api.Service(root, api.read_token(token, "ana"))
httpd = api.server(service)  # port 0: a free port
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{httpd.server_port}"


def call(path, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(base + path, data, {"Authorization": f"Bearer {token}"})
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


listed = call("/v1/tasks")
print(listed["api"], listed["actor"], listed["next"])
for t in listed["tasks"]:
    print(t["document"], t["mode"], t["field"])
```

```text
groundgate-review/1 ana None
inv-0007 audit tax
inv-0007 review total
```

The list gives the open tasks of the actor. With `?limit=1`, a page has one task, and `next` is
the cursor of the next page. Send it back as it is, in `?cursor=`.

The `task` of each task is a task ID: `task:` and 64 hex digits. It is not the task key of the
store. Use it as it is, in a path and in an answer. A task ID is good only while the server
runs, so read the list again after a new start. No response gives a key of the store: section 6
says why.

The `total` task is a review task. Its `body` is the `task@1` object without its packet key,
with the question, the choices and the evidence of each choice. Each choice has `choice`, its
number in the task from 1. The body has no index of the receipt.

The document comes from a second call. Each span is in UTF-8 bytes of that text, when the
`source` of the choice is `document`. If the `source` is `reference`, the span is in the text of
the reference that `ref` names, and version 1 does not give that text. Then show no passage.

```python
total = next(t["task"] for t in listed["tasks"] if t["field"] == "total")
task = call(f"/v1/tasks/{total}")
print(task["definition"])
print(task["body"]["question"])
document = call(f"/v1/tasks/{total}/document")["text"].encode("utf-8")
for choice in task["body"]["choices"]:
    e = choice["evidence"]
    passage = document[e["start"] : e["end"]].decode("utf-8")
    print(choice["choice"], choice["shown"], "|", choice["source"], "|", passage)
```

```text
The total of the invoice.
Which amount is total?
1 4,200 with no unit (written 4,200, not scaled, positive) | document | 4,200 thousand
2 4,200,000 with no unit (written 4,200, in thousands, positive) | document | 4,200 thousand
```

For a model text task, the response also has `statements`: the text of each statement and the
spans of the document that it cites. An answer to it has the verdict `confirm` and one
`{"statement", "verdict"}` for each statement. A model text task is a review task of its packet
for the groups of section 3: a statement can state the value that a blind task hides.

An answer names its task and its verdict. `choose` gives the number of the right choice: here
choice 2, because the invoice gives the total in thousands. The response has the record that
the store now has, without its task key, and with `choice` in place of its `decision`. The
reviewer is the actor of the claim: a body cannot name another reviewer.

```python
written = call("/v1/answers", {"task": total, "verdict": "choose", "choice": 2})
record = written["record"]
print(record["format"], record["reviewer"], record["verdict"], record["choice"])
print([t["field"] for t in call("/v1/tasks")["tasks"]])
```

```text
answer@1 ana choose 2
['tax']
```

The answer settles the slot, so the task leaves the list. `groundgate review resolve` reads this
answer as it reads an answer from the page.

## 3. Answer a blind audit task

The `tax` task has the mode `audit`: the gate admitted the value, and the audit checks it. Such
a task is blind. The API gives the document, the field and the key, and never the proposed value.
Its `body` is null. No response gives its value, its evidence, its question or the outcome of the
gate.

An actor gets one group of the tasks of each packet. Each blind task of a packet is a group, and
the other tasks of the packet are the review group. The first answer of the actor to the packet
fixes its group. With no answer, the actor gets the first blind task that has fewer than `agree`
answers from other actors, and then the review group. A task outside the group gives the error
`not_assigned` (403), and the list does not show it. So the answer to a blind task does not
depend on a value that the actor saw in another task of the packet.

A blind task takes three verdicts: `correct`, `not_in_document` and `unsure`. For `correct`, send
the span of the value that you found in the document. The service reads the value from the span,
and the gate checks it again.

```python
tax = next(t["task"] for t in listed["tasks"] if t["field"] == "tax")
blind = call(f"/v1/tasks/{tax}")
print(blind["mode"], blind["field"], blind["body"])
written = call("/v1/answers", {"task": tax, "verdict": "correct", "span": span("310 thousand")})
print(written["record"])
```

```text
audit tax None
None
```

The response of a blind answer has no record, because the record of a correction can hold the
unit of the proposed value. The store has the record.

Version 1 has a limit here. The check of a correction reads the other candidates of the packet.
If the schema has a relation between two fields, the outcome of a correction can change with
the hidden value of the related field. SPEC §4.20 has an example.

## 4. Corrections and their errors

A correction is a span, as on the review page. The service reads a number from the span with its
scale word. To give the value yourself, add `value`. To cite a scale line or a sign, add `parts`.

The gate checks each correction. An error is a JSON object with a code:

```python
import urllib.error

try:
    call("/v1/answers", {"task": total, "verdict": "correct", "span": span("4,200")})
except urllib.error.HTTPError as refused:
    error = json.loads(refused.read())["error"]
    print(refused.code, error["code"], error["codes"])
```

```text
409 codes_not_kept ['SCALE_WORD']
```

The span `4,200` leaves out the word `thousand`, so the gate flags the value 4200 with
`SCALE_WORD`. Select `4,200 thousand`, or send the answer again with
`"codes_kept": ["SCALE_WORD"]` if 4200 is right.

| Code | Status | What to do |
|---|---|---|
| `no_claim`, `bad_claim`, `unknown_issuer`, `expired_claim` | 401 | Send a good claim. |
| `not_found` | 404 | Check the path and the task ID. Use the ID that the list gives. |
| `bad_request` | 400 | Check the query or the body against SPEC §4.20. |
| `bad_answer` | 400 | The answer breaks its task: read the task again. |
| `correction_rejected` | 409 | The gate rejects the value. Select another span. |
| `codes_not_kept` | 409 | Send the answer again with each code of `codes` in `codes_kept`, if the value is right. |
| `parts_disagree` | 409 | The value does not agree with the scale or the sign in the text. Send it again with `"parts_seen": true` to keep it. |
| `log_refused` | 409 | Another writer holds the answer log. Send the answer again later. |

SPEC §4.20 has the full list.

## 5. Use signed claims

A static token gives one reviewer name. For more than one reviewer, give the server a list of
issuers. Each request then carries a claim that an issuer signed, and the `sub` of the claim is
the reviewer of the answer.

```json
{"groundgate_review_issuers": 1,
 "issuers": [{"issuer": "https://id.example.test",
              "secret": "c2VjcmV0LW9mLTMyLWJ5dGVzLW9yLW1vcmUtMDEyMzQ1Njc4OQ"}]}
```

```bash
groundgate review api --store work/store --issuers issuers.json --port 8649
```

A secret is base64url with no `=`, of 32 bytes or more. A claim is a JWT with `HS256`. Its
payload has `iss`, the name of the issuer, `sub`, the reviewer, `aud`, the string
`groundgate-review`, and `exp`, the end of its life in seconds. The standard library can make
one:

```python
import base64
import hashlib
import hmac
import time


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def claim(secret, issuer, reviewer, seconds=300):
    payload = {
        "iss": issuer,
        "sub": reviewer,
        "aud": "groundgate-review",
        "exp": int(time.time()) + seconds,
    }
    signed = ".".join(
        b64(json.dumps(part).encode("utf-8")) for part in ({"alg": "HS256", "typ": "JWT"}, payload)
    )
    return signed + "." + b64(hmac.new(secret, signed.encode("ascii"), hashlib.sha256).digest())


secret = b"secret-of-32-bytes-or-more-0123456789"
issuers = api.read_issuers(
    {
        "groundgate_review_issuers": 1,
        "issuers": [{"issuer": "https://id.example.test", "secret": b64(secret)}],
    }
)
header = "Bearer " + claim(secret, "https://id.example.test", "ben")
print(api.check_claim([header], issuers, int(time.time())))
```

```text
ben
```

The server refuses a request with no claim, a claim past its `exp`, a claim of an issuer that it
does not have, and a claim with a wrong signature. It keeps no list of used claims, so give each
claim a short life.

Version 1 takes `HS256` only, because the standard library has it. The issuer and the server
share the secret, so each holder of the secret can sign as each reviewer. Keep the issuers file
out of the store folder, with mode 600.

## 6. What stays the same

- The server keeps no state outside the store. It reads the store again for each request, and it
  holds no log between two requests. So `review serve`, `review resolve` and the API work on one
  store. If two writers send an answer to one log at the same time, one of them gets
  `log_refused`.
- No response gives a key of the store. A store key is a hash of its object, and a packet holds
  the proposed value of each audit task. With a task key or a packet key, a person could test a
  guess of that value with no request. So a task has an opaque ID, a task body has no packet
  key, and the record of an answer has no task key. To get a key, read the store.
- Within version 1, a later release can add an operation, a response member, a request member
  that you can leave out, and an error code. It does not remove or rename one, and it does not
  change its meaning. Ignore a response member that you do not know.
- The server speaks HTTP on `127.0.0.1`. To give it to other hosts, put a proxy with TLS before
  it. The proxy must send the `Host` header `127.0.0.1:<port>`.

```python
httpd.shutdown()
httpd.server_close()
```
