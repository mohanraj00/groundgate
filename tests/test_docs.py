"""The examples in docs/schema.md and docs/howto/ run, and print what the page shows."""

from __future__ import annotations

import contextlib
import io
import json
import re
from pathlib import Path

import pytest

DOCS = Path(__file__).parent.parent / "docs"
PAGES = [DOCS / "schema.md", *sorted((DOCS / "howto").glob("*.md"))]
FENCE = re.compile(r"^```(\w*)\n(.*?)^```$", re.M | re.S)


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_page_examples(page: Path) -> None:
    """Every python block runs in one namespace per page. A text block right after a python block
    is that block's output. Every json block parses."""
    blocks = FENCE.findall(page.read_text(encoding="utf-8"))
    assert any(lang == "python" for lang, _ in blocks), "the page has no python example"
    namespace: dict[str, object] = {"__name__": f"docs_{page.stem}"}
    printed: str | None = None
    for n, (lang, body) in enumerate(blocks):
        if lang == "python":
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                exec(compile(body, f"{page.name} block {n}", "exec"), namespace)
            printed = out.getvalue()
            continue
        if lang == "text" and printed is not None:
            assert printed == body, f"{page.name} block {n}: the output differs"
        if lang == "json":
            json.loads(body)
        printed = None
