"""Synthetic checks for approved terms from calibration event drafts (#547)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from requested.event_terms import event_terms
from requested.run_set import apply_terms, digest

MANIFEST = {
    "schemas": {
        "sbc": {
            "fields": {
                "specialist_copay": {"type": "number", "aliases": ["Specialist visit"]},
                "deductible_family": {"type": "number"},
            }
        }
    }
}
PROFILE = {"id": "sbc", "version": "1", "sha256": "sha256:" + "a" * 64}
ORIGIN = {"system": "approver", "id": "decision-1"}


def term(field: str, alias: str, line: int = 3) -> dict[str, Any]:
    packet = "sha256:" + "b" * 64
    return {
        "draft": "term",
        "field": field,
        "alias": alias,
        "packet": packet,
        "line": line,
        "origin": ORIGIN,
    }


def drafts(*terms: dict[str, Any]) -> bytes:
    share = {"draft": "review_share", "field": "specialist_copay", "key": None, "share": "0.50"}
    body = {
        "groundgate_profile_drafts": 1,
        "profile": PROFILE,
        "events": 2,
        "drafts": [share, *terms],
        "missing_packets": [],
        "unscanned_corrections": 0,
    }
    return json.dumps(body).encode()


def approval(*pairs: tuple[str, str]) -> bytes:
    terms = [{"field": f, "alias": a} for f, a in pairs]
    return json.dumps(
        {"approved_on": "2026-11-27", "approver": "maintainer", "terms": terms}
    ).encode()


def test_only_approved_term_drafts_add_aliases_after_the_approved_terms() -> None:
    raw = drafts(
        term("specialist_copay", "Specialist copay"),
        term("specialist_copay", "Office visit", 7),
        term("deductible_family", "Family deductible"),
    )
    base = {"issue": 547, "fields": {"sbc": {"specialist_copay": {"aliases": ["Specialist"]}}}}
    out = event_terms(
        MANIFEST,
        "sbc",
        raw,
        approval(
            ("specialist_copay", "Specialist copay"), ("deductible_family", "Family deductible")
        ),
        base,
    )
    assert out["fields"]["sbc"]["specialist_copay"]["aliases"] == ["Specialist", "Specialist copay"]
    assert out["fields"]["sbc"]["deductible_family"] == {"aliases": ["Family deductible"]}
    assert out["issue"] == 547 and base["fields"]["sbc"]["specialist_copay"]["aliases"] == [
        "Specialist"
    ]
    events = out["events"]
    assert events["drafts_sha256"] == digest(raw) and events["profile"] == PROFILE
    assert [t["alias"] for t in events["added"]] == ["Specialist copay", "Family deductible"]
    assert events["added"][0]["origin"] == ORIGIN and events["added"][0]["line"] == 3
    assert events["not_added"] == [
        {k: v for k, v in term("specialist_copay", "Office visit", 7).items() if k != "draft"}
    ]
    # The replay adds the terms to the frozen schema.
    schema = apply_terms(MANIFEST["schemas"]["sbc"], out["fields"]["sbc"])
    assert schema["fields"]["specialist_copay"]["aliases"] == [
        "Specialist visit",
        "Specialist",
        "Specialist copay",
    ]


def test_a_known_alias_adds_nothing() -> None:
    raw = drafts(term("specialist_copay", "specialist VISIT"))
    out = event_terms(
        MANIFEST, "sbc", raw, approval(("specialist_copay", "specialist VISIT")), None
    )
    assert out["fields"] == {"sbc": {}}
    assert out["events"]["not_added"][0]["reason"] == "the field already has this alias"


@pytest.mark.parametrize(
    ("raw", "ok", "message"),
    [
        (drafts(term("specialist_copay", "A")), approval(("specialist_copay", "B")), "not a term"),
        (drafts(term("other", "A")), approval(("other", "A")), "does not request"),
        (drafts(term("specialist_copay", "")), approval(), "term draft needs"),
        (drafts(term("specialist_copay", "x" * 65)), approval(), "term draft needs"),
        (b'{"groundgate_profile_drafts": 2}', approval(), "format 1"),
        (drafts(), b'{"approver": "m", "terms": []}', "approved_on"),
        (
            drafts(term("specialist_copay", "A")),
            approval(("specialist_copay", "A"), ("specialist_copay", "A")),
            "two times",
        ),
    ],
)
def test_bad_drafts_or_approvals_are_refused(raw: bytes, ok: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        event_terms(MANIFEST, "sbc", raw, ok, None)


def test_unknown_kind_and_unknown_term_member_are_refused() -> None:
    raw = drafts(term("specialist_copay", "A"))
    with pytest.raises(ValueError, match="unknown kind"):
        event_terms(MANIFEST, "annual", raw, approval(), None)
    base = {"fields": {"sbc": {"specialist_copay": {"note": "x"}}}}
    with pytest.raises(ValueError, match="unknown term member"):
        event_terms(MANIFEST, "sbc", raw, approval(("specialist_copay", "A")), base)


def test_cli_writes_the_terms_file(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps(MANIFEST))
    (tmp_path / "drafts.json").write_bytes(drafts(term("specialist_copay", "Specialist copay")))
    (tmp_path / "approval.json").write_bytes(approval(("specialist_copay", "Specialist copay")))
    args = [
        sys.executable,
        "-m",
        "requested.event_terms",
        "--set",
        str(tmp_path),
        "--kind",
        "sbc",
        "--drafts",
        str(tmp_path / "drafts.json"),
        "--approval",
        str(tmp_path / "approval.json"),
        "--out",
        str(tmp_path / "terms.json"),
    ]
    bench = str(Path(__file__).parents[1])
    done = subprocess.run(args, capture_output=True, text=True, cwd=bench)
    assert done.returncode == 0, done.stderr
    assert "1 added, 0 not added" in done.stderr
    out = json.loads((tmp_path / "terms.json").read_text())
    assert out["fields"]["sbc"]["specialist_copay"]["aliases"] == ["Specialist copay"]
