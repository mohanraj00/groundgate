"""Run the example on the stand-in, and verify the receipt after the run ends.

    python examples/koodam-agent/run.py

The script makes a new folder for the storage of the run, and it copies the inputs into it. It
prints the status of the run, then the result of ``groundgate verify`` on the store.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from standin import run_agent  # noqa: E402

from groundgate.cli import main as groundgate  # noqa: E402

JOB = HERE.parent / "job-runner"


def main() -> int:
    storage = Path(tempfile.mkdtemp(prefix="koodam-agent-"))
    shutil.copytree(JOB / "input", storage / "input")
    manifest = json.loads((HERE / "agent.json").read_text(encoding="utf-8"))
    replies = json.loads((JOB / "replies.json").read_text(encoding="utf-8"))
    # /data is the volume of the manifest, and /job is the folder of the examples in the image.
    status = run_agent(manifest, {"/data": storage, "/job": HERE.parent}, replies)
    print(json.dumps(status, indent=2))
    if status["phase"] != "Succeeded":
        return 1
    # The run ended. Only the storage and the status are left.
    packet = (storage / "packet.txt").read_bytes()
    if hashlib.sha256(packet).hexdigest() != status["output"]["sha256"]:
        print("packet.txt is not the file of the output digest")
        return 1
    return groundgate(["verify", "--store", str(storage / "store"), packet.decode().strip()])


if __name__ == "__main__":
    raise SystemExit(main())
