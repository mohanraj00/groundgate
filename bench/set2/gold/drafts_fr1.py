"""Set-2 gold drafts: Federal Register final rules, targeted groups (batch fr1). Written by a model
(Claude) from reading bench/set2/docs, after spec 0.2 was frozen. Not ground truth: a person
checks every fact."""

from __future__ import annotations

from build import f

_REG_A_FIELDS = {
    "primary_credit_rate_increase": (
        f("number", "pp"),
        "Size of the increase in the primary credit rate the Board approved on September 16, "
        "2026, in percentage points.",
    ),
    "primary_credit_rate_old": (
        f("number", "%"),
        "Primary credit rate before the September 2026 increase.",
    ),
    "primary_credit_rate_new": (
        f("number", "%"),
        "Primary credit rate after the September 2026 increase.",
    ),
    "secondary_credit_rate_increase": (
        f("number", "pp"),
        "Size of the increase in the secondary credit rate that followed the primary credit rate "
        "action, in percentage points.",
    ),
    "secondary_credit_rate_old": (
        f("number", "%"),
        "Secondary credit rate before the September 2026 increase.",
    ),
    "secondary_credit_rate_new": (
        f("number", "%"),
        "Secondary credit rate after the September 2026 increase.",
    ),
    "apa_min_publication_days": (
        f("integer", "days", "ge"),
        "Minimum number of days before its effective date that the Administrative Procedure Act "
        "generally requires a final rule to be published.",
    ),
    "seasonal_credit_rate": (
        f("number", "%"),
        "Seasonal credit rate at the Federal Reserve Banks after the September 2026 action.",
    ),
}
_REG_A_UNITS = {"pp": {"suffix": ["percentage point", "percentage points"]}}
_REG_A_DRAFTS = {
    "primary_credit_rate_increase": [
        "0.25",
        "voted to approve a [[0.25 percentage point]] increase",
        "The [[0.25 percentage point]] increase in the primary credit rate was associated",
    ],
    "primary_credit_rate_old": ["3.75", "increasing the primary credit rate from [[3.75 percent]]"],
    "primary_credit_rate_new": ["4.00", "from 3.75 percent to [[4.00 percent]]"],
    "secondary_credit_rate_increase": [
        "0.25",
        "the secondary credit rate increased by [[0.25 percentage points]]",
    ],
    "secondary_credit_rate_old": ["4.25", "secondary credit rate from [[4.25 percent]]"],
    "secondary_credit_rate_new": ["4.50", "from 4.25 percent to [[4.50 percent]]"],
    "apa_min_publication_days": [
        "30",
        "publication of the final rule not less than [[30 days]] before its effective date",
        "publication at least [[30 days]] prior to a",
    ],
    "seasonal_credit_rate": [None],
}

_ALMA_FIELDS = {
    "class_e_radius_old": (
        f("number", "miles"),
        "Radius of the Class E airspace extending upward from 700 feet around Gratiot Community "
        "Airport before this action, in miles.",
    ),
    "class_e_radius_new": (
        f("number", "miles"),
        "Radius of the Class E airspace extending upward from 700 feet around Gratiot Community "
        "Airport after this action, in miles.",
    ),
    "annual_aircraft_operations": (
        f("integer", None),
        "Number of aircraft operations per year at Gratiot Community Airport.",
    ),
}
_ALMA_UNITS = {"miles": {"suffix": ["miles", "-mile"]}}
_ALMA_DRAFTS = {
    "class_e_radius_old": [
        "6.5",
        "increases the radius from [[6.5]] to 7.4 miles",
        "(previously [[6.5-mile]]) radius",
    ],
    "class_e_radius_new": [
        "7.4",
        "increases the radius from 6.5 to [[7.4 miles]]",
        "extending from the [[7.4- mile]] (previously",
        "within a [[7.4-mile]] radius of Gratiot",
        "extending from the [[7.4-mile]] radius to 10.7 miles",
    ],
    "annual_aircraft_operations": [None],
}

FIELDS = {
    "fr-2026-20036": _REG_A_FIELDS,
    "fr-2026-19966": {
        "state_regulation_issuance_cap": (
            f("integer", "USD", "le"),
            "Maximum consolidated total outstanding issuance of payment stablecoins for a "
            "State-qualified issuer to opt for State regulation under section 4(c) of the "
            "GENIUS Act.",
        ),
        "state_certification_fee": (
            f("integer", "USD"),
            "Fee a State pays to submit a substantial similarity certification to the Committee.",
        ),
    },
    "fr-2026-19946": {
        "ucp_supplemental_total_fy2026": (
            f("integer", "USD"),
            "Uncompensated care payments and supplemental payments summed across all hospitals "
            "projected to receive DSH payments, estimated for FY 2026.",
        ),
        "ucp_supplemental_total_fy2027": (
            f("integer", "USD"),
            "Uncompensated care payments and supplemental payments summed across all hospitals "
            "projected to receive DSH payments, estimated for FY 2027.",
        ),
        "factor_1_amount_fy2027": (
            f("integer", "USD"),
            "Factor 1: the total amount available for uncompensated care payments in FY 2027.",
        ),
    },
    "fr-2026-19929": {
        "umra_expenditure_threshold": (
            f("integer", "USD", "ge"),
            "Annual expenditure by State, local, or Tribal governments or the private sector "
            "above which the Unfunded Mandates Reform Act requires an assessment of a rule.",
        ),
        "estimated_annual_cost": (
            f("integer", "USD"),
            "Estimated annual cost of this Title IX rule to recipients of Federal funding.",
        ),
    },
    "fr-2026-19887": {
        "almond_export_value": (
            f("integer", "USD"),
            "Value of almond exports from August 2022 to July 2023 (shelled equivalent), from "
            "the GATS database.",
        ),
        "almond_export_quantity": (
            f("integer", "pounds"),
            "Quantity of almond exports from August 2022 to July 2023, in pounds.",
        ),
        "handler_price_per_pound": (
            f("number", "USD"),
            "Unit value of almond exports per shelled pound, used as the representative handler "
            "price per pound.",
        ),
        "almond_production_2022": (
            f("integer", "pounds"),
            "Pounds of almonds the California almond industry produced in 2022, as estimated by "
            "NASS.",
        ),
        "handler_total_revenue": (
            f("integer", "USD"),
            "Estimated total revenue at the handler level for the California almond industry.",
        ),
        "handler_count": (
            f("integer", None),
            "Estimated number of handlers in the California almond industry (production area).",
        ),
        "average_revenue_per_handler": (
            f("integer", "USD"),
            "Approximate average revenue per almond handler.",
        ),
        "assessment_rate_per_pound": (
            f("number", "USD"),
            "Assessment rate per pound of almonds that handlers pay to the Board.",
        ),
    },
    "fr-2026-19745": {
        "depth_min": (
            f("integer", "ft"),
            "Shallowest water depth of the modified CCSC and CCNW ODMDSs, in feet.",
        ),
        "depth_max": (
            f("integer", "ft"),
            "Deepest water depth of the modified CCSC and CCNW ODMDSs, in feet.",
        ),
        "offshore_distance_min": (
            f("number", "nmi"),
            "Nearest distance offshore of the modified ODMDSs, in nautical miles.",
        ),
        "offshore_distance_max": (
            f("number", "nmi"),
            "Farthest distance offshore of the modified ODMDSs, in nautical miles.",
        ),
        "monitoring_interval_years": (
            f("integer", "years"),
            "Number of years between monitoring surveys of the modified ODMDSs under the SMMP.",
        ),
    },
    "fr-2026-19666": {
        "closing_letter_fee_old": (
            f("integer", "USD"),
            "User fee for a request for an estate tax closing letter before these regulations.",
        ),
        "closing_letter_fee_new": (
            f("integer", "USD"),
            "User fee for a request for an estate tax closing letter under these final "
            "regulations.",
        ),
        "annual_closing_letter_requests": (
            f("integer", None),
            "Number of estate tax closing letter requests the IRS receives per year.",
        ),
    },
    "fr-2026-19493": {
        "unauthorized_enrollment_complaints_2023_2025": (
            f("integer", None),
            "Consumer complaints about unauthorized enrollments or plan switching by agents or "
            "brokers in the Federally-facilitated Exchanges, confirmed by issuer review, "
            "received from 2023 through 2025.",
        ),
        "moratorium_max_duration_days": (
            f("integer", "days", "le"),
            "Maximum duration, in days, of a temporary moratorium on agent and broker "
            "registrations.",
        ),
    },
    "fr-2026-19389": {
        "industry_seats_old": (
            f("integer", None),
            "Number of industry seats on the Softwood Lumber Board before this action.",
        ),
        "industry_seats_new": (
            f("integer", None),
            "Number of industry seats on the Softwood Lumber Board after this action.",
        ),
        "board_members_total": (
            f("integer", None),
            "Total number of Softwood Lumber Board members after this action.",
        ),
        "sba_small_firm_receipts": (
            f("integer", "USD", "le"),
            "SBA annual receipts limit for a small firm in Support Activities for Forestry.",
        ),
        "small_entity_max_volume": (
            f("integer", "board_feet", "le"),
            "Maximum softwood lumber volume per year, in board feet, a domestic manufacturer "
            "may ship to be considered a small entity for the RFA.",
        ),
        "small_manufacturer_count": (
            f("integer", None),
            "Number of domestic softwood lumber manufacturers classified as small entities.",
        ),
    },
    "fr-2026-19173": _ALMA_FIELDS,
    "fr-2026-19006": {
        "financial_remedies_total": (
            f("integer", "USD"),
            "Financial remedies in enforcement actions that whistleblower reports contributed "
            "to, through the end of calendar year 2025.",
        ),
        "returned_to_customers": (
            f("integer", "USD"),
            "Amount of those financial remedies returned to harmed customers, excluding added "
            "interest.",
        ),
        "awards_granted": (
            f("integer", None),
            "Number of whistleblower awards the Commission granted from 2014 through the end "
            "of calendar year 2025.",
        ),
        "award_matters": (
            f("integer", None),
            "Number of matters in which those whistleblower awards were granted.",
        ),
        "award_payments_total": (
            f("integer", "USD"),
            "Total whistleblower award payments from 2014 through the end of calendar year 2025.",
        ),
        "average_award_time": (
            f("number", "years"),
            "Average time from 2012 to 2025 from the award claim deadline to a Final Order "
            "granting an award, in years.",
        ),
        "tips_received_fy2025": (
            f("integer", None),
            "Number of whistleblower tips the Commission received in fiscal year 2025.",
        ),
    },
}

UNITS = {
    "fr-2026-20036": _REG_A_UNITS,
    "fr-2026-19887": {"pounds": {"suffix": ["pounds"]}},
    "fr-2026-19745": {"ft": {"suffix": ["feet"]}, "nmi": {"suffix": ["nautical miles", "nmi"]}},
    "fr-2026-19389": {"board_feet": {"suffix": ["board feet"]}},
    "fr-2026-19173": _ALMA_UNITS,
}

DRAFTS = {
    "fr-2026-20036": _REG_A_DRAFTS,
    "fr-2026-19966": {
        "state_regulation_issuance_cap": [
            "10000000000",
            "outstanding issuance of payment stablecoins of not more than [[$10 billion]]",
        ],
        "state_certification_fee": [None],
    },
    # The text says "$7.821 million" and "$8.049 million"; drafted as written.
    "fr-2026-19946": {
        "ucp_supplemental_total_fy2026": ["7821000", "estimated to be [[$7.821 million]]"],
        "ucp_supplemental_total_fy2027": ["8049000", "estimated to be [[$8.049 million]]"],
        "factor_1_amount_fy2027": [None],
    },
    "fr-2026-19929": {
        "umra_expenditure_threshold": [
            "100000000",
            "annual expenditure of more than [[$100 million]]",
        ],
        "estimated_annual_cost": [None],
    },
    "fr-2026-19887": {
        "almond_export_value": [
            "4115000000",
            "inshell) was [[$4.115 billion]]",
            "([[$4.115 billion]] divided by 1.783",
        ],
        "almond_export_quantity": [
            "1783000000",
            "over that period was [[1.783 billion pounds]]",
            "divided by [[1.783 billion pounds]] equals",
        ],
        "handler_price_per_pound": [
            "2.31",
            "yields a unit value of [[$2.31]] per shelled pound",
            "billion pounds equals [[$2.31]])",
            "Applying the [[$2.31]] derived",
            "pounds times [[$2.31]] per pound",
        ],
        "almond_production_2022": [
            "2511000000",
            "produced [[2.511 billion pounds]] of almonds in 2022",
            "([[2.511 billion pounds]] times",
        ],
        "handler_total_revenue": [
            "5800000000",
            "revenue at the handler level of [[$5.80 billion]]",
            "per pound equals [[$5.80 billion]])",
            "([[$5.80 billion]] divided by 100",
        ],
        "handler_count": [
            "100",
            "approximately [[100 handlers]] in the production area",
            "With an estimated [[100 handlers]]",
            "divided by [[100]] equals $58",
        ],
        "average_revenue_per_handler": [
            "58000000",
            "approximately [[$58 million]] (",
            "divided by 100 equals [[$58 million]]",
        ],
        "assessment_rate_per_pound": [None],
    },
    "fr-2026-19745": {
        "depth_min": ["35", "range from [[35]] to 55 feet"],
        "depth_max": ["55", "from 35 to [[55 feet]] of water"],
        "offshore_distance_min": ["1.7", "located between [[1.7 nautical miles]]"],
        "offshore_distance_max": ["2.7", "(nmi) and [[2.7 nmi]] offshore"],
        "monitoring_interval_years": [None],
    },
    "fr-2026-19666": {
        "closing_letter_fee_old": [
            "56",
            "letter from [[$56]] to $76. The Independent",
            "from [[$56]] to $76. The preamble",
        ],
        "closing_letter_fee_new": [
            "76",
            "letter from $56 to [[$76]]. The Independent",
            "from $56 to [[$76]]. The preamble",
        ],
        "annual_closing_letter_requests": [None],
    },
    "fr-2026-19493": {
        "unauthorized_enrollment_complaints_2023_2025": [
            "624000",
            "CMS received over [[624,000]] consumer complaints",
            "300,000 of the [[624,000]] consumer complaints",
        ],
        "moratorium_max_duration_days": [None],
    },
    # The matched sentence "The Board analyzed Customs and industry geographical data from 2022
    # through 2024 and found the U.S" holds only years; no field.
    "fr-2026-19389": {
        "industry_seats_old": ["14", "will increase from [[14]] to 15"],
        "industry_seats_new": ["15", "increase from 14 to [[15]], for a total"],
        "board_members_total": ["16", "for a total of [[16]] Board members"],
        "sba_small_firm_receipts": [
            "11500000",
            "annual receipts of no more than [[$11.5 million]]",
            "Dividing the [[$11.5 million]] threshold",
        ],
        "small_entity_max_volume": [
            "22000000",
            "maximum threshold of about [[22 million board feet]]",
        ],
        "small_manufacturer_count": [None],
    },
    "fr-2026-19173": _ALMA_DRAFTS,
    "fr-2026-19006": {
        "financial_remedies_total": [
            "3300000000",
            "resulting in over [[$3.3 billion]] in financial remedies",
        ],
        "returned_to_customers": ["160000000", "approximately [[$160 million]] (excluding"],
        "awards_granted": ["73", "Commission granted [[73 awards]] in 56"],
        "award_matters": ["56", "73 awards in [[56 matters]]"],
        "award_payments_total": ["395000000", "totaling over [[$395 million]] in award payments"],
        "average_award_time": ["2.5", "averaged more than [[2.5 years]]"],
        "tips_received_fy2025": [None],
    },
}
