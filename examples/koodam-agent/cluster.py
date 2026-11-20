"""Run the example on koodam, in a new kind cluster, and verify the receipt after the pod ends.

    python examples/koodam-agent/cluster.py

The script needs ``docker``, ``kind``, ``kubectl`` and ``helm``, and a network connection for the
images. It makes a cluster with its own kubeconfig file, so it does not change your kubeconfig.
It deletes the cluster at the end.

The pins are the constants below. The chart and the controller image have the digest of the
koodam release ``KOODAM``. The gateway of the chart gives the recorded reply of
``examples/job-runner/replies.json`` for the model of the manifest, so no model runs.
"""

from __future__ import annotations

import copy
import hashlib
import json
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
JOB = HERE.parent / "job-runner"

# The koodam release of this example: the tag, and the commit of the tag.
KOODAM = "v0.4.0"
COMMIT = "1a8c3a133c4155e1120268109e7436d07cbcb095"
# The Helm chart of the release, with its digest.
CHART = (
    "oci://ghcr.io/mohanraj00/charts/koodam:0.4.0"
    "@sha256:3a99eecfbf959cd6d6c3f992e9b594cf732ce9f9f5487095efa13e7219f123c2"
)
# The controller image of the release. The chart adds this value after the image name.
CONTROLLER_TAG = "0.4.0@sha256:a0f13bd00780db9caa8496fe49fced838dbe4cd1714d43921ddbbbfb635819b7"
# The base image of the job image.
PYTHON = "python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1"

TOOLS = ("docker", "kind", "kubectl", "helm")
JOB_IMAGE = "groundgate-job:koodam-example"
SYSTEM = "koodam-system"
DOCKERFILE = f"""FROM {PYTHON}
COPY src /src
COPY job /job
ENV PYTHONPATH=/src PYTHONDONTWRITEBYTECODE=1
"""


def missing_tools() -> list[str]:
    """Return the names of the tools that this script needs and cannot find."""
    return [tool for tool in TOOLS if shutil.which(tool) is None]


def _run(command: Sequence[str], *, data: str | None = None, timeout: float = 300) -> str:
    """Run one command with a list of arguments and a timeout, and return its output."""
    done = subprocess.run(
        list(command), input=data, capture_output=True, text=True, timeout=timeout, check=False
    )
    if done.returncode != 0:
        output = (done.stdout + done.stderr)[-2000:]
        raise RuntimeError(f"{' '.join(command[:3])} failed:\n{output}")
    return done.stdout


class Koodam:
    """One kind cluster with the koodam release, the bundled gateway and the job image.

    The gateway has one mock model. It gives ``reply`` for each call, and it records a spend.
    """

    def __init__(self, model: str, reply: str, name: str = "") -> None:
        self.model = model
        self.reply = reply
        self.name = name or "groundgate-koodam-" + secrets.token_hex(3)
        self.work = Path(tempfile.mkdtemp(prefix="koodam-cluster-"))
        self.kubeconfig = self.work / "kubeconfig"

    def __enter__(self) -> Koodam:
        try:
            self._create()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Delete the cluster and the work folder."""
        subprocess.run(
            [
                "kind",
                "delete",
                "cluster",
                "--name",
                self.name,
                "--kubeconfig",
                str(self.kubeconfig),
            ],
            capture_output=True,
            timeout=300,
            check=False,
        )
        shutil.rmtree(self.work, ignore_errors=True)

    def kubectl(self, *args: str, data: str | None = None, timeout: float = 300) -> str:
        return _run(
            ["kubectl", "--kubeconfig", str(self.kubeconfig), *args], data=data, timeout=timeout
        )

    def _state(self, namespace: str) -> str:
        """Return the pods and the last events of a namespace, for an error message."""
        events = self.kubectl("get", "events", "-n", namespace, "--sort-by=.lastTimestamp")
        return self.kubectl("get", "pods", "-n", namespace) + events[-2000:]

    def _apply(self, manifest: Mapping[str, Any], namespace: str) -> None:
        self.kubectl("apply", "-n", namespace, "-f", "-", data=json.dumps(manifest))

    def _create(self) -> None:
        config = ["--name", self.name, "--kubeconfig", str(self.kubeconfig)]
        _run(["kind", "create", "cluster", *config, "--wait", "180s"], timeout=900)
        # The job image: groundgate, and the two example folders below /job.
        context = self.work / "image"
        shutil.copytree(ROOT / "src" / "groundgate", context / "src" / "groundgate")
        shutil.copytree(JOB, context / "job" / "job-runner")
        (context / "job" / "koodam-agent").mkdir()
        shutil.copy(HERE / "agent_job.py", context / "job" / "koodam-agent" / "agent_job.py")
        (context / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
        _run(["docker", "build", "--quiet", "--tag", JOB_IMAGE, str(context)], timeout=900)
        _run(["kind", "load", "docker-image", JOB_IMAGE, "--name", self.name], timeout=900)
        # The chart, with the bundled gateway and one mock model.
        self.kubectl("create", "namespace", SYSTEM)
        self.kubectl(
            "create", "secret", "generic", "koodam-gateway", "-n", SYSTEM,
            "--from-file=master-key=/dev/stdin", data="sk-" + secrets.token_hex(32),
        )  # fmt: skip
        mock = {"enabled": True, "modelName": self.model, "response": self.reply}
        values = {
            "image": {"tag": CONTROLLER_TAG},
            "gateway": {
                "mode": "bundled",
                "masterKeySecret": {"name": "koodam-gateway", "key": "master-key"},
                "bundled": {"mock": mock, "postgres": {"persistence": {"enabled": False}}},
            },
        }
        (self.work / "values.json").write_text(json.dumps(values), encoding="utf-8")
        helm = ["helm", "install", "koodam", CHART, "--kubeconfig", str(self.kubeconfig)]
        _run([*helm, "-n", SYSTEM, "-f", str(self.work / "values.json")], timeout=900)
        available = ["wait", "--for=condition=Available", "deployment", "--all", "-n", SYSTEM]
        try:
            self.kubectl(*available, "--timeout=900s", timeout=960)
        except RuntimeError as error:
            raise RuntimeError(f"{error}\n{self._state(SYSTEM)}") from error

    def _with_volume(self, namespace: str, claim: str, *copy_args: str) -> None:
        """Start a pod that mounts the claim at /data, run one ``kubectl cp``, delete the pod."""
        pod = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "volume-access"},
            "spec": {
                "restartPolicy": "Never",
                "terminationGracePeriodSeconds": 0,
                "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": claim}}],
                "containers": [
                    {
                        "name": "access",
                        "image": JOB_IMAGE,
                        "command": ["sleep", "3600"],
                        "volumeMounts": [{"name": "data", "mountPath": "/data"}],
                    }
                ],
            },
        }
        self._apply(pod, namespace)
        try:
            ready = ["wait", "--for=condition=Ready", "pod/volume-access", "-n", namespace]
            self.kubectl(*ready, "--timeout=300s", timeout=360)
            self.kubectl("cp", "-n", namespace, *copy_args)
        finally:
            self.kubectl("delete", "pod", "volume-access", "-n", namespace, "--wait=true")

    def run_agent(
        self, manifest: Mapping[str, Any], inputs: Path, storage: Path, namespace: str
    ) -> dict[str, Any]:
        """Run one Agent in a new namespace. Copy ``inputs`` to the volume before the run, and
        copy the volume to ``storage`` after the pod ends. Return the status of the Agent."""
        agent = copy.deepcopy(dict(manifest))
        agent["spec"]["image"] = JOB_IMAGE
        name = agent["metadata"]["name"]
        claim = agent["spec"]["podTemplate"]["spec"]["volumes"][0]["persistentVolumeClaim"]
        self.kubectl("create", "namespace", namespace)
        volume = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": claim["claimName"]},
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": "64Mi"}},
            },
        }
        self._apply(volume, namespace)
        self._with_volume(namespace, claim["claimName"], str(inputs), "volume-access:/data/input")
        self._apply(agent, namespace)
        status = self._wait(name, namespace, float(agent["spec"].get("deadlineSeconds", 900)) + 300)
        # The pod ended. Only the volume and the status are left.
        self._with_volume(namespace, claim["claimName"], "volume-access:/data", str(storage))
        return status

    def _wait(self, name: str, namespace: str, seconds: float) -> dict[str, Any]:
        """Wait until the run ended and the controller wrote the usage, and return the status."""
        end = time.monotonic() + seconds
        status: dict[str, Any] = {}
        while time.monotonic() < end:
            agent = json.loads(self.kubectl("get", "agent", name, "-n", namespace, "-o", "json"))
            status = agent.get("status", {})
            if status.get("phase") in ("Succeeded", "Failed") and "usage" in status:
                return status
            time.sleep(2)
        state = json.dumps(status) + "\n" + self._state(namespace)
        raise RuntimeError(f"the Agent did not end in {seconds:.0f} seconds: {state}")


def main() -> int:
    missing = missing_tools()
    if missing:
        print("these tools are not installed: " + ", ".join(missing))
        return 2
    from groundgate.cli import main as groundgate

    manifest = json.loads((HERE / "agent.json").read_text(encoding="utf-8"))
    replies = json.loads((JOB / "replies.json").read_text(encoding="utf-8"))
    storage = Path(tempfile.mkdtemp(prefix="koodam-agent-")) / "data"
    print(f"koodam {KOODAM} ({COMMIT[:7]}) in a new kind cluster. This takes some minutes.")
    with Koodam(manifest["spec"]["model"], replies[0]) as koodam:
        status = koodam.run_agent(manifest, JOB / "input", storage, "invoice")
    print(json.dumps(status, indent=2))
    if status["phase"] != "Succeeded":
        return 1
    packet = (storage / "packet.txt").read_bytes()
    if hashlib.sha256(packet).hexdigest() != status["output"]["sha256"]:
        print("packet.txt is not the file of the output digest")
        return 1
    return groundgate(["verify", "--store", str(storage / "store"), packet.decode().strip()])


if __name__ == "__main__":
    sys.exit(main())
