"""Packaging rules from CONTRIBUTING: no core dependencies, permissive extras, and one module
that starts a process: the OCR reader, which runs the tesseract program (#7)."""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, metadata, requires
from pathlib import Path

import pytest

import groundgate

REQUIRES = requires("groundgate") or []  # from the installed metadata, so a built wheel is checked
PERMISSIVE = re.compile(r"^(MIT|BSD-[23]-Clause|Apache-2\.0|MPL-2\.0|ISC)$")
# A package whose metadata is not one license name: the metadata text, and the licenses I read.
# A new text fails the test, so a change of license gets a new check.
LICENSES = {
    "pypdfium2": ("BSD-3-Clause, Apache-2.0, dependency licenses", ("BSD-3-Clause", "Apache-2.0"))
}
PROCESS = Path("read") / "ocr.py"


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
    found = meta.get("License-Expression") or meta.get("License") or ""
    if name in LICENSES:
        text, licenses = LICENSES[name]
        assert found == text
        assert all(PERMISSIVE.match(lic) for lic in licenses)
    else:
        assert PERMISSIVE.match(found)


def test_groundgate_starts_a_process_only_in_the_ocr_reader() -> None:
    root = Path(groundgate.__file__).parent
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        found = re.search(r"\bsubprocess\b|os\.system|os\.popen|os\.exec|os\.spawn", text)
        assert path.relative_to(root) == PROCESS or not found, path
    text = (root / PROCESS).read_text(encoding="utf-8")
    assert not re.search(r"os\.system|os\.popen|os\.exec|os\.spawn|shell=True", text)
    assert "subprocess.run(" not in text and "subprocess.call(" not in text
    assert text.count("subprocess.Popen(") == 1  # in _run: tesseract --version, and one page
