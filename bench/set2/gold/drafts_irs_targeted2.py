"""Set-2 gold drafts: targeted IRS publications, second batch (p510 to p538). Written by a model
(Claude) from reading bench/set2/docs, after spec 0.2 was frozen. Not ground truth: a person
checks every fact."""

from __future__ import annotations

from build import f

FIELDS = {
    "irs-p510": {
        "taxable_transportation_zone_miles": (
            f("integer", "miles", "le"),
            "Maximum distance from the nearest point on the continental U.S. boundary of a "
            "place in Canada or Mexico where taxable air transportation can begin or end (the "
            "zone named after this distance).",
        ),
        "registration_exception_max_maturity_years": (
            f("integer", "years", "le"),
            "Maximum maturity at issue of an obligation that is not a registration-required "
            "obligation for that reason.",
        ),
        "rate_increase_safe_harbor_min_deposit_percent": (
            f("number", "%", "ge"),
            "Minimum deposit for each semimonthly period, as a percent of the look-back "
            "quarter's tax liability refigured at the increased rate, for the safe harbor rule "
            "to apply after an increase in the rate of tax.",
        ),
        "domestic_segment_tax_per_segment": (
            f("number", "USD"),
            "Dollar amount of the domestic-segment tax for each segment of taxable air "
            "transportation.",
        ),
    },
    "irs-p514": {
        "redetermination_no_form_1116_limit": (
            f("integer", "USD", "le"),
            "Maximum creditable foreign taxes paid or accrued during the tax year as a result "
            "of a foreign tax redetermination for which you need not attach Form 1116, for "
            "filers other than married filing jointly.",
        ),
        "redetermination_no_form_1116_limit_joint": (
            f("integer", "USD", "le"),
            "Maximum creditable foreign taxes paid or accrued during the tax year as a result "
            "of a foreign tax redetermination for which you need not attach Form 1116, if "
            "married filing a joint return.",
        ),
        "failure_to_notify_penalty_max_percent": (
            f("number", "%", "le"),
            "Maximum failure-to-notify penalty for not notifying the IRS of a foreign tax "
            "redetermination, as a percent of the tax due.",
        ),
        "sanction_waiver_report_notice_days": (
            f("integer", "days", "ge"),
            "Minimum number of days before a sanctioned-country waiver is granted by which the "
            "President must report the intention to grant it to Congress.",
        ),
        "foreign_earned_income_exclusion_limit": (
            f("integer", "USD", "le"),
            "Maximum foreign earned income exclusion for the tax year.",
        ),
    },
    "irs-p515": {
        "individual_documentary_evidence_max_age_years": (
            f("integer", "years", "le"),
            "Maximum age of an official document used as documentary evidence for an "
            "individual claiming treaty benefits: it must be issued no more than this many "
            "years before being presented.",
        ),
        "unknown_gain_withholding_min_percent": (
            f("number", "%", "ge"),
            "When the amount of the gain is not known, the minimum tax withheld as a percent "
            "of the recognized gain.",
        ),
        "unknown_gain_withholding_max_percent": (
            f("number", "%", "le"),
            "When the amount of the gain is not known, the maximum amount withheld as a "
            "percent of the amount payable because of the transaction.",
        ),
        "annuity_personal_services_max_days": (
            f("integer", "days", "le"),
            "For no withholding on an annuity payment for personal services, the maximum days "
            "the nonresident individual was present in the United States during each tax year.",
        ),
        "annuity_personal_services_max_pay": (
            f("integer", "USD", "le"),
            "For no withholding on an annuity payment for personal services, the maximum pay "
            "for those services.",
        ),
        "backup_withholding_rate": (
            f("number", "%"),
            "Backup withholding rate.",
        ),
    },
    "irs-p516": {
        "foreign_tax_limit_exemption_max_taxes": (
            f("integer", "USD", "le"),
            "Maximum total foreign taxes to elect exemption from the foreign tax credit limit, "
            "for returns other than joint returns.",
        ),
        "foreign_tax_limit_exemption_max_taxes_joint": (
            f("integer", "USD", "le"),
            "Maximum total foreign taxes to elect exemption from the foreign tax credit limit, "
            "for joint tax returns.",
        ),
        "foreign_housing_exclusion_limit": (
            f("integer", "USD", "le"),
            "Maximum foreign housing exclusion for the tax year.",
        ),
    },
    "irs-p519": {
        "residency_start_excluded_days_max": (
            f("integer", "days", "le"),
            "Maximum total days of actual presence in the United States that can be excluded "
            "in determining the residency starting date.",
        ),
        "residency_termination_excluded_days_max": (
            f("integer", "days", "le"),
            "Maximum total days of actual presence in the United States that can be excluded "
            "in determining the residency termination date (de minimis presence).",
        ),
        "foreign_employer_services_max_days": (
            f("integer", "days", "le"),
            "For pay from a foreign employer not to be U.S. source income, the maximum total "
            "days the nonresident alien is temporarily present in the United States during the "
            "tax year.",
        ),
        "foreign_employer_services_max_pay": (
            f("integer", "USD", "le"),
            "For pay from a foreign employer not to be U.S. source income, the maximum pay for "
            "the services performed in the United States.",
        ),
        "expatriation_net_worth_threshold": (
            f("integer", "USD", "ge"),
            "Net worth at or above which an expatriate is a covered expatriate for the "
            "expatriation tax.",
        ),
    },
    "irs-p523": {
        "surviving_spouse_exclusion_from": (
            f("integer", "USD"),
            "Surviving spouse's gain exclusion before the increase (the amount the exclusion "
            "can be increased from).",
        ),
        "surviving_spouse_exclusion_to": (
            f("integer", "USD"),
            "Surviving spouse's increased (higher) gain exclusion, if the conditions are met.",
        ),
        "suspension_period_max_years": (
            f("integer", "years", "le"),
            "Maximum length, in years, of the suspension period for qualified official "
            "extended duty.",
        ),
        "test_period_years": (
            f("integer", "years"),
            "Length, in years, of the test period for ownership and residence ending on the "
            "date of sale.",
        ),
        "suspension_and_test_period_max_years": (
            f("integer", "years", "le"),
            "Maximum combined length, in years, of the suspension period and the test period.",
        ),
        "depreciation_recapture_rate": (
            f("number", "%"),
            "Tax rate on the part of the gain equal to depreciation claimed on the home.",
        ),
    },
    "irs-p524": {
        "joint_initial_amount_base_one_disabled": (
            f("integer", "USD"),
            "Table 2 footnote 3: the fixed dollar part of the initial amount (added to the "
            "taxable disability income of the spouse under age 65) for a joint return where "
            "one spouse is 65 or older and the other is under 65 and retired on permanent and "
            "total disability.",
        ),
        "joint_initial_amount_cap_one_disabled": (
            f("integer", "USD", "le"),
            "Table 2 footnote 3: the maximum initial amount for a joint return where one "
            "spouse is 65 or older and the other is under 65 and retired on permanent and "
            "total disability.",
        ),
        "joint_initial_amount_limit_base_one_under_65": (
            f("integer", "USD", "le"),
            "Special rules for joint returns: if only one spouse is under age 65, the fixed "
            "dollar part of the limit on the initial amount (the limit is this plus that "
            "spouse's taxable disability income).",
        ),
        "agi_limit_single": (
            f("integer", "USD", "le"),
            "Adjusted gross income limit for the credit for a single filer.",
        ),
    },
    "irs-p525": {
        "achievement_award_exclusion_limit": (
            f("integer", "USD", "le"),
            "Maximum exclusion for all employee achievement awards received during the year "
            "(qualified plan awards).",
        ),
        "achievement_award_exclusion_limit_nonqualified": (
            f("integer", "USD", "le"),
            "Maximum exclusion for employee achievement awards that are not qualified plan awards.",
        ),
        "group_term_life_exclusion_coverage_limit": (
            f("integer", "USD", "le"),
            "Coverage amount whose cost limits the exclusion for employer-provided group-term "
            "life insurance.",
        ),
        "commuter_transit_exclusion_monthly_limit": (
            f("integer", "USD", "le"),
            "Monthly exclusion limit for commuter vehicle transportation and transit pass "
            "fringe benefits.",
        ),
        "parking_exclusion_monthly_limit": (
            f("integer", "USD", "le"),
            "Monthly exclusion limit for the qualified parking fringe benefit.",
        ),
        "dependent_care_assistance_exclusion_limit": (
            f("integer", "USD", "le"),
            "Maximum exclusion for employer-provided dependent care assistance.",
        ),
    },
    "irs-p526": {
        "agi_limit_general_percent": (
            f("number", "%", "le"),
            "General limit on the deduction for charitable contributions, as a percent of AGI.",
        ),
        "agi_limit_alternative_low_percent": (
            f("number", "%", "le"),
            "The lowest of the three other percent-of-AGI limits that may apply in some cases "
            "instead of the general limit.",
        ),
        "agi_limit_alternative_middle_percent": (
            f("number", "%", "le"),
            "The middle one of the three other percent-of-AGI limits that may apply in some "
            "cases instead of the general limit.",
        ),
        "agi_limit_alternative_high_percent": (
            f("number", "%", "le"),
            "The highest of the three other percent-of-AGI limits that may apply in some cases "
            "instead of the general limit.",
        ),
        "state_credit_example_deduction_limit": (
            f("integer", "USD", "le"),
            "State tax credit Example 1 (70% state tax credit): the charitable contribution "
            "deduction the example's result says can't be exceeded.",
        ),
        "state_credit_example_contribution": (
            f("integer", "USD"),
            "State tax credit Example 1 (70% state tax credit): the cash contribution made to "
            "the qualified organization.",
        ),
        "state_credit_example_credit": (
            f("integer", "USD"),
            "State tax credit Example 1 (70% state tax credit): the state tax credit that "
            "reduces the contribution.",
        ),
        "state_credit_exception_percent_fmv": (
            f("number", "%", "le"),
            "Exception to reducing the deduction for a state or local tax credit: the maximum "
            "credit as a percent of the FMV of the transferred property.",
        ),
        "qcd_annual_limit": (
            f("integer", "USD", "le"),
            "Maximum total qualified charitable distributions (QCDs) for the year.",
        ),
        "charitable_mileage_rate": (
            f("number", "cents"),
            "Standard mileage rate, in cents per mile, for using a car for charitable purposes.",
        ),
    },
    "irs-p530": {
        "pre_2018_debt_limit": (
            f("integer", "USD", "le"),
            "Limit on qualifying debt taken out on or before December 15, 2017, on which home "
            "mortgage interest can be deducted, for filers other than married filing "
            "separately.",
        ),
        "pre_2018_debt_limit_mfs": (
            f("integer", "USD", "le"),
            "Limit on qualifying debt taken out on or before December 15, 2017, on which home "
            "mortgage interest can be deducted, if married filing separately.",
        ),
        "post_2017_debt_limit": (
            f("integer", "USD", "le"),
            "Limit on qualifying debt taken out after December 15, 2017, on which home "
            "mortgage interest can be deducted, for filers other than married filing "
            "separately.",
        ),
        "post_2017_debt_limit_mfs": (
            f("integer", "USD", "le"),
            "Limit on qualifying debt taken out after December 15, 2017, on which home "
            "mortgage interest can be deducted, if married filing separately.",
        ),
        "home_acquisition_debt_limit": (
            f("integer", "USD", "le"),
            "Home acquisition debt limit (other than grandfathered debt), under Home "
            "acquisition debt limit, for filers other than married filing separately.",
        ),
        "home_acquisition_debt_limit_mfs": (
            f("integer", "USD", "le"),
            "Home acquisition debt limit (other than grandfathered debt), under Home "
            "acquisition debt limit, if married filing separately.",
        ),
        "home_acquisition_debt_limit_after_2017": (
            f("integer", "USD", "le"),
            "Home acquisition debt limit for a home purchased in tax years beginning after "
            "2017, for filers other than married filing separately.",
        ),
        "home_acquisition_debt_limit_after_2017_mfs": (
            f("integer", "USD", "le"),
            "Home acquisition debt limit for a home purchased in tax years beginning after "
            "2017, if married filing separately.",
        ),
        "salt_deduction_limit": (
            f("integer", "USD", "le"),
            "Limit on the itemized deduction for state and local taxes, including real estate "
            "taxes.",
        ),
    },
    "irs-p537": {
        "farm_sale_section_1274_exception_limit": (
            f("integer", "USD", "le"),
            "Maximum price for a sale or exchange of a farm (by an individual, estate, "
            "testamentary trust, small business corporation or qualifying partnership) that "
            "is excepted from section 1274.",
        ),
        "deferred_tax_interest_obligations_threshold": (
            f("integer", "USD", "ge"),
            "Interest on deferred tax: total balance of nondealer installment obligations "
            "outstanding at the close of the tax year above which interest is due (and above "
            "which the applicable percentage counts the excess).",
        ),
        "section_453a_example_basis": (
            f("integer", "USD"),
            "Section 453A Example: ABC, Inc.'s basis in the intellectual property it sold.",
        ),
        "section_453a_example_sale_price": (
            f("integer", "USD"),
            "Section 453A Example: the price for which ABC, Inc. sold the intellectual "
            "property on the installment method.",
        ),
        "section_453a_example_payment_2022": (
            f("integer", "USD"),
            "Section 453A Example: the installment payment in 2022.",
        ),
        "section_453a_example_payment_2023": (
            f("integer", "USD"),
            "Section 453A Example: the installment payment in 2023.",
        ),
        "section_453a_example_payment_2024": (
            f("integer", "USD"),
            "Section 453A Example: the installment payment in 2024, when the note is paid off.",
        ),
        "underpayment_rate": (
            f("number", "%"),
            "Underpayment rate used to figure interest on deferred tax.",
        ),
    },
    "irs-p538": {
        "cash_method_gross_receipts_limit": (
            f("integer", "USD", "le"),
            "Gross receipts test for a corporation or partnership to use the cash method: "
            "maximum average annual gross receipts.",
        ),
        "cash_method_gross_receipts_years": (
            f("integer", "years"),
            "Gross receipts test for a corporation or partnership to use the cash method: "
            "number of prior tax years averaged.",
        ),
        "small_business_taxpayer_gross_receipts_limit": (
            f("integer", "USD", "le"),
            "Small business taxpayer (inventories): maximum average annual gross receipts.",
        ),
        "small_business_taxpayer_gross_receipts_years": (
            f("integer", "years"),
            "Small business taxpayer (inventories): number of prior tax years in the period "
            "used to figure average annual gross receipts.",
        ),
        "simplified_lifo_gross_receipts_limit": (
            f("integer", "USD", "le"),
            "Eligible small business for the simplified dollar-value LIFO method: maximum "
            "average annual gross receipts.",
        ),
        "simplified_lifo_gross_receipts_years": (
            f("integer", "years"),
            "Eligible small business for the simplified dollar-value LIFO method: number of "
            "preceding tax years averaged.",
        ),
        "de_minimis_safe_harbor_limit": (
            f("integer", "USD", "le"),
            "De minimis safe harbor limit per invoice or item for taxpayers without an "
            "applicable financial statement.",
        ),
    },
}

TAX_YEARS = ["years", "year", "-year", "prior tax years", "preceding tax years", "tax-year"]
UNITS = {
    "irs-p510": {"miles": {"suffix": ["miles", "mile", "-mile"]}},
    "irs-p523": {"years": {"suffix": ["years", "year", "-year"]}},
    "irs-p538": {"years": {"suffix": TAX_YEARS}},
}

DRAFTS = {
    "irs-p510": {
        # The matched sentence writes the fraction "1/6", which is not a decimal. The same
        # rate-increase rule under Exceptions writes it as "1/6 (16.67%)", so the field takes
        # 16.67 from there.
        "taxable_transportation_zone_miles": [
            "225",
            "Canada or Mexico not more than [[225 miles]] from the nearest",
            "(this is the [[225-mile]] zone)",
            "begin and end in the United States or in the [[225-mile]] zone if",
            "station in the [[225-mile]] zone) and the point",
            "when it leaves a port or station in the [[225-mile]] zone.",
        ],
        "registration_exception_max_maturity_years": [
            "1",
            "It has a maturity (at issue) of not more than [[1 year]].",
        ],
        "rate_increase_safe_harbor_min_deposit_percent": [
            "16.67",
            "dar quarter is at least 1/6 ([[16.67%]]) of the tax liability you would have had",
        ],
        "domestic_segment_tax_per_segment": [None],
    },
    "irs-p514": {
        "redetermination_no_form_1116_limit": [
            "300",
            "during the tax year is not more than [[$300]] ($600 if",
        ],
        "redetermination_no_form_1116_limit_joint": [
            "600",
            "not more than $300 ([[$600]] if married filing a joint return)",
        ],
        "failure_to_notify_penalty_max_percent": [
            "25",
            "This penalty can- not be more than [[25%]] of the tax due.",
        ],
        "sanction_waiver_report_notice_days": [
            "30",
            "gress, not less than [[30 days]] before the date on which the",
        ],
        "foreign_earned_income_exclusion_limit": [None],
    },
    "irs-p515": {
        "individual_documentary_evidence_max_age_years": [
            "3",
            "c. Is issued no more than [[3 years]] prior to being pre-",
        ],
        "unknown_gain_withholding_min_percent": [
            "30",
            "held will not be less than [[30%]] of the recognized gain.",
        ],
        "unknown_gain_withholding_max_percent": [
            "30",
            "must not be more than [[30%]] of the amount payable because of the transaction.",
        ],
        "annuity_personal_services_max_days": [
            "90",
            "present in the United States for [[90 days]] or less during each tax year,",
        ],
        "annuity_personal_services_max_pay": [
            "3000",
            "whose pay for those services did not exceed [[$3,000]], and",
        ],
        "backup_withholding_rate": [None],
    },
    "irs-p516": {
        # The matched sentence ends at "not more than" (a blank line follows); the amounts on
        # the next line complete it.
        "foreign_tax_limit_exemption_max_taxes": [
            "300",
            "The total of all your foreign taxes is not more than [[$300]] ($600 for joint tax returns).",
        ],
        "foreign_tax_limit_exemption_max_taxes_joint": [
            "600",
            "$300 ([[$600]] for joint tax returns).",
        ],
        "foreign_housing_exclusion_limit": [None],
    },
    "irs-p519": {
        "residency_start_excluded_days_max": [
            "10",
            "See Closer Connection to a Foreign Country, earlier. In determining whether you can exclude up to [[10 days]],",
            "earlier. In determining whether you can exclude up to 10 days, the following rules apply. • You can exclude days from more than one period of presence as long as the total days in all periods are not more than [[10]].",
            "• Although you can exclude up to [[10 days]] of presence in determining your residency starting date,",
            "Statement required to exclude up to [[10 days]] of presence.",
            "if you are excluding up to [[10 days]] of presence in the United States for purposes of your residency starting date.",
        ],
        "residency_termination_excluded_days_max": [
            "10",
            "clude up to [[10 days]] of actual presence in the United States in determining your residency termination date.",
            "residency termination date. In determining whether you can exclude up to [[10 days]], the following rules apply.",
            "residency termination date. In determining whether you can exclude up to 10 days, the following rules apply. • You can exclude days from more than one period of presence as long as the total days in all periods are not more than [[10]].",
            "• Although you can exclude up to [[10 days]] of presence in determining your residency termination date,",
        ],
        "foreign_employer_services_max_days": [
            "90",
            "a period or periods of not more than a total of [[90 days]] during the tax year.",
        ],
        "foreign_employer_services_max_pay": [
            "3000",
            "3. Your pay for these services is not more than [[$3,000]].",
            "If your pay for these services is more than [[$3,000]], the entire amount",
            "To find if your pay is more than [[$3,000]], do not include",
        ],
        "expatriation_net_worth_threshold": [None],
    },
    "irs-p523": {
        "surviving_spouse_exclusion_from": [
            "250000",
            "increase your exclusion amount from [[$250,000]] to $500,000.",
        ],
        "surviving_spouse_exclusion_to": [
            "500000",
            "increase your exclusion amount from $250,000 to [[$500,000]].",
        ],
        "suspension_period_max_years": [
            "10",
            "The period of suspension can’t last more than [[10 years]].",
            "Together, the [[10-year]] sus- pension period",
            "You choose to use the entire [[10-year]] suspension period.",
            "or 2) for [[10 years]] or less and due to a “stop the clock” exception",
        ],
        "test_period_years": [
            "5",
            "you may choose to suspend the [[5-year]] test period for ownership and residence",
            "at least the 2 years during the [[5-year]] period ending on the date of sale. Make",
            "pension period and the [[5-year]] test period can be as long",
            "You can’t suspend the [[5-year]] period for more than one property at a time.",
            "You can revoke your choice to suspend the [[5-year]] period at any time.",
            "and the [[5-year]] test period would extend back to Au- gust 2, 2009.",
            "you choose to suspend the [[5-year]] test period for the 6 years",
            "Therefore, your [[5-year]] test period consists of the 5 years before",
            "During the [[5-year]] period ending on the date of sale (May 1,",
            "doesn’t include any part of the [[5-year]] period after the last date Cartier lived",
            "used the entire property as your main home during the [[5-year]] period prior to the date of sale.* Otherwise,",
            "home during the [[5-year]] period prior to the date of sale. This number is your",
        ],
        "suspension_and_test_period_max_years": [
            "15",
            "can be as long as, but no more than, [[15 years]].",
        ],
        "depreciation_recapture_rate": [None],
    },
    "irs-p524": {
        "joint_initial_amount_base_one_disabled": [
            "5000",
            "3 Amount is [[$5,000]] plus the taxable disability income of the spouse under age 65",
        ],
        "joint_initial_amount_cap_one_disabled": [
            "7500",
            "of the spouse under age 65, but not more than [[$7,500]].",
        ],
        "joint_initial_amount_limit_base_one_under_65": [
            "5000",
            "your initial amount can't be more than [[$5,000]] plus the taxable disability in- come of the spouse who is under age 65.",
        ],
        "agi_limit_single": [None],
    },
    "irs-p525": {
        "achievement_award_exclusion_limit": [
            "1600",
            "can’t be more than [[$1,600]] ($400 for awards",
            "awards is more than [[$1,600]], you must include",
            "($1,750 − [[$1,600]]) in your income.",
        ],
        "achievement_award_exclusion_limit_nonqualified": [
            "400",
            "([[$400]] for awards that aren’t qualified plan awards)",
        ],
        "group_term_life_exclusion_coverage_limit": [
            "50000",
            "coverage can’t exceed the cost of [[$50,000]] of coverage,",
            "provided more than [[$50,000]] of group-term life insurance coverage during the year,",
            "coverage that totals more than [[$50,000]], the amounts",
            "2. [[50,000]] 3. Subtract line 2 from",
        ],
        "commuter_transit_exclusion_monthly_limit": [
            "325",
            "transit pass fringe benefits can’t be more than [[$325]] a month.",
        ],
        "parking_exclusion_monthly_limit": [
            "325",
            "qualified parking fringe benefit can’t be more than [[$325]] a month.",
        ],
        "dependent_care_assistance_exclusion_limit": [None],
    },
    "irs-p526": {
        "agi_limit_general_percent": [
            "60",
            "generally can’t be more than [[60%]] of your AGI,",
        ],
        "agi_limit_alternative_low_percent": [
            "20",
            "but in some cases [[20%]], 30%, or 50% limits may apply.",
        ],
        "agi_limit_alternative_middle_percent": [
            "30",
            "but in some cases 20%, [[30%]], or 50% limits may apply.",
        ],
        "agi_limit_alternative_high_percent": [
            "50",
            "but in some cases 20%, 30%, or [[50%]] limits may apply.",
        ],
        "state_credit_example_deduction_limit": [
            "300",
            "your charitable contribution deduction can’t exceed [[$300]] ($1,000 donation",
            "for that year. Your deductible charitable contribution is [[$300]].",
        ],
        "state_credit_example_contribution": [
            "1000",
            "You make a cash contribution of [[$1,000]] to a qualified organization. In return for your payment,",
            "a state tax credit of 70% of your [[$1,000]] contribution.",
            "reduced by $700 (70% of [[$1,000]]).",
            "can’t exceed $300 ([[$1,000]] donation",
        ],
        "state_credit_example_credit": [
            "700",
            "contribution is reduced by [[$700]] (70% of $1,000).",
            "donation − [[$700]] state tax credit).",
        ],
        "state_credit_exception_percent_fmv": [
            "15",
            "amount or [[15%]] of the FMV of the transferred property,",
            "does not exceed [[15%]] of the FMV of the painting.",
        ],
        "qcd_annual_limit": [
            "108000",
            "Your total QCDs for the year can’t be more than [[$108,000]].",
        ],
        "charitable_mileage_rate": [None],
    },
    "irs-p530": {
        "pre_2018_debt_limit": [
            "1000000",
            "you can only deduct home mortgage in- terest on up to [[$1 million]] (",
            "that exceed [[$1 million]] ($500,000 if you are married filing separately).",
            "qualifying debt subject to the [[$1 million]] ($500,000 if you are married filing separately) limi-",
            "amount of your qualifying debt subject to the [[$1 million]] limit.",
        ],
        "pre_2018_debt_limit_mfs": [
            "500000",
            "up to $1 million ([[$500,000]] if you are married fil- ing separately) of that debt.",
            "million ([[$500,000]] if you are married filing separately). Limit on loans taken out after",
            "million ([[$500,000]] if you are married filing separately) limi-",
        ],
        "post_2017_debt_limit": [
            "750000",
            "home mortgage interest on up to [[$750,000]] ($375,000",
            "earlier, the [[$750,000]] limit for debt taken out after",
            "that exceed [[$750,000]] ($375,000 or less",
        ],
        "post_2017_debt_limit_mfs": [
            "375000",
            "$750,000 ([[$375,000]] if you are married filing separately) of that debt.",
            "$750,000 ([[$375,000]] or less if you are married filing separately).",
        ],
        "home_acquisition_debt_limit": [
            "1000000",
            "at any time on your home cannot be more than [[$1 million]] ($500,000 if married",
        ],
        "home_acquisition_debt_limit_mfs": [
            "500000",
            "be more than $1 million ([[$500,000]] if married filing sepa- rately).",
        ],
        "home_acquisition_debt_limit_after_2017": [
            "750000",
            "generally cannot be more than [[$750,000]] ($375,000 if married",
        ],
        "home_acquisition_debt_limit_after_2017_mfs": [
            "375000",
            "more than $750,000 ([[$375,000]] if married filing sepa- rately).",
        ],
        "salt_deduction_limit": [None],
    },
    "irs-p537": {
        "farm_sale_section_1274_exception_limit": [
            "1000000",
            "The sale or exchange of a farm for [[$1 million]] or less by",
        ],
        "deferred_tax_interest_obligations_threshold": [
            "5000000",
            "outstanding at the close of, the tax year is more than [[$5 million]].",
            "the close of the tax year in excess of [[$5 million]] divided by",
        ],
        "section_453a_example_basis": [
            "0",
            "sold in- tellectual property with a [[$0]] basis",
        ],
        "section_453a_example_sale_price": [
            "15000000",
            "November 15, 2022, for [[$15 million]] on the installment",
            "(([[$15,000,000]] – $500,000)/$15,000,000)",
            "(($15,000,000 – $500,000)/[[$15,000,000]])",
            "[[15,000,000]] (1,000,000)",
        ],
        "section_453a_example_payment_2022": [
            "1000000",
            "• 2022: [[$1 million]].",
            "15,000,000 ([[1,000,000]])",
        ],
        "section_453a_example_payment_2023": [
            "5000000",
            "• 2023: [[$5 million]].",
        ],
        "section_453a_example_payment_2024": [
            "9000000",
            "• 2024: [[$9 million]]—Note is paid off.",
        ],
        "underpayment_rate": [None],
    },
    "irs-p538": {
        "cash_method_gross_receipts_limit": [
            "26000000",
            "for the 3 prior tax years were [[$26 million]] or less",
        ],
        "cash_method_gross_receipts_years": [
            "3",
            "average annual gross receipts for the [[3 prior tax years]] were",
            "1. Adding the gross receipts for the [[3 prior tax years]];",
        ],
        "small_business_taxpayer_gross_receipts_limit": [
            "26000000",
            "• Have average annual gross receipts of [[$26 million]] or less",
        ],
        "small_business_taxpayer_gross_receipts_years": [
            "3",
            "less (indexed for inflation) for the [[3 prior tax years]], and",
            "for all of the [[3 tax-year]] period used in figuring",
            "predecessor entity from the [[3 tax-year]] period",
            "for any of the [[3 tax-year]] period, annualize",
        ],
        "simplified_lifo_gross_receipts_limit": [
            "5000000",
            "ceipts of [[$5 million]] or less for the 3 preceding tax years)",
        ],
        "simplified_lifo_gross_receipts_years": [
            "3",
            "or less for the [[3 preceding tax years]])",
        ],
        "de_minimis_safe_harbor_limit": [None],
    },
}
