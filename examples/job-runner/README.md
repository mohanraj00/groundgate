# Run groundgate as a job

This example is a groundgate job for a job runner: a container, a batch queue or a cluster. The
job saves its run in a store on storage that outlives the job. After the job ends, `groundgate
verify` passes on that store. [Run groundgate under a job runner](../../docs/howto/job-runner.md)
gives the steps.

| File | Content |
|---|---|
| [`job.py`](job.py) | The job. It reads the inputs, runs the extraction and saves the run. |
| [`input/document.txt`](input/document.txt) | A synthetic invoice. |
| [`input/schema.json`](input/schema.json) | Two fields: `total_due` and `sales_tax`. |
| [`replies.json`](replies.json) | The recorded model replies, in call order. |

## Run the job on your machine

```bash
uv run python examples/job-runner/job.py --input examples/job-runner/input --store work/store --replies examples/job-runner/replies.json
```

The job prints the packet key, and it writes the key to `work/packet.txt`. It calls no model:
the client gives the recorded replies.

```bash
uv run groundgate verify --store work/store "$(cat work/packet.txt)"
```

```text
receipt verified
```

## Run the job in a container

The job needs only Python and groundgate. This command mounts the source of this repository, the
example and one folder for the output. It gives the container no network:

```bash
docker run --rm --network none --user "$(id -u):$(id -g)" \
  --env PYTHONPATH=/src --volume "$PWD/src:/src:ro" \
  --volume "$PWD/examples/job-runner:/job:ro" --volume "$PWD/work-box:/out" \
  python:3.12-slim python /job/job.py --input /job/input --store /out/store --replies /job/replies.json
```

Make the folder `work-box` before the run. After the container ends, `work-box` holds the same
files as `work`, byte for byte, and `verify` gives the same result.
`tests/test_job_runner.py` checks this.
