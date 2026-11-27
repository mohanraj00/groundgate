"""The member list of the 1.0 release set (#748)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SET = ROOT / "bench" / "release1"


def test_the_member_list_comes_from_metadata_only() -> None:
    body = json.loads((SET / "members.json").read_text())
    assert body["body_read"] is False
    assert body["download_approved"] is None
    assert not (SET / "manifest.json").exists()
    opinions = body["kinds"]["opinions"]["members"]
    reports = body["kinds"]["reports"]["members"]
    assert len(opinions) == len(reports) == 30
    ids = [m["package"] for m in opinions + reports]
    assert len(set(ids)) == 60
    for m in opinions:
        assert m["court_type"] == "Appellate" and m["granules"] == 1
        assert 6 <= m["pages"] <= 60 and m["date_issued"].startswith("2025")
    assert max(Counter(m["court"] for m in opinions).values()) <= 3
    assert Counter(m["doc_class"] for m in reports) == {"HRPT": 15, "SRPT": 15}
    for m in reports:
        assert m["bill"] and m["committee"] not in ("hsru00", "ssra00")
        assert 8 <= m["pages"] <= 150
    rejected = body["kinds"]["opinions"]["rejected"] + body["kinds"]["reports"]["rejected"]
    assert not {r["package"] for r in rejected} & set(ids)
