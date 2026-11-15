"""The built-in pack status and the pack list command (#648)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from groundgate import pack as packs
from groundgate.cli import main

EXPECTED = [
    ("annual-reports", "kind"),
    ("benefit-summaries", "kind"),
    ("component-datasheets", "kind"),
    ("electronics", "vocabulary"),
    ("finance", "vocabulary"),
    ("us-10k", "kind"),
    ("us-government-reports", "kind"),
]


@pytest.mark.parametrize(("pid", "version"), sorted(packs.BUILT_IN_SHA256))
def test_built_in_measured_rows_have_reports(pid: str, version: str) -> None:
    pack = packs.built_in_pack(pid, version)
    assert pack is not None
    root = Path(__file__).resolve().parents[1]
    for row in pack.get("status", []):
        if row["status"] == "measured":
            assert {"documents", "bound", "results"} <= row.keys(), (pid, version, row)
            assert row["documents"] > 0
            assert row["bound"]
            assert row["results"]
            assert (root / row["results"]).is_file(), (pid, version, row)


def test_real_packs_are_examples(capsys: pytest.CaptureFixture[str]) -> None:
    expected = [
        {"id": pid, "version": "1.0.0", "type": kind, "status": "example", "measured": []}
        for pid, kind in EXPECTED
    ]
    assert packs.list_built_in_packs() == expected
    for pid, _ in EXPECTED:
        pack = packs.built_in_pack(pid, "1.0.0")
        assert pack is not None
        assert pack["status"] == []
    assert main(["pack", "list"]) == 0
    assert capsys.readouterr().out == "id\tversion\ttype\tstatus\n" + "".join(
        f"{pid}\t1.0.0\t{kind}\texample\n" for pid, kind in EXPECTED
    )
    assert main(["pack", "list", "--json"]) == 0
    first = capsys.readouterr()
    assert not first.err
    assert json.loads(first.out) == expected
    assert main(["pack", "list", "--json"]) == 0
    assert capsys.readouterr() == first


@pytest.fixture
def measured_pack(tmp_path: Path) -> dict[str, Any]:
    report = tmp_path / "results.json"
    report.write_text('{"documents": 60, "bound": "0.0487"}', encoding="utf-8")
    return {
        "groundgate_pack": 1,
        "type": "kind",
        "id": "sample",
        "version": "1.0.0",
        "status": [
            {"kind": "sample", "field": "amount", "code": "KEY_NOT_CITED", "status": "draft"},
            {
                "kind": "sample",
                "field": "amount",
                "code": "FIELD_CITATION_INVALID",
                "status": "measured",
                "documents": 60,
                "bound": "0.0487",
                "results": str(report),
            },
        ],
    }


def _install_pack(pack: dict[str, Any], root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = root / "packs" / pack["id"] / f"{pack['version']}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(pack), encoding="utf-8")
    monkeypatch.setattr(
        packs, "BUILT_IN_SHA256", {(pack["id"], pack["version"]): packs.pack_digest(pack)}
    )
    monkeypatch.setattr(packs, "_LOADED", {})
    monkeypatch.setattr(packs.resources, "files", lambda name: root)


def test_measured_pack_lists_only_measured_rows(
    measured_pack: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    second = {**measured_pack["status"][1], "field": "total"}
    measured_pack["status"].insert(0, second)
    _install_pack(measured_pack, tmp_path, monkeypatch)
    rows = [measured_pack["status"][2], second]
    assert main(["pack", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        {"id": "sample", "version": "1.0.0", "type": "kind", "status": "measured", "measured": rows}
    ]
    assert main(["pack", "list"]) == 0
    assert (
        capsys.readouterr().out
        == "id\tversion\ttype\tstatus\nsample\t1.0.0\tkind\tmeasured\n"
        + "".join(
            f"  kind=sample field={row['field']} code=FIELD_CITATION_INVALID "
            f"documents=60 bound=0.0487 results={tmp_path / 'results.json'}\n"
            for row in rows
        )
    )


@pytest.mark.parametrize("missing", ["documents", "bound", "results"])
def test_measured_pack_needs_each_report_member(
    missing: str,
    measured_pack: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del measured_pack["status"][1][missing]
    _install_pack(measured_pack, tmp_path, monkeypatch)
    with pytest.raises(packs.PacketError, match="L8"):
        packs.list_built_in_packs()
    assert main(["pack", "list", "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "L8" in captured.err


def test_draft_rows_do_not_make_a_pack_measured(
    measured_pack: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    measured_pack["status"] = measured_pack["status"][:1]
    _install_pack(measured_pack, tmp_path, monkeypatch)
    assert packs.list_built_in_packs()[0] == {
        "id": "sample",
        "version": "1.0.0",
        "type": "kind",
        "status": "example",
        "measured": [],
    }
