"""`verify` finds the packs of a receipt (#338, docs/design/packs.md §11)."""

from __future__ import annotations

import json
import os
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate import pack as pack_module
from groundgate.cli import main
from groundgate.pack import BASE_ID, BUILT_IN_SHA256, MAX_FILE, RETIRED, pack_digest

DOC = "The grant is 5 lac. The loss was $7."
LAC = {
    "groundgate_pack": 1,
    "type": "vocabulary",
    "id": "lac-x-test",
    "version": "1.0.0",
    "scale": {"words": {"lac": 5}},
}
SCHEMA = {
    "packs": [{"id": "lac-x-test", "version": "1.0.0"}, {"id": "finance", "version": "1.0.0"}],
    "fields": {"grant": {"type": "integer"}, "loss": {"type": "integer", "unit": "USD"}},
}
CANDS = [
    {"id": "a", "field": "grant", "value": "5", "evidence": {"text": "5 lac"}},
    {"id": "b", "field": "loss", "value": "-7", "unit": "USD", "evidence": {"text": "loss was $7"}},
]
SHA = pack_digest(LAC)


def receipt() -> dict[str, Any]:
    return gg.admit(DOC, SCHEMA, CANDS, packs=[LAC]).to_dict()


def write(folder: Path, name: str, obj: object) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / name
    f.write_text(json.dumps(obj), encoding="utf-8")
    return f


def resealed(r: dict[str, Any]) -> dict[str, Any]:
    """The receipt with a correct receipt_sha256, so that only the pack check can fail."""
    body = {k: v for k, v in r.items() if k != "receipt_sha256"}
    return {**body, "receipt_sha256": gg.digest("receipt", body)}


def test_verify_takes_a_pack_from_the_folder_by_its_digest(tmp_path: Path) -> None:
    r = receipt()
    write(tmp_path / "packs", "any-name.json", LAC)
    assert gg.verify(r, DOC, SCHEMA, CANDS, pack_dir=tmp_path / "packs") == gg.Verification(
        True, ()
    )
    assert gg.verify(r, DOC, SCHEMA, CANDS, packs=[LAC]).ok  # a given pack, as before


def test_a_missing_pack_is_one_problem_that_names_id_version_and_digest(tmp_path: Path) -> None:
    r = receipt()
    want = f"pack 'lac-x-test' 1.0.0 with the digest {SHA} is not built in or given"
    assert gg.verify(r, DOC, SCHEMA, CANDS).problems == (want,)
    (tmp_path / "packs").mkdir()
    check = gg.verify(r, DOC, SCHEMA, CANDS, pack_dir=tmp_path / "packs")
    assert check.problems == (
        f"pack 'lac-x-test' 1.0.0 with the digest {SHA} is not built in, not given and not in "
        "the pack folder",
    )


def test_a_pack_with_another_digest_is_one_problem_with_both_digests(tmp_path: Path) -> None:
    r = receipt()
    other = {**LAC, "description": "another copy"}
    check = gg.verify(r, DOC, SCHEMA, CANDS, packs=[other])
    assert check.problems == (
        f"pack 'lac-x-test' 1.0.0: the receipt names the digest {SHA}, and the given pack has "
        f"the digest {pack_digest(other)}",
    )
    write(tmp_path / "packs", "lac.json", other)
    check = gg.verify(r, DOC, SCHEMA, CANDS, pack_dir=tmp_path / "packs")
    assert check.problems == (
        f"pack 'lac-x-test' 1.0.0: the receipt names the digest {SHA}, and the pack folder has "
        f"only the digest {pack_digest(other)}",
    )


def test_a_built_in_pack_with_another_digest_stops_verify() -> None:
    r = receipt()
    finance = BUILT_IN_SHA256[("finance", "1.0.0")]
    for e in r["packs"]:
        if e["id"] == "finance":
            e["sha256"] = "sha256:" + "0" * 64
    check = gg.verify(resealed(r), DOC, SCHEMA, CANDS, packs=[LAC])
    assert check.problems == (
        f"pack 'finance' 1.0.0: the receipt names the digest sha256:{'0' * 64}, and the built-in "
        f"pack has the digest {finance}",
    )


def test_the_receipt_digest_problem_stays_with_a_pack_problem() -> None:
    r = receipt()
    r["packs"][1]["version"] = "9.0.0"
    check = gg.verify(r, DOC, SCHEMA, CANDS, packs=[LAC])
    assert check.problems[0] == "receipt_sha256 does not match the receipt body"
    assert check.problems[1].startswith("pack 'lac-x-test' 9.0.0 with the digest")


@pytest.mark.parametrize(
    "entry",
    [
        {"id": "../lac-x-test", "type": "vocabulary", "version": "1.0.0", "sha256": SHA},
        {"id": "/etc/passwd", "type": "vocabulary", "version": "1.0.0", "sha256": SHA},
        {"id": "lac-x-test", "type": "vocabulary", "version": "../1", "sha256": SHA},
        {"id": "lac-x-test", "type": "vocabulary", "version": "1.0.0", "sha256": "sha256:../x"},
        {"id": "lac-x-test", "type": "other", "version": "1.0.0", "sha256": SHA},
        {"id": "lac-x-test", "version": "1.0.0", "sha256": SHA},
        "lac-x-test",
    ],
)
def test_a_malformed_receipt_entry_is_one_problem(tmp_path: Path, entry: object) -> None:
    write(tmp_path / "packs", "lac.json", LAC)
    r = receipt()
    r["packs"][1] = entry
    check = gg.verify(resealed(r), DOC, SCHEMA, CANDS, pack_dir=tmp_path / "packs")
    assert check.problems == ("the receipt member packs is not a list of pack entries",)


def test_verify_does_not_follow_a_link_out_of_the_folder(tmp_path: Path) -> None:
    outside = write(tmp_path / "outside", "lac.json", LAC)
    folder = tmp_path / "packs"
    folder.mkdir()
    (folder / "lac.json").symlink_to(outside)
    (folder / "up.json").symlink_to("../outside/lac.json")
    check = gg.verify(receipt(), DOC, SCHEMA, CANDS, pack_dir=folder)
    assert not check.ok
    assert check.problems[-1] == (
        "the pack folder has 2 files that are not valid packs: 'lac.json' is a link, and verify "
        "does not follow links; 'up.json' is a link, and verify does not follow links"
    )


def test_verify_reads_only_regular_json_files_directly_in_the_folder(tmp_path: Path) -> None:
    folder = tmp_path / "packs"
    write(folder / "sub.json", "lac.json", LAC)  # a folder with a .json name, and a file in it
    write(folder, "lac.txt", LAC)  # not a .json name
    os.mkfifo(folder / "pipe.json")  # a reader that waits for a writer would hang here
    check = gg.verify(receipt(), DOC, SCHEMA, CANDS, pack_dir=folder)
    assert not check.ok
    assert check.problems[-1] == (
        "the pack folder has 2 files that are not valid packs: 'pipe.json' is not a regular "
        "file; 'sub.json' is not a regular file"
    )


def test_a_big_or_broken_file_in_the_folder_is_never_used(tmp_path: Path) -> None:
    folder = tmp_path / "packs"
    folder.mkdir()
    (folder / "big.json").write_bytes(b" " * (MAX_FILE + 1))
    (folder / "bad.json").write_bytes(b"{")
    write(folder, "built.json", {**LAC, "id": "finance"})  # a given pack has no built-in id
    write(folder, "lac.json", LAC)
    assert gg.verify(receipt(), DOC, SCHEMA, CANDS, pack_dir=folder).ok  # the others are skipped
    (folder / "lac.json").unlink()
    problems = gg.verify(receipt(), DOC, SCHEMA, CANDS, pack_dir=folder).problems
    assert problems[-1].startswith("the pack folder has 3 files that are not valid packs: ")
    assert f"'big.json' is more than {MAX_FILE} bytes (L4)" in problems[-1]
    assert "pack file 'bad.json' is not JSON" in problems[-1]
    assert "has the id of a built-in pack (L7)" in problems[-1]


def test_a_pack_folder_with_too_many_files_or_no_folder_is_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "packs"
    for n in range(3):
        write(folder, f"{n}.json", {})
    monkeypatch.setattr(pack_module, "MAX_DIR_FILES", 2)
    with pytest.raises(gg.PacketError, match=r"more than 2 \.json files"):
        gg.verify(receipt(), DOC, SCHEMA, CANDS, pack_dir=folder)
    with pytest.raises(gg.PacketError, match=r"Not a directory|is not a folder"):
        gg.verify(receipt(), DOC, SCHEMA, CANDS, pack_dir=folder / "0.json")
    with pytest.raises(gg.PacketError, match="cannot be opened"):
        gg.verify(receipt(), DOC, SCHEMA, CANDS, pack_dir=tmp_path / "none")


def test_the_folder_is_read_only_when_a_pack_is_not_found(tmp_path: Path) -> None:
    assert gg.verify(receipt(), DOC, SCHEMA, CANDS, packs=[LAC], pack_dir=tmp_path / "none").ok


def test_a_schema_object_takes_no_pack_folder(tmp_path: Path) -> None:
    schema = gg.Schema.from_dict(SCHEMA, [LAC])
    assert gg.verify(receipt(), DOC, schema, CANDS).ok
    with pytest.raises(gg.PacketError, match="as a dict"):
        gg.verify(receipt(), DOC, schema, CANDS, pack_dir=tmp_path)


def test_admit_refuses_a_retired_version_and_verify_still_reads_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = receipt()
    monkeypatch.setattr(pack_module, "RETIRED", frozenset({("finance", "1.0.0")}))
    with pytest.raises(gg.PacketError, match=r"'finance' 1\.0\.0 is a retired built-in version"):
        gg.admit(DOC, SCHEMA, CANDS, packs=[LAC])
    with pytest.raises(gg.PacketError, match="retired"):  # also when a kind pack needs it
        gg.admit(DOC, {"packs": [{"id": "us-10k", "version": "1.0.0"}], "fields": {}}, [])
    assert gg.verify(r, DOC, SCHEMA, CANDS, packs=[LAC]).ok


def test_each_built_in_pack_file_is_in_the_list_of_released_digests() -> None:
    """A changed released file, or a new file that the list does not name, fails CI."""
    root = resources.files("groundgate") / "packs"
    files = {
        (d.name, f.name.removesuffix(".json"))
        for d in root.iterdir()
        if d.is_dir()
        for f in d.iterdir()
        if f.name.endswith(".json")
    }
    assert files == {(BASE_ID, pack_module.BASE_VERSION), *BUILT_IN_SHA256}
    for (pid, version), sha in BUILT_IN_SHA256.items():
        raw = json.loads((root / pid / f"{version}.json").read_text(encoding="utf-8"))
        assert pack_digest(raw) == sha, (pid, version)
    assert set(BUILT_IN_SHA256) >= RETIRED  # a retired version stays in the list and the wheel


def test_the_cli_takes_a_pack_folder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = write(tmp_path, "doc.txt", "")
    doc.write_text(DOC, encoding="utf-8")
    schema, cands = write(tmp_path, "s.json", SCHEMA), write(tmp_path, "c.json", CANDS)
    stored = write(tmp_path, "r.json", receipt())
    args = ["verify", str(stored), str(doc), str(schema), str(cands)]
    assert main(args) == 1
    assert "is not built in or given" in capsys.readouterr().err
    write(tmp_path / "packs", f"lac-x-test-1.0.0-{SHA[7:19]}.json", LAC)
    assert main([*args, "--pack-dir", str(tmp_path / "packs")]) == 0
    assert capsys.readouterr().out == "receipt verified\n"
