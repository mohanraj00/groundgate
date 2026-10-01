"""Set-2 gold drafts: IRS publications, general group. Written by a model (Claude) from reading
bench/set2/docs, after spec 0.2 was frozen. Not ground truth: a person checks every fact."""

from __future__ import annotations

from build import f

USD = f()
USD_LE = f(comparator="le")
USD_GE = f(comparator="ge")
PCT = f("number", "%")
PCT_LE = f("number", "%", "le")
CENTS = f("number", "cents")
COUNT = f("integer", None)
DAYS_GE = f("integer", "days", "ge")
DAYS_LE = f("integer", "days", "le")

DAYS = {"days": {"suffix": ["days", "day"]}}

UNITS = {
    "irs-p561": {"times": {"suffix": ["times"]}},
    "irs-p783": DAYS,
    "irs-p784": DAYS,
    "irs-p962": {"years": {"suffix": ["years", "year"]}},
    "irs-p1321": DAYS,
}

FIELDS = {
    "irs-p3": {
        "late_filing_min_penalty": (
            USD,
            "Minimum penalty for a return filed more than 60 days late (unless the tax owed is "
            "smaller).",
        ),
        "standard_deduction_single_2025": (
            USD,
            "2025 standard deduction, single or married filing separately.",
        ),
        "standard_deduction_joint_2025": (
            USD,
            "2025 standard deduction, married filing jointly or qualifying surviving spouse.",
        ),
        "standard_deduction_hoh_2025": (USD, "2025 standard deduction, head of household."),
        "child_tax_credit_max_2025": (
            USD_LE,
            "Maximum child tax credit per qualifying child, beginning in 2025.",
        ),
        "form_1099k_threshold_amount_2025": (
            USD_GE,
            "2025 amount of business transactions above which payment card companies, payment "
            "apps and online marketplaces must send a Form 1099-K.",
        ),
        "form_1099k_threshold_transactions_2025": (
            COUNT | {"comparator": "ge"},
            "2025 number of transactions above which a Form 1099-K must be sent.",
        ),
        "business_mileage_rate_2025": (CENTS, "2025 standard mileage rate for business use."),
        "charitable_mileage_rate_2025": (
            CENTS,
            "2025 standard mileage rate for volunteer work for charitable organizations.",
        ),
        "medical_mileage_rate_2025": (
            CENTS,
            "2025 standard mileage rate for car operating expenses for medical reasons.",
        ),
        "catch_up_limit_age_60_to_63_2025": (
            USD_LE,
            "2025 higher catch-up contribution limit for participants aged 60 to 63 in a "
            "deferred compensation plan.",
        ),
        "ira_deduction_phaseout_start_joint_2025": (
            USD_GE,
            "2025 modified AGI above which the traditional IRA deduction phases out for a "
            "married couple filing jointly (or qualifying surviving spouse) covered by a "
            "retirement plan at work.",
        ),
        "ira_deduction_phaseout_start_single_2025": (
            USD_GE,
            "2025 modified AGI above which the traditional IRA deduction phases out for a single "
            "individual or head of household covered by a retirement plan at work.",
        ),
        "roth_ira_no_contribution_magi_joint_2025": (
            USD_GE,
            "2025 modified AGI at or above which a married couple filing jointly (or qualifying "
            "surviving spouse) can't make a Roth IRA contribution.",
        ),
        "combat_zone_exclusion_officer_monthly_cap": (
            USD_LE,
            "Monthly limit on the combat zone pay exclusion for commissioned officers.",
        ),
    },
    "irs-p517": {
        "tips_deduction_max": (USD_LE, "Maximum deduction for qualified tips (no tax on tips)."),
        "tips_deduction_magi_threshold": (
            USD_GE,
            "Modified AGI above which the no-tax-on-tips deduction is limited, not married "
            "filing jointly.",
        ),
        "tips_deduction_magi_threshold_joint": (
            USD_GE,
            "Modified AGI above which the no-tax-on-tips deduction is limited, married filing "
            "jointly.",
        ),
        "overtime_deduction_max": (
            USD_LE,
            "Maximum deduction for qualified overtime compensation, not married filing jointly.",
        ),
        "overtime_deduction_max_joint": (
            USD_LE,
            "Maximum deduction for qualified overtime compensation, married filing jointly.",
        ),
        "car_loan_interest_deduction_max": (
            USD_LE,
            "Maximum deduction for qualified passenger vehicle loan interest.",
        ),
        "car_loan_interest_phaseout_magi": (
            USD_GE,
            "Modified AGI above which the car loan interest deduction begins to phase out, not "
            "married filing jointly.",
        ),
        "car_loan_interest_phaseout_magi_joint": (
            USD_GE,
            "Modified AGI above which the car loan interest deduction begins to phase out, "
            "married filing jointly.",
        ),
        "senior_deduction_magi_threshold": (
            USD_GE,
            "Modified AGI above which the enhanced deduction for seniors is limited, not married "
            "filing jointly.",
        ),
        "senior_deduction_max": (USD_LE, "Maximum enhanced deduction for seniors, per person."),
        "senior_deduction_max_both_spouses": (
            USD_LE,
            "Maximum enhanced deduction for seniors when both spouses are eligible.",
        ),
        "business_mileage_rate_2025": (CENTS, "2025 business standard mileage rate."),
        "social_security_wage_base_2025": (
            USD_LE,
            "2025 maximum wages and self-employment income subject to social security tax.",
        ),
        "roth_ira_magi_limit_single_2025": (
            USD_LE,
            "2025 modified AGI a single or head of household filer (or married filing "
            "separately, not living with the spouse) must be under to contribute to a Roth IRA.",
        ),
        "eic_max_income_2025": (
            USD_LE,
            "2025 maximum income a taxpayer can earn and still claim the earned income credit.",
        ),
    },
    "irs-p527": {
        "car_mileage_rate_2025": (
            CENTS,
            "2025 standard mileage rate for operating a car, van, pickup or panel truck.",
        ),
        "bonus_depreciation_pct": (
            PCT,
            "Special depreciation allowance restored for qualified property acquired and placed "
            "in service after January 19, 2025.",
        ),
        "section_179_max_2025": (
            USD_LE,
            "Maximum section 179 expense deduction for tax years beginning in 2025.",
        ),
        "section_179_phaseout_threshold_2025": (
            USD_GE,
            "Cost of section 179 property placed in service above which the 2025 section 179 "
            "limit is reduced.",
        ),
        "salt_limit": (
            USD_LE,
            "Overall limit on the state and local tax deduction, not married filing separately.",
        ),
        "salt_limit_mfs": (
            USD_LE,
            "Overall limit on the state and local tax deduction, married filing separately.",
        ),
        "salt_limit_magi_threshold": (
            USD_GE,
            "Modified AGI above which the SALT limit is reduced, not married filing separately.",
        ),
        "salt_limit_magi_threshold_mfs": (
            USD_GE,
            "Modified AGI above which the SALT limit is reduced, married filing separately.",
        ),
        "salt_limit_floor": (
            USD_GE,
            "Amount below which the SALT limit is not reduced, not married filing separately.",
        ),
        "salt_limit_floor_mfs": (
            USD_GE,
            "Amount below which the SALT limit is not reduced, married filing separately.",
        ),
        "niit_rate": (PCT, "Net investment income tax rate."),
        "passive_rental_loss_special_allowance": (
            USD_LE,
            "Special allowance for rental real estate losses of taxpayers who actively "
            "participate.",
        ),
    },
    "irs-p561": {
        "conservation_contribution_basis_multiple": (
            f("number", "times", "ge"),
            "Multiple of the sum of each ultimate member's relevant basis above which a "
            "partnership's or S corporation's conservation contribution is not treated as a "
            "qualified conservation contribution.",
        ),
        "option_example_exercise_price": (
            USD,
            "Options example: price at which the university could buy the real property under "
            "the option (the exercise price).",
        ),
        "option_example_fmv_at_grant": (
            USD,
            "Options example: FMV of the property on the date the option is granted.",
        ),
        "option_example_fmv_at_exercise": (
            USD,
            "Options example: FMV of the property on the date the option is exercised.",
        ),
        "option_example_contribution": (
            USD,
            "Options example: charitable contribution made in the year the option is exercised.",
        ),
        "gems_example_purchase_price": (
            USD,
            "Bailey Morgan example: price paid for the assortment of gems.",
        ),
        "gems_example_promoter_deduction": (
            USD,
            "Bailey Morgan example: charitable deduction the promoter said Bailey could claim.",
        ),
        "painting_example_cost": (USD, "Corey Brown example: price paid for the painting."),
        "painting_example_claimed_deduction": (
            USD,
            "Corey Brown example: charitable contribution deduction claimed for the painting.",
        ),
        "painting_example_value_increase_pct": (
            PCT,
            "Corey Brown example: increase in value over the 13 months the appraisal must justify.",
        ),
        "qualified_appraisal_threshold": (
            USD_GE,
            "Claimed deduction for a donated item above which a qualified appraisal is required.",
        ),
    },
    "irs-p783": {
        "application_lead_time_days": (
            DAYS_GE,
            "How many days before the transaction date the discharge application should be "
            "submitted, at least.",
        ),
        "third_party_suit_deadline_days": (
            DAYS_LE,
            "Days a property owner who is not the taxpayer has to file an action in federal "
            "district court after a deposit or bond under 6325(b)(4).",
        ),
        "b1_example_tax_liability": (USD, "6325(b)(1) example: tax liability."),
        "b1_example_other_debts": (USD, "6325(b)(1) example: other debts."),
        "b1_example_total_debts": (USD, "6325(b)(1) example: tax liability plus other debts."),
        "b1_example_min_remaining_property": (
            USD_GE,
            "6325(b)(1) example: value the property remaining subject to the lien must reach.",
        ),
        "b2a_example_lien_total": (USD, "6325(b)(2)(A) example: total IRS lien."),
        "b2a_example_sale_price": (USD, "6325(b)(2)(A) example: price the property sells for."),
        "b2a_example_senior_encumbrances": (
            USD,
            "6325(b)(2)(A) example: encumbrances senior to the IRS lien.",
        ),
        "b2a_example_settlement_costs": (
            USD,
            "6325(b)(2)(A) example: proposed settlement costs.",
        ),
        "b2a_example_lien_interest": (
            USD,
            "6325(b)(2)(A) example: IRS lien interest in the property, paid in partial "
            "satisfaction.",
        ),
        "b2a_example_remaining_debt": (
            USD,
            "6325(b)(2)(A) example: tax debt outstanding after the partial payment.",
        ),
        "b3_example_government_interest": (
            USD,
            "6325(b)(3) example: government's interest in the property.",
        ),
        "discharge_application_fee": (USD, "Fee for applying for a certificate of discharge."),
    },
    "irs-p784": {
        "application_lead_time_days": (
            DAYS_GE,
            "How many days before the transaction date the subordination application should be "
            "submitted, at least.",
        ),
        "example_loan_to_value_pct": (PCT, "Refinance example: loan-to-value ratio."),
        "example_closing_cost_pct": (PCT, "Refinance example: closing cost to financing ratio."),
        "example_fair_market_value": (USD, "Refinance example: fair market value of the property."),
        "example_refinance_amount": (USD, "Refinance example: new refinance loan amount."),
        "example_closing_costs": (USD, "Refinance example: closing costs to obtain the loan."),
        "example_united_states_interest": (
            USD,
            "Refinance example: United States' interest, the amount the IRS would ask for.",
        ),
        "example_existing_loan": (USD, "Refinance example: original (existing) loan paid off."),
        "example_potential_equity": (
            USD,
            "Refinance example: potential equity before closing costs.",
        ),
        "aaa_example_monthly_payment_current": (
            USD,
            "AAA Auto Sales example: current monthly payment to the IRS.",
        ),
        "aaa_example_tax_debt": (USD, "AAA Auto Sales example: tax debt."),
        "aaa_example_monthly_payment_proposed": (
            USD,
            "AAA Auto Sales example: monthly payment after the inventory replenishment.",
        ),
        "aaa_example_inventory_cars": (
            COUNT,
            "AAA Auto Sales example: number of cars in the inventory replenishment.",
        ),
        "subordination_application_fee": (
            USD,
            "Fee for applying for a certificate of subordination.",
        ),
    },
    "irs-p936": {
        "mortgage_debt_limit": (
            USD_LE,
            "Home acquisition debt on which interest is deductible, for debt incurred after "
            "December 15, 2017, not married filing separately.",
        ),
        "mortgage_debt_limit_mfs": (
            USD_LE,
            "The same limit (debt incurred after December 15, 2017), married filing separately.",
        ),
        "mortgage_debt_limit_pre_2017": (
            USD_LE,
            "Higher debt limit for mortgage interest on indebtedness incurred before December "
            "16, 2017, not married filing separately.",
        ),
        "mortgage_debt_limit_pre_2017_mfs": (
            USD_LE,
            "The same higher limit (debt incurred before December 16, 2017), married filing "
            "separately.",
        ),
        "home_equity_debt_limit": (
            USD_LE,
            "Limit on home equity debt on which interest is deductible.",
        ),
    },
    "irs-p962": {
        "average_eitc_2024": (USD, "Average EITC received nationwide in tax year 2024."),
        "investment_income_limit": (
            USD_LE,
            "Investment income the taxpayer must have less than to claim the EITC.",
        ),
        "max_eitc_no_child_2025": (USD_LE, "Maximum EITC for tax year 2025, no qualifying child."),
        "max_eitc_one_child_2025": (USD_LE, "Maximum EITC for tax year 2025, 1 qualifying child."),
        "max_eitc_two_children_2025": (
            USD_LE,
            "Maximum EITC for tax year 2025, 2 qualifying children.",
        ),
        "max_eitc_three_children_2025": (
            USD_LE,
            "Maximum EITC for tax year 2025, 3 qualifying children.",
        ),
        "income_limit_no_child": (
            USD_LE,
            "Maximum income limit for the EITC, no qualifying child, not married filing jointly.",
        ),
        "income_limit_no_child_joint": (
            USD_LE,
            "Maximum income limit for the EITC, no qualifying child, married filing jointly.",
        ),
        "income_limit_one_child": (
            USD_LE,
            "Maximum income limit for the EITC, 1 qualifying child, not married filing jointly.",
        ),
        "income_limit_one_child_joint": (
            USD_LE,
            "Maximum income limit for the EITC, 1 qualifying child, married filing jointly.",
        ),
        "income_limit_two_children": (
            USD_LE,
            "Maximum income limit for the EITC, 2 qualifying children, not married filing jointly.",
        ),
        "income_limit_two_children_joint": (
            USD_LE,
            "Maximum income limit for the EITC, 2 qualifying children, married filing jointly.",
        ),
        "income_limit_three_children": (
            USD_LE,
            "Maximum income limit for the EITC, 3 qualifying children, not married filing jointly.",
        ),
        "income_limit_three_children_joint": (
            USD_LE,
            "Maximum income limit for the EITC, 3 qualifying children, married filing jointly.",
        ),
        "self_only_min_age": (
            f("integer", "years", "ge"),
            "Minimum age to claim the self-only EITC without a qualifying child.",
        ),
    },
    "irs-p1136": {
        "high_income_returns_2022": (
            f("integer", None, "le"),
            "Number of individual income tax returns for TY 2022 with AGI of $200,000 or more.",
        ),
        "high_income_share_2022": (
            PCT,
            "Share of all TY 2022 returns that had AGI of $200,000 or more.",
        ),
        "high_income_no_tax_returns_2022": (
            COUNT,
            "TY 2022 returns with AGI of $200,000 or more and no worldwide income tax liability.",
        ),
        "high_income_no_tax_increase_pct_2022": (
            PCT,
            "Increase from the previous year in TY 2022 high-income returns with no worldwide "
            "income tax liability.",
        ),
        "high_income_no_tax_peak_2008": (
            COUNT,
            "Peak number of high-income returns with no worldwide income tax liability, TY 2008.",
        ),
        "cdcc_expense_limit_one_2022": (
            USD_LE,
            "TY 2022 child and dependent care credit dollar limit on qualifying expenses, one "
            "qualifying person.",
        ),
        "cdcc_expense_limit_two_2022": (
            USD_LE,
            "TY 2022 child and dependent care credit dollar limit on qualifying expenses, two or "
            "more qualifying persons.",
        ),
        "cdcc_max_pct_2022": (
            PCT_LE,
            "TY 2022 maximum percentage of qualifying expenses eligible for the child and "
            "dependent care credit.",
        ),
        "cdcc_phaseout_income_2022": (
            USD_GE,
            "TY 2022 income at which the child and dependent care credit began phasing out.",
        ),
        "dependent_care_exclusion_2022": (
            USD_LE,
            "TY 2022 dollar limit on the exclusion for employer dependent care benefits.",
        ),
        "dependent_care_exclusion_mfs_2022": (
            USD_LE,
            "TY 2022 maximum dependent care benefits exclusion, married employees filing "
            "separate returns.",
        ),
        "child_tax_credit_max_2022": (
            USD_LE,
            "TY 2022 maximum child tax credit per qualifying child.",
        ),
        "additional_child_tax_credit_max_2022": (
            USD_LE,
            "TY 2022 maximum additional child tax credit per qualifying child.",
        ),
        "credit_other_dependents_2022": (USD, "TY 2022 credit for other dependents."),
        "high_income_average_agi_2022": (
            USD,
            "Average AGI of TY 2022 returns with AGI of $200,000 or more.",
        ),
    },
    "irs-p1321": {
        "std_deduction_single_under_65": (
            USD,
            "Worksheet line 1 standard deduction, single, under 65.",
        ),
        "std_deduction_single_65_or_older": (
            USD,
            "Worksheet line 1 standard deduction, single, 65 or older.",
        ),
        "std_deduction_joint_both_under_65": (
            USD,
            "Worksheet line 1 standard deduction, married filing jointly, both under 65.",
        ),
        "std_deduction_joint_one_65_or_older": (
            USD,
            "Worksheet line 1 standard deduction, married filing jointly, one 65 or older.",
        ),
        "std_deduction_joint_both_65_or_older": (
            USD,
            "Worksheet line 1 standard deduction, married filing jointly, both 65 or older.",
        ),
        "std_deduction_hoh_under_65": (
            USD,
            "Worksheet line 1 standard deduction, head of household, under 65.",
        ),
        "std_deduction_hoh_65_or_older": (
            USD,
            "Worksheet line 1 standard deduction, head of household, 65 or older.",
        ),
        "std_deduction_qss_under_65": (
            USD,
            "Worksheet line 1 standard deduction, qualifying surviving spouse, under 65.",
        ),
        "std_deduction_qss_65_or_older": (
            USD,
            "Worksheet line 1 standard deduction, qualifying surviving spouse, 65 or older.",
        ),
        "filing_threshold_mfs": (
            USD_GE,
            "Gross income subject to U.S. tax at or above which a bona fide resident of Puerto "
            "Rico married filing separately must file a return.",
        ),
        "presence_test_days": (
            DAYS_GE,
            "Days in Puerto Rico needed to meet the presence test.",
        ),
    },
}

DRAFTS = {
    "irs-p3": {
        "late_filing_min_penalty": ["525", "the minimum penalty will be [[$525]] or the amount"],
        "standard_deduction_single_2025": ["15750", "Married filing separately—[[$15,750]];"],
        "standard_deduction_joint_2025": ["31500", "spouse—[[$31,500]]; and"],
        "standard_deduction_hoh_2025": ["23625", "Head of household—[[$23,625]]."],
        "child_tax_credit_max_2025": [
            "2200",
            "has increased to [[$2,200]] for each qualifying child",
        ],
        "form_1099k_threshold_amount_2025": [
            "20000",
            "during the year is more than [[$20,000]] in more than 200",
        ],
        "form_1099k_threshold_transactions_2025": [
            "200",
            "more than $20,000 in more than [[200]] transactions",
        ],
        "business_mileage_rate_2025": ["70", "business use of a vehicle is [[70 cents]] a mile"],
        "charitable_mileage_rate_2025": ["14", "ganizations is [[14 cents]] a mile"],
        "medical_mileage_rate_2025": ["21", "medical reasons is [[21 cents]] a mile"],
        "catch_up_limit_age_60_to_63_2025": [
            "11250",
            "catch-up contribution limit is [[$11,250]].",
        ],
        "ira_deduction_phaseout_start_joint_2025": [
            "126000",
            "More than [[$126,000]] but less than $146,000",
        ],
        "ira_deduction_phaseout_start_single_2025": [
            "79000",
            "More than [[$79,000]] but less than $89,000",
        ],
        "roth_ira_no_contribution_magi_joint_2025": [
            "246000",
            "You can't make a Roth IRA contribution if your modified AGI is [[$246,000]] or more.",
        ],
        "combat_zone_exclusion_officer_monthly_cap": [None],
    },
    "irs-p517": {
        "tips_deduction_max": ["25000", "You can't deduct more than [[$25,000]]"],
        "tips_deduction_magi_threshold": [
            "150000",
            "can't deduct more than $25,000 of those tips. Your deduction will be limited if your modified adjusted gross income is more than [[$150,000]]",
        ],
        "tips_deduction_magi_threshold_joint": [
            "300000",
            "more than $150,000 ([[$300,000]] if married filing jointly). To be eligible, you and/or your spouse who received the tips",
        ],
        "overtime_deduction_max": ["12500", "duct up to [[$12,500]] ($25,000"],
        "overtime_deduction_max_joint": ["25000", "up to $12,500 ([[$25,000]] if married"],
        "car_loan_interest_deduction_max": ["10000", "deduct up to [[$10,000]] of that inter-"],
        "car_loan_interest_phaseout_magi": ["100000", "more than [[$100,000]] ($200,000"],
        "car_loan_interest_phaseout_magi_joint": ["200000", "$100,000 ([[$200,000]] if married"],
        "senior_deduction_magi_threshold": ["75000", "more than [[$75,000]] ($150,000"],
        "senior_deduction_max": ["6000", "maximum amount of the deduction is [[$6,000]]"],
        "senior_deduction_max_both_spouses": ["12000", "$6,000 ([[$12,000]] if both spouses"],
        "business_mileage_rate_2025": ["70", "for 2025 is [[70 cents]] per mile"],
        "social_security_wage_base_2025": [
            "176100",
            "social security tax has increased to [[$176,100]].",
        ],
        "roth_ira_magi_limit_single_2025": ["165000", "Less than [[$165,000]] if single"],
        "eic_max_income_2025": [None],
    },
    "irs-p527": {
        "car_mileage_rate_2025": ["70", "panel truck increased to [[70 cents]] a mile"],
        "bonus_depreciation_pct": ["100", "The [[100%]] special depreciation"],
        "section_179_max_2025": ["2500000", "ex- pense deduction is [[$2,500,000]]."],
        "section_179_phaseout_threshold_2025": [
            "4000000",
            "placed in service during the year exceeds [[$4,000,000]].",
        ],
        "salt_limit": ["40000", "has increased to [[$40,000]]"],
        "salt_limit_mfs": ["20000", "$40,000 ([[$20,000]] if married filing separately)"],
        "salt_limit_magi_threshold": ["500000", "more than [[$500,000]] ($250,000"],
        "salt_limit_magi_threshold_mfs": [
            "250000",
            "$500,000 ([[$250,000]] if married filing separately)",
        ],
        "salt_limit_floor": ["10000", "will not be reduced below [[$10,000]]"],
        "salt_limit_floor_mfs": ["5000", "$10,000 ([[$5,000]] if married filing"],
        "niit_rate": ["3.8", "NIIT is a [[3.8%]] tax"],
        "passive_rental_loss_special_allowance": [None],
    },
    "irs-p561": {
        "conservation_contribution_basis_multiple": [
            "2.5",
            "contribution ex- ceeds [[2.5 times]] the sum",
        ],
        "option_example_exercise_price": [
            "40000",
            "2-year period for [[$40,000]].",
            "minus [[$40,000]], the exercise price",
        ],
        "option_example_fmv_at_grant": ["50000", "is [[$50,000]]."],
        "option_example_fmv_at_exercise": [
            "55000",
            "the option is exercised is [[$55,000]].",
            "of $15,000 ([[$55,000]], the FMV",
        ],
        "option_example_contribution": [
            "15000",
            "you have made a charitable contribu- tion of [[$15,000]]",
        ],
        "gems_example_purchase_price": [
            "5000",
            "assortment of gems for [[$5,000]] from a promoter",
            "The [[$5,000]] paid by Bailey",
        ],
        "gems_example_promoter_deduction": [
            "15000",
            "Bailey could claim a chari- table contribution deduction of [[$15,000]]",
        ],
        "painting_example_cost": ["10000", "bought a painting for [[$10,000]]."],
        "painting_example_claimed_deduction": [
            "15000",
            "claiming a charitable contri- bution deduction of [[$15,000]] on their tax return",
        ],
        "painting_example_value_increase_pct": ["50", "justify a [[50%]] increase in value"],
        "qualified_appraisal_threshold": [None],
    },
    "irs-p783": {
        "application_lead_time_days": ["45", "at least [[45 days]] before the transaction date"],
        "third_party_suit_deadline_days": ["120", "you have [[120 days]] to file an action"],
        "b1_example_tax_liability": ["15500", "Tax liability Other Debts [[$15,500]]"],
        "b1_example_other_debts": ["23334", "+ [[$23,334]]"],
        "b1_example_total_debts": ["38834", "[[$38,834]] x 2"],
        "b1_example_min_remaining_property": [
            "77668",
            "x 2 [[$77,668]]",
            "must be at least [[$77,668]].",
        ],
        "b2a_example_lien_total": ["203000", "lien totaling [[$203,000]] and"],
        "b2a_example_sale_price": ["215000", "Property selling for: [[$215,000]]"],
        "b2a_example_senior_encumbrances": ["135000", "senior to IRS lien: [[$135,000]]"],
        "b2a_example_settlement_costs": ["15000", "[[$ 15,000]] $ 65,000"],
        "b2a_example_lien_interest": [
            "65000",
            "$ 15,000 [[$ 65,000]]",
            "applies the [[$65,000]] in partial",
        ],
        "b2a_example_remaining_debt": ["138000", "outstanding tax debt of [[$138,000]]."],
        "b3_example_government_interest": [
            "40000",
            "interest in the property is [[$40,000]] and",
            "c. [[$40,000]]",
        ],
        "discharge_application_fee": [None],
    },
    "irs-p784": {
        "application_lead_time_days": ["45", "at least [[45 days]] before the transaction date"],
        "example_loan_to_value_pct": [
            "80",
            "uses an [[80%]] loan to value",
            "property value x [[80%]] loan to value ratio",
        ],
        "example_closing_cost_pct": [
            "3",
            "and a [[3%]] closing cost to financing ratio",
            "$160,000 x [[3%]] = $4800",
        ],
        "example_fair_market_value": [
            "200000",
            "Current/New [[$200,000]]",
            "([[$200,000]] property value",
        ],
        "example_refinance_amount": [
            "160000",
            "$200,000 [[$160,000]] $4,800",
            "= [[$160,000]] refinance loan amount",
        ],
        "example_closing_costs": [
            "4800",
            "$160,000 [[$4,800]] $10,200",
            "= [[$4800]] closing costs",
            "equity - [[$4,800]] closing costs",
        ],
        "example_united_states_interest": [
            "10200",
            "$4,800 [[$10,200]] Original",
            "closing costs = [[$10,200]])",
            "IRS would ask for [[$10,200]]",
        ],
        "example_existing_loan": [
            "145000",
            "N/A [[$145,000]] N/A",
            "existing loan of [[$145,000]]",
            "$160,000 - [[$145,000]] loan payoff",
        ],
        "example_potential_equity": [
            "15000",
            "loan payoff = [[$15,000]] potential equity",
            "[[$15,000]] potential equity - $4,800",
        ],
        "aaa_example_monthly_payment_current": ["2000", "pays the IRS [[$2000]] per month"],
        "aaa_example_tax_debt": ["120000", "per month on a [[$120,000]] tax debt"],
        "aaa_example_monthly_payment_proposed": ["3000", "monthly payment to [[$3000]]"],
        "aaa_example_inventory_cars": ["500", "inventory replenishment of [[500]] cars"],
        "subordination_application_fee": [None],
    },
    "irs-p936": {
        "mortgage_debt_limit": [
            "750000",
            "interest on the first [[$750,000]]",
            "totaled [[$750,000]] or less",
        ],
        "mortgage_debt_limit_mfs": [
            "375000",
            "$750,000 ([[$375,000]] if married fil-",
            "or less ([[$375,000]] or less if married",
        ],
        "mortgage_debt_limit_pre_2017": [
            "1000000",
            "higher limita- tions ([[$1 million]]",
            "totaled [[$1 million]] or less",
        ],
        "mortgage_debt_limit_pre_2017_mfs": [
            "500000",
            "($1 million ([[$500,000]] if married filing separately))",
            "or less ([[$500,000]] or less",
        ],
        "home_equity_debt_limit": [None],
    },
    "irs-p962": {
        "average_eitc_2024": ["2894", "tax year 2024 was about [[2,894]]."],
        "investment_income_limit": ["11950", "income less than [[$11,950]]."],
        "max_eitc_no_child_2025": ["649", "(Self-only) [[$649]]"],
        "max_eitc_one_child_2025": ["4328", "[[$4,328]]"],
        "max_eitc_two_children_2025": ["7152", "[[$7,152]]"],
        "max_eitc_three_children_2025": ["8046", "[[$8,046]]"],
        "income_limit_no_child": ["19104", "[[$19,104]]"],
        "income_limit_no_child_joint": ["26214", "[[$26,214]] if married filing jointly"],
        "income_limit_one_child": ["50434", "[[$50,434]]"],
        "income_limit_one_child_joint": ["57554", "[[$57,554]] if married filing jointly"],
        "income_limit_two_children": ["57310", "[[$57,310]]"],
        "income_limit_two_children_joint": ["64430", "[[$64,430]] if married filing jointly"],
        "income_limit_three_children": ["61555", "[[$61,555]]"],
        "income_limit_three_children_joint": ["68675", "[[$68,675]] if married filing jointly"],
        "self_only_min_age": [None],
    },
    "irs-p1136": {
        "high_income_returns_2022": [
            "12500000",
            "there were just under [[12.5 million]] individual income tax returns with an adjusted gross income of $200,000 or more, which accounted for 7.8% of all returns that were filed",
            "there were just under [[12.5 million]] individual income tax returns with an adjusted gross income (AGI)",
        ],
        "high_income_share_2022": [
            "7.8",
            "accounted for [[7.8%]] of all returns that were filed",
            "accounted for [[7.8%]] of all returns filed",
        ],
        "high_income_no_tax_returns_2022": [
            "9997",
            "Of these, [[9,997]] returns had no worldwide income tax liability, which was a 12.7 %",
            "Of these, [[9,997]] returns had no world- wide",
        ],
        "high_income_no_tax_increase_pct_2022": [
            "12.7",
            "which was a [[12.7 %]] increase",
            "which was a [[12.7%]] increase",
        ],
        "high_income_no_tax_peak_2008": [
            "12326",
            "peak of [[12,326]] returns for Tax Year 2008",
            "peak of [[12,326]] returns for TY 2008",
        ],
        "cdcc_expense_limit_one_2022": ["3000", "qualifying expenses was [[$3,000]]"],
        "cdcc_expense_limit_two_2022": ["6000", "[[$6,000]] (previously $16,000)"],
        "cdcc_max_pct_2022": ["35", "decreased from 50% to [[35%]]"],
        "cdcc_phaseout_income_2022": ["15000", "began phasing out, [[$15,000]]"],
        "dependent_care_exclusion_2022": ["5000", "for TY 2022 to [[$5,000]] (previously $10,500)"],
        "dependent_care_exclusion_mfs_2022": ["2500", "to [[$2,500]] (previously $5,250)"],
        "child_tax_credit_max_2022": [
            "2000",
            "credit amount of up to [[$2,000]] for a qualifying child",
        ],
        "additional_child_tax_credit_max_2022": [
            "1500",
            "credit amount increased to [[$1,500]] for each",
        ],
        "credit_other_dependents_2022": ["500", "remained at [[$500]]."],
        "high_income_average_agi_2022": [None],
    },
    "irs-p1321": {
        "std_deduction_single_under_65": ["15750", "under 65 enter [[$15,750]]"],
        "std_deduction_single_65_or_older": ["17750", "65 or older enter [[$17,750]]"],
        "std_deduction_joint_both_under_65": ["31500", "both under 65 enter [[$31,500]]"],
        "std_deduction_joint_one_65_or_older": ["33100", "one 65 or older enter [[$33,100]]"],
        "std_deduction_joint_both_65_or_older": ["34700", "both 65 or older enter [[$34,700]]"],
        "std_deduction_hoh_under_65": ["23625", "under 65 enter [[$23,625]]"],
        "std_deduction_hoh_65_or_older": ["25625", "65 or older enter [[$25,625]]"],
        "std_deduction_qss_under_65": [
            "31500",
            "Qualifying surviving spouse under 65 enter [[$31,500]]",
        ],
        "std_deduction_qss_65_or_older": [
            "33100",
            "65 or older enter [[$33,100]] ................ Married filing separately",
        ],
        "filing_threshold_mfs": ["5", "equal to or more than [[$5]]."],
        "presence_test_days": [None],
    },
}
