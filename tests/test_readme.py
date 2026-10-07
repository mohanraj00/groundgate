"""The README quickstart runs and prints what the README says it prints."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

README = Path(__file__).parent.parent / "README.md"


def test_quickstart_prints_what_the_readme_shows() -> None:
    section = README.read_text(encoding="utf-8").split("## Quickstart", 1)[1]
    code = re.search(r"```python\n(.*?)```", section, re.S)
    shown = re.search(r"```text\n(.*?)```", section, re.S)
    assert code and shown
    run = subprocess.run(
        [sys.executable, "-c", code.group(1)], capture_output=True, text=True, check=True
    )
    assert run.stdout == shown.group(1)


def test_guide_key_span_example_prints_what_the_guide_shows() -> None:
    guide = README.parent / "docs" / "guide.md"
    section = guide.read_text(encoding="utf-8").split("#### The key span", 1)[1]
    code = re.search(r"```python\n(.*?)```", section, re.S)
    shown = re.findall(r"```text\n(.*?)```", section, re.S)
    assert code and len(shown) >= 2
    run = subprocess.run(
        [sys.executable, "-c", code.group(1)], capture_output=True, text=True, check=True
    )
    assert run.stdout == shown[1]
