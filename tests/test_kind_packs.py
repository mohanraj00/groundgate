"""The built-in kind packs from the bench schemas (#337, packs.md §10.3 stage 4).

Each bench set keeps its own schema file. Here each schema is written again in template form,
by hand, and it must resolve to the same fields as the set's file, member by member. So the
templates hold the knowledge of the sets with no change.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate.pack import BUILT_IN_SHA256, built_in_pack, pack_digest

REPO = Path(__file__).resolve().parents[1]
BENCH = REPO / "bench"
YEARS3 = ["2025", "2024", "2023"]
YEARS2 = ["2025", "2024"]
TEN_K = ("revenue", "net_income", "operating_income", "cash_and_equivalents", "total_debt")
AFR = (
    "total_assets",
    "total_liabilities",
    "total_net_position",
    "net_cost_of_operations",
    "total_budgetary_resources",
)
ACFR = ("total_assets", "total_liabilities", "total_net_position", "change_in_net_position")
# the descriptions of the acfr sets name the primary government, so they stay in the app schema
ACFR_DESCRIPTION = {
    "total_assets": "Total assets of the primary government (its Total column) at the fiscal "
    "year end.",
    "total_liabilities": "Total liabilities of the primary government (its Total column) at the "
    "fiscal year end.",
    "total_net_position": "Total net position of the primary government (its Total column) at "
    "the fiscal year end.",
    "change_in_net_position": "Change in net position of the primary government (its Total "
    "column) for the year.",
}
ANNUAL = (
    "cost_of_sales",
    "gross_profit",
    "revenue",
    "total_assets",
    "total_equity",
    "total_liabilities",
)
COMPONENT = (
    "operating_temperature_max",
    "operating_temperature_min",
    "supply_current_typ",
    "supply_voltage_max",
    "supply_voltage_min",
)
SBC = (
    "deductible_family",
    "deductible_individual",
    "out_of_pocket_family",
    "out_of_pocket_individual",
    "specialist_copay",
)


def uses(pid: str) -> list[dict[str, str]]:
    return [{"id": pid, "version": "1.0.0"}]


def take(pid: str, names: tuple[str, ...], **more: Any) -> dict[str, dict[str, Any]]:
    """Each field takes the template of the same name, and gives the members in ``more``."""
    return {n: {"template": f"{pid}/{n}", **more} for n in names}


# each bench schema in template form, written by hand: the set, then the schema that takes the
# templates. A member here is a member that the template does not give.
FORMS: dict[str, dict[str, Any]] = {
    # the first 10-K set reads no aliases, so its fields give aliases null
    "sec": {
        "packs": uses("us-10k"),
        "fields": take("us-10k", TEN_K, multiple=True, keys=YEARS3, aliases=None),
    },
    "sec2": {"packs": uses("us-10k"), "fields": take("us-10k", TEN_K, multiple=True, keys=YEARS3)},
    "sec3": {"packs": uses("us-10k"), "fields": take("us-10k", TEN_K, multiple=True, keys=YEARS3)},
    "afr": {
        "packs": uses("us-government-reports"),
        "fields": take("us-government-reports", AFR, multiple=True, keys=YEARS2),
    },
    "acfr": {
        "packs": uses("us-government-reports"),
        "fields": {
            n: {"template": f"us-government-reports/{n}", "description": ACFR_DESCRIPTION[n]}
            for n in ACFR
        },
    },
    "acfr2": {
        "packs": uses("us-government-reports"),
        "fields": {
            n: {
                "template": f"us-government-reports/{n}",
                "multiple": True,
                "keys": YEARS2,
                "description": ACFR_DESCRIPTION[n],
            }
            for n in ACFR
        },
    },
    # the annual template has no unit: the schema gives the reporting currency
    "annual": {
        "packs": uses("annual-reports"),
        "fields": take("annual-reports", ANNUAL, unit="GBP"),
    },
    # the unit forms of the schema's units come from electronics, which the kind pack needs
    "component": {
        "packs": uses("component-datasheets"),
        "fields": take("component-datasheets", COMPONENT),
    },
    "sbc": {"packs": uses("benefit-summaries"), "fields": take("benefit-summaries", SBC)},
}


def current(name: str) -> list[dict[str, Any]]:
    """The schemas of a set as the bench reads them today."""
    if name in ("annual", "component", "sbc"):
        return [
            json.loads((BENCH / s / "manifest.json").read_text(encoding="utf-8"))["schemas"][name]
            for s in ("requested", "requested2")
        ]
    return [json.loads((BENCH / name / "schema.json").read_text(encoding="utf-8"))]


@pytest.mark.parametrize("name", sorted(FORMS))
def test_the_template_form_resolves_to_the_fields_of_the_set(name: str) -> None:
    form = gg.Schema.from_dict(FORMS[name]).to_dict()
    for schema in current(name):
        want = gg.Schema.from_dict(schema).to_dict()["fields"]
        assert sorted(form["fields"]) == sorted(want)
        for field, members in want.items():
            got = dict(form["fields"][field])
            assert got.pop("template") == FORMS[name]["fields"][field]["template"]
            assert got == members, field  # member by member, after the defaults


@pytest.mark.parametrize("name", ["sec", "sec2", "sec3", "afr", "acfr", "acfr2", "annual"])
def test_a_financial_kind_reads_finance(name: str) -> None:
    schema = gg.Schema.from_dict(FORMS[name])
    finance = BUILT_IN_SHA256[("finance", "1.0.0")]
    assert {"id": "finance", "type": "vocabulary", "version": "1.0.0", "sha256": finance} in [
        dict(p) for p in schema.packs
    ]
    assert sorted(schema.vocabulary.pack["sign"]["loss"]) == [
        "deficit",
        "deficits",
        "loss",
        "losses",
    ]


def test_electronics_gives_the_unit_forms_of_the_component_schema() -> None:
    form = gg.Schema.from_dict(FORMS["component"])
    for schema in current("component"):
        want = gg.Schema.from_dict(schema)
        assert sorted(form.units) == sorted(want.units)
        for code, (prefixes, suffixes) in want.units.items():
            assert sorted(form.units[code][0]) == sorted(prefixes), code
            assert sorted(form.units[code][1]) == sorted(suffixes), code


def test_the_built_in_packs_load_with_their_digests_and_hold_no_measured_row() -> None:
    for (pid, version), sha in BUILT_IN_SHA256.items():
        pack = built_in_pack(pid, version)
        assert pack is not None and pack_digest(pack) == sha
        assert pack["status"] == []  # draft: no route is measured in 0.10
        for need in pack.get("needs", []):
            assert (need["id"], need["version"]) in BUILT_IN_SHA256


def test_spec_lists_each_built_in_pack_with_its_digest() -> None:
    spec = (REPO / "SPEC.md").read_text(encoding="utf-8").split("### 4.8")[1].split("### 4.9")[0]
    listed = set(
        re.findall(
            r"\| `([a-z0-9-]+)` \| `([0-9.]+)` \|[^|\n]*\|[^|\n]*\| `(sha256:[0-9a-f]{64})`", spec
        )
    )
    assert listed == {(pid, v, sha) for (pid, v), sha in BUILT_IN_SHA256.items()}


def test_a_field_can_take_a_built_in_template_and_give_its_keys() -> None:
    doc = "Revenue was $5,000 in 2025."
    schema = {
        "packs": uses("us-10k"),
        "fields": {"revenue": {"template": "us-10k/revenue", "keys": ["2025"]}},
    }
    cand = {
        "id": "r",
        "field": "revenue",
        "key": "2025",
        "value": "5000",
        "unit": "USD",
        "evidence": [{"text": "$5,000"}, {"role": "field", "text": "Revenue"}],
    }
    receipt = gg.admit(doc, schema, [cand]).to_dict()
    assert [p["id"] for p in receipt["packs"]] == ["finance", "us-10k"]
    assert receipt["decisions"][0]["outcome"] == "admitted"
    assert receipt["decisions"][0]["packs"] == ["us-10k"]
