"""Set-2 gold drafts: Federal Register final rules, targeted groups (batch fr3). Written by a
model (Claude) from reading bench/set2/docs, after spec 0.2 was frozen. Not ground truth: a
person checks every fact."""

from __future__ import annotations

from build import f

FIELDS = {
    "fr-2026-17116": {
        "vevraa_coverage_threshold_before_oct_2025": (
            f("integer", "USD", "ge"),
            "VEVRAA coverage threshold (single Federal contract or subcontract amount) before "
            "the inflation adjustment effective October 1, 2025.",
        ),
        "vevraa_coverage_threshold_from_oct_2025": (
            f("integer", "USD", "ge"),
            "VEVRAA coverage threshold (single Federal contract or subcontract amount) after the "
            "inflation adjustment effective October 1, 2025.",
        ),
        "covered_contractor_count": (
            f("integer", None),
            "Number of Federal contractors and subcontractors covered by VEVRAA.",
        ),
    },
    "fr-2026-17400": {
        "snun_fee_standard": (
            f("integer", "USD"),
            "SNUN submission fee before the reduction offered to qualifying small businesses.",
        ),
        "snun_fee_small_business": (
            f("integer", "USD"),
            "Reduced SNUN submission fee for qualifying small businesses.",
        ),
        "umra_unfunded_mandate_threshold_1995_dollars": (
            f("integer", "USD", "ge"),
            "UMRA unfunded mandate threshold in any one year, in 1995 dollars.",
        ),
        "umra_private_sector_threshold_2023_dollars": (
            f("integer", "USD", "ge"),
            "UMRA threshold for costs to the private sector in any one year, adjusted to 2023 "
            "dollars, that the action's estimated costs do not exceed.",
        ),
        "snur_violation_civil_penalty": (
            f("integer", "USD"),
            "Civil penalty per day for violating one of these significant new use rules.",
        ),
    },
    "fr-2026-17429": {
        "annual_fee_per_area_code_fy2026": (
            f("integer", "USD"),
            "Do Not Call Registry annual fee for each area code of data before this rule's "
            "increase (the fee being replaced).",
        ),
        "annual_fee_per_area_code_fy2027": (
            f("integer", "USD"),
            "Do Not Call Registry annual fee for each area code of data for fiscal year 2027, "
            "after the increase.",
        ),
        "max_charge_per_entity_fy2026": (
            f("integer", "USD", "le"),
            "Maximum amount charged to any single entity for accessing area codes of data, "
            "before this rule's increase.",
        ),
        "max_charge_per_entity_fy2027": (
            f("integer", "USD", "le"),
            "Maximum amount charged to any single entity for accessing area codes of data for "
            "fiscal year 2027, after the increase.",
        ),
        "second_half_area_code_fee_fy2026": (
            f("integer", "USD"),
            "Fee for each area code added during the second six months of the annual "
            "subscription period, before this rule's increase.",
        ),
        "second_half_area_code_fee_fy2027": (
            f("integer", "USD"),
            "Fee for each area code added during the second six months of the annual "
            "subscription period, for fiscal year 2027 after the increase.",
        ),
        "free_area_codes_per_entity": (
            f("integer", None),
            "Number of area codes of data an entity may access at no charge.",
        ),
    },
}

DRAFTS = {
    "fr-2026-17116": {
        # Not drafted: "contract or subcontract of $200,000 or more" for the affirmative action
        # program requirement (with 50 or more employees) is a separate threshold, so it is
        # not listed as a context of the coverage threshold.
        "vevraa_coverage_threshold_before_oct_2025": [
            "150000",
            "threshold under VEVRAA increased from [[$150,000]] to $200,000",
        ],
        "vevraa_coverage_threshold_from_oct_2025": [
            "200000",
            "threshold under VEVRAA increased from $150,000 to [[$200,000]]",
            "holds a single Federal contract or subcontract of at least [[$200,000]]",
        ],
        "covered_contractor_count": [None],
    },
    "fr-2026-17400": {
        "snun_fee_standard": [
            "37000",
            "reducing the SNUN submission fee from [[$37,000]] to $6,480",
        ],
        "snun_fee_small_business": [
            "6480",
            "reducing the SNUN submission fee from $37,000 to [[$6,480]]",
        ],
        "umra_unfunded_mandate_threshold_1995_dollars": [
            "100000000",
            "unfunded mandate of [[$100 million]] or more (in 1995 dollars)",
        ],
        "umra_private_sector_threshold_2023_dollars": [
            "183000000",
            "private sector do not exceed [[$183 million]] or more in any one year",
        ],
        "snur_violation_civil_penalty": [None],
    },
    "fr-2026-17429": {
        # The $82 in the amendment to paragraph (d) is the fee for additional area codes in the
        # first six months, a separate provision, so it is not a context of the annual fee.
        "annual_fee_per_area_code_fy2026": [
            "82",
            "for each area code of data from [[$82]] to $85 per area code",
            "In paragraph (c): i. Removing ‘‘[[$82]]’’",
        ],
        "annual_fee_per_area_code_fy2027": [
            "85",
            "for each area code of data from $82 to [[$85]] per area code",
            "leads to a [[$85]] fee for access to a single area code",
            "pursuant to the Act, [[$85]] is the appropriate fee",
            "In paragraph (c): i. Removing ‘‘$82’’ and adding ‘‘[[$85]]’’",
        ],
        "max_charge_per_entity_fy2026": [
            "22626",
            "accessing area codes of data from [[$22,626]] to $23,425",
            "Removing ‘‘[[$22,626]]’’",
        ],
        "max_charge_per_entity_fy2027": [
            "23425",
            "accessing area codes of data from $22,626 to [[$23,425]]",
            "The maximum amount charged increases to [[$23,425]] (rounded",
            "adding ‘‘[[$23,425]]’’ in its place",
        ],
        "second_half_area_code_fee_fy2026": [
            "41",
            "the fee for those additional area codes increases from [[$41]] to $43",
            "Removing ‘‘[[$41]]’’",
        ],
        "second_half_area_code_fee_fy2027": [
            "43",
            "the fee for those additional area codes increases from $41 to [[$43]]",
            "for a half year increases by two dollars to [[$43]] (rounded",
            "adding ‘‘[[$43]]’’ in its place",
        ],
        "free_area_codes_per_entity": [None],
    },
}
