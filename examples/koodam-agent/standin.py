"""A local stand-in for the koodam Agent run contract.

This file is not koodam. It is a fake of the parts of the contract that this example uses, for
the koodam version in ``CONTRACT``. It lets the example and its seam test run with no cluster.
``cluster.py`` runs the example on koodam itself.

The stand-in does these steps for one Agent manifest:

1. It checks the manifest against the rules of the contract that this example uses.
2. It makes a run identity, a gateway key and a local gateway. The gateway gives the recorded
   replies to chat completions requests, and it counts the calls and the tokens.
3. It starts the command of the manifest as a local process. The process gets ``KOODAM_RUN_ID``,
   ``OPENAI_BASE_URL``, ``OPENAI_API_KEY`` and the ``env`` entries of the manifest. Each mount
   path of the manifest maps to a local folder.
4. After the process ends, it stops the gateway. Then it writes the SHA-256 digest and the size
   of the file at ``spec.output.path`` into the status, with the usage summary.

The stand-in has no image, no pod, no budget limit, no price table and no network policy.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import threading
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

CONTRACT = "v0.4.0"
API_VERSION = "core.koodam.dev/v1alpha1"
DEADLINE_SECONDS = 900  # the default of spec.deadlineSeconds
MAX_REQUEST_BYTES = 1 << 20
# A made-up price for one token. The spend of the stand-in is not a real cost.
TOKEN_PRICE = Decimal("0.000002")


def check_manifest(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the spec of an Agent manifest, or raise ``ValueError`` for a manifest that the
    contract refuses. The stand-in checks only the fields that this example uses."""
    if manifest.get("apiVersion") != API_VERSION or manifest.get("kind") != "Agent":
        raise ValueError(f"the manifest is not an Agent of {API_VERSION}")
    spec = manifest.get("spec")
    if not isinstance(spec, Mapping):
        raise ValueError("the manifest has no spec")
    command = spec.get("command")
    if not isinstance(spec.get("image"), str) or not spec["image"]:
        raise ValueError("spec.image is required")
    if not isinstance(command, list) or not command or not all(isinstance(c, str) for c in command):
        raise ValueError("spec.command is a list of at least 1 string")
    if ("model" in spec) == ("models" in spec):
        raise ValueError("set exactly one of spec.model and spec.models")
    if "budget" not in spec:
        raise ValueError("spec.budget is required")
    for container in _containers(spec):
        if container.get("name") == "agent" and ({"image", "command"} & set(container)):
            raise ValueError("the agent container of spec.podTemplate cannot set image or command")
    return spec


def _containers(spec: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    found = spec.get("podTemplate", {}).get("spec", {}).get("containers", [])
    return [c for c in found if isinstance(c, Mapping)]


def _models(spec: Mapping[str, Any]) -> list[str]:
    return [spec["model"]] if "model" in spec else list(spec["models"])


def _tokens(text: str) -> int:
    return len(text.split())


class _Server(ThreadingHTTPServer):
    gateway: _Gateway


class _Gateway:
    """A local gateway for one run: one key, the models of the run and the recorded replies."""

    def __init__(self, models: Sequence[str], replies: Sequence[str]) -> None:
        self.key = secrets.token_urlsafe(24)
        self.models = list(models)
        self._replies = list(replies)
        self._lock = threading.Lock()
        self._calls: list[tuple[str, bool, int, int]] = []  # model, failed, input, output
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.gateway = self
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()

    def reply(self, model: str, prompt: str) -> str | None:
        """The next recorded reply, or ``None`` if no reply is left. Each call is counted."""
        with self._lock:
            reply = self._replies.pop(0) if self._replies else None
            output = _tokens(reply) if reply is not None else 0
            self._calls.append((model, reply is None, _tokens(prompt), output))
            return reply

    def usage(self) -> dict[str, Any]:
        """The usage summary of the run, in the form of ``status.usage``."""

        def summary(calls: list[tuple[str, bool, int, int]]) -> dict[str, Any]:
            # The counts and the tokens are of the successful calls. A zero count is not in
            # the status.
            good = [c for c in calls if not c[1]]
            tokens_in = sum(c[2] for c in good)
            tokens_out = sum(c[3] for c in good)
            counts = {
                "calls": len(good),
                "failedCalls": len(calls) - len(good),
                "inputTokens": tokens_in,
                "outputTokens": tokens_out,
            }
            spend = str((tokens_in + tokens_out) * TOKEN_PRICE)
            return {"spend": spend, **{name: n for name, n in counts.items() if n}}

        with self._lock:
            calls = list(self._calls)
        by_model = [
            {"model": name, **summary([c for c in calls if c[0] == name])}
            for name in sorted({c[0] for c in calls})
        ]
        return {**summary(calls), "models": by_model}


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        assert isinstance(self.server, _Server)
        gateway = self.server.gateway
        if self.path != "/v1/chat/completions":
            return self._send(404, {"error": "the stand-in has only /v1/chat/completions"})
        given = self.headers.get("Authorization", "")
        if not hmac.compare_digest(given.encode(), f"Bearer {gateway.key}".encode()):
            return self._send(401, {"error": "the key is not the key of the run"})
        try:
            length = int(self.headers.get("Content-Length", ""))
            if not 0 < length <= MAX_REQUEST_BYTES:
                raise ValueError
            body = json.loads(self.rfile.read(length))
            model, prompt = body["model"], body["messages"][-1]["content"]
            if not isinstance(model, str) or not isinstance(prompt, str):
                raise ValueError
        except (ValueError, KeyError, IndexError, TypeError):
            return self._send(400, {"error": "the request is not a chat completions request"})
        if model not in gateway.models:
            return self._send(400, {"error": "the key does not permit this model"})
        reply = gateway.reply(model, prompt)
        if reply is None:
            return self._send(500, {"error": "no recorded reply is left"})
        message = {"role": "assistant", "content": reply}
        choice = {"index": 0, "message": message, "finish_reason": "stop"}
        usage = {"prompt_tokens": _tokens(prompt), "completion_tokens": _tokens(reply)}
        return self._send(200, {"model": model, "choices": [choice], "usage": usage})

    def _send(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        """Write no access log."""


def _split(path: str, mounts: Mapping[str, Path]) -> tuple[Path, list[str]] | None:
    """The local folder of the mount that holds a pod path, and the parts of the path below it."""
    for mount, folder in mounts.items():
        if path == mount or path.startswith(mount.rstrip("/") + "/"):
            return Path(folder), [part for part in path[len(mount) :].split("/") if part]
    return None


def _local(path: str, mounts: Mapping[str, Path]) -> Path | None:
    """The local path of a pod path, or ``None`` if no mount holds it."""
    found = _split(path, mounts)
    return None if found is None else found[0].joinpath(*found[1])


def _output(path: str, mounts: Mapping[str, Path]) -> dict[str, Any]:
    """The digest of the output file, in the form of ``status.output``. A link in the path below
    the mount is refused."""
    found = _split(path, mounts)
    if found is None:
        return {"path": path, "reason": "NotFound"}
    step, parts = found
    for part in parts:
        step = step / part
        if step.is_symlink():
            return {"path": path, "reason": "NotRegularFile"}
    if not step.exists():
        return {"path": path, "reason": "NotFound"}
    if not step.is_file():
        return {"path": path, "reason": "NotRegularFile"}
    data = step.read_bytes()
    return {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def run_agent(
    manifest: Mapping[str, Any], mounts: Mapping[str, Path], replies: Sequence[str]
) -> dict[str, Any]:
    """Run the Agent of ``manifest`` as a local process, and return its status after it ends.

    ``mounts`` maps each pod path of the manifest to a local folder, as the volumes and the image
    of a pod do. ``replies`` are the recorded model replies that the gateway gives, in call
    order. The status has ``runID``, ``phase``, ``usage`` and, with ``spec.output``, ``output``."""
    spec = check_manifest(manifest)
    run_id = str(uuid.uuid4())
    gateway = _Gateway(_models(spec), replies)
    command = [sys.executable if spec["command"][0] == "python" else spec["command"][0]]
    for word in spec["command"][1:]:
        local = _local(word, mounts)
        command.append(word if local is None else str(local))
    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT") if name in os.environ}
    env.update(spec.get("env", {}))
    env.update(
        KOODAM_RUN_ID=run_id,
        OPENAI_BASE_URL=gateway.url + "/v1",
        OPENAI_API_KEY=gateway.key,
    )
    deadline = spec.get("deadlineSeconds", DEADLINE_SECONDS)
    gateway.start()
    try:
        done = subprocess.run(command, env=env, capture_output=True, timeout=deadline, check=False)
        succeeded = done.returncode == 0
    except subprocess.TimeoutExpired:
        succeeded = False
    finally:
        gateway.stop()  # the key of the run has no use after the run
    status: dict[str, Any] = {
        "runID": run_id,
        "phase": "Succeeded" if succeeded else "Failed",
        "usage": gateway.usage(),
    }
    if "output" in spec:
        status["output"] = _output(spec["output"]["path"], mounts)
    return status
