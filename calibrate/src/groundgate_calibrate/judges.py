"""Judges: models that answer typed questions about a value (hybrid design §7).

A judge has an ``id``, a ``digest`` that names one model version, and ``ask(state, questions)``,
which returns the answers in the typed-decision format: ``{"choice", "confidence"}`` for a choice
question and ``{"noul"}`` for a noul question. A package adds a judge with an entry point in the
group ``groundgate.judges``; the entry point loads a function with no arguments that returns the
judge. A hosted judge sends document text out of the machine, so it runs only when the user names
it, and its key comes from the environment only.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from importlib.metadata import entry_points
from typing import Any, Protocol

GROUP = "groundgate.judges"


class Judge(Protocol):
    id: str
    digest: str

    def ask(self, state: str, questions: dict[str, Any]) -> dict[str, Any]: ...


class Jev:
    """The hosted Jev API. The key is TYPESAFE_API_KEY."""

    id = "jev"
    digest = "jev-1.13.0"
    url = "https://api.typesafe.ai/v1/systemone"

    def __init__(self) -> None:
        key = os.environ.get("TYPESAFE_API_KEY")
        if not key:
            raise SystemExit("set TYPESAFE_API_KEY")
        self._key = key

    def ask(self, state: str, questions: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"state": state, "model": self.digest, "questions": questions}).encode()
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.load(r)
        if res["model"] != self.digest:
            raise SystemExit(f"answered by {res['model']}, not {self.digest}")
        return dict(res["answers"])


BUILT_IN: dict[str, Callable[[], Judge]] = {"jev": Jev}


def available() -> dict[str, Callable[[], Judge]]:
    """The built-in judges and those that installed packages register. A plug-in cannot take
    the name of a built-in judge or of another plug-in."""
    out = dict(BUILT_IN)
    for ep in entry_points(group=GROUP):
        if ep.name in out:
            raise SystemExit(f"two judges are named {ep.name!r}; uninstall one of them")
        out[ep.name] = ep.load()
    return out


def load(name: str) -> Judge:
    judges = available()
    if name not in judges:
        raise SystemExit(f"no judge {name!r}; installed: {', '.join(sorted(judges))}")
    judge = judges[name]()
    for attr in ("id", "digest"):
        if not isinstance(getattr(judge, attr, None), str) or not getattr(judge, attr).strip():
            raise SystemExit(f"judge {name!r} has no {attr}")
    if judge.id != name:
        # a policy names the judge by its id, and production loads it by that name
        raise SystemExit(f"judge {name!r} says its id is {judge.id!r}; they must be equal")
    return judge
