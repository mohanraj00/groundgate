"""The last groundgate-calibrate release only runs groundgate calibrate."""

from __future__ import annotations

from pathlib import Path

import pytest
from groundgate_calibrate import cli


def test_the_wrapper_says_to_change_and_runs_groundgate_calibrate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stop:
        cli.main(["--help"])
    assert stop.value.code == 0
    out, err = capsys.readouterr()
    assert out.startswith("usage: groundgate calibrate ")
    assert err == cli.MOVED + "\n"
    with pytest.raises(SystemExit, match=r"config\.json is not there"):
        cli.main(["report", "--work", str(tmp_path)])
