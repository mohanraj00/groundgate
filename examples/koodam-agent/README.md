# A groundgate job as a koodam Agent run

This example is optional. groundgate does not need koodam. The example shows one job runner: the
job of [`examples/job-runner`](../job-runner/README.md) runs as a koodam Agent run, the model
calls go through the gateway of the run, and the receipt verifies after the pod ends.

**This example runs on a stand-in, not on koodam.** The example pins koodam `v0.4.0`. That version
has no tag yet, and koodam `v0.3.0` has no run identity and no output digest.
[`standin.py`](standin.py) is a local fake of the parts of the Agent run contract that the
example uses. When koodam `v0.4.0` has a tag, the seam test starts the run on that version.

| File | Content |
|---|---|
| [`agent.json`](agent.json) | The Agent manifest. `kubectl` reads JSON as it reads YAML. |
| [`agent_job.py`](agent_job.py) | The job. It sends each model call to the gateway of the run. |
| [`standin.py`](standin.py) | The stand-in for the Agent run contract. |
| [`run.py`](run.py) | It runs the example on the stand-in, then it verifies the receipt. |

## Run the example

```bash
uv run python examples/koodam-agent/run.py
```

The script prints the status of the run, then `receipt verified`. The run admits two facts from
the synthetic invoice: `total_due` and `sales_tax`.

## What the run gives

The manifest mounts one volume at `/data`. The job reads `/data/input`, and it writes the store
to `/data/store` and the packet key to `/data/packet.txt`. The volume outlives the pod.

`spec.output.path` names `/data/packet.txt`. After the pod ends, the status of the Agent holds
these values:

- `status.runID` is the run identity.
- `status.output.sha256` is the SHA-256 digest of `packet.txt`.
- `status.usage` is the usage summary of the gateway: the spend, the calls and the tokens.

The digest joins the status to the receipt. `packet.txt` holds the packet key. The packet key is
a digest of the packet, and the packet names the receipt and each input by its digest. Thus one
run identity names one receipt, and `groundgate verify` checks that receipt from the store.

The run identity and the usage summary are not inputs of the receipt. The job does not read
`KOODAM_RUN_ID`. Two runs with the same model replies give the same store, byte for byte, and
a local run with the recorded replies gives that store too.
`tests/test_job_runner_koodam.py` checks this.

## What the stand-in does

1. It checks the manifest: the kind, `image`, `command`, one of `model` and `models`, `budget`,
   and no `image` or `command` in the `agent` container of `podTemplate`.
2. It makes a run identity and a gateway key.
3. It starts a local gateway. The gateway takes chat completions requests at
   `/v1/chat/completions` with the key as a bearer token. It refuses a different key and a model
   that the manifest does not name. It gives the recorded replies of
   [`replies.json`](../job-runner/replies.json).
4. It starts the command as a local process, with `KOODAM_RUN_ID`, `OPENAI_BASE_URL` and
   `OPENAI_API_KEY` in the environment. It maps `/data` to a local folder and `/job` to the
   `examples` folder.
5. After the process ends, it stops the gateway. It writes `runID`, `phase`, `output` and `usage`
   into the status.

The stand-in has no image, no pod, no budget limit, no price table and no network policy. Its
spend is a made-up price for each word, not a cost.

## On a cluster

These steps are not tested here until the seam test runs on koodam `v0.4.0`.

1. Build an image that holds groundgate, and the two example folders below `/job`. Put its name
   in `spec.image`.
2. Make the volume claim `invoice-data`, and copy `input/` to its root.
3. Apply the manifest: `kubectl apply -f examples/koodam-agent/agent.json`.
4. After the run ends, read `status.output.sha256` of the Agent. Compare it with the SHA-256
   digest of `packet.txt` on the volume.
5. Run `groundgate verify --store store "$(cat packet.txt)"` on the volume.
