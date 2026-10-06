"""Judges: a model that answers typed questions. A judge takes a state and questions, and gives
the answers. A hosted judge sends document text out of the machine, so it runs only when the
user names it, and its key comes from the environment only."""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from typing import Any

Ask = Callable[[str, dict[str, Any]], dict[str, Any]]

JEV_MODEL = "jev-1.13.0"
JEV_URL = "https://api.typesafe.ai/v1/systemone"


def jev() -> tuple[dict[str, str], Ask]:
    """The hosted Jev API. The key is TYPESAFE_API_KEY."""
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise SystemExit("set TYPESAFE_API_KEY")

    def ask(st: str, qs: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"state": st, "model": JEV_MODEL, "questions": qs}).encode()
        req = urllib.request.Request(
            JEV_URL,
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.load(r)
        if res["model"] != JEV_MODEL:
            raise SystemExit(f"answered by {res['model']}, not {JEV_MODEL}")
        return dict(res["answers"])

    return {"judge": "jev", "model": JEV_MODEL}, ask


JUDGES: dict[str, Callable[[], tuple[dict[str, str], Ask]]] = {"jev": jev}
