"""groundgate schema check: settings that make a check fail every time, or pass for the wrong key
or field (#168)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from groundgate.cli import main


def check(tmp_path: Path, schema: Any, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(schema), encoding="utf-8")
    code = main(["schema", "check", str(path)])
    return code, capsys.readouterr().out


def test_clean_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = {
        "fields": {
            "net_sales": {"type": "integer", "unit": "USD", "keys": ["2025"], "aliases": ["sales"]},
            "fee": {"minimum": "5", "maximum": "5"},
            "name": {"type": "string"},
        }
    }
    assert check(tmp_path, schema, capsys) == (0, "")


def test_unit_without_aliases(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = {"fields": {"fee": {"unit": "USD"}}}
    assert check(tmp_path, schema, capsys) == (
        1,
        "field 'fee' has a unit and no aliases: a unit item never passes\n",
    )


def test_keys_without_aliases(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = {"fields": {"dose": {"unit": "mg", "keys": ["adults", "children"]}}}
    assert check(tmp_path, schema, capsys) == (
        1,
        "field 'dose' has a unit and no aliases: a unit item never passes\n"
        "field 'dose' has keys and no aliases: a key item never puts the key at the value\n",
    )


def test_key_in_an_alias(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = {"fields": {"sales": {"keys": ["Product", "service"], "aliases": ["product"]}}}
    assert check(tmp_path, schema, capsys) == (
        1,
        "field 'sales' has the key 'Product' in an alias: "
        "each mention of the field puts that key at the value\n",
    )
    inside = {"fields": {"sales": {"keys": ["net", "gross"], "aliases": ["Net Sales", "net"]}}}
    assert check(tmp_path, inside, capsys) == (
        1,
        "field 'sales' has the key 'net' in an alias: "
        "each mention of the field puts that key at the value\n",
    )
    spaced = {"fields": {"sales": {"keys": ["net  sales"], "aliases": ["Net Sales"]}}}
    assert check(tmp_path, spaced, capsys)[0] == 1
    across = {"fields": {"sales": {"keys": ["net sales", "netting"], "aliases": ["net", "sales"]}}}
    assert check(tmp_path, across, capsys) == (0, "")


def test_alias_on_two_fields(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = {
        "fields": {
            "net_sales": {"aliases": ["Sales", "revenue"]},
            "cost": {"aliases": ["costs"]},
            "gross": {"aliases": ["sales"]},
            "other": {"aliases": [" SALES "]},
        }
    }
    assert check(tmp_path, schema, capsys) == (
        1,
        "alias 'Sales' is on fields 'net_sales', 'gross' and 'other': "
        "a field item does not tell them apart\n",
    )


def test_alias_in_another_fields_alias(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = {
        "fields": {
            "gross": {"aliases": ["sales"]},
            "net": {"aliases": ["net sales", "sales, net of returns"]},
            "cost": {"aliases": ["cost of salesman"]},
        }
    }
    assert check(tmp_path, schema, capsys) == (
        1,
        "alias 'sales' of field 'gross' is in alias 'net sales' of field 'net': "
        "a field item for 'net' passes for 'gross'\n"
        "alias 'sales' of field 'gross' is in alias 'sales, net of returns' of field 'net': "
        "a field item for 'net' passes for 'gross'\n",
    )


def test_minimum_above_maximum(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = {"fields": {"rate": {"minimum": "10", "maximum": 9}, "id": {"type": "string"}}}
    assert check(tmp_path, schema, capsys) == (
        1,
        "field 'rate' has a minimum above its maximum: no value is in range\n",
    )
    unused = {"fields": {"code": {"type": "string", "minimum": "10", "maximum": "9"}}}
    assert check(tmp_path, unused, capsys) == (0, "")


def test_invalid_schema_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = check(tmp_path, {"fields": {"fee": {"type": "float"}}}, capsys)
    assert (code, out) == (2, "")
    (tmp_path / "bad.json").write_text('{"fields": {}, "fields": {}}', encoding="utf-8")
    assert main(["schema", "check", str(tmp_path / "bad.json")]) == 2
    assert main(["schema", "check", str(tmp_path / "missing.json")]) == 2


def test_schema_command_still_writes_the_extractor_schema(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "s.json").write_text(json.dumps({"fields": {"fee": {}}}), encoding="utf-8")
    assert main(["schema", str(tmp_path / "s.json")]) == 0
    assert json.loads(capsys.readouterr().out)["type"] == "object"


def test_alias_in_alias_by_word_index(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = {
        "fields": {
            "net": {"aliases": ["(Net Sales)"]},
            "sales": {"aliases": ["net sales"]},
            "share": {"aliases": ["%"]},
            "margin": {"aliases": ["% of sales"]},
            "clean": {"aliases": [f"item {n} total" for n in range(1, 400)]},
        }
    }
    assert check(tmp_path, schema, capsys) == (
        1,
        "alias 'net sales' of field 'sales' is in alias '(Net Sales)' of field 'net': "
        "a field item for 'net' passes for 'sales'\n"
        "alias '%' of field 'share' is in alias '% of sales' of field 'margin': "
        "a field item for 'margin' passes for 'share'\n",
    )


def test_alias_in_alias_with_re_i_letters(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The word index matches letters as re.I does, as key_mentions does."""
    dotless, kelvin = "\N{LATIN SMALL LETTER DOTLESS I}", "\N{KELVIN SIGN}"
    mark, iota = "\N{COMBINING GREEK YPOGEGRAMMENI}", "\N{GREEK SMALL LETTER IOTA}"
    schema = {
        "fields": {
            "short": {"aliases": ["i", "kg"]},
            "dotless": {"aliases": [f"{dotless} x"]},
            "kelvin": {"aliases": [f"{kelvin}g total"]},
            "mark": {"aliases": [f"a{mark}"]},
            "iota": {"aliases": [f"a{iota} b"]},
        }
    }
    found = [
        ("i", "short", f"{dotless} x", "dotless"),
        ("kg", "short", f"{kelvin}g total", "kelvin"),
        (f"a{mark}", "mark", f"a{iota} b", "iota"),
    ]
    assert check(tmp_path, schema, capsys) == (
        1,
        "".join(
            f"alias {a!r} of field {f!r} is in alias {b!r} of field {g!r}: "
            f"a field item for {g!r} passes for {f!r}\n"
            for a, f, b, g in found
        ),
    )


def test_many_fields_with_one_alias(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = {"fields": {f"f{n}": {"aliases": ["sales"]} for n in range(3000)}}
    code, out = check(tmp_path, schema, capsys)
    assert code == 1
    assert out.count("\n") == 1
    assert out.startswith("alias 'sales' is on fields 'f0', 'f1', 'f2'")
