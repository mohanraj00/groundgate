"""Document-family profiles (SPEC §4.10, §5; #639, #648)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate.profile import (
    built_in_kinds,
    built_in_profile,
    check_profile,
    load_profile,
    profile_digest,
)

ROOT = Path(__file__).parent.parent
PROFILES = sorted((ROOT / "conformance" / "profiles").glob("*.json"))
EXAMPLES = ROOT / "examples" / "profiles"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.mark.parametrize("path", PROFILES, ids=lambda p: p.stem)
def test_profile_vector(path: Path) -> None:
    v = _load(path)
    if v["expected"].get("error"):
        with pytest.raises(gg.PacketError):
            gg.admit(v["document"], v.get("schema"), v["candidates"], profile=v["profile"])
        return
    receipt = gg.admit(v["document"], None, v["candidates"], profile=v["profile"]).to_dict()
    for cand, want in zip(v["candidates"], v["expected"]["decisions"], strict=True):
        got = next(
            d for d in receipt["decisions"] if d["candidate_sha256"] == gg.digest("candidate", cand)
        )
        assert (got["outcome"], got["codes"]) == (want["outcome"], want["codes"])
    assert receipt["profile"] == v["expected"]["profile"]
    assert list(receipt).index("profile") == list(receipt).index("packs") + 1
    assert gg.verify(receipt, v["document"], None, v["candidates"], profile=v["profile"]).ok


def test_profile_vectors_cover_each_check() -> None:
    checks = {f"P{n}" for n in range(1, 8)}
    found = {c for p in PROFILES for c in checks if f"({c})" in _load(p)["description"]}
    assert found == checks


def test_profile_decides_as_the_packet_without_it() -> None:
    """A profile changes no decision: the receipt without its profile member is the receipt of
    the same schema and policy (SPEC §4.10)."""
    prof = _load(EXAMPLES / "fee-schedule-v1" / "profile.json")
    text = (EXAMPLES / "fee-schedule-v1" / "document.txt").read_text(encoding="utf-8")
    cands = _load(EXAMPLES / "fee-schedule-v1" / "candidates.json")
    with_profile = gg.admit(text, None, cands, profile=prof).to_dict()
    plain = gg.admit(text, prof["schema"], cands, prof["policy"]).to_dict()
    assert "profile" not in plain
    body = {k: v for k, v in with_profile.items() if k not in ("profile", "receipt_sha256")}
    assert body == {k: v for k, v in plain.items() if k != "receipt_sha256"}
    assert with_profile["receipt_sha256"] != plain["receipt_sha256"]


def test_verify_finds_a_changed_profile() -> None:
    prof = _load(EXAMPLES / "fee-schedule-v1" / "profile.json")
    text = (EXAMPLES / "fee-schedule-v1" / "document.txt").read_text(encoding="utf-8")
    cands = _load(EXAMPLES / "fee-schedule-v1" / "candidates.json")
    receipt = gg.admit(text, None, cands, profile=prof).to_dict()
    other = {**prof, "version": "1.0.1"}
    result = gg.verify(receipt, text, None, cands, profile=other)
    assert not result.ok
    assert "profile differs from the re-derived receipt" in result.problems
    with pytest.raises(gg.PacketError):
        gg.verify(receipt, text, prof["schema"], cands, profile=prof)


def test_a_profile_excludes_schema_policy_and_packs() -> None:
    prof = _load(EXAMPLES / "invoice-v1" / "profile.json")
    for kw in ({"policy": {}}, {"packs": prof["packs"]}):
        with pytest.raises(gg.PacketError, match="in the profile"):
            gg.admit("Total due: $1\n", None, [], profile=prof, **kw)
    with pytest.raises(gg.PacketError):
        gg.admit("Total due: $1\n", None, [])


def test_profile_digest_reads_terms_not_layout() -> None:
    """Member order and a pack's absent defaults do not change the digest. A term does."""
    prof = _load(EXAMPLES / "invoice-v1" / "profile.json")
    same = dict(reversed(list(prof.items())))
    assert profile_digest(same) == profile_digest(prof)
    changed = json.loads(json.dumps(prof))
    changed["packs"][0]["fields"]["total"]["aliases"].append("Amount due")
    assert profile_digest(changed) != profile_digest(prof)
    assert check_profile(prof).entry()["id"] == "invoice"


def test_load_profile(tmp_path: Path) -> None:
    assert load_profile(EXAMPLES / "invoice-v1" / "profile.json")["id"] == "invoice"
    twice = tmp_path / "twice.json"
    twice.write_text('{"id": "a", "id": "b"}', encoding="utf-8")
    with pytest.raises(gg.PacketError, match="twice"):
        load_profile(twice)
    big = tmp_path / "big.json"
    big.write_bytes(b" " * ((4 << 20) + 1))
    with pytest.raises(gg.PacketError, match="P8"):
        load_profile(big)
    deep = tmp_path / "deep.json"
    nested = "[" * 500 + "]" * 500
    deep.write_text(
        f'{{"groundgate_profile": 1, "id": "a", "version": "1.0.0", "description": {nested},'
        ' "schema": {"fields": {}}}',
        encoding="utf-8",
    )
    with pytest.raises(gg.PacketError, match="P8"):
        load_profile(deep)
    with pytest.raises(gg.PacketError, match="P8"):
        gg.admit("x", None, [], profile=json.loads(deep.read_text(encoding="utf-8")))
    with pytest.raises(gg.PacketError, match="not a file"):
        load_profile(tmp_path / "none.json")


def test_built_in_kind_packs_load_as_example_profiles() -> None:
    """#648: each built-in kind pack loads as a profile with no measured route."""
    kinds = built_in_kinds()
    assert [pid for pid, _ in kinds] == [
        "annual-reports",
        "benefit-summaries",
        "component-datasheets",
        "us-10k",
        "us-government-reports",
    ]
    for pid, version in kinds:
        prof = built_in_profile(pid)
        checked = check_profile(prof)
        assert (checked.id, checked.version) == (pid, version)
        assert prof["routes"] == [] and prof["gold_sha256"] is None
        assert "No route is measured" in prof["description"]
        assert set(checked.schema.fields) == set(gg.Schema.from_dict(prof["schema"]).fields)
    with pytest.raises(KeyError):
        built_in_profile("finance")
    with pytest.raises(KeyError):
        built_in_profile("us-10k", "9.0.0")


def test_a_measured_route_needs_its_measure() -> None:
    prof = _load(EXAMPLES / "invoice-v1" / "profile.json")
    (row,) = prof["routes"]
    assert row["status"] == "measured"
    for drop in ("date", "documents", "bound"):
        bad = {**prof, "routes": [{k: v for k, v in row.items() if k != drop}]}
        with pytest.raises(gg.PacketError, match="P6"):
            check_profile(bad)
    with pytest.raises(gg.PacketError, match="P7"):
        check_profile({**prof, "gold_sha256": None})


def test_examples_rebuild(tmp_path: Path) -> None:
    """The two example profiles run through one gate, with other terms and thresholds, and
    build.py rewrites each output with the same bytes."""
    before = {p: p.read_bytes() for p in EXAMPLES.rglob("*") if p.is_file()}
    subprocess.run([sys.executable, str(EXAMPLES / "build.py")], check=True, capture_output=True)
    after = {p: p.read_bytes() for p in EXAMPLES.rglob("*") if p.is_file()}
    assert after == before
    invoice = _load(EXAMPLES / "invoice-v1" / "profile.json")
    fees = _load(EXAMPLES / "fee-schedule-v1" / "profile.json")
    assert invoice["schema"] != fees["schema"] and invoice["policy"] != fees["policy"]
    assert [r["status"] for r in invoice["routes"]] == ["measured"]
    for folder, prof in (("invoice-v1", invoice), ("fee-schedule-v1", fees)):
        receipt = _load(EXAMPLES / folder / "receipt.json")
        assert receipt["profile"]["sha256"] == profile_digest(prof)
