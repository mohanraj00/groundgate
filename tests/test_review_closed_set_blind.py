"""A blind answer for a closed set task (SPEC §4.20, docs/design/review.md §7, #696). The
expectations are written by hand."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_review_http import CLOCK, EVERY, ISSUERS, KEY, claim, error, id_of, serving

from groundgate.review import api
from groundgate.review.api import Service
from groundgate.review.blind import write_blind_tasks
from groundgate.review.resolve import write_resolution
from groundgate.review.serve import Refused, Review
from groundgate.review.tasks import write_tasks
from groundgate.store import FolderStore, reviewer_key
from groundgate.store.packets import admit_packet

TEXT = "Billing is monthly. A quarterly plan and a weekly plan exist.\n"
OPTIONS = ["monthly", "quarterly", "annual"]
SCHEMA = {"fields": {"billing": {"type": "string", "options": OPTIONS,
                                 "description": "How often the bill comes."}}}  # fmt: skip
CANDIDATES = [{"id": "a", "field": "billing", "value": "monthly",
               "evidence": [{"text": "Billing is monthly"}]}]  # fmt: skip


def at(words: str) -> dict[str, int]:
    """The span of ``words`` in TEXT, in UTF-8 bytes. TEXT is ASCII."""
    start = TEXT.index(words)
    return {"start": start, "end": start + len(words)}


def stored(root: Path, label: bool = False) -> tuple[str, str]:
    """A store with one packet. The gate admits monthly, so the policy EVERY gives an audit
    task. With ``label``, the packet has the label task of the blind audit only."""
    with FolderStore(root) as store:
        k, receipt = admit_packet(store, TEXT, SCHEMA, CANDIDATES, None, "doc-1", None)
        assert receipt.to_dict()["decisions"][0]["outcome"] == "admitted"
        if label:
            ((tk, _),) = write_blind_tasks(store, k)
        else:
            ((tk, task),) = write_tasks(store, k, EVERY).tasks
            assert (task["mode"], task["item"]) == ("audit", "closed_set")
    return k, tk


def records(root: Path, k: str) -> list[dict[str, Any]]:
    with FolderStore(root) as store:
        return store.read(("answers", k, reviewer_key("ana")))


def status(root: Path, k: str) -> tuple[str, Any]:
    with FolderStore(root) as store:
        resolved = write_resolution(store, k, None, ["ana"])
    assert resolved.resolution is not None
    (slot,) = resolved.resolution["slots"]
    return slot["status"], slot["value"]


@pytest.mark.parametrize("label", [False, True], ids=["audit", "label"])
def test_the_api_serves_a_blind_closed_set_task_with_the_options_only(
    tmp_path: Path, label: bool
) -> None:
    root = tmp_path / "store"
    k, tk = stored(root, label)
    blind = id_of(tk)
    service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
    with serving(api.server(service), {"Authorization": claim()}) as call:
        seen = [call("GET", "/v1/tasks"), call("GET", f"/v1/tasks/{blind}")]
        assert [t["task"] for t in json.loads(seen[0][2])["tasks"]] == [blind]
        assert json.loads(seen[1][2]) == {
            "api": "groundgate-review/1", "task": blind, "document": "doc-1", "mode": "audit",
            "field": "billing", "key": None, "definition": "How often the bill comes.",
            "options": OPTIONS, "answered": None, "body": None, "statements": None,
        }  # fmt: skip
        # a value that is not an option: the gate rejects it with OPTION_INVALID
        weekly = {"task": blind, "verdict": "correct", "span": at("weekly")}
        seen.append(call("POST", "/v1/answers", weekly))
        assert error(seen[-1]) == (409, "correction_rejected")
        assert "OPTION_INVALID" in json.loads(seen[-1][2])["error"]["codes"]
        # an option that the span does not give: the gate rejects it too
        seen.append(call("POST", "/v1/answers", {**weekly, "value": "annual"}))
        assert error(seen[-1]) == (409, "correction_rejected")
        assert records(root, k) == []
        # one option at its place in the text
        seen.append(call("POST", "/v1/answers", {"task": blind, "verdict": "correct",
                                                 "span": at("quarterly")}))  # fmt: skip
        assert seen[-1][0] == 201
        assert json.loads(seen[-1][2])["record"] is None
        seen.append(call("GET", f"/v1/tasks/{blind}"))
        assert json.loads(seen[-1][2])["answered"] == "correct"
    # no response gives the proposed option, its evidence or its choice
    for _, _, text in seen:
        for word in ("Billing is monthly", "choices", "evidence", "shown", "question", '"item"',
                     "Is monthly", '"start"'):  # fmt: skip
            assert word not in text, (word, text)
    (record,) = records(root, k)
    assert (record["verdict"], record["candidate"]["value"]) == ("correct", "quarterly")
    assert record["candidate"]["evidence"] == [at("quarterly")]


def test_a_blind_option_corrects_the_slot_and_the_admitted_option_keeps_it_admitted(
    tmp_path: Path,
) -> None:
    # Rule 4 gives the target of a closed set as its span, as for text. So the admitted option at
    # the admitted span keeps the slot admitted, and the same option at another span corrects
    # the slot to the same value.
    for name, words, value, expected in (
        ("other", "quarterly", None, ("corrected", "quarterly")),
        ("same", "Billing is monthly", "monthly", ("admitted", "monthly")),
        ("moved", "monthly", None, ("corrected", "monthly")),
    ):
        root = tmp_path / name
        k, tk = stored(root)
        with FolderStore(root) as store:
            Review(store, "ana", EVERY, clock=lambda: CLOCK).write(
                {"task": tk, "verdict": "correct", "decision": None, "codes_kept": [],
                 "reason_seen": False, "keys": 0, "ms": 0, "value": value, **at(words)}
            )  # fmt: skip
        assert status(root, k) == expected, name


def test_the_page_checks_a_blind_option_and_a_review_task_still_takes_no_correction(
    tmp_path: Path,
) -> None:
    root = tmp_path / "store"
    _, tk = stored(root)
    with FolderStore(root) as store:
        review = Review(store, "ana", EVERY, clock=lambda: CLOCK)
        view = review.view(tk)
        assert (view["mode"], view["options"]) == ("audit", OPTIONS)
        found = review.check({"task": tk, "verdict": "correct", **at("quarterly")})
        assert found["outcome"] == "admitted" and found["shown"] == "quarterly"
        found = review.check({"task": tk, "verdict": "correct", **at("weekly")})
        assert found["outcome"] == "rejected"
        assert "OPTION_INVALID" in [c["code"] for c in found["codes"]]
        with pytest.raises(Refused, match="audit task takes only"):
            review.write({"task": tk, "verdict": "adjust_span", "decision": None,
                          "codes_kept": [], "reason_seen": False, "keys": 0, "ms": 0,
                          **at("monthly")})  # fmt: skip
    # a closed set review task: its choices give the options that the gate found
    other = tmp_path / "review"
    cands = [*CANDIDATES, {"id": "b", "field": "billing", "value": "quarterly",
                           "evidence": [{"text": "A quarterly plan"}]}]  # fmt: skip
    with FolderStore(other) as store:
        k, _ = admit_packet(store, TEXT, SCHEMA, cands, None, "doc-1", None)
        ((rk, task),) = write_tasks(store, k, EVERY).tasks
        assert (task["mode"], task["item"]) == ("review", "closed_set")
        review = Review(store, "ana", EVERY, clock=lambda: CLOCK)
        assert review.view(rk)["mode"] == "review"
        with pytest.raises(Refused, match="takes no correction"):
            review.check({"task": rk, "verdict": "correct", **at("quarterly")})
        with pytest.raises(Refused, match="closed_set task takes only confirm"):
            review.write({"task": rk, "verdict": "correct", "decision": None, "codes_kept": [],
                          "reason_seen": False, "keys": 0, "ms": 0, **at("quarterly")})  # fmt: skip
