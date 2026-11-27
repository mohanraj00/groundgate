"""groundgate calibrate promotion (#747): the items, the summary and the refusals."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from groundgate.calibrate import promotion
from groundgate.calibrate.cli import main

CASE = Path(__file__).parent / "vectors" / "calibrate" / "two-routes"


def _measure(out: Path, target: str) -> None:
    main([
        "measure", "--profile", str(CASE / "profile.json"), "--gold", str(CASE / "gold"),
        "--split", str(CASE / "split.json"), "--out", str(out),
        "--target", target, "--date", "2026-11-13",
    ])  # fmt: skip


def _promote(folder: Path, out: Path, *more: str) -> None:
    main([
        "promotion", "--report", str(folder / "report.json"),
        "--profile", str(folder / "profile.json"), "--collection", "extraction-profiles",
        "--out", str(out), *more,
    ])  # fmt: skip


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    ("bound", "bp"),
    [("0", 0), ("0.02", 200), ("0.0605", 605), ("0.050001", 501), ("0.00000001", 1),
     ("0.99999", 10000), ("1", 10000), ("1.000", 10000)],
)  # fmt: skip
def test_a_bound_rounds_up_to_basis_points(bound: str, bp: int) -> None:
    assert promotion.bound_bp(bound) == bp


@pytest.mark.parametrize("bound", ["1.0001", "2", ".5", "0.", "-0.1", "1e-2", "0,5", " 0.5", 0.5])
def test_a_bound_that_is_not_valid(bound: Any) -> None:
    with pytest.raises(promotion.PromotionError):
        promotion.bound_bp(bound)


def test_the_promotion_of_a_measure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The step reads the output of ``calibrate measure``. With the target 1, each route of
    the vector with an admitted value is measured, and the operating point clears 3 values of
    ``rate`` with 1 error. The expected bounds are the 95% upper bounds of 0 errors in 2
    values (0.7764), of 1 error in 3 (0.8646) and of 1 error in 5 (0.6574)."""
    folder, out = tmp_path / "measure", tmp_path / "out"
    _measure(folder, "1")
    capsys.readouterr()
    _promote(folder, out)
    assert capsys.readouterr().out == (
        f"wrote {out}/manifest.json and summary.json: 3 routes, "
        "the largest bound is 8646 basis points\n"
    )
    report, profile = (folder / "report.json").read_bytes(), (folder / "profile.json").read_bytes()
    gold = json.loads(report)["gold_sha256"]
    # the exact text: the candidate reference of the approver is its SHA-256
    item = '{{"item_id":"{}","digest":"{}","size":{},"media_type":"application/json"}}'
    assert (out / "manifest.json").read_text("utf-8") == (
        '{"format":"entelos.content/1","collection":"extraction-profiles",'
        '"partition":"rates-test","base":"","items":['
        + item.format("measure", _sha(report), len(report))
        + ","
        + item.format("profile", _sha(profile), len(profile))
        + '],"metadata":{"profile_id":"rates-test","profile_version":"1.0.1"}}'
    )
    assert json.loads((out / "summary.json").read_text("utf-8")) == {
        "format": "entelos.measure/1",
        "profile_digest": _sha(profile),
        "measure_digest": _sha(report),
        "gold_digest": gold,
        "labels_digest": gold,  # no audit: the gold set digest covers each label
        # total/cleared admits no value, so it has no row
        "routes": [
            {"field": "rate", "route": "checked", "bound_bp": 7764},
            {"field": "rate", "route": "cleared", "bound_bp": 8646},
            {"field": "total", "route": "checked", "bound_bp": 6574},
        ],
    }
    with pytest.raises(SystemExit, match="has a manifest or a summary already"):
        _promote(folder, out)  # never write over a file

    base = "sha256:" + "b" * 64
    _promote(folder, tmp_path / "next", "--base", base)
    assert json.loads((tmp_path / "next" / "manifest.json").read_text("utf-8"))["base"] == base


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [("--collection", "", "the collection must be"), ("--collection", "a/b", "the collection"),
     ("--collection", "c" * 129, "the collection"), ("--base", "sha256:12", "the base must be"),
     ("--base", "sha256:" + "B" * 64, "the base must be")],
)  # fmt: skip
def test_the_manifest_names_are_checked(
    tmp_path: Path, option: str, value: str, message: str
) -> None:
    folder = tmp_path / "measure"
    _measure(folder, "1")
    with pytest.raises(SystemExit, match=message):
        _promote(folder, tmp_path / "out", option, value)
    assert not (tmp_path / "out").exists()


def _edit(folder: Path, change: Any) -> None:
    report = json.loads((folder / "report.json").read_text("utf-8"))
    change(report)
    (folder / "report.json").write_text(json.dumps(report), "utf-8")


def test_a_route_that_is_not_measured_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / "measure"
    _measure(folder, "0.7")  # the target of the vector: rate/checked is a draft at 0.7764
    with pytest.raises(
        SystemExit, match="checked of the field 'rate' is not measured: its status is 'draft'"
    ):
        _promote(folder, tmp_path / "out")

    folder = tmp_path / "unscored"
    _measure(folder, "1")
    _edit(folder, lambda r: r["fields"]["total"]["routes"]["cleared"].update(unscored=2))
    with pytest.raises(
        SystemExit, match="cleared of the field 'total' is not measured: no label covers 2"
    ):
        _promote(folder, tmp_path / "refused")


def test_the_labels_digest_names_the_audit(tmp_path: Path) -> None:
    folder = tmp_path / "measure"
    _measure(folder, "1")
    audit = {"audit_sha256": "sha256:" + "a" * 64, "since": "2026-11-01"}
    _edit(folder, lambda r: r.update(audit=audit))
    _promote(folder, tmp_path / "out")
    summary = json.loads((tmp_path / "out" / "summary.json").read_text("utf-8"))
    assert summary["labels_digest"] == "sha256:" + "a" * 64
    assert (
        summary["gold_digest"]
        == json.loads((CASE / "expected-report.json").read_text())["gold_sha256"]
    )

    _edit(folder, lambda r: r.update(audit={"since": None}))
    with pytest.raises(SystemExit, match="the audit of the report has no digest audit_sha256"):
        _promote(folder, tmp_path / "none")


def test_the_profile_and_the_report_must_agree(tmp_path: Path) -> None:
    folder = tmp_path / "measure"
    _measure(folder, "1")
    draft = (folder / "profile.json").read_bytes()

    # the input profile of the measure is not the profile that the report qualifies
    (folder / "profile.json").write_bytes((CASE / "profile.json").read_bytes())
    with pytest.raises(SystemExit, match="not the draft profile of the report"):
        _promote(folder, tmp_path / "refused")
    (folder / "profile.json").write_bytes(draft)

    # a report with a lower bound than the route table of the profile
    _edit(folder, lambda r: r["fields"]["total"]["routes"]["checked"].update(bound="0.01"))
    with pytest.raises(
        SystemExit, match="checked of the field 'total' of the profile does not agree"
    ):
        _promote(folder, tmp_path / "refused")

    # a route with an admitted value that the route table has not
    _edit(folder, lambda r: r["fields"]["total"]["routes"]["cleared"].update(
        admitted=1, status="measured", bound="0.01"))  # fmt: skip
    with pytest.raises(SystemExit, match="route table of the profile does not agree"):
        _promote(folder, tmp_path / "refused")

    for text in ("[]", '{"groundgate_calibration_report": 2}', '{"a": 1, "a": 2}', "\xff"):
        (folder / "report.json").write_bytes(text.encode("latin-1"))
        with pytest.raises(SystemExit, match="calibrate promotion: the report is not"):
            _promote(folder, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()  # a refusal writes nothing
