"""The seam test of examples/koodam-agent: a groundgate job as a koodam Agent run (#594).

The test pins one koodam version in ``KOODAM``. That version has no tag yet, so ``agent_run``
uses the local stand-in of ``examples/koodam-agent/standin.py``. When the version has a tag,
``agent_run`` starts the run on that version, and the checks stay the same."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from groundgate.cli import main
from groundgate.extract import RunResult
from groundgate.store import FolderStore

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples" / "koodam-agent"
JOB = ROOT / "examples" / "job-runner"
if not EXAMPLE.is_dir():  # the sdist holds the tests, and not the examples
    pytest.skip("the examples are not here", allow_module_level=True)
# The koodam version of the seam. It is a release version, not a branch and not a pre-release.
KOODAM = "v0.4.0"

_spec = importlib.util.spec_from_file_location("koodam_agent_standin", EXAMPLE / "standin.py")
assert _spec is not None and _spec.loader is not None
standin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(standin)

MANIFEST = json.loads((EXAMPLE / "agent.json").read_text(encoding="utf-8"))
REPLIES = json.loads((JOB / "replies.json").read_text(encoding="utf-8"))

AgentRun = Callable[..., tuple[dict[str, Any], Path]]


@pytest.fixture
def agent_run(tmp_path: Path) -> AgentRun:
    """Start one Agent run on new storage, and return its status and the storage folder after
    the run ends. This function is the seam: it is the only part that knows the stand-in."""

    def start(name: str, replies: list[str] = REPLIES) -> tuple[dict[str, Any], Path]:
        storage = tmp_path / name
        shutil.copytree(JOB / "input", storage / "input")
        status = standin.run_agent(MANIFEST, {"/data": storage, "/job": ROOT / "examples"}, replies)
        return status, storage

    return start


def tree(folder: Path) -> dict[str, bytes]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def test_the_pin_is_a_release_version_and_the_stand_in_names_it() -> None:
    assert re.fullmatch(r"v\d+\.\d+\.\d+", KOODAM)
    assert standin.CONTRACT == KOODAM
    assert KOODAM in (EXAMPLE / "README.md").read_text(encoding="utf-8")


def test_the_manifest_follows_the_contract() -> None:
    spec = standin.check_manifest(MANIFEST)
    assert spec["output"]["path"] == "/data/packet.txt"
    both = copy.deepcopy(MANIFEST)
    both["spec"]["models"] = ["invoice-model"]
    image = copy.deepcopy(MANIFEST)
    image["spec"]["podTemplate"]["spec"]["containers"][0]["image"] = "other:1"
    no_budget = copy.deepcopy(MANIFEST)
    del no_budget["spec"]["budget"]
    for refused in (both, image, no_budget, {**MANIFEST, "kind": "Job"}):
        with pytest.raises(ValueError):
            standin.check_manifest(refused)


def test_verify_passes_on_the_store_after_the_run_ends(
    agent_run: AgentRun, capsys: pytest.CaptureFixture[str]
) -> None:
    status, storage = agent_run("run")
    # The run ended. Only the storage and the status are left.
    assert status["phase"] == "Succeeded"
    packet_file = (storage / "packet.txt").read_bytes()
    assert status["output"] == {
        "path": "/data/packet.txt",
        "sha256": hashlib.sha256(packet_file).hexdigest(),
        "size": len(packet_file),
    }
    packet = packet_file.decode("utf-8").strip()
    capsys.readouterr()
    assert main(["verify", "--store", str(storage / "store"), packet]) == 0
    assert capsys.readouterr().out == "receipt verified\n"
    with FolderStore(storage / "store") as store:
        replayed = RunResult.load(store, packet)
    outcomes = {d.field: (d.value, d.unit, d.outcome) for d in replayed.receipt.decisions}
    assert outcomes == {
        "sales_tax": ("13.8", "USD", "admitted"),
        "total_due": ("289.8", "USD", "admitted"),
    }
    usage = status["usage"]
    assert (usage["calls"], usage["failedCalls"]) == (1, 0)
    assert [m["model"] for m in usage["models"]] == ["invoice-model"]


def test_the_run_identity_and_the_spend_are_not_inputs(agent_run: AgentRun, tmp_path: Path) -> None:
    first, first_storage = agent_run("first")
    second, second_storage = agent_run("second")
    assert first["runID"] != second["runID"]
    assert tree(first_storage) == tree(second_storage)
    for status, storage in ((first, first_storage), (second, second_storage)):
        for data in tree(storage).values():
            assert status["runID"].encode() not in data
            assert status["usage"]["spend"].encode() not in data
    # A local run with the same recorded replies, with no gateway and no run identity.
    local = tmp_path / "local"
    local.mkdir()
    command = [sys.executable, str(JOB / "job.py"), "--input", str(JOB / "input")]
    command += ["--store", str(local / "store"), "--replies", str(JOB / "replies.json")]
    command += ["--model-id", MANIFEST["spec"]["model"]]
    subprocess.run(command, capture_output=True, check=True)
    assert tree(local) == {
        name: data for name, data in tree(first_storage).items() if not name.startswith("input/")
    }


def test_a_run_with_no_reply_fails_and_has_no_output(agent_run: AgentRun) -> None:
    status, storage = agent_run("failed", [])
    assert status["phase"] == "Failed"
    assert status["output"] == {"path": "/data/packet.txt", "reason": "NotFound"}
    assert status["usage"]["failedCalls"] == 1
    assert not (storage / "store").exists()
