"""A groundgate job for a job runner.

The job reads ``document.txt`` and ``schema.json`` from the input folder. It runs the extraction
with a model client, and it saves the run in a store folder. It prints the packet key, and it
writes the key to ``packet.txt`` beside the store folder. Put the input folder and the store
folder on storage that outlives the job.

    python job.py --input DIR --store DIR --replies FILE [--model-id ID]

``--replies`` is a JSON list of recorded model replies, in call order. With this option the job
needs no model and no network. To call a model, give ``run`` your own client.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

from groundgate.extract import extract
from groundgate.store import FolderStore

MODEL_ID = "recorded-replies-1"


def recorded(path: Path) -> Callable[[str], str]:
    """A client that gives the recorded replies in call order. It never calls a model."""
    replies = iter(json.loads(path.read_text(encoding="utf-8")))

    def client(prompt: str) -> str:
        reply = next(replies, None)
        if not isinstance(reply, str):
            raise RuntimeError("the job made more calls than the recorded replies")
        return reply

    return client


def run(inputs: Path, store_folder: Path, client: Callable[[str], str], model_id: str) -> str:
    """Run the extraction on the inputs, save the run in the store, and return the packet key.

    The run identity, the trace and the spend record of the job runner are not parameters. The
    store holds only the inputs, the prompts, the replies and the decisions."""
    text = (inputs / "document.txt").read_text(encoding="utf-8")
    schema = json.loads((inputs / "schema.json").read_text(encoding="utf-8"))
    result = extract(text, schema, client=client, model_id=model_id, document_id="invoice-2041")
    if not result.complete:
        raise RuntimeError("the run is not complete")
    with FolderStore(store_folder) as store:
        packet = result.save(store)
    (store_folder.parent / "packet.txt").write_text(packet + "\n", encoding="utf-8", newline="\n")
    return packet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run groundgate as a job and save the run.")
    parser.add_argument("--input", type=Path, required=True, help="the folder of the inputs")
    parser.add_argument("--store", type=Path, required=True, help="the store folder")
    parser.add_argument("--replies", type=Path, required=True, help="the recorded model replies")
    parser.add_argument("--model-id", default=MODEL_ID, help="the model name in the run record")
    args = parser.parse_args(argv)
    print(run(args.input, args.store, recorded(args.replies), args.model_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
