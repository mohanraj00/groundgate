# groundgate.profile.load_profile()

Release: main, before 1.0.0 (spec 0.13).

`load_profile` reads a document-family profile from a file, and runs the checks P1 to P8 of
SPEC §4.10 on it. Give the result to `admit` and `verify` in `profile`.

## Call

```text
from groundgate.profile import load_profile

load_profile(path) -> dict
```

- `path`: a `str` or a `pathlib.Path` to a JSON file of at most 4 MiB.

## Example

```python
import json

import groundgate as gg
from groundgate.profile import load_profile

folder = "examples/profiles/invoice-v1/"
profile = load_profile(folder + "profile.json")
text = open(folder + "document.txt", encoding="utf-8").read()
candidates = json.load(open(folder + "candidates.json", encoding="utf-8"))
receipt = gg.admit(text, None, candidates, profile=profile)
print(profile["id"], profile["version"])
print(receipt.profile["sha256"][:23], receipt.to_dict()["summary"])
print(gg.verify(receipt.to_dict(), text, None, candidates, profile=profile).ok)
```

```text
invoice 1.0.0
sha256:97463eeb74ff7be0 {'admitted': 4, 'needs_verification': 0, 'rejected': 0}
True
```

## Result

The profile as a dict, after the checks. It is the same object as the file, not a checked
`Profile`. Use [`check_profile`](check-profile.md) to get the digest, the schema and the policy.

The receipt of `admit` names the profile in `receipt.profile`: its `id`, `version` and
`sha256`. Give the profile in place of the schema, the policy and the packs.

## Errors

`load_profile` raises `gg.PacketError`:

- `profile file '<path>' is not a file`
- `profile file '<path>' cannot be read: <cause>`
- `profile file '<path>' is more than 4194304 bytes (P8)`: groundgate refuses the file before
  it parses it.
- `profile file '<path>' is not JSON: <cause>`
- `profile file '<path>': pack: an object has one key twice (L1)`: a JSON object in the file
  has one key two times.
- `profile: <check>`: the profile fails a check. See [`check_profile`](check-profile.md#errors).

## See also

- [Profiles](../guide.md#profiles) in the guide.
- [`examples/profiles/`](../../examples/profiles/) has two profiles.
