"""Draft gold labels, written by a model (Claude) from reading bench/docs. Not ground truth.

A person checks every draft in the labeling app (bench/label/app.py) before it counts: they
confirm, correct or reject each fact, add what is missing, and confirm each absent field. Only
facts with status "confirmed" and absences with status "confirmed" are used for scoring.

Each fact gives one or more contexts copied from the document, with the evidence in [[...]].
Spaces in a context match any whitespace run, so line breaks need not be copied.

    uv run python bench/gold/prelabels.py     # writes bench/gold/<id>.json for new documents only
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).parent
DOCS = HERE.parent / "docs"


def f(
    type_: str = "integer", unit: str | None = "USD", comparator: str = "eq", **kw: object
) -> dict:
    return {"type": type_, "unit": unit, "comparator": comparator, "minimum": "0", **kw}


# --------------------------------------------------------------------------------- schemas

FDA_FIELDS = {
    "adult_starting_dose": (
        f("number", "mg"),
        "Usual recommended starting dose for adults, for the first indication in section 2. "
        "If the label gives a range, its lower bound.",
    ),
    "adult_max_daily_dose": (
        f("number", "mg", "le"),
        "Maximum recommended daily dose for adults, for the first indication in section 2. "
        "Doses that were only studied or used are not a recommendation.",
    ),
    "pediatric_min_age": (
        f("integer", "years", "ge"),
        "Youngest age, in years, for which section 2 gives pediatric dosing.",
    ),
    "tablet_strengths": (
        f("number", "mg", multiple=True),
        "Every tablet strength listed in section 3 (one extraction per strength).",
    ),
    "hepatic_starting_dose": (
        f("number", "mg"),
        "Recommended starting dose for patients with hepatic impairment, when the label gives "
        "a number.",
    ),
}
FDA_UNITS = {"years": {"suffix": ["years", "year", "Years", "Year", "-year"]}}

NTSB_FIELDS = {
    "pilot_age": (f("integer", None), "Age of the pilot in command (the flight instructor on "
                  "instructional flights)."),
    "pilot_total_hours": (f("number", "hours"), "Pilot in command's total flight time, all "
                          "aircraft."),
    "pilot_make_model_hours": (f("number", "hours"), "Pilot in command's total flight time in "
                               "this make and model."),
    "pilot_last_90_days_hours": (f("number", "hours"), "Pilot in command's flight time in the "
                                 "last 90 days, all aircraft."),
    "aircraft_year": (f("integer", None), "Aircraft year of manufacture."),
    "airframe_total_hours": (f("number", "hours"), "Airframe total time."),
    "airport_elevation": (f("integer", "ft"), "Elevation of the airport in the Airport "
                          "Information table (not the weather station's elevation)."),
    "runway_length": (f("integer", "ft"), "Length of the runway used."),
    "visibility": (f("number", "miles"), "Visibility in the weather observation."),
    "wind_speed": (f("integer", "knots"), "Wind speed in the weather observation (not gusts)."),
    "temperature": (f("number", "C", minimum=None), "Temperature in the weather observation "
                    "(not dew point), in degrees Celsius."),
    "altimeter_setting": (f("number", "inHg"), "Altimeter setting, in inches of mercury."),
}  # fmt: skip
NTSB_UNITS = {
    "hours": {"suffix": ["hours", "hour", "Hrs", "hrs"]},
    "ft": {"suffix": ["ft", "feet", "-ft", "-foot"]},
    "miles": {"suffix": ["miles", "mile"]},
    "knots": {"suffix": ["knots", "knot", "kts"]},
    "C": {"suffix": ["°C", "° C"]},
    "inHg": {"suffix": ["inches Hg", "in Hg", "inHg"]},
}

IRS_UNITS = {"cents": {"suffix": ["cents"]}}


def irs(**fields: tuple[str, str] | tuple[str, str, str]) -> dict:
    """field=(description, comparator[, unit]) -> field table. Unit defaults to USD."""
    out = {}
    for name, spec in fields.items():
        desc, cmp_, *unit = spec
        code = unit[0] if unit else "USD"
        out[name] = (f("number" if code == "%" else "integer", code, cmp_), desc)
    return out


IRS_FIELDS = {
    "irs-p501": irs(
        senior_deduction_max=("Maximum enhanced deduction for seniors, per person.", "eq"),
        senior_deduction_max_joint=(
            "Maximum enhanced deduction for seniors, married filing "
            "jointly with both spouses eligible.",
            "eq",
        ),
        trump_account_pilot_contribution=("Trump account pilot program contribution.", "eq"),
        filing_threshold_single_under_65=(
            "2025 gross income filing threshold, single, under 65.",
            "ge",
        ),
        filing_threshold_single_65_or_older=(
            "2025 gross income filing threshold, single, 65 or older.",
            "ge",
        ),
        filing_threshold_hoh_under_65=(
            "2025 gross income filing threshold, head of household, under 65.",
            "ge",
        ),
        filing_threshold_joint_both_under_65=(
            "2025 gross income filing threshold, married filing jointly, both spouses under 65.",
            "ge",
        ),
        filing_threshold_separate=(
            "2025 gross income filing threshold, married filing separately, any age.",
            "ge",
        ),
        ss_benefits_income_threshold=(
            "Income above which social security benefits must be "
            "counted in gross income (not married filing jointly).",
            "gt",
        ),
        ss_benefits_income_threshold_joint=("The same threshold for married filing jointly.", "gt"),
        dependent_standard_deduction_min=("Minimum standard deduction for a dependent.", "eq"),
    ),
    "irs-p505": irs(
        standard_deduction_single_2026=(
            "2026 standard deduction, single or married filing separately.",
            "eq",
        ),
        standard_deduction_joint_2026=("2026 standard deduction, married filing jointly.", "eq"),
        standard_deduction_hoh_2026=("2026 standard deduction, head of household.", "eq"),
        savers_credit_magi_limit_single_2026=(
            "2026 retirement savings contribution credit MAGI limit, single.",
            "le",
        ),
        savers_credit_magi_limit_joint_2026=("The same limit, married filing jointly.", "le"),
        adoption_credit_max_2026=("2026 maximum adoption credit or exclusion.", "eq"),
        adoption_credit_magi_limit_2026=(
            "MAGI the taxpayer must be under to claim the adoption credit or exclusion.",
            "lt",
        ),
        adoption_credit_refundable_max_2026=("Refundable portion of the adoption credit.", "le"),
        minimum_qbid_2026=("Minimum qualified business income deduction.", "eq"),
        itemized_limit_threshold_joint_2026=(
            "Taxable income above which itemized deductions are reduced, married filing jointly.",
            "gt",
        ),
        charitable_nonitemizer_max_2026=("Maximum charitable deduction for non-itemizers.", "eq"),
        charitable_nonitemizer_max_joint_2026=("The same maximum, married filing jointly.", "eq"),
        standard_deduction_single_2025=("2025 standard deduction, single.", "eq"),
    ),
    "irs-p970": irs(
        trump_account_pilot_contribution=("Trump account pilot program contribution.", "eq"),
        student_loan_phaseout_start=(
            "2025 MAGI where the student loan interest deduction phase-out starts (not joint).",
            "range",
        ),
        student_loan_phaseout_end=("MAGI where that phase-out ends (not joint).", "range"),
        student_loan_phaseout_start_joint=("The same start, joint return.", "range"),
        student_loan_phaseout_end_joint=("The same end, joint return.", "range"),
        savings_bond_phaseout_start=(
            "2025 MAGI where the education savings bond exclusion phase-out starts (not joint).",
            "range",
        ),
        savings_bond_phaseout_end=("MAGI where that phase-out ends (not joint).", "range"),
        savings_bond_phaseout_start_joint=("The same start, joint return.", "range"),
        savings_bond_phaseout_end_joint=("The same end, joint return.", "range"),
        education_mileage_rate=(
            "2025 deductible rate per mile for work-related education, in cents.",
            "eq",
            "cents",
        ),
        american_opportunity_credit_max=("Maximum American opportunity credit per student.", "eq"),
    ),
    "irs-p596": irs(
        eic_limit_three_children=(
            "2025 EIC AGI limit, three or more qualifying children, not joint.",
            "lt",
        ),
        eic_limit_three_children_joint=("The same limit, married filing jointly.", "lt"),
        eic_limit_two_children=("2025 EIC AGI limit, two qualifying children, not joint.", "lt"),
        eic_limit_two_children_joint=("The same limit, married filing jointly.", "lt"),
        eic_limit_one_child=("2025 EIC AGI limit, one qualifying child, not joint.", "lt"),
        eic_limit_one_child_joint=("The same limit, married filing jointly.", "lt"),
        eic_limit_no_child=("2025 EIC AGI limit, no qualifying child, not joint.", "lt"),
        eic_limit_no_child_joint=("The same limit, married filing jointly.", "lt"),
        eic_investment_income_limit=("Maximum investment income for the EIC.", "le"),
        eic_max_credit_three_children=(
            "Maximum 2025 EIC with three or more qualifying children.",
            "eq",
        ),
    ),
    "irs-p463": irs(
        standard_mileage_rate=(
            "2025 business standard mileage rate, in cents per mile.",
            "eq",
            "cents",
        ),
        car_depreciation_year1_bonus=(
            "2025 first-year depreciation limit for passenger "
            "automobiles with the section 168(k) bonus.",
            "eq",
        ),
        car_depreciation_year2=("Second-year depreciation limit (bonus table).", "eq"),
        car_depreciation_year3=("Third-year depreciation limit (bonus table).", "eq"),
        car_depreciation_later_years=("Limit for each succeeding year (bonus table).", "eq"),
        car_depreciation_year1_no_bonus=(
            "First-year limit when no section 168(k) bonus applies.",
            "eq",
        ),
        section_179_limit=("2025 section 179 expense limit.", "eq"),
        section_179_suv_limit=("Section 179 limit for a sport utility vehicle.", "eq"),
        section_179_phaseout_threshold=(
            "Cost of section 179 property above which the limit is reduced.",
            "gt",
        ),
        standard_mileage_rate_2026=(
            "2026 business standard mileage rate, in cents per mile.",
            "eq",
            "cents",
        ),
    ),
    "irs-p15": irs(
        ss_wage_base_2026=("2026 social security wage base limit.", "eq"),
        household_worker_threshold_2026=(
            "Cash wages to a household worker at which social security and Medicare taxes apply.",
            "ge",
        ),
        election_worker_threshold_2026=(
            "Pay to an election worker at which those taxes apply.",
            "ge",
        ),
        backup_withholding_threshold_2026=(
            "Aggregate reportable payment threshold for backup withholding in 2026.",
            "eq",
        ),
        qualified_tips_deduction_max=("Maximum deduction for qualified tips.", "le"),
        ss_tax_rate_2026=(
            "Social security tax rate, each for employer and employee, in percent.",
            "eq",
            "%",
        ),
        supplemental_withholding_rate=(
            "Withholding rate on supplemental wages (up to $1 million), in percent.",
            "eq",
            "%",
        ),
        backup_withholding_rate=("Backup withholding rate, in percent.", "eq", "%"),
        ss_wage_base_2025=("2025 social security wage base limit.", "eq"),
    ),
    "irs-p560": irs(
        compensation_limit_2025=("2025 maximum compensation for contributions and benefits.", "eq"),
        compensation_limit_2026=("The same limit for 2026.", "eq"),
        elective_deferral_limit_2025=("2025 elective deferral limit, excluding catch-up.", "eq"),
        elective_deferral_limit_2026=("The same limit for 2026.", "eq"),
        defined_contribution_limit_2025=(
            "2025 defined contribution plan limit, excluding catch-up.",
            "eq",
        ),
        defined_contribution_limit_2026=("The same limit for 2026.", "eq"),
        defined_benefit_limit_2025=("2025 defined benefit plan annual benefit limit.", "eq"),
        defined_benefit_limit_2026=("The same limit for 2026.", "eq"),
        simple_deferral_limit_2025=(
            "2025 SIMPLE plan salary reduction limit (general, not the higher limit).",
            "eq",
        ),
        simple_deferral_limit_2026=("The same limit for 2026.", "eq"),
        catch_up_limit_2025=(
            "2025 catch-up limit for defined contribution plans other than SIMPLE plans.",
            "eq",
        ),
        catch_up_limit_2026=("The same limit for 2026.", "eq"),
        catch_up_limit_age_60_to_63=("Higher catch-up limit for ages 60 to 63 (not SIMPLE).", "eq"),
        ira_contribution_limit_2026=("2026 traditional IRA contribution limit.", "eq"),
    ),
    "irs-p571": irs(
        savers_credit_limit_joint_2025=(
            "2025 saver's credit AGI limit, married filing jointly.",
            "eq",
        ),
        savers_credit_limit_joint_2026=("The same limit for 2026.", "eq"),
        savers_credit_limit_hoh_2025=("2025 saver's credit AGI limit, head of household.", "eq"),
        savers_credit_limit_hoh_2026=("The same limit for 2026.", "eq"),
        savers_credit_limit_single_2025=(
            "2025 saver's credit AGI limit, single and similar filers.",
            "eq",
        ),
        savers_credit_limit_single_2026=("The same limit for 2026.", "eq"),
        elective_deferral_limit_2025=("2025 limit on elective deferrals.", "eq"),
        elective_deferral_limit_2026=("2026 limit on elective deferrals.", "eq"),
        annual_additions_limit_2025=("2025 limit on annual additions.", "eq"),
        annual_additions_limit_2026=("2026 limit on annual additions.", "eq"),
        catch_up_age_60_to_63_floor=(
            "Dollar floor of the higher catch-up for ages 60 to 63.",
            "eq",
        ),
        catch_up_limit_age_50_2026=(
            "2026 age-50 catch-up contribution limit for 403(b) plans.",
            "eq",
        ),
    ),
    "irs-p554": irs(
        senior_deduction_max=("Maximum enhanced deduction for seniors, per person.", "eq"),
        senior_deduction_max_joint=("The same, married filing jointly with both eligible.", "eq"),
        standard_deduction_single=(
            "2025 standard deduction, single or married filing separately.",
            "eq",
        ),
        standard_deduction_joint=("2025 standard deduction, married filing jointly.", "eq"),
        standard_deduction_hoh=("2025 standard deduction, head of household.", "eq"),
        amt_exemption=("AMT exemption amount (single and other filers).", "eq"),
        amt_exemption_joint=("AMT exemption, married filing jointly.", "eq"),
        amt_exemption_separate=("AMT exemption, married filing separately.", "eq"),
        eic_limit_no_child=("EIC earned income limit, no qualifying child, not joint.", "lt"),
        eic_limit_three_children_joint=(
            "EIC earned income limit, three or more children, married filing jointly.",
            "lt",
        ),
        medical_mileage_rate=(
            "2025 medical standard mileage rate, in cents per mile.",
            "eq",
            "cents",
        ),
        standard_deduction_single_2026=("2026 standard deduction, single.", "eq"),
    ),
    "irs-p15b": irs(
        qualified_parking_exclusion_2026=("2026 monthly exclusion for qualified parking.", "eq"),
        transit_exclusion_2026=(
            "2026 monthly exclusion for commuter highway vehicles and transit passes.",
            "eq",
        ),
        health_fsa_limit_2026=("2026 health FSA salary reduction limit.", "le"),
        dependent_care_fsa_limit_2026=(
            "2026 dependent care FSA limit (not married filing separately).",
            "eq",
        ),
        dependent_care_fsa_limit_separate_2026=("The same limit, married filing separately.", "eq"),
        student_loan_payment_exclusion=("Exclusion for employer payments of student loans.", "eq"),
        supplemental_withholding_rate=(
            "Withholding rate on supplemental wages (up to $1 million), in percent.",
            "eq",
            "%",
        ),
        supplemental_wage_threshold=(
            "Supplemental wages above which the 37% rate applies, in dollars.",
            "gt",
        ),
        business_mileage_rate_2026=(
            "2026 business standard mileage rate, in cents per mile.",
            "eq",
            "cents",
        ),
    ),
}

# ---------------------------------------------------------------------------------- drafts
# field: [value, context, context, ...] ; value None = absent

FDA = {
    "fda-lisinopril": {
        "adult_starting_dose": [
            "10",
            "Initial adult dose is [[10 mg]] once daily",
            "The recommended initial dose is [[10 mg]] once a day",
        ],
        "adult_max_daily_dose": ["40", "Titrate up to [[40 mg]] daily based on blood pressure"],
        "pediatric_min_age": [
            "6",
            "Initial dose in patients [[6 years]] of age and older",
            "Pediatric Patients [[6 Years]] of Age and Older with Hypertension",
        ],
        "tablet_strengths": [
            ["2.5", "Tablets: [[2.5 mg]], 5 mg"],
            ["5", "Tablets: 2.5 mg, [[5 mg]]"],
            ["10", "5 mg, [[10 mg]], 20 mg, 40 mg (3)"],
            ["20", "10 mg, [[20 mg]], 40 mg (3)"],
            ["40", "20 mg, [[40 mg]] (3)"],
        ],
        "hepatic_starting_dose": [None],
    },
    "fda-amlodipine": {
        "adult_starting_dose": [
            "5",
            "Adult recommended starting dose: [[5 mg]] once daily",
            "antihypertensive oral dose of Amlodipine besylate tablets is [[5 mg]]",
        ],
        "adult_max_daily_dose": [
            "10",
            "once daily with maximum dose [[10 mg]] once daily",
            "and the maximum dose is [[10 mg]] once daily",
        ],
        "pediatric_min_age": ["6", "pediatric patients ages [[6]] to 17 years"],
        "tablet_strengths": [
            ["2.5", "Tablets: [[2.5 mg]], 5 mg, and 10 mg"],
            ["5", "Tablets: 2.5 mg, [[5 mg]], and 10 mg"],
            ["10", "2.5 mg, 5 mg, and [[10 mg]] ( 3)"],
        ],
        "hepatic_starting_dose": [
            "2.5",
            "patients with hepatic insufficiency may be started on [[2.5 mg]] once daily. ( 2.1)",
            "hepatic insufficiency may be started on [[2.5 mg]] once daily and",
        ],
    },
    "fda-atorvastatin": {
        "adult_starting_dose": [
            "10",
            "Recommended starting dosage is [[10]] or 20 mg once daily",
            "Adult Patients\n\nThe recommended starting dosage of atorvastatin calcium is [[10 mg]]",
        ],
        "adult_max_daily_dose": [
            "80",
            "Recommended starting dosage is 10 or 20 mg once daily; dosage range is 10 mg to [[80 mg]]",
            "Adult Patients\n\nThe recommended starting dosage of atorvastatin calcium is 10 mg to 20 mg once daily. The dosage range is 10 mg to [[80 mg]]",
        ],
        "pediatric_min_age": [
            "10",
            "Pediatric Patients Aged [[10 Years]] of Age and Older with HeFH:",
        ],
        "tablet_strengths": [
            ["10", "Tablets: [[10 mg]]; 20 mg"],
            ["20", "10 mg; [[20 mg]]; 40 mg"],
            ["40", "20 mg; [[40 mg]] 80 mg"],
            ["80", "40 mg [[80 mg]] of atorvastatin ( 3)"],
        ],
        "hepatic_starting_dose": [None],
    },
    "fda-metoprolol-succinate": {
        "adult_starting_dose": [
            "25",
            "Hypertension: Starting dose is [[25]] to 100 mg",
            "The usual initial dosage is [[25]] to 100 mg daily",
        ],
        "adult_max_daily_dose": [None],
        "pediatric_min_age": ["6", "Pediatric Hypertensive Patients ≥ [[6 Years]] of age"],
        "tablet_strengths": [
            ["25", "Metoprolol succinate extended-release tablets: [[25 mg]]. (3)"]
        ],
        "hepatic_starting_dose": [None],
    },
    "fda-losartan": {
        "adult_starting_dose": [
            "50",
            "Usual adult dose: [[50 mg]] once daily",
            "The usual starting dose of losartan potassium tablets are [[50 mg]]",
        ],
        "adult_max_daily_dose": [
            "100",
            "increased to a maximum dose of [[100 mg]] once daily as needed",
        ],
        "pediatric_min_age": ["6", "pediatric patients less than [[6 years]] of age"],
        "tablet_strengths": [
            ["25", "Tablets: [[25 mg]]; 50 mg"],
            ["50", "25 mg; [[50 mg]]; and 100 mg"],
            ["100", "50 mg; and [[100 mg]]. (3)"],
        ],
        "hepatic_starting_dose": [
            "25",
            "the recommended starting dose of losartan potassium tablet is [[25 mg]] once daily",
        ],
    },
    "fda-escitalopram": {
        "adult_starting_dose": [
            "10",
            "Adults ( 2.1)\n\nInitial: [[10 mg]] once daily",
            "The recommended dosage of escitalopram tablets in adults is [[10 mg]] once daily. A fixed",
        ],
        "adult_max_daily_dose": [
            "20",
            "Adults ( 2.1)\n\nInitial: 10 mg once daily\n\nRecommended: 10 mg once daily\n\nMaximum: [[20 mg]]",
            "increased to the maximum recommended dosage of [[20 mg]] once daily at an interval of no less than 1 week.\n\nPediatric Patients 12",
        ],
        "pediatric_min_age": ["7", "Pediatric Patients [[7 years]] of age and older\n\nThe"],
        "tablet_strengths": [["10", "Tablets: [[10 mg]] (scored)"]],
        "hepatic_starting_dose": [
            "10",
            "Hepatic impairment: recommended dosage is [[10 mg]] once daily",
            "patients with hepatic impairment is [[10 mg]] once daily",
        ],
    },
    "fda-sertraline": {
        "adult_starting_dose": ["50", "MDD (2.1)\n\n[[50 mg]] per day"],
        "adult_max_daily_dose": ["200", "MDD (2.1)\n\n50 mg per day\n\n[[200 mg]] per day"],
        "pediatric_min_age": [
            "6",
            "25 mg per day (ages [[6]] to 12)",
            "OCD (ages [[6]] to 12 years old)",
        ],
        "tablet_strengths": [
            ["25", "Tablets: [[25 mg]], 50 mg and 100 mg"],
            ["50", "25 mg, [[50 mg]] and 100 mg (3)"],
            ["100", "50 mg and [[100 mg]] (3)"],
        ],
        "hepatic_starting_dose": [None],
    },
    "fda-gabapentin": {
        "adult_starting_dose": [
            "300",
            "Day 1: Single [[300 mg]] dose",
            "on Day 1 as a single [[300 mg]] dose",
        ],
        "adult_max_daily_dose": [
            "1800",
            "titrated up as needed to a dose of [[1800 mg]]/day\nDay",
            "for pain relief to a dose of [[1800 mg]]/day (600 mg",
        ],
        "pediatric_min_age": [
            "3",
            "Patients [[3]] to 11 years of age: starting dose",
            "Pediatric Patients Age [[3]] to 11 years",
        ],
        "tablet_strengths": [
            ["600", "Tablets: [[600 mg]], and 800 mg"],
            ["800", "600 mg, and [[800 mg]] (3)"],
        ],
        "hepatic_starting_dose": [None],
    },
    "fda-simvastatin": {
        "adult_starting_dose": [
            "20",
            "Adults: Recommended dosage is [[20 mg]] to 40 mg once daily",
            "recommended dosage range of simvastatin tablets USP is [[20 mg]] to 40 mg once daily",
        ],
        "adult_max_daily_dose": [
            "40",
            "Maximum recommended dosage is simvastatin tablets USP [[40 mg]] once daily.",
            "The maximum recommended dosage is simvastatin tablets USP [[40 mg]] once daily [",
        ],
        "pediatric_min_age": ["10", "Pediatric Patients Aged [[10 Years]] and Older with HeFH"],
        "tablet_strengths": [
            ["5", "Tablets: [[5 mg]], 10 mg"],
            ["10", "5 mg, [[10 mg]]; 20 mg"],
            ["20", "10 mg; [[20 mg]]; 40 mg"],
            ["40", "20 mg; [[40 mg]]; 80 mg"],
            ["80", "40 mg; [[80 mg]]"],
        ],
        "hepatic_starting_dose": [None],
    },
    "fda-levothyroxine": {
        "adult_starting_dose": [None],
        "adult_max_daily_dose": [None],
        "pediatric_min_age": [None],
        "tablet_strengths": [
            ["25", "[[25 mcg]]\n\nPeach/Round"],
            ["50", "[[50 mcg]]\n\nWhite/Round"],
            ["75", "[[75 mcg]]\n\nViolet/Round"],
            ["88", "[[88 mcg]]\n\nOlive/Round"],
            ["100", "[[100 mcg]]\n\nYellow/Round"],
            ["112", "[[112 mcg]]\n\nRose/Round"],
            ["125", "[[125 mcg]]\n\nTan/Round"],
            ["137", "[[137 mcg]]\n\nTurquoise/Round"],
            ["150", "[[150 mcg]]\n\nBlue/Round"],
            ["175", "[[175 mcg]]\n\nLilac/Round"],
            ["200", "[[200 mcg]]\n\nPink/Round"],
            ["300", "[[300 mcg]]\n\nGreen/Round"],
        ],
        "hepatic_starting_dose": [None],
    },
}
FDA_UNIT_OVERRIDE = {"fda-levothyroxine": "mcg"}

NTSB = {
    "ntsb-192700": {
        "pilot_age": ["43", "Toxicology Performed:\n\n[[43]],Male"],
        "pilot_total_hours": ["213", "[[213 hours]] (Total, all aircraft)"],
        "pilot_make_model_hours": ["0.4", "[[0.4 hours]] (Total, this make and model)"],
        "pilot_last_90_days_hours": ["8", "[[8 hours]] (Last 90 days, all aircraft)"],
        "aircraft_year": ["2002", "V-Strut\n\n[[2002]]"],
        "airframe_total_hours": ["100", "[[100 Hrs]]"],
        "airport_elevation": ["808", "[[808 ft]] msl"],
        "runway_length": [None],
        "visibility": ["4", "[[4 miles]]"],
        "wind_speed": [None],
        "temperature": ["22", "[[22°C]] / 19°C"],
        "altimeter_setting": ["30.07", "[[30.07 inches Hg]]"],
    },
    "ntsb-192703": {
        "pilot_age": ["50", "Toxicology Performed:\n\n[[50]],"],
        "pilot_total_hours": ["30948", "[[30948 hours]] (Total, all aircraft)"],
        "pilot_make_model_hours": ["5240", "[[5240 hours]] (Total, this make and model)"],
        "pilot_last_90_days_hours": ["340", "[[340 hours]] (Last 90 days, all aircraft)"],
        "aircraft_year": ["2010", "AT-602\n\n[[2010]]"],
        "airframe_total_hours": [None],
        "airport_elevation": ["2762", "[[2762 ft]] msl"],
        "runway_length": ["3200", "[[3200 ft]] / 25 ft"],
        "visibility": ["10", "[[10 miles]]"],
        "wind_speed": ["10", "[[10 knots]] / None"],
        "temperature": ["0", "[[0°C]] / 0°C"],
        "altimeter_setting": ["30.22", "[[30.22 inches Hg]]"],
    },
    "ntsb-192705": {
        "pilot_age": ["21", "[[21]],Male\n\nRight"],
        "pilot_total_hours": ["672", "[[672 hours]] (Total, all aircraft)"],
        "pilot_make_model_hours": ["39", "[[39 hours]] (Total, this make and model)"],
        "pilot_last_90_days_hours": ["232", "[[232 hours]] (Last 90 days, all aircraft)"],
        "aircraft_year": ["1969", "Year of Manufacture:\n\n[[1969]]"],
        "airframe_total_hours": [None],
        "airport_elevation": ["609", "Airport Elevation:\n\n[[609 ft]] msl"],
        "runway_length": ["5499", "[[5499 ft]] / 100 ft"],
        "visibility": ["10", "[[10 miles]]"],
        "wind_speed": ["4", "[[4 knots]] / None"],
        "temperature": ["31", "[[31°C]] / 21°C"],
        "altimeter_setting": ["30.12", "[[30.12 inches Hg]]"],
    },
    "ntsb-192706": {
        "pilot_age": ["76", "Toxicology Performed:\n\n[[76]]\n\nLeft"],
        "pilot_total_hours": ["1395", "[[1395 hours]] (Total, all aircraft)"],
        "pilot_make_model_hours": ["1326", "[[1326 hours]] (Total, this make and model)"],
        "pilot_last_90_days_hours": ["28", "[[28 hours]] (Last 90 days, all aircraft)"],
        "aircraft_year": ["1946", "415-D\n\n[[1946]]"],
        "airframe_total_hours": ["2378.12", "[[2378.12 Hrs]] as of last inspection"],
        "airport_elevation": [None],
        "runway_length": [None],
        "visibility": ["10", "[[10 miles]]"],
        "wind_speed": ["8", "[[8 knots]] / None"],
        "temperature": ["23", "[[23°C]] / 16°C"],
        "altimeter_setting": ["29.83", "[[29.83 inches Hg]]"],
    },
    "ntsb-192707": {
        "pilot_age": ["66", "[[66]],Male"],
        "pilot_total_hours": ["728", "[[728 hours]] (Total, all aircraft)"],
        "pilot_make_model_hours": ["114", "[[114 hours]] (Total, this make and model)"],
        "pilot_last_90_days_hours": ["30", "[[30 hours]] (Last 90 days, all aircraft)"],
        "aircraft_year": ["2022", "RV-10\n\n[[2022]]"],
        "airframe_total_hours": ["109.4", "[[109.4 Hrs]] at time of accident"],
        "airport_elevation": ["808", "Airport Elevation:\n\n[[808 ft]] msl"],
        "runway_length": ["6179", "[[6179 ft]] / 150 ft"],
        "visibility": [None],
        "wind_speed": ["12", "[[12 knots]] / 20 knots"],
        "temperature": ["25", "[[25°C]] / 14.4°C"],
        "altimeter_setting": ["29.89", "[[29.89 inches Hg]]"],
    },
    "ntsb-192708": {
        "pilot_age": ["34", "[[34]],Male"],
        "pilot_total_hours": ["29", "[[29 hours]] (Total, all aircraft)"],
        "pilot_make_model_hours": ["29", "[[29 hours]] (Total, this make and model)"],
        "pilot_last_90_days_hours": [None],
        "aircraft_year": ["1963", "Year of Manufacture:\n\n[[1963]]"],
        "airframe_total_hours": ["6092", "[[6092 Hrs]] as of last inspection"],
        "airport_elevation": ["145", "Airport Elevation:\n\n[[145 ft]] msl"],
        "runway_length": ["5005", "[[5005 ft]] / 99 ft"],
        "visibility": ["10", "[[10 miles]]"],
        "wind_speed": ["7", "[[7 knots]] / None"],
        "temperature": ["28", "[[28°C]] / 25°C"],
        "altimeter_setting": ["29.97", "[[29.97 inches Hg]]"],
    },
    "ntsb-192709": {
        "pilot_age": ["22", "Toxicology Performed:\n\n[[22]]\n\nRight"],
        "pilot_total_hours": ["324", "[[324 hours]] (Total, all aircraft)"],
        "pilot_make_model_hours": ["303", "[[303 hours]] (Total, this make and model)"],
        "pilot_last_90_days_hours": ["44", "[[44 hours]] (Last 90 days, all aircraft)"],
        "aircraft_year": ["2003", "DA 40\n\n[[2003]]"],
        "airframe_total_hours": ["3813.5", "[[3813.5 Hrs]] at time of accident"],
        "airport_elevation": ["1175", "Airport Elevation:\n\n[[1175 ft]] msl"],
        "runway_length": ["6800", "[[6800 ft]] / 150 ft"],
        "visibility": ["10", "[[10 miles]]"],
        "wind_speed": ["5", "[[5 knots]] / None"],
        "temperature": ["28", "[[28°C]] / 20°C"],
        "altimeter_setting": ["29.89", "[[29.89 inches Hg]]"],
    },
    "ntsb-192715": {
        "pilot_age": ["34", "[[34]],Male"],
        "pilot_total_hours": ["975", "[[975 hours]] (Total, all aircraft)"],
        "pilot_make_model_hours": ["110", "[[110 hours]] (Total, this make and model)"],
        "pilot_last_90_days_hours": ["145", "[[145 hours]] (Last 90 days, all aircraft)"],
        "aircraft_year": ["2008", "Year of Manufacture:\n\n[[2008]]"],
        "airframe_total_hours": ["4033.3", "[[4033.3 Hrs]] at time of accident"],
        "airport_elevation": [None],
        "runway_length": [None],
        "visibility": ["7", "[[7 miles]]"],
        "wind_speed": ["4", "[[4 knots]] / 0 knots"],
        "temperature": ["23", "[[23°C]] / 19°C"],
        "altimeter_setting": ["29.98", "[[29.98 inches Hg]]"],
    },
    "ntsb-192716": {
        "pilot_age": ["57", "[[57]],Male"],
        "pilot_total_hours": ["2680", "[[2680 hours]] (Total, all aircraft)"],
        "pilot_make_model_hours": ["200", "[[200 hours]] (Total, this make and model)"],
        "pilot_last_90_days_hours": [None],
        "aircraft_year": ["2021", "Year of Manufacture:\n\n[[2021]]"],
        "airframe_total_hours": ["132", "[[132 Hrs]] at time of accident"],
        "airport_elevation": [None],
        "runway_length": [None],
        "visibility": ["10", "[[10 miles]]"],
        "wind_speed": ["5", "[[5 knots]] / 15 knots"],
        "temperature": ["18", "[[18°C]] / 9°C"],
        "altimeter_setting": ["30.09", "[[30.09 inches Hg]]"],
    },
    "ntsb-192717": {
        "pilot_age": ["57", "[[57]],Male\n\nRear"],
        "pilot_total_hours": ["19200", "(Estimated) [[19200 hours]] (Total, all aircraft)"],
        "pilot_make_model_hours": ["105", "[[105 hours]] (Total, this make and model)"],
        "pilot_last_90_days_hours": ["201", "[[201 hours]] (Last 90 days, all aircraft)"],
        "aircraft_year": ["1942", "A75N1\n\n[[1942]]"],
        "airframe_total_hours": ["2693.4", "[[2693.4 Hrs]] at time of accident"],
        "airport_elevation": ["5762", "Airport Elevation:\n\n[[5762 ft]] msl"],
        "runway_length": ["4000", "[[4000 ft]] / 75 ft"],
        "visibility": ["10", "[[10 miles]]"],
        "wind_speed": ["5", "[[5 knots]] / 10 knots"],
        "temperature": ["27", "[[27°C]] / 2°C"],
        "altimeter_setting": ["30.18", "[[30.18 inches Hg]]"],
    },
}

IRS = {
    "irs-p501": {
        "senior_deduction_max": ["6000", "The maximum amount of the deduction is [[$6,000]]"],
        "senior_deduction_max_joint": ["12000", "deduction is $6,000 ([[$12,000]] if married"],
        "trump_account_pilot_contribution": ["1000", "elect to receive a [[$1,000]] pilot program"],
        "filing_threshold_single_under_65": ["15750", "[[$15,750]]\n$17,750"],
        "filing_threshold_single_65_or_older": ["17750", "$15,750\n[[$17,750]]"],
        "filing_threshold_hoh_under_65": ["23625", "[[$23,625]]\n$25,625"],
        "filing_threshold_joint_both_under_65": ["31500", "$25,625\n[[$31,500]]"],
        "filing_threshold_separate": [
            "5",
            "$34,700\n[[$5]]\n$31,500",
            "your gross income was at least [[$5]], you must file",
        ],
        "ss_benefits_income_threshold": [
            "25000",
            "income and any tax-exempt interest is more than [[$25,000]]",
        ],
        "ss_benefits_income_threshold_joint": [
            "32000",
            "more than $25,000 ([[$32,000]] if married filing jointly)",
        ],
        "dependent_standard_deduction_min": [None],
    },
    "irs-p505": {
        "standard_deduction_single_2026": ["16100", "rately—[[$16,100]]."],
        "standard_deduction_joint_2026": ["32200", "spouse—[[$32,200]]."],
        "standard_deduction_hoh_2026": ["24150", "Head of household—[[$24,150]]."],
        "savers_credit_magi_limit_single_2026": ["40250", "must not be more than [[$40,250]]"],
        "savers_credit_magi_limit_joint_2026": [
            "80500",
            "$40,250 ([[$80,500]] if Married filing jointly",
        ],
        "adoption_credit_max_2026": ["17670", "has to [[$17,670]]."],
        "adoption_credit_magi_limit_2026": ["305080", "your MAGI must be less than [[$305,080]]."],
        "adoption_credit_refundable_max_2026": [
            "5120",
            "For 2026, up to [[$5,120]] of the adoption credit",
        ],
        "minimum_qbid_2026": ["400", "claim a minimum QBID of [[$400]]."],
        "itemized_limit_threshold_joint_2026": ["768700", "[[$768,700]] if Married filing jointly"],
        "charitable_nonitemizer_max_2026": ["1000", "mum deduction is [[$1,000]] ($2,000"],
        "charitable_nonitemizer_max_joint_2026": [
            "2000",
            "is $1,000 ([[$2,000]] for married filing jointly)",
        ],
        "standard_deduction_single_2025": [None],
    },
    "irs-p970": {
        "trump_account_pilot_contribution": ["1000", "elect to receive a [[$1,000]] pilot program"],
        "student_loan_phaseout_start": [
            "85000",
            "if your MAGI is between [[$85,000]] and $100,000",
        ],
        "student_loan_phaseout_end": [
            "100000",
            "between $85,000 and [[$100,000]] ($170,000",
            "if your MAGI is [[$100,000]] or more ($200,000",
        ],
        "student_loan_phaseout_start_joint": ["170000", "$100,000 ([[$170,000]] and $200,000"],
        "student_loan_phaseout_end_joint": [
            "200000",
            "($170,000 and [[$200,000]] if you file a joint",
            "$100,000 or more ([[$200,000]] or more if you file",
        ],
        "savings_bond_phaseout_start": ["99500", "between [[$99,500]] and $114,500"],
        "savings_bond_phaseout_end": [
            "114500",
            "between $99,500 and [[$114,500]] ($149,250",
            "interest if your MAGI is [[$114,500]] or more",
        ],
        "savings_bond_phaseout_start_joint": ["149250", "$114,500 ([[$149,250]] and $179,250"],
        "savings_bond_phaseout_end_joint": [
            "179250",
            "($149,250 and [[$179,250]] if you file a joint",
            "$114,500 or more ([[$179,250]] or more if you file",
        ],
        "education_mileage_rate": ["70", "is [[70 cents]] a mile. See chapter 11."],
        "american_opportunity_credit_max": [None],
    },
    "irs-p596": {
        "eic_limit_three_children": [
            "61555",
            "must be less than:\n• [[$61,555]] ($68,675 for married filing jointly) if you have three or more qualifying children who have valid social",
            "must be less than:\n12. You can’t be the dependent of another person.\n13. You can’t be a qualifying child of another person.\n14. You must have lived in the United States more than half of the year.\n• [[$61,555]]",
        ],
        "eic_limit_three_children_joint": [
            "68675",
            "income under [[$68,675]].",
            "must be less than:\n• $61,555 ([[$68,675]] for married filing jointly) if you have three or more qualifying children who have valid social",
        ],
        "eic_limit_two_children": [
            "57310",
            "numbers (SSNs),\n• [[$57,310]]",
            "children who have valid SSNs,\n• [[$57,310]]",
        ],
        "eic_limit_two_children_joint": [
            "64430",
            "numbers (SSNs),\n• $57,310 ([[$64,430]]",
            "children who have valid SSNs,\n• $57,310 ([[$64,430]]",
        ],
        "eic_limit_one_child": [
            "50434",
            "• [[$50,434]] ($57,554 for married filing jointly) if you have one qualifying child who has a valid SSN, or\n• $19,104 ($26,214 for married filing jointly) if you don’t have a qualifying child who has a valid SSN.\n2.",
            "• [[$50,434]] ($57,554 for married filing jointly) if you have one qualifying child who has a valid SSN, or\n• $19,104 ($26,214 for married filing jointly) if you don’t have a qualifying child who has a valid SSN.\nDo I Need",
        ],
        "eic_limit_one_child_joint": [
            "57554",
            "• $50,434 ([[$57,554]] for married filing jointly) if you have one qualifying child who has a valid SSN, or\n• $19,104 ($26,214 for married filing jointly) if you don’t have a qualifying child who has a valid SSN.\n2.",
            "• $50,434 ([[$57,554]] for married filing jointly) if you have one qualifying child who has a valid SSN, or\n• $19,104 ($26,214 for married filing jointly) if you don’t have a qualifying child who has a valid SSN.\nDo I Need",
        ],
        "eic_limit_no_child": [
            "19104",
            "• [[$19,104]] ($26,214 for married filing jointly) if you don’t have a qualifying child who has a valid SSN.\n2.",
            "• [[$19,104]] ($26,214 for married filing jointly) if you don’t have a qualifying child who has a valid SSN.\nDo I Need",
        ],
        "eic_limit_no_child_joint": [
            "26214",
            "• $19,104 ([[$26,214]] for married filing jointly) if you don’t have a qualifying child who has a valid SSN.\n2.",
            "• $19,104 ([[$26,214]] for married filing jointly) if you don’t have a qualifying child who has a valid SSN.\nDo I Need",
        ],
        "eic_investment_income_limit": [
            "11950",
            "Your investment income must be [[$11,950]] or less.",
        ],
        "eic_max_credit_three_children": [None],
    },
    "irs-p463": {
        "standard_mileage_rate": ["70", "for business use is [[70 cents]] ($0.70) per mile"],
        "car_depreciation_year1_bonus": ["20200", "first tax year, [[$20,200]]; second"],
        "car_depreciation_year2": [
            "19600",
            "$20,200; second tax year, [[$19,600]];",
            "$12,200; second tax year, [[$19,600]];",
        ],
        "car_depreciation_year3": [
            "11800",
            "$20,200; second tax year, $19,600; third tax year, [[$11,800]];",
            "$12,200; second tax year, $19,600; third tax year, [[$11,800]];",
        ],
        "car_depreciation_later_years": [
            "7060",
            "$20,200; second tax year, $19,600; third tax year, $11,800; and each succeeding year, [[$7,060]].",
            "$12,200; second tax year, $19,600; third tax year, $11,800; and each succeed- ing year, [[$7,060]].",
        ],
        "car_depreciation_year1_no_bonus": ["12200", "first tax year, [[$12,200]]; second"],
        "section_179_limit": ["2500000", "cannot exceed [[$2,500,000]] and the cost"],
        "section_179_suv_limit": ["31300", "Code section 179 cannot exceed [[$31,300]]."],
        "section_179_phaseout_threshold": ["4000000", "2025 tax year exceeds [[$4,000,000]]."],
        "standard_mileage_rate_2026": [None],
    },
    "irs-p15": {
        "ss_wage_base_2026": ["184500", "wage base limit is [[$184,500]]."],
        "household_worker_threshold_2026": ["3000", "household workers you pay [[$3,000]] or more"],
        "election_worker_threshold_2026": ["2500", "who are paid [[$2,500]] or more"],
        "backup_withholding_threshold_2026": [
            "2000",
            "payment threshold from $600 to [[$2,000]]. This threshold will",
        ],
        "qualified_tips_deduction_max": ["25000", "to deduct up to [[$25,000]] of qualified tips"],
        "ss_tax_rate_2026": ["6.2", "taxable wages is [[6.2%]] each"],
        "supplemental_withholding_rate": ["22", "supplemental wages remains [[22%]] (37%"],
        "backup_withholding_rate": ["24", "The backup withholding rate re- mains [[24%]]"],
        "ss_wage_base_2025": [None],
    },
    "irs-p560": {
        "compensation_limit_2025": ["350000", "contributions and benefits is [[$350,000]]."],
        "compensation_limit_2026": ["360000", "This limit increases to [[$360,000]] for 2026."],
        "elective_deferral_limit_2025": [
            "23500",
            "catch-up contributions, is [[$23,500]] for 2025",
        ],
        "elective_deferral_limit_2026": ["24500", "is $23,500 for 2025 and [[$24,500]] for 2026."],
        "defined_contribution_limit_2025": [
            "70000",
            "defined contribution plan is [[$70,000]] for 2025",
        ],
        "defined_contribution_limit_2026": ["72000", "increases to [[$72,000]] for 2026."],
        "defined_benefit_limit_2025": ["280000", "defined benefit plan is [[$280,000]] for 2025"],
        "defined_benefit_limit_2026": ["290000", "increases to [[$290,000]] for 2026."],
        "simple_deferral_limit_2025": ["16500", "catch-up contributions, is [[$16,500]] for 2025"],
        "simple_deferral_limit_2026": ["17000", "increases to [[$17,000]] for 2026."],
        "catch_up_limit_2025": ["7500", "other than SIMPLE plans is [[$7,500]] for 2025"],
        "catch_up_limit_2026": ["8000", "is $7,500 for 2025 and [[$8,000]] for 2026."],
        "catch_up_limit_age_60_to_63": ["11250", "for such participants is [[$11,250]] ($5,250"],
        "ira_contribution_limit_2026": [None],
    },
    "irs-p571": {
        "savers_credit_limit_joint_2025": ["79000", "increased from [[$79,000]] to $80,500"],
        "savers_credit_limit_joint_2026": ["80500", "from $79,000 to [[$80,500]] for married"],
        "savers_credit_limit_hoh_2025": ["59250", "from [[$59,250]] to $60,375"],
        "savers_credit_limit_hoh_2026": ["60375", "from $59,250 to [[$60,375]] for head"],
        "savers_credit_limit_single_2025": ["39500", "from [[$39,500]] to $40,250"],
        "savers_credit_limit_single_2026": ["40250", "from $39,500 to [[$40,250]] for single"],
        "elective_deferral_limit_2025": ["23500", "increased from [[$23,500]] to $24,500."],
        "elective_deferral_limit_2026": ["24500", "from $23,500 to [[$24,500]]."],
        "annual_additions_limit_2025": ["70000", "increased from [[$70,000]] to $72,000."],
        "annual_additions_limit_2026": ["72000", "from $70,000 to [[$72,000]]."],
        "catch_up_age_60_to_63_floor": ["10000", "between the greater of [[$10,000]] or 150%"],
        "catch_up_limit_age_50_2026": [None],
    },
    "irs-p554": {
        "senior_deduction_max": [
            "6000",
            "The maximum amount of the deduction is [[$6,000]] per person",
        ],
        "senior_deduction_max_joint": ["12000", "per person ([[$12,000]] if married"],
        "standard_deduction_single": ["15750", "Married filing separately—[[$15,750]];"],
        "standard_deduction_joint": ["31500", "spouse—[[$31,500]]; and"],
        "standard_deduction_hoh": ["23625", "Head of household—[[$23,625]]."],
        "amt_exemption": ["88100", "has increased to [[$88,100]] ($137,000"],
        "amt_exemption_joint": ["137000", "$88,100 ([[$137,000]] if married filing jointly"],
        "amt_exemption_separate": [
            "68500",
            "surviving spouse; [[$68,500]] if married filing separately)",
        ],
        "eic_limit_no_child": [
            "19104",
            "• [[$19,104]] ($26,214 if married filing jointly), don’t have",
        ],
        "eic_limit_three_children_joint": [
            "68675",
            "$61,555 ([[$68,675]] if married filing jointly), and you have three",
        ],
        "medical_mileage_rate": ["21", "for medical reasons is [[21 cents]] a mile."],
        "standard_deduction_single_2026": [None],
    },
    "irs-p15b": {
        "qualified_parking_exclusion_2026": ["340", "fied parking is [[$340]] and the monthly"],
        "transit_exclusion_2026": ["340", "transit passes is [[$340]]. See Qualified"],
        "health_fsa_limit_2026": ["3400", "health FSA in excess of [[$3,400]]."],
        "dependent_care_fsa_limit_2026": ["7500", "raised from $5,000 to [[$7,500]] ($2,500"],
        "dependent_care_fsa_limit_separate_2026": [
            "3750",
            "($2,500 to [[$3,750]] for married filing separately",
        ],
        "student_loan_payment_exclusion": ["5250", "manently extends the [[$5,250]] exclusion"],
        "supplemental_withholding_rate": ["22", "supplemental wages remains [[22%]] (37%"],
        "supplemental_wage_threshold": [
            "1000000",
            "during the calendar year exceed [[$1 million]])",
        ],
        "business_mileage_rate_2026": [None],
    },
}


# ---------------------------------------------------------------------------------- builder


ERRORS: list[str] = []


def _locate(text: str, raw: bytes, context: str) -> dict[str, int]:
    """Byte span of the [[...]] part of a context that occurs exactly once."""
    pre, rest = context.split("[[", 1)
    mid, post = rest.split("]]", 1)
    pieces = [re.escape(p) for p in re.split(r"\s+", pre.strip())] if pre.strip() else []
    ws = r"\s+"
    pat = (ws.join(pieces) + (ws if pre[-1:].isspace() else "")) if pieces else ""
    pat += "(" + ws.join(re.escape(p) for p in mid.split()) + ")"
    if post.strip():
        pat += (ws if post[:1].isspace() else "") + ws.join(re.escape(p) for p in post.split())
    hits = list(re.finditer(pat, text))
    if len(hits) != 1:
        raise ValueError(f"context matches {len(hits)} times: {context!r}")
    s, e = hits[0].span(1)
    return {"start": len(text[:s].encode()), "end": len(text[:e].encode())}


def build(doc_id: str) -> dict:
    kind = doc_id.split("-", 1)[0]
    if kind == "fda":
        table, units, drafts = FDA_FIELDS, FDA_UNITS, FDA[doc_id]
    elif kind == "ntsb":
        table, units, drafts = NTSB_FIELDS, NTSB_UNITS, NTSB[doc_id]
    else:
        table, units, drafts = IRS_FIELDS[doc_id], IRS_UNITS, IRS[doc_id]
    text = (DOCS / f"{doc_id}.txt").read_text(encoding="utf-8")
    raw = text.encode()
    fields = {}
    for name, (schema, desc) in table.items():
        schema = {k: v for k, v in schema.items() if v is not None or k == "unit"}
        if kind == "fda" and schema["unit"] == "mg" and doc_id in FDA_UNIT_OVERRIDE:
            schema["unit"] = FDA_UNIT_OVERRIDE[doc_id]
        fields[name] = {"schema": schema, "description": desc}
    facts, absent = [], {}
    for name, spec in drafts.items():
        if name not in fields:
            raise SystemExit(f"{doc_id}: draft for unknown field {name}")
        unit = fields[name]["schema"]["unit"]
        entries = spec if fields[name]["schema"].get("multiple") else [spec]
        for entry in entries:
            value, *contexts = entry
            if value is None:
                absent[name] = "draft"
                continue
            evidence = []
            for c in contexts:
                try:
                    evidence.append(_locate(text, raw, c))
                except ValueError as e:
                    ERRORS.append(f"{doc_id}: {e}")
            facts.append({"id": f"f{len(facts) + 1}", "field": name, "value": value, "unit": unit,
                          "evidence": evidence, "status": "draft"})  # fmt: skip
    missing = set(fields) - set(drafts)
    if missing:
        raise SystemExit(f"{doc_id}: no draft for {sorted(missing)}")
    return {"doc": doc_id, "kind": kind, "fields": fields, "units": units, "facts": facts,
            "absent": absent, "excluded": {}, "prelabeled_by": "Claude (model draft)",
            "checked": None}  # fmt: skip


def main() -> None:
    ids = [*FDA, *NTSB, *IRS]
    wrote = 0
    built = {doc_id: build(doc_id) for doc_id in ids}  # validates every draft
    if ERRORS:
        raise SystemExit("\n".join(ERRORS))
    for doc_id, gold in built.items():
        path = HERE / f"{doc_id}.json"
        if path.exists():
            continue  # never overwrite labels a person may have edited
        path.write_text(json.dumps(gold, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        wrote += 1
    print(f"{len(ids)} drafts valid; wrote {wrote} new gold files")


if __name__ == "__main__":
    main()
