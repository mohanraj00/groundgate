from __future__ import annotations

import json
import math
from typing import Any

import pytest
import rfc8785
from hypothesis import given
from hypothesis import strategies as st

from groundgate.canonical import Offsets, digest, jcs

json_scalars = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**53 - 1), max_value=2**53 - 1)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text()
)
json_values = st.recursive(
    json_scalars,
    lambda inner: st.lists(inner, max_size=5) | st.dictionaries(st.text(), inner, max_size=5),
    max_leaves=25,
)


@given(json_values)
def test_matches_independent_rfc8785(value: Any) -> None:
    assert jcs(value).encode("utf-8", "surrogatepass") == rfc8785.dumps(value)


@pytest.mark.parametrize(
    ("x", "expected"),
    [
        (0.0, "0"),
        (-0.0, "0"),
        (1.0, "1"),
        (0.1, "0.1"),
        (1e21, "1e+21"),
        (1e20, "100000000000000000000"),
        (1e-7, "1e-7"),
        (0.000001, "0.000001"),
        (123.456, "123.456"),
        (-1.5e-10, "-1.5e-10"),
        (5e-324, "5e-324"),
    ],
)
def test_ecmascript_numbers(x: float, expected: str) -> None:
    assert jcs(x) == expected


def test_rejects_non_json() -> None:
    for bad in (math.nan, math.inf, 2**53, object(), {1: "a"}):
        with pytest.raises((ValueError, TypeError)):
            jcs(bad)


def test_key_order_is_utf16() -> None:
    # U+FF61 sorts before U+1F600 in UTF-16 (0xFF61 < 0xD83D) but after it in code points.
    obj = {"\U0001f600": 1, "｡": 2, "a": 3}
    assert jcs(obj) == '{"a":3,"\U0001f600":1,"｡":2}'


def test_digest_is_domain_separated() -> None:
    assert digest("document", {"text": "x"}) != digest("schema", {"text": "x"})
    assert digest("document", {"text": "x"}).startswith("sha256:")


@given(st.text())
def test_offsets_round_trip(text: str) -> None:
    off = Offsets(text)
    assert off.byte_length == len(text.encode("utf-8", "surrogatepass"))
    for i in range(len(text) + 1):
        assert off.to_char(off.to_bytes(i)) == i


def test_offsets_reject_mid_character() -> None:
    off = Offsets("é")
    assert off.to_char(1) is None
    assert json.dumps(off.to_bytes(1)) == "2"
