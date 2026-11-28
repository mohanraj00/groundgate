# gg.jcs()

Release: main, before 1.0.0 (spec 0.13).

`jcs` writes an object as canonical JSON (RFC 8785). Each digest of groundgate reads these
bytes, so two equal objects give one digest.

## Call

```text
gg.jcs(obj) -> str
```

- `obj`: a JSON value: a dict with string keys, a list or a tuple, a string, an integer, a
  float, `True`, `False` or `None`.

## Example

```python
import groundgate as gg

print(gg.jcs({"b": [1, 2.50, None], "a": "é\n", "c": 1e21, "d": True}))
```

```text
{"a":"é\n","b":[1,2.5,null],"c":1e+21,"d":true}
```

## Result

A `str` with no white space between the tokens. The keys of each object are sorted by their
UTF-16 code units. A float is written as ECMAScript writes it, so `2.50` is `2.5` and `1e21` is
`1e+21`. A string keeps each character other than the quote, the backslash, the control
characters and a lone surrogate. Encode the result as UTF-8 to get the canonical bytes.

## Errors

- `ValueError("NaN and infinities are not permitted in canonical JSON")`: a float is not
  finite.
- `ValueError("integer <n> is outside the exactly representable range")`: an integer is
  larger than 2^53 - 1 or smaller than -(2^53 - 1).
- `TypeError("object keys must be strings")`: a dict has a key that is not a string.
- `TypeError("<type> is not JSON-serialisable")`: the object has another type, such as a set.

## See also

- [`gg.digest()`](digest.md) hashes this output.
- [Python API](../guide.md#python-api) in the guide.
- RFC 8785, JSON Canonicalization Scheme.
