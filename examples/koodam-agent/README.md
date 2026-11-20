# A groundgate job as a koodam Agent run

This example is optional. groundgate does not need koodam. The example shows one job runner: the
job of [`examples/job-runner`](../job-runner/README.md) runs as a koodam Agent run, the model
calls go through the gateway of the run, and the receipt verifies after the pod ends.

The example pins the koodam release `v0.4.0`, which is the commit `1a8c3a1`. An earlier release
has no run identity and no output digest. [`cluster.py`](cluster.py) holds the pins: the Helm
chart and the controller image of the release, each with its digest.

| File | Content |
|---|---|
| [`agent.json`](agent.json) | The Agent manifest. `kubectl` reads JSON as it reads YAML. |
| [`agent_job.py`](agent_job.py) | The job. It sends each model call to the gateway of the run. |
| [`cluster.py`](cluster.py) | It runs the example on koodam in a new kind cluster, then it verifies the receipt. |
| [`standin.py`](standin.py) | A local stand-in for the Agent run contract, for a run with no cluster. |
| [`run.py`](run.py) | It runs the example on the stand-in, then it verifies the receipt. |

## Run the example on koodam

You need `docker`, `kind`, `kubectl` and `helm`, and a network connection for the images. The run
takes some minutes.

```bash
uv run python examples/koodam-agent/cluster.py
```

The script does these steps:

1. It makes a new kind cluster with its own kubeconfig file. Your kubeconfig does not change.
2. It builds the job image and loads it into the cluster. The image holds groundgate, and the
   two example folders below `/job`.
3. It installs the koodam chart with the bundled gateway. The gateway has one mock model with
   the model name of the manifest. The mock model gives the recorded reply of
   [`replies.json`](../job-runner/replies.json), so no model runs.
4. It makes a namespace and the volume claim `invoice-data`, and it copies `input/` to the
   volume.
5. It applies the manifest, with the job image in `spec.image`. It waits until the run ends and
   the status of the Agent has the usage.
6. It copies the volume to a local folder. It compares `status.output.sha256` with the SHA-256
   digest of `packet.txt`, then it runs `groundgate verify` on the store.
7. It deletes the cluster.

The script prints the status of the Agent, then `receipt verified`. The run admits two facts from
the synthetic invoice: `total_due` and `sales_tax`.

## Run the example with no cluster

```bash
uv run python examples/koodam-agent/run.py
```

This script uses the stand-in, not koodam. It prints the status of the run, then
`receipt verified`.

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

`tests/test_job_runner_koodam.py` checks this on the stand-in in each test run. It checks the
same on koodam when the environment variable `GROUNDGATE_KOODAM` is `1`:

```bash
GROUNDGATE_KOODAM=1 uv run pytest tests/test_job_runner_koodam.py
```

## What the stand-in does

[`standin.py`](standin.py) is not koodam. It is a local fake of the parts of the Agent run
contract of koodam `v0.4.0` that the example uses.

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

## On your cluster

`cluster.py` does these steps on a kind cluster. On a cluster with koodam `v0.4.0`, do them by
hand:

1. Build an image that holds groundgate, and the two example folders below `/job`. Put its name
   in `spec.image`.
2. Make sure that the gateway has the model of `spec.model`.
3. Make the volume claim `invoice-data`, and copy `input/` to its root.
4. Apply the manifest: `kubectl apply -f examples/koodam-agent/agent.json`.
5. After the run ends, read `status.output.sha256` of the Agent. Compare it with the SHA-256
   digest of `packet.txt` on the volume.
6. Run `groundgate verify --store store "$(cat packet.txt)"` on the volume.

The sidecar that computes the digest does not run as the user of the job. Thus `packet.txt` and
its folder must permit a read by other users.
