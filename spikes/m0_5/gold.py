"""Spike gold facts: (id, field, value, unit, qualifier, pattern).

Each pattern must match its document exactly once; the named group `v` is the value's span.
A literal space in a pattern matches any run of whitespace. `qualifier` is the comparator the
field itself declares (e.g. a phase-out "starts above"), so a matching qualifier in the source
is expected and does not need review.

Labelled by the spike author from the source text; every span is verified mechanically by
`locate()`. This is spike data, not the person-checked benchmark gold.
"""

IRS = "irs-p590a"
FDA = "fda-metformin-er"

GOLD: list[tuple[str, str, str, str, str, str | None, str]] = [
    # doc, id, field, value, unit, qualifier, pattern
    (IRS, "irs01", "ira_contribution_limit_2025", "7000", "USD", None, r"limit remains (?P<v>\$7,000)"),
    (IRS, "irs02", "ira_contribution_limit_2025_age50", "8000", "USD", None, r"remains \$7,000 \((?P<v>\$8,000)"),
    (IRS, "irs03", "trump_account_pilot_contribution", "1000", "USD", None, r"a (?P<v>\$1,000) pilot program"),
    (IRS, "irs04", "trad_ira_phaseout_start_mfj_2025", "126000", "USD", "more_than", r"More than (?P<v>\$126,000)"),
    (IRS, "irs05", "trad_ira_phaseout_end_mfj_2025", "146000", "USD", "less_than", r"less than (?P<v>\$146,000)"),
    (IRS, "irs06", "trad_ira_phaseout_start_single_2025", "79000", "USD", "more_than", r"More than (?P<v>\$79,000)"),
    (IRS, "irs07", "trad_ira_phaseout_end_single_2025", "89000", "USD", "less_than", r"less than (?P<v>\$89,000)"),
    (IRS, "irs08", "spousal_phaseout_start_2025", "236000", "USD", "more_than", r"more than (?P<v>\$236,000) \(up from \$230,000"),
    (IRS, "irs09", "spousal_phaseout_start_2024", "230000", "USD", None, r"up from (?P<v>\$230,000)"),
    (IRS, "irs10", "spousal_phaseout_end_2025", "246000", "USD", "less_than", r"less than (?P<v>\$246,000) \(up"),
    (IRS, "irs11", "spousal_phaseout_end_2024", "240000", "USD", None, r"up from (?P<v>\$240,000)"),
    (IRS, "irs12", "roth_phaseout_start_mfj_2025", "236000", "USD", "at_least", r"at least (?P<v>\$236,000)\."),
    (IRS, "irs13", "roth_phaseout_end_mfj_2025", "246000", "USD", "at_least", r"\$236,000\. You can’t make a Roth IRA contribution if your modified AGI is (?P<v>\$246,000)"),
    (IRS, "irs14", "roth_phaseout_start_single_2025", "150000", "USD", "at_least", r"least (?P<v>\$150,000)"),
    (IRS, "irs15", "roth_phaseout_end_single_2025", "165000", "USD", "at_least", r"(?P<v>\$165,000) or more"),
    (IRS, "irs16", "ira_contribution_limit_2026", "7500", "USD", None, r"increased to (?P<v>\$7,500)"),
    (IRS, "irs17", "ira_contribution_limit_2026_age50", "8600", "USD", None, r"\((?P<v>\$8,600)"),
    (IRS, "irs18", "trad_ira_phaseout_start_mfj_2026", "129000", "USD", "more_than", r"More than (?P<v>\$129,000)"),
    (IRS, "irs19", "trad_ira_phaseout_end_mfj_2026", "149000", "USD", "less_than", r"less than (?P<v>\$149,000)"),
    (IRS, "irs20", "trad_ira_phaseout_start_single_2026", "81000", "USD", "more_than", r"More than (?P<v>\$81,000)"),
    (IRS, "irs21", "trad_ira_phaseout_end_single_2026", "91000", "USD", "less_than", r"less than (?P<v>\$91,000)"),
    (IRS, "irs22", "spousal_phaseout_start_2026", "242000", "USD", "more_than", r"more than (?P<v>\$242,000)"),
    (IRS, "irs23", "spousal_phaseout_end_2026", "252000", "USD", "less_than", r"less than (?P<v>\$252,000) \(up"),
    (IRS, "irs24", "roth_phaseout_start_single_2026", "153000", "USD", "at_least", r"least (?P<v>\$153,000)"),
    (IRS, "irs25", "roth_phaseout_end_single_2026", "168000", "USD", "at_least", r"(?P<v>\$168,000) or more"),
    (IRS, "irs26", "spousal_ira_combined_limit_2025", "14000", "USD", "up_to", r"as much as (?P<v>\$14,000)"),
    (IRS, "irs27", "spousal_ira_combined_limit_both_age50_2025", "16000", "USD", None, r"or (?P<v>\$16,000) if both"),
    (FDA, "fda01", "starting_dose", "500", "mg", None, r"starting dose of metformin hydrochloride extended-release tablets is (?P<v>500 mg)"),
    (FDA, "fda02", "titration_increment", "500", "mg", None, r"increments of (?P<v>500 mg)"),
    (FDA, "fda03", "max_daily_dose", "2000", "mg", "up_to", r"up to a maximum of (?P<v>2,000 mg) once daily with the evening meal"),
    (FDA, "fda04", "egfr_contraindicated_below", "30", "mL/min/1.73m2", "below", r"glomerular filtration rate \(eGFR\) below (?P<v>30) mL/minute/1\.73 m2\. •Initiation"),
    (FDA, "fda05", "egfr_initiation_not_recommended_low", "30", "mL/min/1.73m2", None, r"eGFR between (?P<v>30) to 45 mL/minute/1\.73 m2 is not recommended"),
    (FDA, "fda06", "egfr_initiation_not_recommended_high", "45", "mL/min/1.73m2", None, r"eGFR between 30 to (?P<v>45) mL/minute/1\.73 m2 is not recommended"),
    (FDA, "fda07", "egfr_reassess_below", "45", "mL/min/1.73m2", "below", r"whose eGFR later falls below (?P<v>45) mL/minute/1\.73 m2, assess the benefit risk"),
    (FDA, "fda08", "contrast_egfr_low", "30", "mL/min/1.73m2", None, r"procedure in patients with an eGFR between (?P<v>30) and 60 mL/minute/1\.73 m2; in patients with a history of liver"),
    (FDA, "fda09", "contrast_egfr_high", "60", "mL/min/1.73m2", None, r"procedure in patients with an eGFR between 30 and (?P<v>60) mL/minute/1\.73 m2; in patients with a history of liver"),
    (FDA, "fda10", "reevaluate_egfr_after", "48", "hours", None, r"Re-evaluate eGFR (?P<v>48) hours"),
    (FDA, "fda11", "lactic_acidosis_lactate_level", "5", "mmol/L", "above", r"blood lactate levels \(>(?P<v>5) mmol/Liter\)"),
    (FDA, "fda12", "lactic_acidosis_plasma_level", "5", "mcg/mL", "above", r"plasma levels generally >(?P<v>5) mcg/mL"),
    (FDA, "fda13", "risk_factor_age", "65", "years", "at_least", r"age (?P<v>65) years old or greater"),
    (FDA, "fda14", "tmax_low", "7", "hours", None, r"approximately (?P<v>7) to 8 hours"),
    (FDA, "fda15", "cmax_increase_vs_ir", "35", "%", "up_to", r"up to (?P<v>35)% higher Cmax"),
    (FDA, "fda16", "steady_state_time_low", "24", "hours", None, r"within (?P<v>24) to 48 hours"),
    (FDA, "fda17", "steady_state_plasma_level", "1", "mcg/mL", "below", r"generally <(?P<v>1) mcg/mL"),
    (FDA, "fda18", "rat_carcinogenicity_max_dose_male", "450", "mg/kg/day", None, r"150, 300, and (?P<v>450) mg/kg/day in males"),
    (FDA, "fda19", "rat_carcinogenicity_max_dose_female", "1200", "mg/kg/day", None, r"900, and (?P<v>1,200) mg/kg/day in females"),
    (FDA, "fda20", "rat_fertility_dose", "600", "mg/kg/day", "up_to", r"doses up to (?P<v>600) mg/kg/day"),
    (FDA, "fda21", "rat_fertility_dose_multiple", "3", "times", None, r"which is approximately (?P<v>3) times the maximum"),
    (FDA, "fda22", "study_n_newly_diagnosed", "338", "count", None, r"\(n=(?P<v>338)\)"),
    (FDA, "fda23", "washout_weeks", "6", "weeks", None, r"underwent a (?P<v>6)-week washout"),
    (FDA, "fda24", "randomized_period_weeks", "21", "weeks", None, r"additional (?P<v>21)-week period"),
]
