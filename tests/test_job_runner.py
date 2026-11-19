"""The job of examples/job-runner keeps a receipt that verifies after the job ends, and a run in
a container gives the same store as a local run with the same recorded model replies (#594)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from groundgate.cli import main
from groundgate.extract import RunResult
from groundgate.store import FolderStore

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples" / "job-runner"
if not EXAMPLE.is_dir():  # the sdist holds the tests, and not the examples
    pytest.skip("the examples are not here", allow_module_level=True)
# The image of the container run, with the digest of its index. The index has linux/amd64 and
# linux/arm64.
IMAGE = os.environ.get(
    "GROUNDGATE_CONTAINER_IMAGE",
    "python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1",
)


def local_run(folder: Path, *options: str) -> str:
    """Run the job as a local process with the recorded replies, and return the packet key."""
    command = [sys.executable, str(EXAMPLE / "job.py"), "--input", str(EXAMPLE / "input")]
    command += ["--store", str(folder / "store"), "--replies", str(EXAMPLE / "replies.json")]
    done = subprocess.run([*command, *options], capture_output=True, text=True, check=True)
    return done.stdout.strip()


def tree(folder: Path) -> dict[str, bytes]:
    """Each file below ``folder``, by its relative path."""
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def verify(folder: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    """The exit code and the output of ``groundgate verify`` on the store of a finished job."""
    packet = (folder / "packet.txt").read_text(encoding="utf-8").strip()
    capsys.readouterr()
    status = main(["verify", "--store", str(folder / "store"), packet])
    return status, capsys.readouterr().out


def test_the_receipt_verifies_after_the_job_ends(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    packet = local_run(tmp_path)
    # The job process ended. Only the files on the storage are left.
    assert (tmp_path / "packet.txt").read_text(encoding="utf-8") == packet + "\n"
    assert verify(tmp_path, capsys) == (0, "receipt verified\n")
    with FolderStore(tmp_path / "store") as store:
        replayed = RunResult.load(store, packet)  # the recorded replies, with no model call
    outcomes = {d.field: (d.value, d.unit, d.outcome) for d in replayed.receipt.decisions}
    assert outcomes == {
        "sales_tax": ("13.8", "USD", "admitted"),
        "total_due": ("289.8", "USD", "admitted"),
    }


def test_a_second_run_with_the_same_replies_gives_the_same_store(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    assert local_run(first) == local_run(second)
    assert tree(first) == tree(second)


def test_verify_fails_if_a_stored_object_changed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local_run(tmp_path)
    changed = 0
    for path in (tmp_path / "store" / "objects").rglob("*"):
        if path.is_file() and b"$289.80" in path.read_bytes():
            path.chmod(0o600)
            path.write_bytes(path.read_bytes().replace(b"$289.80", b"$299.80"))
            changed += 1
    assert changed > 0
    status, _ = verify(tmp_path, capsys)
    assert status != 0


def _engine() -> str:
    """The container program, or a skip if no Linux container engine runs here."""
    program = shutil.which("docker")
    if program is None:
        pytest.skip("no container program")
    try:
        found = subprocess.run(
            [program, "info", "--format", "{{.OSType}}"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("the container engine does not answer")
    if found.returncode != 0 or found.stdout.strip() != "linux":
        pytest.skip("no Linux container engine")
    present = subprocess.run([program, "image", "inspect", IMAGE], capture_output=True, check=False)
    if present.returncode != 0:
        pulled = subprocess.run(
            [program, "pull", "--quiet", IMAGE], capture_output=True, check=False
        )
        if pulled.returncode != 0:
            pytest.skip("the container image is not here, and the pull failed")
    return program


@pytest.fixture
def shared_folder(tmp_path: Path) -> Iterator[Path]:
    """A folder that the container engine can mount. Some engines mount only some host folders.
    ``GROUNDGATE_CONTAINER_TMP`` names a host folder that the engine mounts."""
    base = os.environ.get("GROUNDGATE_CONTAINER_TMP")
    if base is None:
        yield tmp_path
        return
    folder = Path(tempfile.mkdtemp(dir=base))
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_a_container_run_gives_the_same_store_and_the_same_verify_result(
    shared_folder: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    program = _engine()
    local, box = tmp_path / "local", shared_folder / "box"
    local.mkdir()
    box.mkdir()
    start = [program, "run", "--rm", "--network", "none"]
    if hasattr(os, "getuid"):
        start += ["--user", f"{os.getuid()}:{os.getgid()}"]  # the host user owns the store
    start += ["--volume", f"{box}:/out"]
    (box / "probe").write_bytes(b"")
    seen = subprocess.run([*start, IMAGE, "test", "-f", "/out/probe"], capture_output=True)
    (box / "probe").unlink()
    if seen.returncode != 0:
        pytest.skip("the engine does not mount this folder: set GROUNDGATE_CONTAINER_TMP")
    command = [*start, "--env", "PYTHONPATH=/src", "--env", "PYTHONDONTWRITEBYTECODE=1"]
    command += ["--volume", f"{ROOT / 'src'}:/src:ro", "--volume", f"{EXAMPLE}:/job:ro", IMAGE]
    command += ["python", "/job/job.py", "--input", "/job/input"]
    command += ["--store", "/out/store", "--replies", "/job/replies.json"]
    done = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    assert done.returncode == 0, done.stderr
    # The container ended and --rm removed it. Only the mounted folder is left.
    assert done.stdout.strip() == local_run(local)
    assert tree(box) == tree(local)
    assert verify(box, capsys) == verify(local, capsys) == (0, "receipt verified\n")
