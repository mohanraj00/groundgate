"""The format list of SPEC §8.5 names each format name of the code, and no other name (#718)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from groundgate.canonical import SPEC_VERSION

REPO = Path(__file__).parent.parent
SPEC = (REPO / "SPEC.md").read_text(encoding="utf-8")
AT = re.compile(r"[a-z][a-z0-9-]*@[0-9]+")  # facts@2
PREFIX = re.compile(r"groundgate(?:-[a-z]+)+/[0-9]+")  # groundgate-pack/1
MEMBER = re.compile(r"groundgate_[a-z_]+")  # groundgate_pack
# Strings of the code that have the form of a format name and name no format.
NOT_FORMATS = {
    "groundgate_verifying": "the name of a context variable in pack.py",
    "run@3": "a kind with a version that the store contract vectors refuse",
    "text@0": "a kind with a version that the store contract vectors refuse",
    "profile@1": "the store contract vectors use it to make a key for an events log",
}


def _code_names() -> set[str]:
    """Each string of ``src/groundgate`` with the form of a format name. A docstring does not
    count. A name that the code makes from parts is not found: ``run@N`` and the kind of a log
    entry, ``<word>-entry@1``. SPEC §8.5 names both in the text of a row."""
    found: set[str] = set()
    for path in sorted((REPO / "src" / "groundgate").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        scopes = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, scopes) and node.body and isinstance(node.body[0], ast.Expr)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or id(node) in docstrings:
                continue
            value = node.value.decode("latin-1") if isinstance(node.value, bytes) else node.value
            if not isinstance(value, str):
                continue
            if AT.fullmatch(value) or MEMBER.fullmatch(value):
                found.add(value)
            found.update(PREFIX.findall(value))
    return found


def _formats_section() -> str:
    """The text of SPEC §8.5, up to the next heading."""
    rest = SPEC.split("\n### 8.5 The formats\n", 1)[1]
    return re.split(r"^#{2,3} ", rest, maxsplit=1, flags=re.M)[0]


def _listed_names() -> set[str]:
    """Each name in the first column of the tables of SPEC §8.5."""
    section = _formats_section()
    names: set[str] = set()
    for line in section.splitlines():
        if line.startswith("| `"):
            names.update(re.findall(r"`([^`]+)`", line.split("|")[1]))
    return names


def test_the_format_list_names_each_format_of_the_code() -> None:
    code = _code_names()
    assert set(NOT_FORMATS) <= code, "remove a name that the code no longer has"
    listed = _listed_names()
    assert code - set(NOT_FORMATS) - listed == set(), "add each name to SPEC §8.5"
    assert listed - code == set(), "SPEC §8.5 lists a name that the code does not have"


def test_the_extraction_finds_each_form_of_a_format_name() -> None:
    code = _code_names()
    assert {"facts@2", "groundgate-pack/1", "groundgate_pack", "groundgate-object/1"} <= code


def test_the_version_column_agrees_with_the_name() -> None:
    """A name with ``@N`` or ``/N`` holds its version, and its row gives the same number."""
    for line in _formats_section().splitlines():
        if not line.startswith("| `"):
            continue
        names, version = (cell.strip() for cell in line.split("|")[1:3])
        for name in re.findall(r"`([^`]+)`", names):
            if "@" in name or "/" in name:
                assert re.split(r"[@/]", name)[-1] == version.strip("`"), name


def test_the_spec_names_its_own_version() -> None:
    assert f"this document is version {SPEC_VERSION}." in SPEC
    assert f"the prefix `groundgate/{SPEC_VERSION}:`" in SPEC
    runner = (REPO / "src" / "groundgate" / "extract" / "runner.py").read_text(encoding="utf-8")
    number = re.search(r'_VERSION = "groundgate-run/([0-9]+)"', runner)
    assert number is not None
    assert f"The store kind of the record is `run@{number.group(1)}`." in SPEC
