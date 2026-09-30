"""Packaging rules from CONTRIBUTING: no core dependencies, permissive extras, no subprocesses."""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, metadata, requires
from pathlib import Path

import pytest

import groundgate

REQUIRES = requires("groundgate") or []  # from the installed metadata, so a built wheel is checked
PERMISSIVE = re.compile(r"^(MIT|BSD-[23]-Clause|Apache-2\.0|MPL-2\.0|ISC)$")


def test_version_is_exposed() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", groundgate.__version__)


def test_the_core_has_no_dependencies() -> None:
    assert [r for r in REQUIRES if "extra ==" not in r] == []


@pytest.mark.parametrize("requirement", [r for r in REQUIRES if "extra ==" in r])
def test_extras_are_permissively_licensed(requirement: str) -> None:
    name = re.split(r"[<>=\[ ;]", requirement, maxsplit=1)[0]
    try:
        meta = metadata(name)
    except PackageNotFoundError:
        pytest.skip(f"{name} is not installed here")
    assert PERMISSIVE.match(meta.get("License-Expression") or meta.get("License") or "")


def test_groundgate_never_starts_a_process() -> None:
    for path in Path(groundgate.__file__).parent.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\bsubprocess\b|os\.system|os\.popen|os\.exec", text), path
