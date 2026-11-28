# groundgate.profile.check_profile()

Release: main, before 1.0.0 (spec 0.13).

`check_profile` runs the checks P1 to P8 of SPEC §4.10 on a profile object, and returns the
checked profile with its digest. `admit` and `verify` run the same checks on their `profile`.

## Call

```text
from groundgate.profile import check_profile

check_profile(profile) -> groundgate.profile.Profile
```

- `profile`: a profile as a dict, such as the result of [`load_profile`](load-profile.md).

## Example

```python
import groundgate as gg
from groundgate.profile import check_profile, load_profile

checked = check_profile(load_profile("examples/profiles/invoice-v1/profile.json"))
print(checked.entry()["id"], checked.version, checked.sha256[:23])
print(sorted(checked.schema.fields))
try:
    check_profile({"groundgate_profile": 1, "id": "my-invoices", "version": "1.0"})
except gg.PacketError as e:
    print(e)
```

```text
invoice 1.0.0 sha256:97463eeb74ff7be0
['invoice_number', 'subtotal', 'tax', 'total']
profile: a profile must give a schema (P1)
```

## Result

A frozen `Profile` with these fields:

- `id`, `version`: from the profile.
- `sha256`: the profile digest. groundgate computes it and never reads it from the profile. It
  reads the schema digest, the policy digest, the kind, the route rows and the gold set digest.
- `schema`, `policy`: the checked `gg.Schema` and `gg.Policy`.
- `entry()`: the `profile` member of the receipt, `{"id", "version", "sha256"}`.

## Errors

`check_profile` raises `gg.PacketError`. Each message starts with `profile:` and ends with the
number of the check. Some messages:

- `profile: a profile must be a JSON object (P1)`
- `profile: groundgate_profile must be 1 (P1)`
- `profile: a profile must give a schema (P1)`
- `profile: the id must be lowercase letters and digits with single '-' (P2)`
- `profile: <schema, policy or pack error> (P4)`: the schema, the policy or a pack is invalid.
- `profile: kind must name a kind pack that the schema names (P5)`
- `profile: a measured route row needs the gold_sha256 of the profile (P7)`
- `profile: the profile is nested deeper than 32 (P8)`

## See also

- [Profiles](../guide.md#profiles) in the guide.
- SPEC §4.10 lists each check.
