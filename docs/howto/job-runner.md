# Run groundgate under a job runner

A job runner starts a process, gives it limits and removes it when it ends. A container, a batch
queue and a cluster job are job runners. This page runs an extraction as such a job, and it keeps
a receipt that verifies after the job ends.

Four rules make this work:

1. Put the inputs and the store on storage that outlives the job.
2. Save the run in the store before the job ends, and write the packet key to that storage.
3. Verify from the store, in a different process.
4. Keep the run identity, the trace and the spend record of the job runner outside the store.

[`examples/job-runner`](../../examples/job-runner/README.md) holds the job of this page as files.

## 1. Write the job

The job reads a document and a schema from an input folder. `extract` calls the model through
one function, the client, and it records each prompt and each reply. `RunResult.save` writes the
inputs, the prompts, the replies, the receipt and a packet into the store. The packet key is the
one value that the next step needs, so the job writes it to `packet.txt` beside the store.

The client of this page gives recorded replies in call order. It calls no model, so the page
runs with no key and no network. Replace it with your model call
([Run extraction and evidence repairs](feedback.md) shows the client contract).

```python
import json
import tempfile
from pathlib import Path

from groundgate.extract import RunResult, extract
from groundgate.store import FolderStore

document = (
    "INVOICE\n"
    "Invoice number: 2041\n"
    "Bill to: Lakeside Workshop\n"
    "\n"
    "Subtotal: $276.00\n"
    "Sales tax (5%): $13.80\n"
    "Total due: $289.80\n"
)
schema = {
    "fields": {
        "total_due": {"type": "number", "unit": "USD", "required": True},
        "sales_tax": {"type": "number", "unit": "USD"},
    }
}


def quote(words):
    return [{"source": "document", "role": "value", "text": words}]


recorded_replies = [
    json.dumps(
        {
            "candidates": [
                {
                    "field": "total_due",
                    "value": "289.80",
                    "unit": "USD",
                    "key": None,
                    "evidence": quote("$289.80"),
                },
                {
                    "field": "sales_tax",
                    "value": "13.80",
                    "unit": "USD",
                    "key": None,
                    "evidence": quote("$13.80"),
                },
            ],
            "not_found": [],
        }
    )
]


def recorded(replies):
    """A client that gives the recorded replies in call order."""
    left = iter(replies)
    return lambda prompt: next(left)


def job(inputs, store_folder, client):
    """Run the extraction, save the run, and return the packet key."""
    text = (inputs / "document.txt").read_text(encoding="utf-8")
    fields = json.loads((inputs / "schema.json").read_text(encoding="utf-8"))
    result = extract(text, fields, client=client, model_id="recorded-1", document_id="invoice-2041")
    if not result.complete:
        raise RuntimeError("the run is not complete")
    with FolderStore(store_folder) as store:
        packet = result.save(store)
    (store_folder.parent / "packet.txt").write_text(packet + "\n", encoding="utf-8")
    return packet


def storage_with_inputs():
    """A new folder that stands for the storage, with the inputs in it."""
    folder = Path(tempfile.mkdtemp())
    (folder / "input").mkdir()
    (folder / "input" / "document.txt").write_text(document, encoding="utf-8")
    (folder / "input" / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
    return folder


storage = storage_with_inputs()
packet = job(storage / "input", storage / "store", recorded(recorded_replies))
print(sorted(path.name for path in storage.iterdir()))
print((storage / "packet.txt").read_text(encoding="utf-8") == packet + "\n")
```

```text
['input', 'packet.txt', 'store']
True
```

The job stops if the run is not complete. A client failure or a call limit gives a run that is
not complete, and its receipt does not cover each field. A job runner reads the exit code, so
the job must fail then.

## 2. Verify after the job ends

The job process is gone. The storage holds the store and `packet.txt`, and they are sufficient.
`groundgate verify --store` gets each input from the store, decides each candidate again and
compares the result with the stored receipt:

```bash
groundgate verify --store store "$(cat packet.txt)"
```

The same check in Python, with the exit code:

```python
from groundgate.cli import main

packet = (storage / "packet.txt").read_text(encoding="utf-8").strip()
print(main(["verify", "--store", str(storage / "store"), packet]))
```

```text
receipt verified
0
```

`RunResult.load` does more. It builds each prompt again, gives the recorded replies in place of
the model, and compares each line of the run record. It makes no model call:

```python
with FolderStore(storage / "store") as store:
    replayed = RunResult.load(store, packet)
for decision in sorted(replayed.receipt.decisions, key=lambda d: d.field):
    print(decision.field, decision.value, decision.unit, decision.outcome)
```

```text
sales_tax 13.8 USD admitted
total_due 289.8 USD admitted
```

Verify with the groundgate release that made the receipt. `verify` accepts only the spec version
that it implements, and `RunResult.load` accepts only the record version of its runner. So pin
the same release in the image of the job and in the environment that verifies.

## 3. Keep the run identity, the trace and the spend record outside the store

A job runner gives each run an identity. Many job runners also keep a trace and a spend record.
These records are useful, but they are not inputs of the decision. `admit` is a function of the
document, the schema, the policy and the candidates. `job` has no parameter for a run identity,
and the store has no object for a trace.

Thus two runs with the same model replies give the same packet key. This is a second run on new
storage, as a second job with a different run identity:

```python
second = storage_with_inputs()
print(job(second / "input", second / "store", recorded(recorded_replies)) == packet)
```

```text
True
```

To join a run to its receipt, record the packet key with the run identity. Keep this record in
the job runner, or in a file beside the store:

```python
(storage / "run.json").write_text(
    json.dumps({"run_id": "batch-0417", "packet": packet}), encoding="utf-8"
)
print(main(["verify", "--store", str(storage / "store"), packet]))
```

```text
receipt verified
0
```

The model name is part of the run record. Two runs give the same packet key only if they have
the same model name, the same inputs and the same replies.

## 4. Run the job in a container

The job needs Python and groundgate, with no other package. Put both in the image, and pin the
groundgate release. This command runs the job of
[`examples/job-runner`](../../examples/job-runner/README.md) from the root of this repository.
It mounts the source in place of an image with groundgate:

```bash
mkdir work-box
docker run --rm --network none --user "$(id -u):$(id -g)" \
  --env PYTHONPATH=/src --volume "$PWD/src:/src:ro" \
  --volume "$PWD/examples/job-runner:/job:ro" --volume "$PWD/work-box:/out" \
  python:3.12-slim python /job/job.py --input /job/input --store /out/store --replies /job/replies.json
groundgate verify --store work-box/store "$(cat work-box/packet.txt)"
```

- `--volume "$PWD/work-box:/out"` is the storage that outlives the container. On a cluster, use
  a volume claim. `--rm` removes the container when the job ends.
- `--user` makes the host user the owner of the store. The store writes each file with mode
  `0600`. If a different user of the same group verifies, open the store with
  `FolderStore(folder, group_read=True)` in the job.
- `--network none` is possible because the replies are recorded. A job that calls a model needs
  a route to the model only.

`tests/test_job_runner.py` runs this job in a container and as a local process. The two stores
hold the same files, byte for byte, and `verify` gives the same result for the two.

## 5. Share one store between jobs

Each object in the store has the key of its bytes. Two jobs that write the same object write the
same bytes, so the objects need no lock. Jobs on different documents can thus write one store
folder. Give each job its own file for the packet key, or collect the keys in the job runner.

## An example with a cluster job runner

[`examples/koodam-agent`](../../examples/koodam-agent/README.md) is an optional example. It runs
the same job as a koodam Agent run. The model calls go through the gateway of the run, the run
has a spend record, and the status of the run holds the digest of `packet.txt`. The example pins
the koodam release `v0.4.0`, and one script runs it in a kind cluster. groundgate does not need
koodam.
