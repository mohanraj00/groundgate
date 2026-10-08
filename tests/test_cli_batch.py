from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate.cli import main

TEXT = "Amount 10.\r\nOther amount 20."
SCHEMA = {"fields": {"amount": {"type": "integer", "multiple": True, "required": True}}}
CANDIDATE = {"id": "a", "field": "amount", "value": 10, "evidence": {"text": "10"}}


def _json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj), encoding="utf-8")


def _batch(tmp: Path, documents: dict[str, Any]) -> list[str]:
    docs, candidates = tmp / "docs", tmp / "candidates"
    docs.mkdir()
    candidates.mkdir()
    for doc, items in documents.items():
        (docs / f"{doc}.txt").write_bytes(TEXT.encode())
        _json(candidates / f"{doc}.json", items)
    _json(tmp / "schema.json", SCHEMA)
    return [
        "admit", "--docs", str(docs), "--candidates", str(candidates),
        "--schema", str(tmp / "schema.json"), "--out", str(tmp / "out"),
    ]  # fmt: skip


def test_batch_receipts_summary_and_totals(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    items = [
        CANDIDATE,
        {**CANDIDATE, "id": "b", "value": 20, "evidence": {"text": "20"}, "confidence": 0.1},
        {**CANDIDATE, "id": "c", "field": "unknown"},
    ]
    args = _batch(tmp_path, {"z": [], "a": items})
    _json(tmp_path / "policy.json", {"min_confidence": 0.5})
    args += ["--policy", str(tmp_path / "policy.json")]
    (tmp_path / "docs" / "ignored.md").write_text("ignored", encoding="utf-8")
    (tmp_path / "docs" / "ignored.TXT").write_text("ignored", encoding="utf-8")
    (tmp_path / "docs" / "nested").mkdir()
    (tmp_path / "docs" / "nested" / "ignored.txt").write_text(TEXT, encoding="utf-8")
    _json(tmp_path / "candidates" / "extra.json", [CANDIDATE])

    assert main(args) == 0
    output = tmp_path / "out"
    assert {path.name for path in output.iterdir()} == {"a.json", "z.json", "summary.json"}
    for doc, candidates in (("a", items), ("z", [])):
        stored = json.loads((output / f"{doc}.json").read_bytes())
        assert (
            stored
            == gg.admit(
                TEXT, SCHEMA, candidates, {"min_confidence": 0.5}, document_id=doc
            ).to_dict()
        )
        assert gg.verify(stored, TEXT, SCHEMA, candidates, {"min_confidence": 0.5}).ok

    summary = json.loads((output / "summary.json").read_bytes())
    assert list(summary["documents"]) == ["a", "z"]
    assert summary == {
        "documents": {
            "a": {
                "outcomes": {"admitted": 1, "needs_verification": 1, "rejected": 1},
                "codes": {"FIELD_UNKNOWN": 1, "LOW_CONFIDENCE": 1},
            },
            "z": {
                "outcomes": {"admitted": 0, "needs_verification": 0, "rejected": 0},
                "codes": {"REQUIRED_FIELD_MISSING": 1},
            },
        },
        "totals": {
            "outcomes": {"admitted": 1, "needs_verification": 1, "rejected": 1},
            "codes": {"FIELD_UNKNOWN": 1, "LOW_CONFIDENCE": 1, "REQUIRED_FIELD_MISSING": 1},
        },
    }
    assert capsys.readouterr().out == (
        "| Outcome | Total |\n|---|---:|\n"
        "| admitted | 1 |\n| needs_verification | 1 |\n| rejected | 1 |\n"
        "\n| Code | Total |\n|---|---:|\n"
        "| FIELD_UNKNOWN | 1 |\n| LOW_CONFIDENCE | 1 |\n| REQUIRED_FIELD_MISSING | 1 |\n"
    )
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    assert main(args) == 0
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before


def test_batch_shared_inputs_and_document_judgments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate = {**CANDIDATE, "evidence": {"source": "reference", "ref": "table", "text": "10"}}
    args = _batch(tmp_path, {"a": [candidate], "b": [candidate]})
    judge = {"id": "test", "digest": "test-1"}
    policy = {"judge": {**judge, "doubt": {"field_match": 0.2}}}
    references = [{"id": "table", "text": "Amount 10.", "source": "https://example.org/table"}]
    judgments = [{"candidate_id": "a", "question": "field_match", "judge": judge, "p": 0.1}]
    _json(tmp_path / "policy.json", policy)
    _json(tmp_path / "references.json", references)
    (tmp_path / "judgments").mkdir()
    _json(tmp_path / "judgments" / "a.json", judgments)
    _json(tmp_path / "judgments" / "b.json", [])
    args += [
        "--policy", str(tmp_path / "policy.json"),
        "--references", str(tmp_path / "references.json"),
        "--judgments", str(tmp_path / "judgments"),
        "--document-source", "https://example.org/doc",
    ]  # fmt: skip
    assert main(args) == 0
    capsys.readouterr()
    for doc, js in (("a", judgments), ("b", [])):
        stored = tmp_path / "out" / f"{doc}.json"
        single = tmp_path / "single.json"
        assert main([
            "admit", str(tmp_path / "docs" / f"{doc}.txt"), str(tmp_path / "schema.json"),
            str(tmp_path / "candidates" / f"{doc}.json"),
            "--document-id", doc, "-o", str(single),
            "--policy", str(tmp_path / "policy.json"),
            "--references", str(tmp_path / "references.json"),
            "--judgments", str(tmp_path / "judgments" / f"{doc}.json"),
            "--document-source", "https://example.org/doc",
        ]) == 0  # fmt: skip
        assert stored.read_bytes() == single.read_bytes()
        assert gg.verify(
            json.loads(stored.read_bytes()), TEXT, SCHEMA, [candidate], policy, js,
            references=references, document_source="https://example.org/doc",
        ).ok  # fmt: skip
    summary = json.loads((tmp_path / "out" / "summary.json").read_bytes())
    assert summary["documents"]["a"]["codes"] == {"MODEL_DOUBT": 1}
    assert summary["documents"]["b"]["codes"] == {}
    assert summary["totals"] == {
        "outcomes": {"admitted": 1, "needs_verification": 1, "rejected": 0},
        "codes": {"MODEL_DOUBT": 1},
    }


def test_batch_counts_every_code_on_every_decision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate = {
        **CANDIDATE,
        "evidence": {"source": "knowledge", "text": "The amount is 10."},
        "confidence": 0.1,
    }
    args = _batch(tmp_path, {"a": [candidate, {**candidate, "id": "b"}], "b": [candidate]})
    _json(tmp_path / "policy.json", {"min_confidence": 0.5, "sources": {"knowledge": "admit"}})
    assert main([*args, "--policy", str(tmp_path / "policy.json")]) == 0
    summary = json.loads((tmp_path / "out" / "summary.json").read_bytes())
    assert summary["documents"]["a"]["codes"] == {"ADMITTED_BY_POLICY": 2, "LOW_CONFIDENCE": 2}
    assert summary["documents"]["b"]["codes"] == {"ADMITTED_BY_POLICY": 1, "LOW_CONFIDENCE": 1}
    assert summary["totals"] == {
        "outcomes": {"admitted": 0, "needs_verification": 3, "rejected": 0},
        "codes": {"ADMITTED_BY_POLICY": 3, "LOW_CONFIDENCE": 3},
    }
    assert "| ADMITTED_BY_POLICY | 3 |" in capsys.readouterr().out


@pytest.mark.parametrize("folder", ["candidates", "judgments"])
@pytest.mark.parametrize("alias", ["direct", "parent", "symlink"])
def test_batch_rejects_output_folder_matching_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], folder: str, alias: str
) -> None:
    args = _batch(tmp_path, {"a": [CANDIDATE], "z": []})
    if folder == "judgments":
        (tmp_path / folder).mkdir()
        for doc in ("a", "z"):
            _json(tmp_path / folder / f"{doc}.json", [])
        args += ["--judgments", str(tmp_path / folder)]
    input_folder = tmp_path / folder
    before = {path.name: path.read_bytes() for path in input_folder.iterdir()}
    output_folder = input_folder
    if alias == "parent":
        output_folder = input_folder / ".." / folder
    elif alias == "symlink":
        output_folder = tmp_path / "out"
        output_folder.symlink_to(input_folder, target_is_directory=True)
    args[args.index("--out") + 1] = str(output_folder)

    assert main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert f"--out must not be the same folder as --{folder}" in output.err
    assert {path.name: path.read_bytes() for path in input_folder.iterdir()} == before


@pytest.mark.parametrize(("first", "second"), [("a", "A"), ("ss", "ß")])
def test_batch_rejects_document_names_equal_under_casefold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], first: str, second: str
) -> None:
    args = _batch(tmp_path, {first: [], "z": []})
    try:
        with (tmp_path / "docs" / f"{second}.txt").open("x", encoding="utf-8") as document:
            document.write(TEXT)
    except FileExistsError:
        pytest.skip("The filesystem cannot hold both document names")
    _json(tmp_path / "candidates" / f"{second}.json", [])

    assert main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert f"{first}.txt" in output.err
    assert f"{second}.txt" in output.err
    assert "document names are equal in any letter case" in output.err
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("folder", ["candidates", "judgments"])
def test_batch_missing_document_input_stops_before_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], folder: str
) -> None:
    args = _batch(tmp_path, {"a": [CANDIDATE], "z": []})
    if folder == "judgments":
        (tmp_path / folder).mkdir()
        _json(tmp_path / folder / "a.json", [])
        args += ["--judgments", str(tmp_path / folder)]
    else:
        (tmp_path / folder / "z.json").unlink()
    assert main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert str(tmp_path / folder / "z.json") in output.err
    assert f"write [] for a document with no {folder}" in output.err
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    ("name", "content", "error"),
    [
        ("docs/z.txt", "Cafe\u0301", "Unicode NFC"),
        ("docs/z.txt", b"\xff", "utf-8"),
        ("candidates/z.json", "{", "Expecting"),
        ("candidates/z.json", '{"a": 1, "a": 2}', "duplicate JSON key"),
        ("candidates/z.json", "[NaN]", "not valid JSON"),
        ("candidates/z.json", "{}", "candidates must be a list"),
    ],
)
def test_batch_invalid_input_identifies_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str, content: str | bytes, error: str
) -> None:
    args = _batch(tmp_path, {"a": [CANDIDATE], "z": []})
    (tmp_path / name).write_bytes(content.encode() if isinstance(content, str) else content)
    assert main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "z.txt:" in output.err
    assert error in output.err
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("option", ["--docs", "--candidates", "--judgments"])
def test_batch_requires_input_folders(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], option: str
) -> None:
    args = _batch(tmp_path, {"a": []})
    path = tmp_path / "schema.json"
    if option == "--judgments":
        args += [option, str(path)]
    else:
        args[args.index(option) + 1] = str(path)
    assert main(args) == 2
    assert "expected a folder" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    ("documents", "error"),
    [
        ({}, "no .txt documents"),
        ({"summary": []}, "summary.json is reserved"),
        ({"Summary": []}, "summary.json is reserved"),
    ],
)
def test_batch_rejects_empty_folder_and_reserved_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], documents: dict[str, Any], error: str
) -> None:
    assert main(_batch(tmp_path, documents)) == 2
    assert error in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("missing", ["--docs", "--candidates", "--schema", "--out"])
def test_batch_requires_all_options(tmp_path: Path, missing: str) -> None:
    args = _batch(tmp_path, {"a": []})
    index = args.index(missing)
    del args[index : index + 2]
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


@pytest.mark.parametrize("empty", ["--docs", "--candidates", "--schema", "--out"])
def test_batch_requires_nonempty_paths(tmp_path: Path, empty: str) -> None:
    args = _batch(tmp_path, {"a": []})
    args[args.index(empty) + 1] = ""
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


@pytest.mark.parametrize("extra", [["doc.txt"], ["-o", "receipt.json"], ["--document-id", "a"]])
def test_batch_rejects_single_document_options(tmp_path: Path, extra: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main([*_batch(tmp_path, {"a": []}), *extra])
    assert exc.value.code == 2


@pytest.mark.parametrize("args", [[], ["doc.txt"], ["doc.txt", "schema.json"]])
def test_single_admit_still_requires_three_inputs(args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["admit", *args])
    assert exc.value.code == 2
