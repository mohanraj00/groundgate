"""The rule for a receipt of another release or another spec version (SPEC §8.6, #710)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import groundgate as gg
from groundgate.canonical import SPEC_VERSION
from groundgate.releases import SPEC_RELEASES, release_of

REPO = Path(__file__).parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "receipts" / "irs-590a"
# The bytes of examples/irs-590a/receipt.json at each tag: `git show <tag>:<path> | shasum -a 256`.
RECEIPT_0_11_0 = "07d272782e8f4d0b321584d79e7eb194e1567bfc8ababa11c70e175b6fbb4bf5"
RECEIPT_0_14_0 = "c3bc166d81f36cda4cf7ea8b2b963b745335422e70639a930a54fd5407c739a3"
# Releases that have a tag and a changelog entry, and are not on PyPI.
NOT_ON_PYPI = {"0.12.0", "0.13.0"}


def _inputs() -> tuple[str, dict[str, object], list[object]]:
    text = (FIXTURE / "document.txt").read_text(encoding="utf-8")
    schema = json.loads((FIXTURE / "schema.json").read_text(encoding="utf-8"))
    candidates = json.loads((FIXTURE / "candidates.json").read_text(encoding="utf-8"))
    return text, schema, candidates


def _receipt(name: str, sha256: str) -> dict[str, object]:
    data = (FIXTURE / name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == sha256, f"{name} is not the receipt of its release"
    receipt: dict[str, object] = json.loads(data)
    return receipt


def test_a_receipt_of_an_earlier_release_with_the_same_spec_version_verifies() -> None:
    """Rule 1: a receipt of an earlier release with the same spec version verifies. No release
    of spec 0.13 is out yet, so the receipt comes from this release with its version kept."""
    receipt = gg.admit(*_inputs()).to_dict()
    assert receipt["groundgate"] == SPEC_VERSION == "0.13"
    result = gg.verify(receipt, *_inputs())
    assert result.ok, result.problems


def test_a_receipt_of_spec_0_12_names_its_last_release() -> None:
    """Rule 3 for the spec before this one (#736): release 0.14.0 made this receipt under spec
    0.12, and the last release of spec 0.12 is 0.17.0."""
    receipt = _receipt("receipt-0.14.0.json", RECEIPT_0_14_0)
    assert gg.verify(receipt, *_inputs()).problems == (
        "receipt was decided under spec 0.12; this groundgate implements 0.13. groundgate "
        "0.17.0 implements spec 0.12: verify the receipt with that release (SPEC 8.6)",
    )


def test_a_receipt_of_an_older_spec_version_names_its_release() -> None:
    """Rule 3: one problem that names the spec version and the last release, and no other
    check."""
    receipt = _receipt("receipt-0.11.0.json", RECEIPT_0_11_0)
    result = gg.verify(receipt, *_inputs())
    assert not result.ok
    assert result.problems == (
        "receipt was decided under spec 0.11; this groundgate implements 0.13. groundgate "
        "0.11.0 implements spec 0.11: verify the receipt with that release (SPEC 8.6)",
    )
    changed = {**receipt, "receipt_sha256": "sha256:" + "0" * 64}
    assert gg.verify(changed, "another text", {"fields": {}}, []).problems == result.problems


@pytest.mark.parametrize("version", ["9.9", "1.0", "", None, 12, ["0.11"], {"a": 1}, True])
def test_a_spec_version_with_no_known_release_names_no_release(version: object) -> None:
    assert release_of(version) is None
    result = gg.verify({"groundgate": version}, *_inputs())
    assert result.problems == (
        f"receipt was decided under spec {version}; this groundgate implements 0.13",
    )


def _changelog_releases() -> dict[str, list[str]]:
    """The releases of each spec version, oldest first, from the changelog."""
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    entries = re.findall(
        r"^## ([0-9]+\.[0-9]+\.[0-9]+) [^\n]*\n\n(.*?)(?=^## |\Z)", text, re.M | re.S
    )
    out: dict[str, list[str]] = {}
    for release, body in reversed(entries):
        spec = re.match(r"Spec ([0-9]+\.[0-9]+)\b", body)
        # 0.1.0 is the first release, and its entry names no spec version.
        out.setdefault(spec.group(1) if spec else "0.1", []).append(release)
    return out


def test_the_release_table_agrees_with_the_changelog() -> None:
    by_spec = _changelog_releases()
    unreleased = (REPO / "CHANGELOG.md").read_text(encoding="utf-8").split("\n## ")[1]
    # A new spec version is in "Unreleased" until its first release.
    assert SPEC_VERSION in by_spec or f"\n- Spec {SPEC_VERSION}." in unreleased
    assert SPEC_VERSION not in SPEC_RELEASES
    assert set(SPEC_RELEASES) == set(by_spec) - {SPEC_VERSION}
    for spec, release in SPEC_RELEASES.items():
        published = [r for r in by_spec[spec] if r not in NOT_ON_PYPI]
        assert release == published[-1], spec


def test_the_spec_table_agrees_with_the_code() -> None:
    spec = (REPO / "SPEC.md").read_text(encoding="utf-8")
    section = spec.split("\n### 8.6 A receipt of another spec version\n", 1)[1]
    rows = re.findall(r"^\| ([0-9]+\.[0-9]+) \| [^|]+ \| ([^|]+) \|$", section, re.M)
    assert dict(rows) == {**SPEC_RELEASES, SPEC_VERSION: "this release"}


@pytest.mark.skipif(
    os.environ.get("GROUNDGATE_OLD_RELEASES") != "1" or shutil.which("uvx") is None,
    reason="set GROUNDGATE_OLD_RELEASES=1 to install an old release from PyPI with uvx",
)
def test_the_named_release_verifies_the_receipt() -> None:
    """Rule 3, the other half: the release that the problem names verifies the receipt. The
    test needs the network, so it is off by default."""
    release = release_of("0.11")
    assert release == "0.11.0"
    done = subprocess.run(
        ["uvx", "--from", f"groundgate=={release}", "groundgate", "verify",
         "receipt-0.11.0.json", "document.txt", "schema.json", "candidates.json"],
        cwd=FIXTURE, capture_output=True, text=True, timeout=300, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "receipt verified"
