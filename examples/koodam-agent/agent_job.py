"""The groundgate job as a koodam Agent run.

The job is the job of ``examples/job-runner``, with one change: each model call goes through the
gateway of the run. The run gives the gateway address and the key in the environment variables
``OPENAI_BASE_URL`` and ``OPENAI_API_KEY``. The job does not read the run identity.

    python agent_job.py --input DIR --store DIR --model NAME
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "job-runner"))

from job import run

TIMEOUT_SECONDS = 120


def gateway(model: str) -> Callable[[str], str]:
    """A client that sends each prompt to the gateway as one chat completions request."""
    url = os.environ["OPENAI_BASE_URL"].rstrip("/") + "/chat/completions"
    if not url.startswith(("http://", "https://")):
        raise ValueError("the gateway address must start with http:// or https://")
    headers = {
        "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
        "Content-Type": "application/json",
    }

    def client(prompt: str) -> str:
        body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}]})
        request = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers)
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            reply = json.load(response)
        return str(reply["choices"][0]["message"]["content"])

    return client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run groundgate as a koodam Agent run.")
    parser.add_argument("--input", type=Path, required=True, help="the folder of the inputs")
    parser.add_argument("--store", type=Path, required=True, help="the store folder")
    parser.add_argument("--model", required=True, help="the model name of the Agent")
    args = parser.parse_args(argv)
    print(run(args.input, args.store, gateway(args.model), args.model))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
