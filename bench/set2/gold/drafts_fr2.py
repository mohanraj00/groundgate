"""Set-2 gold drafts: Federal Register final rules, targeted groups (batch fr2). Written by a
model (Claude) from reading bench/set2/docs, after spec 0.2 was frozen. Not ground truth: a
person checks every fact."""

from __future__ import annotations

from build import f

HALIBUT_FIELDS = {
    "initial_period_limit_low_lb": (
        f("integer", "lb", "le"),
        "Lowest fishing period limit (vessel catch limit) in the initial 2026 Area 2A fishing "
        "periods (June 23-25 and July 7-9), across vessel size classes, in pounds.",
    ),
    "initial_period_limit_high_lb": (
        f("integer", "lb", "le"),
        "Highest fishing period limit (vessel catch limit) in the initial 2026 Area 2A fishing "
        "periods (June 23-25 and July 7-9), across vessel size classes, in pounds.",
    ),
    "initial_period_limit_low_mt": (
        f("number", "mt", "le"),
        "Lowest fishing period limit (vessel catch limit) in the initial 2026 Area 2A fishing "
        "periods (June 23-25 and July 7-9), across vessel size classes, in metric tons.",
    ),
    "initial_period_limit_high_mt": (
        f("number", "mt", "le"),
        "Highest fishing period limit (vessel catch limit) in the initial 2026 Area 2A fishing "
        "periods (June 23-25 and July 7-9), across vessel size classes, in metric tons.",
    ),
    "participating_vessels_2026": (
        f("integer", None),
        "Number of vessels that participated in the 2026 Area 2A non-Tribal directed commercial "
        "Pacific halibut fishery.",
    ),
}
HALIBUT_UNITS = {
    "lb": {"suffix": ["lb", "-lb", "pounds"]},
    "mt": {"suffix": ["mt", "-mt", "metric tons"]},
}
HALIBUT_DRAFT = {
    "initial_period_limit_low_lb": ["2000", "limits ranging from [[2,000]] to 5,000 lb"],
    "initial_period_limit_high_lb": ["5000", "ranging from 2,000 to [[5,000 lb]] (0.907"],
    "initial_period_limit_low_mt": ["0.907", "lb ([[0.907]] to 2.268 mt)"],
    "initial_period_limit_high_mt": ["2.268", "(0.907 to [[2.268 mt]]), varying"],
    "participating_vessels_2026": [None],
}

FIELDS = {
    "fr-2026-18911": HALIBUT_FIELDS,
    "fr-2026-17645": HALIBUT_FIELDS,
    "fr-2026-18776": {
        "min_recovery_altitude_proposed": (
            f("integer", "ft", "ge"),
            "Minimum recovery altitude for stalls and slow flight tasks that the NPRM proposed "
            "for the sport pilot PTS for Airplane, Gyroplane and Glider categories "
            "(FAA-S-8081-29B), in feet AGL.",
        ),
        "min_recovery_altitude_final": (
            f("integer", "ft", "ge"),
            "Minimum recovery altitude for stalls and slow flight tasks adopted in this final "
            "rule for the sport pilot PTS for Airplane, Gyroplane and Glider categories "
            "(FAA-S-8081-29B), in feet AGL.",
        ),
        "max_stall_speed_knots": (
            f("integer", "knots", "le"),
            "Maximum stall speed, in knots, of aircraft a sport pilot may operate under the "
            "performance limits in section 61.316.",
        ),
    },
    "fr-2026-18766": {
        "exam_cycle_asset_threshold_old": (
            f("integer", "USD", "le"),
            "Total-asset threshold for a qualifying IDI to be eligible for the 18-month on-site "
            "examination cycle before the 21st Century ROAD to Housing Act (the old threshold).",
        ),
        "exam_cycle_asset_threshold_new": (
            f("integer", "USD", "le"),
            "Total-asset threshold for a qualifying IDI to be eligible for the 18-month on-site "
            "examination cycle after the 21st Century ROAD to Housing Act (the new threshold).",
        ),
        "extended_exam_cycle_months": (
            f("integer", "months"),
            "Length, in months, of the extended on-site examination cycle for qualifying IDIs "
            "(instead of the annual cycle).",
        ),
        "good_rating_asset_limit": (
            f("integer", "USD", "le"),
            "Total-asset limit under which an IDI qualifies for the extended cycle with a "
            "composite condition of 'outstanding' or 'good' (rather than only 'outstanding').",
        ),
        "newly_eligible_idis": (
            f("integer", None),
            "Number of IDIs that become eligible for the 18-month examination cycle under the "
            "new asset threshold.",
        ),
    },
    "fr-2026-18123": {
        "flowering_stems_per_plant_low": (
            f("integer", None),
            "Low end of the number of flowering stems an individual tall western penstemon "
            "plant can have.",
        ),
        "flowering_stems_per_plant_high": (
            f("integer", None, "ge"),
            "High end of the number of flowering stems an individual tall western penstemon "
            "plant can have (stated as that number 'or more').",
        ),
        "flowers_per_stem_low": (
            f("integer", None),
            "Low end of the number of flowers per flowering stem of tall western penstemon.",
        ),
        "flowers_per_stem_high": (
            f("integer", None),
            "High end of the number of flowers per flowering stem of tall western penstemon.",
        ),
        "seeds_per_capsule": (
            f("integer", None),
            "Number of seeds in one tall western penstemon capsule.",
        ),
    },
    "fr-2026-17901": {
        "example_idc_ceiling_first": (
            f("integer"),
            "Ceiling value of the single-award IDC in the commenters' first example of orders "
            "falling below the ceiling.",
        ),
        "example_idc_orders_bound_first": (
            f("integer", "USD", "le"),
            "Amount that task or delivery orders under the single-award IDC in the commenters' "
            "first example could fall below.",
        ),
        "example_idc_ceiling_second": (
            f("integer"),
            "Ceiling value of the single-award IDC in the commenters' second example ('Similarly') "
            "of orders falling below the ceiling.",
        ),
        "example_idc_orders_bound_second": (
            f("integer", "USD", "le"),
            "Amount that task or delivery orders under the single-award IDC in the commenters' "
            "second example ('Similarly') could fall below.",
        ),
        "basic_cas_threshold_old": (
            f("integer", "USD", "ge"),
            "Basic CAS applicability threshold before this final rule (the current threshold).",
        ),
        "basic_cas_threshold_new": (
            f("integer", "USD", "ge"),
            "Basic CAS applicability threshold set by this final rule.",
        ),
        "trigger_contract_amount": (
            f("integer", "USD", "ge"),
            "Contract amount of the trigger contract concept that this final rule eliminates.",
        ),
        "full_coverage_threshold_old": (
            f("integer", "USD", "ge"),
            "Threshold for full CAS coverage and Disclosure Statement requirements before this "
            "final rule.",
        ),
        "full_coverage_threshold_new": (
            f("integer", "USD", "ge"),
            "Threshold for full CAS coverage and Disclosure Statement requirements set by this "
            "final rule.",
        ),
        "entities_full_coverage_fy2020_2024": (
            f("integer", None),
            "Estimated number of entities subject to full coverage and Disclosure Statement "
            "requirements in FYs 2020 through 2024, from FPDS data.",
        ),
        "contract_value_full_coverage_fy2020_2024": (
            f("integer"),
            "Aggregate total contract value of the entities subject to full coverage and "
            "Disclosure Statement requirements in FYs 2020 through 2024.",
        ),
        "entities_full_coverage_new_threshold": (
            f("integer", None),
            "Estimated number of entities subject to full coverage when the finalized threshold "
            "is applied to the FYs 2020 through 2024 data.",
        ),
        "contract_value_full_coverage_new_threshold": (
            f("integer"),
            "Aggregate contract dollars still subject to full coverage when the finalized "
            "threshold is applied to the FYs 2020 through 2024 data.",
        ),
        "annual_compliance_savings": (
            f("integer"),
            "Estimated annual compliance cost savings to contractors from this final rule, in "
            "dollars.",
        ),
    },
    "fr-2026-17893": {
        "per_vehicle_increase_smallest_carriers": (
            f("number", "USD", "eq"),
            "Approximate per-vehicle fee increase for the smallest motor carriers in each "
            "bracket under the adopted proposal.",
        ),
        "per_vehicle_increase_range_low": (
            f("number"),
            "Low end of the range of per-vehicle fee increases for the smallest motor carriers "
            "in each bracket.",
        ),
        "per_vehicle_increase_range_high": (
            f("number"),
            "High end of the range of per-vehicle fee increases for the smallest motor carriers "
            "in each bracket.",
        ),
        "fee_largest_bracket_2027": (
            f("integer"),
            "2027 UCR registration fee for motor carriers in the largest fee bracket.",
        ),
    },
    "fr-2026-17752": {
        "avg_days_sentencing_to_designation": (
            f("number", "days"),
            "Average length of time from sentencing to arrival at the designated BOP facility, "
            "for newly committed inmates with sentences starting 2023 through 2025, in days.",
        ),
        "inmates_transfer_no_supervision_annual": (
            f("integer", None),
            "Annual average number of inmates whose Time Credits were applied toward transfer to "
            "prerelease custody (RRC or HC) without a term of supervision (category 1), "
            "2023 through 2025.",
        ),
        "total_bop_population": (
            f("integer", None),
            "Total number of inmates in BOP custody.",
        ),
    },
    "fr-2026-17636": {
        "application_fee_old": (
            f("integer"),
            "Title XI program application fee before this rule.",
        ),
        "application_fee_new": (
            f("integer"),
            "Title XI program application fee under this rule.",
        ),
        "umra_threshold": (
            f("integer", "USD", "ge"),
            "Annual expenditure threshold (as adjusted for inflation in 2025) at which the "
            "Unfunded Mandates Reform Act requires agencies to act.",
        ),
        "expedited_application_fee": (
            f("integer"),
            "Fee for the expedited application approval process in the Title XI program.",
        ),
    },
    "fr-2026-17512": {
        "economic_adjustment_motions_low": (
            f("integer", "lb"),
            "Low end of the range of economic adjustments in the motions the Board discussed at "
            "the June meeting, in pounds.",
        ),
        "economic_adjustment_motions_high": (
            f("integer", "lb"),
            "High end of the range of economic adjustments in the motions the Board discussed "
            "at the June meeting, in pounds.",
        ),
        "preliminary_economic_adjustment": (
            f("integer", "lb"),
            "Preliminary economic adjustment the Board recommended at the June meeting, in pounds.",
        ),
        "assessment_rate_per_pound": (
            f("number", "cents"),
            "Tart cherry assessment rate per pound for the 2024-2025 crop year, in cents.",
        ),
    },
    "fr-2026-17511": {
        "olive_assessment_rate_old": (
            f("number"),
            "California olive assessment rate per ton of assessable olives before this rule.",
        ),
        "olive_assessment_rate_new": (
            f("number"),
            "California olive assessment rate per ton of assessable olives for the 2025 and "
            "subsequent fiscal years, under this rule.",
        ),
        "olive_handlers_count": (
            f("integer", None),
            "Number of handlers of California olives.",
        ),
    },
}

UNITS = {
    "fr-2026-18911": HALIBUT_UNITS,
    "fr-2026-17645": HALIBUT_UNITS,
    "fr-2026-18776": {"ft": {"suffix": ["feet"]}, "knots": {"suffix": ["knots"]}},
    "fr-2026-17512": {"lb": {"suffix": ["pounds", "pound", "-pound"]}},
}

DRAFTS = {
    "fr-2026-18911": HALIBUT_DRAFT,
    "fr-2026-17645": HALIBUT_DRAFT,
    "fr-2026-18776": {
        "min_recovery_altitude_proposed": ["1000", "Category (FAA–S–8081–29B) from [[1,000]] to"],
        "min_recovery_altitude_final": ["1500", "from 1,000 to [[1,500 feet]] AGL"],
        "max_stall_speed_knots": [None],
    },
    "fr-2026-18766": {
        "exam_cycle_asset_threshold_old": [
            "3000000000",
            "raise the asset thresholds from [[$3 billion]] to",
            "only qualifying IDIs with under [[$3 billion]] in total assets were",
            "examine qualifying IDIs with under [[$3 billion]] in total assets not less",
        ],
        "exam_cycle_asset_threshold_new": [
            "6000000000",
            "from $3 billion to [[$6 billion]] to permit",
            "under [[$6 billion]] in total assets to be eligible",
            "has total assets of less than [[$6 billion]];",
        ],
        "extended_exam_cycle_months": [
            "18",
            "during each [[18-month]] period instead of annually",
            "were eligible for an [[18-month]] on-site examination cycle",
            "during each [[18-month]] period). The Agencies",
            "eligible for the extended [[18-month]] examination schedule",
            "at least once during an [[18- month]] period if the IDI",
            "extend eligibility for an [[18- month]] examination cycle",
        ],
        "good_rating_asset_limit": [
            "200000000",
            "with total assets of not more than [[$200 million]],",
        ],
        "newly_eligible_idis": [None],
    },
    "fr-2026-18123": {
        "flowering_stems_per_plant_low": ["1", "Individual plants can have from [[1]] to 100"],
        "flowering_stems_per_plant_high": ["100", "from 1 to [[100]] or more flowering stems"],
        "flowers_per_stem_low": ["10", "each with [[10]] to 80 flowers"],
        "flowers_per_stem_high": ["80", "each with 10 to [[80]] flowers per stem"],
        "seeds_per_capsule": [None],
    },
    "fr-2026-17901": {
        "example_idc_ceiling_first": [
            "35000000",
            "possible for a [[$35 million]] single-award IDC",
        ],
        "example_idc_orders_bound_first": [
            "35000000",
            "IDC to receive less than [[$35 million]] in tasks",
        ],
        "example_idc_ceiling_second": [
            "100000000",
            "Similarly, a [[$100 million]] single-award IDC",
        ],
        "example_idc_orders_bound_second": [
            "100000000",
            "could receive less than [[$100 million]] in tasks",
        ],
        "basic_cas_threshold_old": ["2500000", "threshold from the current [[$2.5 million]] to"],
        "basic_cas_threshold_new": ["35000000", "$2.5 million to [[$35 million]], and eliminates"],
        "trigger_contract_amount": ["7500000", "eliminates the [[$7.5 million]] trigger contract"],
        "full_coverage_threshold_old": [
            "50000000",
            "Disclosure Statement requirements from [[$50 million]] to",
        ],
        "full_coverage_threshold_new": [
            "100000000",
            "from $50 million to [[$100 million]]. This",
            "Applying the finalized threshold of [[$100 million]] to the data set",
        ],
        "entities_full_coverage_fy2020_2024": ["773", "estimates there have been [[773]] entities"],
        "contract_value_full_coverage_fy2020_2024": [
            "1220000000000",
            "contract values during the period of [[$1.22 trillion]]",
        ],
        "entities_full_coverage_new_threshold": ["564", "number of entities to [[564]] while"],
        "contract_value_full_coverage_new_threshold": [
            "1210000000000",
            "while maintaining [[$1.21 trillion]] of the dollars",
        ],
        "annual_compliance_savings": [None],
    },
    "fr-2026-17893": {
        # Skipped: "no more than six fee brackets" writes the amount as a word, not a number.
        "per_vehicle_increase_smallest_carriers": [
            "9.41",
            "raises the fee by approximately [[$9.41]] per vehicle",
        ],
        "per_vehicle_increase_range_low": ["9", "(ranging from [[$9]] to $9.67)"],
        "per_vehicle_increase_range_high": ["9.67", "(ranging from $9 to [[$9.67]])"],
        "fee_largest_bracket_2027": [None],
    },
    "fr-2026-17752": {
        "avg_days_sentencing_to_designation": [
            "66.06",
            "arrival at the designated facility to be [[66.06 days]]",
            "Avg time from sentencing to designation ([[66.06 days]])",
            "the average time of [[66.06 days]] spent in transit",
            "6,486 ........................ [[66.06]] 23.81",
        ],
        "inmates_transfer_no_supervision_annual": [
            "7554",
            "(which averaged [[7,554 inmates]]",
            "23.81 days for [[7,554 inmates]] annually",
            "[[7,554]] 11,258 6,486",
        ],
        "total_bop_population": [None],
    },
    "fr-2026-17636": {
        "application_fee_old": ["5000", "reduce application fees from [[$5,000]] to"],
        "application_fee_new": ["1000", "from $5,000 to [[$1,000]]. These"],
        "umra_threshold": ["206000000", "private sector, of [[$206 million]] or more"],
        "expedited_application_fee": [None],
    },
    "fr-2026-17512": {
        # Not added as a context: "the recommended 5-million-pound economic adjustment" writes
        # the preliminary adjustment with hyphens, which does not read as a scaled amount.
        "economic_adjustment_motions_low": ["0", "economic adjustment ranging from [[0]] to 10"],
        "economic_adjustment_motions_high": [
            "10000000",
            "ranging from 0 to [[10 million pounds]], the Board",
        ],
        "preliminary_economic_adjustment": [
            "5000000",
            "preliminary economic adjustment of [[5 million pounds]] at the June meeting",
            "¥[[5 million pounds]] for the economic adjustment)",
        ],
        "assessment_rate_per_pound": [None],
    },
    "fr-2026-17511": {
        "olive_assessment_rate_old": ["28", "subsequent fiscal years from [[$28]] to $24"],
        "olive_assessment_rate_new": ["24", "from $28 to [[$24]] per ton of assessable olives"],
        "olive_handlers_count": [None],
    },
}
