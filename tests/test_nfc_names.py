"""A reviewer name and a set name must be NFC (store.md section 6, #418)."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from groundgate.calibrate.cli import main as calibrate
from groundgate.cli import main
from groundgate.review.measures import _logs
from groundgate.review.serve import Review
from groundgate.store import FolderStore, key, reviewer_key, set_key
from groundgate.store.splits import split_view

NFC = unicodedata.normalize("NFC", "José")
NFD = unicodedata.normalize("NFD", NFC)
PACKET = "sha256:" + "a" * 64


def test_an_nfc_name_has_a_key() -> None:
    assert NFC != NFD
    assert reviewer_key(NFC) == key("reviewer@1", NFC.encode("utf-8"))
    assert set_key(NFC) == key("set@1", NFC.encode("utf-8"))


def test_an_nfd_name_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="a reviewer name must be NFC"):
        reviewer_key(NFD)
    with pytest.raises(ValueError, match="a set name must be NFC"):
        set_key(NFD)
    with pytest.raises(ValueError, match="a reviewer name must be NFC"):
        Review(FolderStore(tmp_path / "s"), NFD)


def test_a_stored_nfd_name_names_no_log(tmp_path: Path) -> None:
    record = {"set": NFD, "document": PACKET, "split": "development", "sequence": 1}
    with pytest.raises(ValueError, match="names another set"):
        split_view([record], set_key(NFC))
    with FolderStore(tmp_path / "s") as store:
        store.append(("answers", PACKET, reviewer_key(NFC)), {"reviewer": NFD, "task": "x"})
        logs, skipped = _logs(store)
    assert logs == {}
    assert skipped == [f"answer log {PACKET} {reviewer_key(NFC)}: the reviewer is not the log name"]


@pytest.mark.parametrize(
    ("argv", "option"),
    [
        (["review", "serve", "--reviewer", NFD], "--reviewer"),
        (["review", "resolve", PACKET, "--reviewer", NFD], "--reviewer"),
        (["review", "measures", "--set", NFD, "--split", "development"], "--set"),
    ],
)
def test_the_cli_names_the_option(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str], option: str
) -> None:
    assert main([*argv, "--store", str(tmp_path / "s")]) == 2
    err = capsys.readouterr().err
    assert f"groundgate: {option} must be NFC text" in err
    assert "Traceback" not in err


@pytest.mark.parametrize(
    ("argv", "option"),
    [
        (["label", "--store", "s", "--reviewer", NFD], "--reviewer"),
        (["split", "--store", "s", "--set", NFD], "--set"),
    ],
)
def test_calibrate_names_the_option(tmp_path: Path, argv: list[str], option: str) -> None:
    with pytest.raises(SystemExit, match=f"{option} must be NFC text"):
        calibrate([*argv, "--work", str(tmp_path / "w")])
