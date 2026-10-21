"""The review step (docs/design/review.md): tasks, answers and a resolution, outside ``admit``.

This package has the four formats of §5 and the tasks of §5.2 (``groundgate.review.tasks``).
Each format is a store kind with a version, and each has a JSON Schema in this package. The core
(``admit``, ``verify``) does not import this package.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

__all__ = ["FORMATS", "format_schema"]

FORMATS = ("review-policy@1", "task@1", "answer@1", "resolution@1")


def format_schema(name: str) -> dict[str, Any]:
    """The JSON Schema of the review format ``name``, for example ``"task@1"``."""
    if name not in FORMATS:
        raise ValueError(f"{name!r} is not a review format: use one of {', '.join(FORMATS)}")
    raw = resources.files(__package__).joinpath(f"{name}.schema.json").read_text("utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]
