"""Set-2 gold drafts: IRS publications, targeted groups (batch irs_targeted1). Written by a model
(Claude) from reading bench/set2/docs, after spec 0.2 was frozen. Not ground truth: a person
checks every fact."""

from __future__ import annotations

from typing import Any

from build import f

FIELDS: dict[str, dict[str, Any]] = {}
DRAFTS: dict[str, dict[str, Any]] = {}

USD = f("integer", "USD")
USD_LE = f("integer", "USD", "le")
USD_GE = f("integer", "USD", "ge")
PCT = f("number", "%")
PCT_LE = f("number", "%", "le")
COUNT = f("integer", None)


def add(doc: str, name: str, schema: dict, desc: str, entry: list) -> None:
    FIELDS.setdefault(doc, {})[name] = (schema, desc)
    DRAFTS.setdefault(doc, {})[name] = entry


# ---------------------------------------------------------------------------------- irs-p5
d = "irs-p5"
add(
    d,
    "net_worth_limit_individuals",
    USD_LE,
    "Net worth limit for individuals, estates or trusts to qualify as a prevailing party for "
    "recovering administrative and litigation costs.",
    ["2000000", "net worth cannot exceed [[$2,000,000]]"],
)
add(
    d,
    "max_attorney_fee_hourly_rate",
    USD_LE,
    "Maximum hourly rate for recoverable attorney fees, in dollars per hour.",
    [None],
)

# -------------------------------------------------------------------------------- irs-p15-a
# "15" in the second matched sentence is "Pub. 15", a publication number: not an amount.
d = "irs-p15-a"
add(
    d,
    "award_exclusion_limit_mixed_awards",
    USD_LE,
    "Limit on the exclusion for the total cost of all employee achievement awards to one "
    "employee in a year when the employee receives both qualified plan and nonqualified awards.",
    [
        "1600",
        "more than [[$1,600]]. The $400",
        "to exclude more than [[$1,600]] for the cost of awards",
    ],
)
add(
    d,
    "supplemental_wages_withholding_threshold",
    USD_GE,
    "Wages to an individual during the year above which the special rules for withholding "
    "federal income tax from supplemental wages apply (section 7 of Pub. 15).",
    ["1000000", "ex- ceed [[$1 million]] during the year"],
)
add(
    d,
    "social_security_wage_base_2026",
    USD_LE,
    "Maximum wages subject to social security tax for 2026.",
    [None],
)

# -------------------------------------------------------------------------------- irs-p15-t
d = "irs-p15-t"
add(
    d,
    "rounding_drop_below_cents",
    f("integer", "cents", "le"),
    "When rounding withheld tax to the nearest whole dollar, amounts under this many cents "
    "are dropped.",
    ["50", "dropping amounts un- der [[50 cents]]"],
)
add(
    d,
    "rounding_up_from_cents",
    f("integer", "cents"),
    "When rounding withheld tax, the lower end of the range of cents that is increased to the "
    "next dollar.",
    ["50", "increasing amounts from [[50]] to 99 cents"],
)
add(
    d,
    "rounding_up_to_cents",
    f("integer", "cents"),
    "When rounding withheld tax, the upper end of the range of cents that is increased to the "
    "next dollar.",
    ["99", "from 50 to [[99 cents]]"],
)
add(
    d,
    "part_year_employment_max_days",
    f("integer", "days", "le"),
    "Most days of continuous employment with all employers in the calendar year that an "
    "employee requesting the part-year employment method can reasonably anticipate.",
    ["245", "no more than [[245 days]]"],
)
add(
    d,
    "supplemental_wage_flat_rate",
    PCT,
    "Flat federal income tax withholding rate for supplemental wages.",
    [None],
)

# ---------------------------------------------------------------------------------- irs-p16
# Matched sentences are garbled twice: an author footnote interrupts the Educational Services
# sentence ("$66.6 billion Isaac Goodwin ... in 2021 to $92.0 billion"), and Figure A splits
# "from $528.8 ... billion to $633.3 billion". Skipped: "$528.8" (its scale word is cut off by
# the figure and it is not in a matched sentence) and "$604.2 bil- lion" (income tax, 2022):
# the line break splits "billion", so the evidence cannot write the scaled value.
d = "irs-p16"
p16 = [
    # (name, schema, description, value, contexts)
    ("total_assets_pct_increase", PCT,
     "Percentage increase in total assets reported for active corporations from 2021 to 2022.",
     "1.0", ["active corporations increased approximately [[1.0%]]"]),
    ("total_assets_2021", USD, "Total assets reported for active corporations in 2021.",
     "141900000000000", ["from [[$141.9 trillion]] in 2021"]),
    ("total_assets_2022", USD, "Total assets reported for active corporations in 2022.",
     "143300000000000", ["to [[$143.3 trillion]] in 2022"]),
    ("educational_services_assets_pct_increase", PCT,
     "Percentage increase in total assets of the Educational Services sector from 2021 to 2022.",
     "38.1", ["up [[38.1%]] from"]),
    ("educational_services_assets_2021", USD,
     "Total assets of the Educational Services sector in 2021.",
     "66600000000", ["from [[$66.6 billion]] Isaac"]),
    ("educational_services_assets_2022", USD,
     "Total assets of the Educational Services sector in 2022.",
     "92000000000", ["to [[$92.0 billion]] in 2022"]),
    ("finance_insurance_assets_pct_decrease", PCT,
     "Percentage decrease in total assets of the Finance and Insurance sector from 2021 to 2022.",
     "3.8", ["down [[3.8%]] from"]),
    ("finance_insurance_assets_2021", USD,
     "Total assets of the Finance and Insurance sector in 2021.",
     "70100000000000", ["[[$70.1 trillion]] in 2021"]),
    ("finance_insurance_assets_2022", USD,
     "Total assets of the Finance and Insurance sector in 2022.",
     "67400000000000", ["[[$67.4 trillion]] in 2022"]),
    ("total_receipts_pct_increase", PCT,
     "Percentage increase in total receipts from operations and investments, 2021 to 2022.",
     "13.9", ["investments increased [[13.9%]]"]),
    ("total_receipts_2021", USD, "Total receipts from operations and investments in 2021.",
     "39800000000000", ["[[$39.8 trillion]] in 2021"]),
    ("total_receipts_2022", USD, "Total receipts from operations and investments in 2022.",
     "45300000000000", ["[[$45.3 trillion]] the fol- lowing year"]),
    ("business_receipts_pct_increase", PCT,
     "Percentage increase in business receipts, 2021 to 2022.",
     "14.3", ["a [[14.3%]] increase in business receipts"]),
    ("business_receipts_2021", USD, "Business receipts in 2021.",
     "35000000000000", ["[[$35 trillion]] in 2021"]),
    ("business_receipts_2022", USD, "Business receipts in 2022.",
     "39900000000000", ["to [[$39.9 trillion]], as well"]),
    ("interest_receipts_pct_increase", PCT,
     "Percentage increase in interest (a component of total receipts), 2021 to 2022.",
     "49.2", ["a [[49.2%]] increase in interest"]),
    ("interest_receipts_2021", USD, "Interest received (a component of total receipts) in 2021.",
     "1200000000000", ["from [[$1.2 trillion]] to $1.8 trillion"]),
    ("interest_receipts_2022", USD, "Interest received (a component of total receipts) in 2022.",
     "1800000000000", ["to [[$1.8 trillion]]"]),
    ("short_term_capital_gains_pct_decrease", PCT,
     "Percentage decrease in short term capital gains, 2021 to 2022.",
     "84.8", ["decreased by [[84.8%]]"]),
    ("short_term_capital_gains_2021", USD, "Short term capital gains in 2021.",
     "177600000000", ["[[$177.6 billion]] in 2021"]),
    ("short_term_capital_gains_2022", USD, "Short term capital gains in 2022.",
     "27000000000", ["[[$27.0 billion]] in 2022"]),
    ("long_term_capital_gains_pct_decrease", PCT,
     "Percentage decrease in long term capital gains, 2021 to 2022.",
     "33.9", ["decreased by [[33.9%]]"]),
    ("long_term_capital_gains_2021", USD, "Long term capital gains in 2021.",
     "366300000000", ["[[$366.3 billion]] in 2021"]),
    ("long_term_capital_gains_2022", USD, "Long term capital gains in 2022.",
     "242000000000", ["[[$242.0 billion]] in 2022"]),
    ("mining_receipts_pct_increase", PCT,
     "Percentage increase in total receipts of the Mining sector, 2021 to 2022.",
     "37.7", ["up [[37.7%]] from"]),
    ("mining_receipts_2021", USD, "Total receipts of the Mining sector in 2021.",
     "464900000000", ["[[$464.9 billion]] in 2021"]),
    ("mining_receipts_2022", USD, "Total receipts of the Mining sector in 2022.",
     "639900000000", ["[[$639.9 billion]] in 2022"]),
    ("retail_trade_receipts_pct_increase", PCT,
     "Percentage increase in total receipts of the Retail Trade sector, 2021 to 2022.",
     "4.8", ["increase of [[4.8%]] from"]),
    ("retail_trade_receipts_2021", USD, "Total receipts of the Retail Trade sector in 2021.",
     "6000000000000", ["[[$6.0 trillion]] in 2021"]),
    ("retail_trade_receipts_2022", USD, "Total receipts of the Retail Trade sector in 2022.",
     "6200000000000", ["[[$6.2 trillion]] in 2022"]),
    ("total_deductions_pct_increase", PCT,
     "Percentage increase in total deductions, 2021 to 2022.",
     "13.5", ["Total deductions increased [[13.5%]]"]),
    ("total_deductions_2021", USD, "Total deductions in 2021.",
     "36400000000000", ["[[$36.4 trillion]] in 2021"]),
    ("total_deductions_2022", USD, "Total deductions in 2022.",
     "41300000000000", ["[[$41.3 trillion]] in 2022"]),
    ("interest_deduction_pct_increase", PCT,
     "Percentage increase in interest as a component of total deductions, 2021 to 2022.",
     "36", ["increased by [[36%]]"]),
    ("interest_deduction_2021", USD, "Interest deducted (a component of total deductions), 2021.",
     "710100000000", ["[[$710.1 billion]]"]),
    ("interest_deduction_2022", USD, "Interest deducted (a component of total deductions), 2022.",
     "965900000000", ["[[$965.9 billion]]"]),
    ("net_gain_loss_pct_increase", PCT,
     "Percentage increase in Net Gain/Loss (a component of total deductions), 2021 to 2022.",
     "54.1", ["increase of [[54.1%]]"]),
    ("net_gain_loss_2021", USD, "Net Gain/Loss (a component of total deductions) in 2021.",
     "47900000000", ["[[$47.9 billion]] in 2021"]),
    ("net_gain_loss_2022", USD, "Net Gain/Loss (a component of total deductions) in 2022.",
     "73800000000", ["[[$73.8 billion]] in 2022"]),
    ("pretax_profits_pct_increase", PCT,
     "Percentage increase in corporate pretax profits (net income less deficit), 2021 to 2022.",
     "17.7", ["increased [[17.7%]]"]),
    ("pretax_profits_2021", USD, "Corporate pretax profits (net income less deficit) in 2021.",
     "4100000000000", ["from [[$4.1 trillion]]"]),
    ("pretax_profits_2022", USD, "Corporate pretax profits (net income less deficit) in 2022.",
     "4800000000000", ["to [[$4.8 trillion]] (Figure B)"]),
    ("mining_pretax_profits_pct_increase", PCT,
     "Percentage increase in pretax profits of the Mining sector, 2021 to 2022.",
     "159.6", ["up [[159.6%]]"]),
    ("mining_pretax_profits_2021", USD, "Pretax profits of the Mining sector in 2021.",
     "41100000000", ["[[$41.1 billion]] in 2021"]),
    ("mining_pretax_profits_2022", USD, "Pretax profits of the Mining sector in 2022.",
     "106600000000", ["[[$106.6 billion]] in 2022"]),
    ("educational_services_net_income_pct_decrease", PCT,
     "Percentage decrease in net income of the Educational Services sector, 2021 to 2022.",
     "10.9", ["down [[10.9%]]"]),
    ("educational_services_net_income_2021", USD,
     "Net income of the Educational Services sector in 2021.",
     "4700000000", ["[[$4.7 billion]] in 2021"]),
    ("educational_services_net_income_2022", USD,
     "Net income of the Educational Services sector in 2022.",
     "4200000000", ["[[$4.2 billion]] in 2022"]),
    ("pretax_profits_excl_passthrough_2021", USD,
     "Pretax profits excluding passthrough entities in 2021.",
     "2600000000000", ["[[$2.6 trillion]] in 2021"]),
    ("pretax_profits_excl_passthrough_2022", USD,
     "Pretax profits excluding passthrough entities in 2022.",
     "3300000000000", ["[[$3.3 trillion]] in 2022"]),
    ("s_corp_pretax_profits_2022", USD, "Pretax profits reported by S corporations for 2022.",
     "763300000000", ["[[$763.3 billion]] in pretax profits"]),
    ("s_corp_pretax_profits_pct_increase", PCT,
     "Percentage increase in S corporation pretax profits from 2021 to 2022.",
     "1.1", ["increase of [[1.1%]] from 2021"]),
    ("ric_pretax_profits_2022", USD,
     "Pretax profits reported by regulated investment companies (RICs) for 2022.",
     "625400000000", ["[[$625.4 billion]]"]),
    ("ric_pretax_profits_pct_decrease", PCT,
     "Percentage decrease in RIC pretax profits from 2021 to 2022.",
     "2.9", ["down [[2.9%]] from 2021"]),
    ("reit_pretax_profits_2022", USD,
     "Pretax profits reported by real estate investment trusts (REITs) for 2022.",
     "97900000000", ["[[$97.9 billion]]"]),
    ("reit_pretax_profits_pct_increase", PCT,
     "Percentage increase in REIT pretax profits from 2021 to 2022.",
     "4.6", ["up [[4.6%]] from 2021"]),
    ("income_subject_to_tax_pct_increase", PCT,
     "Percentage increase in income subject to tax (the tax base), 2021 to 2022.",
     "18.9", ["increased [[18.9%]]"]),
    ("income_subject_to_tax_2021", USD, "Income subject to tax (the tax base) in 2021.",
     "2400000000000", ["[[$2.4 trillion]] in 2021"]),
    ("income_subject_to_tax_2022", USD, "Income subject to tax (the tax base) in 2022.",
     "2900000000000", ["[[$2.9 trillion]] in 2022"]),
    ("income_tax_before_credits_2022", USD, "Total income tax before credits in 2022.",
     "633300000000", ["[[$633.3 billion]] in 2022"]),
    ("income_tax_pct_increase", PCT,
     "Percentage increase in income tax during the year (2021 to 2022).",
     "18.8", ["[[18.8%]] during the year"]),
    ("income_tax_2021", USD, "Income tax in 2021 (the amount it increased from).",
     "508600000000", ["from [[$508.6 billion]]"]),
    ("income_tax_after_credits_pct_increase", PCT,
     "Percentage increase in total income tax after credits (paid to the U.S. Government), "
     "2021 to 2022.",
     "20.8", ["increased by [[20.8%]]"]),
    ("income_tax_after_credits_2021", USD, "Total income tax after credits in 2021.",
     "371400000000", ["[[$371.4 billion]] in 2021"]),
    ("income_tax_after_credits_2022", USD, "Total income tax after credits in 2022.",
     "448700000000", ["[[$448.7 billion]] in 2022"]),
    ("passthrough_pretax_profits_pct_decrease", PCT,
     "Percentage decrease in pretax profits for passthrough entities during 2022.",
     "0.4", ["decreased [[0.4%]]"]),
    ("passthrough_pretax_profits_decrease", USD,
     "Dollar decrease in pretax profits for passthrough entities during 2022.",
     "6200000000", ["([[$6.2 billion]])"]),
    ("non_passthrough_returns_2022", COUNT,
     "Number of non-passthrough corporate returns for TY 2022.",
     "1600000", ["remaining [[1.6 million]] non-passthrough"]),
    ("non_passthrough_total_receipts_2022", USD,
     "Total receipts reported by non-passthrough corporate returns for 2022.",
     "33600000000000", ["[[$33.6 trillion]]"]),
    ("non_passthrough_receipts_pct_increase", PCT,
     "Percentage increase in total receipts of non-passthrough corporate returns, 2021 to 2022.",
     "15.7", ["increase of [[15.7%]]"]),
    ("largest_size_class_asset_threshold", USD_GE,
     "Total assets at or above which a return is in the largest asset size class discussed "
     "(returns with total assets of this amount or more).",
     "2500000000", ["total assets of [[$2.5 billion]] or more",
                    "total assets greater than [[$2.5 billion]] had a tax liability for 2022",
                    "total assets greater than [[$2.5 billion]] had a tax liability for the year",
                    "[[$2,500,000,000]] or more ......................... 2022",
                    "[[$2,500,000,000]] or more ......................... Number"]),
    ("largest_size_class_share_of_returns", PCT,
     "Share of total returns represented by returns with total assets of $2.5 billion or more.",
     "0.07", ["[[0.07%]] of total returns"]),
    ("largest_size_class_share_of_assets", PCT,
     "Share of total assets held by returns with total assets of $2.5 billion or more.",
     "84.5", ["[[84.5%]] of total assets"]),
    ("large_returns_with_tax_liability_pct", PCT,
     "Share of all returns with net income and total assets greater than $2.5 billion that had "
     "a tax liability for 2022.",
     "48.6", ["Approximately [[48.6%]]"]),
    ("large_non_passthrough_returns_with_tax_liability_pct", PCT,
     "Excluding passthrough entities, share of returns with net income and total assets "
     "greater than $2.5 billion that had a tax liability.",
     "97.9", ["[[97.9%]] of returns reporting net income"]),
    ("section_179_max_deduction_before_2022", USD_LE,
     "Section 179 maximum expense deduction before the 2022 increase (the amount it increased "
     "from).",
     "1050000", ["increased from [[$1,050,000]]"]),
    ("section_179_max_deduction_2022", USD_LE,
     "Section 179 maximum expense deduction for tax years beginning in 2022.",
     "1080000", ["to [[$1,080,000]]. This limit"]),
    ("foreign_tax_credit_2022", USD,
     "Total foreign tax credit claimed by active corporations for 2022.",
     None, []),
]  # fmt: skip
for name, schema, desc, value, contexts in p16:
    add(d, name, schema, desc, [value, *contexts] if value else [None])

# ---------------------------------------------------------------------------------- irs-p17
# The PTC sentence ends at "may not" (a blank line splits it); its amount, 400%, is in the next
# sentence. Drafted anyway because it is the limit the matched sentence negates.
d = "irs-p17"
add(
    d,
    "research_expenditure_amortization_min_months",
    f("integer", "months", "ge"),
    "Shortest period over which taxpayers who elect to capitalize domestic research and "
    "experimental expenditures can deduct them ratably.",
    ["60", "not less than [[60 months]]"],
)
add(
    d,
    "ptc_former_household_income_limit_pct",
    PCT_LE,
    "Household income limit for the premium tax credit, as a percentage of the federal "
    "poverty line, that the ARP eliminated.",
    ["400", "exceed [[400%]] of the federal poverty"],
)
add(
    d,
    "fiscal_year_52_53_min_weeks",
    f("integer", "weeks"),
    "Shortest length, in weeks, of a 52-53-week fiscal year.",
    ["52", "varies from [[52]] to 53"],
)
add(
    d,
    "fiscal_year_52_53_max_weeks",
    f("integer", "weeks"),
    "Longest length, in weeks, of a 52-53-week fiscal year.",
    ["53", "varies from 52 to [[53 weeks]]"],
)
add(
    d,
    "rounding_drop_below_cents",
    f("integer", "cents", "le"),
    "When rounding off dollars on the return, amounts under this many cents are dropped.",
    ["50", "drop amounts under [[50 cents]]"],
)
add(
    d,
    "rounding_up_from_cents",
    f("integer", "cents"),
    "When rounding off dollars on the return, the lower end of the range of cents increased "
    "to the next dollar.",
    ["50", "increase amounts from [[50]] to 99"],
)
add(
    d,
    "rounding_up_to_cents",
    f("integer", "cents"),
    "When rounding off dollars on the return, the upper end of the range of cents increased "
    "to the next dollar.",
    ["99", "from 50 to [[99 cents]] to the next dollar"],
)
add(
    d,
    "standard_deduction_single_2025",
    USD,
    "Standard deduction for a single filer for 2025.",
    [None],
)

# ---------------------------------------------------------------------------------- irs-p54
d = "irs-p54"
add(
    d,
    "foreign_tax_exemption_limit",
    USD_LE,
    "Most qualifying foreign taxes for the year, for filers other than joint filers, to be "
    "exempt from the foreign tax credit limit and from filing Form 1116.",
    ["300", "not more than [[$300]] ($600"],
)
add(
    d,
    "foreign_tax_exemption_limit_joint",
    USD_LE,
    "Most qualifying foreign taxes for the year, on a joint return, to be exempt from the "
    "foreign tax credit limit and from filing Form 1116.",
    ["600", "([[$600]] if you are filing a joint"],
)
add(
    d,
    "earned_share_of_net_income_limit_pct",
    PCT_LE,
    "When both capital and personal services produce business income, the most of net "
    "income (net profit) that is considered earned income.",
    [
        "30",
        "No more than [[30%]] of your net income",
        "($54,147 x [[30%]] (0.30))",
        "the earned income limit of [[30%]] of your net profit",
    ],
)
add(
    d,
    "example3_earned_income_limit",
    USD_LE,
    "In Example 3, the most of net income considered earned and excludable (30% of $54,147).",
    ["16244", "or [[$16,244]] ($54,147", "Your exclusion of [[$16,244]] is"],
)
add(
    d,
    "example2_net_income",
    USD,
    "Net income (profit) of the self-employed taxpayer in Example 2 (also used in Example 3).",
    ["54147", "net income (profit) was [[$54,147]]", "([[$54,147]] x 30%"],
)
add(
    d,
    "foreign_earned_income_exclusion_max_2025",
    USD_LE,
    "Maximum foreign earned income exclusion for 2025.",
    [None],
)

# -------------------------------------------------------------------------------- irs-p55-b
# "FY 2025" is a year, not an amount.
d = "irs-p55-b"
add(
    d,
    "gross_collections_fy2025",
    USD,
    "Gross taxes (revenue) the IRS collected in FY 2025.",
    [
        "5300000000000",
        "collected more than [[$5.3 trillion]] in revenue",
        "collected [[$5.3 trillion]] in gross taxes",
    ],
)
add(
    d,
    "returns_processed_fy2025",
    COUNT,
    "Number of tax returns and other forms (supplemental documents) the IRS processed in FY 2025.",
    [
        "271400000",
        "processed more than [[271.4 million]] tax returns",
        "processed [[271.4 million]] federal tax returns",
    ],
)
add(
    d,
    "individual_returns_processed_fy2025",
    COUNT,
    "Number of individual income tax returns the IRS processed in FY 2025.",
    ["162800000", "almost [[162.8 million]] individual"],
)
add(
    d,
    "refunds_issued_fy2025",
    COUNT,
    "Number of refunds (all types) the IRS issued in FY 2025.",
    ["120600000", "issued [[120.6 million]] refunds (Table 1-7)"],
)
add(
    d,
    "refunds_amount_fy2025",
    USD,
    "Total amount of refunds (all types) the IRS issued in FY 2025.",
    ["638800000000", "amounting to [[$638.8 billion]]"],
)
add(
    d,
    "individual_withholding_and_payments_fy2025",
    USD,
    "Individual income tax withheld and tax payments combined, before refunds, in FY 2025.",
    ["2900000000000", "totaled [[$2.9 trillion]] before refunds"],
)
add(
    d,
    "business_income_taxes_fy2025",
    USD,
    "Income taxes the IRS collected from businesses, before refunds, in FY 2025.",
    ["486400000000", "collected [[$486.4 billion]]"],
)
add(
    d,
    "individual_refunds_fy2025",
    COUNT,
    "Number of refunds the IRS issued to individuals in FY 2025.",
    ["116900000", "issued [[116.9 million]] refunds"],
)
add(
    d,
    "individual_refunds_amount_fy2025",
    USD,
    "Total amount of refunds the IRS issued to individuals in FY 2025.",
    ["516400000000", "to [[$516.4 billion]]"],
)
add(d, "irs_budget_fy2025", USD, "Total IRS budget (appropriations) for FY 2025.", [None])

# --------------------------------------------------------------------------------- irs-p225
d = "irs-p225"
add(
    d,
    "research_expense_amortization_min_months",
    f("integer", "months", "ge"),
    "Shortest period over which R&E expenses charged to a capital account can be amortized.",
    ["60", "no less than [[60 months]]"],
)
add(
    d,
    "cash_method_gross_receipts_limit_2025",
    USD_LE,
    "For tax years beginning in 2025, the most average annual gross receipts a farm "
    "corporation or partnership can have and still use the cash method.",
    ["31000000", "gross re- ceipts of [[$31 million]] or less"],
)
add(
    d,
    "cash_method_gross_receipts_years",
    COUNT,
    "Number of preceding tax years averaged for the gross receipts test that lets farm "
    "corporations and partnerships use the cash method.",
    ["3", "or less for the [[3]] preceding tax years and are not"],
)
add(
    d,
    "inventory_exception_gross_receipts_limit_2025",
    USD_LE,
    "For tax years beginning in 2025, the most average annual gross receipts a farm can "
    "have and not be required to maintain an inventory.",
    ["31000000", "for the farm is [[$31 million]] or less"],
)
add(
    d,
    "inventory_exception_gross_receipts_years",
    COUNT,
    "Number of preceding tax years averaged for the gross receipts test of the inventory "
    "exception.",
    ["3", "for the [[3]] pre- ceding tax years for the farm"],
)
add(
    d,
    "section_179_max_deduction_2025",
    USD_LE,
    "Maximum section 179 expense deduction for 2025.",
    [None],
)

# --------------------------------------------------------------------------------- irs-p334
# "Publication 334 (2025)" is a page header, not an amount.
d = "irs-p334"
add(
    d,
    "section_179_max_deduction_2025",
    USD_LE,
    "Maximum section 179 expense deduction beginning in 2025.",
    ["2500000", "deduc- tion is [[$2.5 million]]"],
)
add(
    d,
    "section_179_phaseout_threshold_2025",
    USD_GE,
    "Cost of section 179 property placed in service in the tax year above which the 2025 "
    "maximum deduction is reduced.",
    ["4000000", "exceeds [[$4 million]]. See"],
)
add(
    d,
    "reportable_loss_single_year",
    USD_GE,
    "Loss in any single tax year at which a transaction is a reportable (loss) transaction.",
    ["2000000", "losses of at least [[$2 million]]"],
)
add(
    d,
    "reportable_loss_single_year_foreign_currency",
    USD_GE,
    "Loss in any single tax year at which certain foreign currency transactions are reportable.",
    ["50000", "([[$50,000]] if from certain foreign"],
)
add(
    d,
    "reportable_loss_combined_years",
    USD_GE,
    "Loss in any combination of tax years at which a transaction is reportable.",
    ["4000000", "or [[$4 million]] in any combina- tion"],
)
add(
    d,
    "sbse_small_business_asset_limit",
    USD_LE,
    "Assets under which small business taxpayers are served by the SB/SE Tax Center.",
    ["10000000", "assets un- der [[$10 million]]"],
)
add(
    d,
    "fiscal_year_52_53_min_weeks",
    f("integer", "weeks"),
    "Shortest length, in weeks, of a 52-53-week tax year.",
    ["52", "varies from [[52]] to 53"],
)
add(
    d,
    "fiscal_year_52_53_max_weeks",
    f("integer", "weeks"),
    "Longest length, in weeks, of a 52-53-week tax year.",
    ["53", "[[53 weeks]] but does not"],
)
add(
    d,
    "home_office_simplified_rate",
    USD,
    "Rate per square foot for the simplified method of the business use of home deduction.",
    [None],
)

# --------------------------------------------------------------------------------- irs-p502
d = "irs-p502"
add(
    d,
    "medical_lodging_limit_per_night",
    USD_LE,
    "Most that can be included in medical expenses for lodging, per night for each person.",
    ["50", "more than [[$50]] for each night"],
)
add(
    d,
    "medical_expense_agi_floor_pct",
    PCT,
    "Percentage of adjusted gross income that medical expenses must exceed to be deductible.",
    [None],
)

# --------------------------------------------------------------------------------- irs-p503
# The first matched sentence ("can't be more than:") has no amount.
d = "irs-p503"
add(
    d,
    "example_expense_limit",
    USD_LE,
    "In the earned income limit example (remarried on December 3), the most work-related "
    "expenses that can be used to figure the credit.",
    ["2000", "more than [[$2,000]] (the smaller"],
)
add(
    d,
    "max_credit_percentage",
    PCT,
    "Highest percentage of work-related expenses allowed as the child and dependent care credit.",
    [None],
)

# --------------------------------------------------------------------------------- irs-p504
# The first matched sentence ends at "6" (a blank line before "months"); the ages 18 and 21 on
# the next line are outside it and not drafted.
d = "irs-p504"
add(
    d,
    "child_contingency_window_months",
    f("integer", "months", "le"),
    "Payments reduced within this many months before or after a child reaches 18, 21 or the "
    "local age of majority are presumed associated with a child contingency.",
    ["6", "reduced not more than [[6 months]] before"],
)
add(
    d,
    "multiple_reductions_window_years",
    f("integer", "years", "le"),
    "For reductions on two or more occasions, the window, in years, before or after each "
    "child reaches a certain age.",
    ["1", "not more than [[1 year]] before or after"],
)
add(
    d,
    "multiple_reductions_min_age",
    COUNT,
    "Lower end of the range of ages (the certain age each child reaches) for payments "
    "reduced on two or more occasions.",
    ["18", "certain age from [[18]] to 24"],
)
add(
    d,
    "multiple_reductions_max_age",
    COUNT,
    "Upper end of the range of ages (the certain age each child reaches) for payments "
    "reduced on two or more occasions.",
    ["24", "certain age from 18 to [[24]]"],
)
add(
    d,
    "alimony_recapture_threshold",
    USD,
    "Amount by which alimony payments must decrease in the third year for recapture to apply.",
    [None],
)

# --------------------------------------------------------------------------------- irs-p509
# "3:00 p.m" and "8 p.m" are times of day, not amounts.
d = "irs-p509"
add(
    d,
    "eftps_same_day_payment_limit",
    USD_LE,
    "Largest payment EFTPS accepts as a same-day payment.",
    ["1000000", "same-day payments of [[$1 million]] or less"],
)
add(
    d,
    "eftps_prior_day_payment_threshold",
    USD_GE,
    "Payment amount above which the deposit must be submitted by 8 p.m. Eastern time the day "
    "before the due date.",
    ["1000000", "more than [[$1 million]], you must"],
)
add(
    d,
    "form_2553_due_months",
    f("integer", "months", "le"),
    "Months part of the latest due date of Form 2553 after the beginning of the tax year the "
    "S election is to take effect (with the days part).",
    ["2", "no more than [[2 months]] and 15 days"],
)
add(
    d,
    "form_2553_due_days",
    f("integer", "days", "le"),
    "Days part of the latest due date of Form 2553 after the beginning of the tax year the S "
    "election is to take effect (with the months part).",
    ["15", "months and [[15 days]] after the beginning"],
)
add(
    d,
    "failure_to_deposit_penalty_pct",
    PCT,
    "Percentage penalty for a federal tax deposit made late.",
    [None],
)
