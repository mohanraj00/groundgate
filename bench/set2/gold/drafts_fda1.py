"""Set-2 gold drafts: FDA drug labels, batch fda1 (general and keyed). Written by a model (Claude)
from reading bench/set2/docs, after spec 0.2 was frozen. Not ground truth: a person checks every
fact."""

from __future__ import annotations

# fda-potassium doses in mEq, not mg.
UNITS = {"fda-potassium": {"mEq": {"suffix": ["mEq"]}}}
DOSE_UNIT = {"fda-potassium": "mEq"}

# In fda-apixaban, phrases of section 2.1 also occur in the summary before it, so a context is
# anchored on the "(2.1)" that ends the summary. _APX_21 is the start of section 2.1 with
# whitespace collapsed.
_APX_21 = (
    "2.1 Recommended Dose Reduction of Risk of Stroke and Systemic Embolism in Patients with "
    "Nonvalvular Atrial Fibrillation The recommended dose of apixaban tablets for most patients "
    "is 5 mg taken orally twice daily. The recommended dose of apixaban tablets is 2.5 mg twice "
    "daily in patients with at least two of the following characteristics: age greater than or "
    "equal to 80 years body weight less than or equal to 60 kg serum creatinine greater than or "
    "equal to 1.5 mg/dL Prophylaxis of Deep Vein Thrombosis Following Hip or Knee Replacement "
    "Surgery The recommended dose of apixaban tablets is 2.5 mg taken orally twice daily. The "
    "initial dose should be taken 12 to 24 hours after surgery. In patients undergoing hip "
    "replacement surgery, the recommended duration of treatment is 35 days. In patients "
    "undergoing knee replacement surgery, the recommended duration of treatment is 12 days. "
    "Treatment of DVT and PE The recommended dose of apixaban tablets is 10 mg taken orally "
    "twice daily for the first 7 days of therapy. After 7 days, the recommended dose is 5 mg "
    "taken orally twice daily. Reduction in the Risk of Recurrence of DVT and PE The recommended "
    "dose of apixaban tablets is 2.5 mg taken orally twice daily"
)


def _apx(target: str) -> list[str]:
    """The context for a marked phrase of apixaban's section 2.1."""
    k = _APX_21.index(target.replace("[[", "").replace("]]", ""))
    return [f"(2.1) {_APX_21[:k]}{target}"]


DRAFTS = {
    "fda-rosuvastatin": {
        "starting_dose": [
            "5",
            "Adults: Recommended dosage range is [[5]] to 40 mg once daily",
            "The dosage range for rosuvastatin tablets is [[5]] to 40 mg orally once daily",
        ],
        "max_daily_dose": [
            "40",
            "Adults: Recommended dosage range is 5 to [[40 mg]] once daily",
            "The dosage range for rosuvastatin tablets is 5 to [[40 mg]] orally once daily",
        ],
        "pediatric_min_age": [
            "7",
            "Recommended dosage is 20 mg once daily for patients aged [[7 years]] and older",
            "Dosage in Pediatric Patients [[7 Years]] of Age and Older with HoFH",
        ],
        "hepatic_starting_dose": [None],
        "strengths": [
            ["5", "[[5 mg]] of rosuvastatin: Pink, oval", "Tablets: [[5 mg]], 10 mg"],
            ["10", "[[10 mg]] of rosuvastatin: Pink, round", "5 mg, [[10 mg]], 20 mg"],
            ["20", "[[20 mg]] of rosuvastatin: Pink, round", "10 mg, [[20 mg]], and 40 mg"],
            ["40", "[[40 mg]] of rosuvastatin: Pink, oval", "20 mg, and [[40 mg]] (3)"],
        ],
    },
    "fda-omeprazole": {
        "starting_dose": {
            "Treatment of Active Duodenal Ulcer": [
                "20",
                "Treatment of Active Duodenal Ulcer [[20 mg]] once daily for 4 weeks",
                "Treatment of Active Duodenal Ulcer [[20 mg]] once daily 4 weeks",
            ],
            # triple therapy 20 mg twice daily; dual therapy 40 mg once daily
            "Helicobacter pylori Eradication to Reduce the Risk of Duodenal Ulcer Recurrence": [
                "20",
                "Triple Therapy: Omeprazole [[20 mg]] Each drug twice daily",
                "Triple Therapy Omeprazole [[20 mg]] Amoxicillin 1000 mg",
            ],
            "Treatment of Active Benign Gastric Ulcer": [
                "40",
                "Active Benign Gastric Ulcer [[40 mg]] once daily for 4 to 8 weeks",
                "Active Benign Gastric Ulcer [[40 mg]] once daily 4 to 8 weeks",
            ],
            "Treatment of Symptomatic Gastroesophageal Reflux Disease (GERD)": [
                "20",
                "Symptomatic GERD [[20 mg]] once daily for up to 4 weeks",
                "Treatment of Symptomatic GERD [[20 mg]] once daily Up to 4 weeks",
            ],
            "Treatment of Erosive Esophagitis (EE) Due to Acid-Mediated GERD": [
                "20",
                "EE due to Acid-Mediated GERD [[20 mg]] once daily for 4 to 8 weeks",
                "Treatment of EE due to Acid-Mediated GERD [[20 mg]] once daily 4 to 8 weeks",
            ],
            "Maintenance of Healing of EE Due to Acid-Mediated GERD": [
                "20",
                "Maintenance of Healing of EE due to Acid-Mediated GERD [[20 mg]] once daily (2.1)",
                "Maintenance of Healing of EE due to Acid-Mediated GERD [[20 mg]] once daily ^3",
            ],
            "Pathological Hypersecretory Conditions": [
                "60",
                "Starting dose is [[60 mg]] once daily (varies",
                "Starting dose is [[60 mg]] once daily; adjust",
            ],
        },
        # "Dosages up to 120 mg three times daily have been administered" is a used dose
        "max_daily_dose": [None],
        "pediatric_min_age": [
            "2",
            "for up to 4 weeks (2.1) See full prescribing information for weight based dosing in pediatric patients [[2 years]] of age",
            "for 4 to 8 weeks (2.1) ^3 See full prescribing information for weight based dosing in pediatric patients [[2 years]] of age",
            "once daily (2.1) ^3 See full prescribing information for weight based dosing in pediatric patients [[2 years]] of age",
            "Treatment of Symptomatic GERD [[2]] to 16 years",
            "Treatment of EE due to Acid- Mediated GERD [[2]] to 16 years",
            "Maintenance of Healing of EE due to Acid-Mediated GERD [[2]] to 16 years",
        ],
        # a dose reduction for maintenance of healing of EE, not a general starting dose
        "hepatic_starting_dose": [
            "10",
            "Reduce the dosage to [[10 mg]] once daily for patients with hepatic impairment",
            "Dosage reduction to [[10 mg]] once daily is recommended for patients with hepatic impairment",
        ],
        "strengths": [
            [
                "10",
                "Omeprazole Delayed-Release Capsules, USP [[10 mg]] are size",
                "Omeprazole Delayed-Release Capsules: [[10 mg]], 20 mg and 40 mg",
            ],
            [
                "20",
                "Omeprazole Delayed-Release Capsules, USP [[20 mg]] are size",
                "Omeprazole Delayed-Release Capsules: 10 mg, [[20 mg]] and 40 mg",
            ],
            [
                "40",
                "Omeprazole Delayed-Release Capsules, USP [[40 mg]] are size",
                "Omeprazole Delayed-Release Capsules: 10 mg, 20 mg and [[40 mg]]",
            ],
        ],
    },
    "fda-pantoprazole": {
        "starting_dose": {
            "Short-Term Treatment of Erosive Esophagitis Associated With Gastroesophageal Reflux Disease (GERD)": [
                "40",
                "Short-Term Treatment of Erosive Esophagitis Associated With GERD (2.1) Adults [[40 mg]]",
                "Short-Term Treatment of Erosive Esophagitis Associated With GERD Adults [[40 mg]]",
            ],
            "Maintenance of Healing of Erosive Esophagitis": [
                "40",
                "Maintenance of Healing of Erosive Esophagitis (2.1) Adults [[40 mg]]",
                "Maintenance of Healing of Erosive Esophagitis Adults [[40 mg]]",
            ],
            "Pathological Hypersecretory Conditions Including Zollinger-Ellison Syndrome": [
                "40",
                "Including Zollinger-Ellison Syndrome (2.1) Adults [[40 mg]] Twice Daily",
                "Including Zollinger-Ellison Syndrome Adults [[40 mg]] Twice daily",
            ],
        },
        # "Doses up to 240 mg daily have been administered" is a used dose
        "max_daily_dose": [None],
        "pediatric_min_age": [
            "5",
            "Children ([[5 years]] and older) ≥ 15 kg to < 40 kg 20 mg Once Daily",
            "Children ([[5 years]] and older) ≥ 15 kg to < 40 kg 20 mg Once daily",
        ],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "20",
                "equivalent to [[20 mg]] or 40 mg of pantoprazole",
                "The [[20 mg]] tablets are dark yellow",
                "Delayed-Release Tablets: [[20 mg]] and 40 mg pantoprazole",
            ],
            [
                "40",
                "equivalent to 20 mg or [[40 mg]] of pantoprazole",
                "The [[40 mg]] tablets are dark yellow",
                "Delayed-Release Tablets: 20 mg and [[40 mg]] pantoprazole",
            ],
        ],
    },
    "fda-apixaban": {
        "starting_dose": {
            "Reduction of Risk of Stroke and Systemic Embolism in Nonvalvular Atrial Fibrillation": [
                "5",
                "The recommended dose is [[5 mg]] orally twice daily. (2.1)",
                *_apx("for most patients is [[5 mg]]"),
            ],
            "Prophylaxis of Deep Vein Thrombosis Following Hip or Knee Replacement Surgery": [
                "2.5",
                "Prophylaxis of DVT following hip or knee replacement surgery: The recommended dose is [[2.5 mg]]",
                *_apx(
                    "Prophylaxis of Deep Vein Thrombosis Following Hip or Knee Replacement Surgery "
                    "The recommended dose of apixaban tablets is [[2.5 mg]]"
                ),
            ],
            "Treatment of Deep Vein Thrombosis": [
                "10",
                "The recommended dose is [[10 mg]] taken orally twice daily for 7 days",
                *_apx("The recommended dose of apixaban tablets is [[10 mg]]"),
            ],
            "Treatment of Pulmonary Embolism": [
                "10",
                "The recommended dose is [[10 mg]] taken orally twice daily for 7 days",
                *_apx("The recommended dose of apixaban tablets is [[10 mg]]"),
            ],
            "Reduction in the Risk of Recurrence of DVT and PE": [
                "2.5",
                "following initial therapy: The recommended dose is [[2.5 mg]]",
                *_apx(
                    "Reduction in the Risk of Recurrence of DVT and PE The recommended dose of "
                    "apixaban tablets is [[2.5 mg]]"
                ),
            ],
        },
        "max_daily_dose": [None],
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            ["2.5", "[[2.5 mg]], yellow, round", "Tablets: [[2.5 mg]] and 5 mg"],
            ["5", "[[5 mg]], pink, oval", "Tablets: 2.5 mg and [[5 mg]]"],
        ],
    },
    "fda-tamsulosin": {
        "starting_dose": [
            "0.4",
            "Tamsulosin hydrochloride capsules [[0.4 mg]] once daily is recommended",
            "[[0.4 mg]] once daily taken approximately",
        ],
        # the highest dose the label allows ("can be increased to"), not worded as a maximum
        "max_daily_dose": [
            "0.8",
            "tamsulosin hydrochloride capsules can be increased to [[0.8 mg]] once daily",
            "Can be increased to [[0.8 mg]] once daily for patients",
        ],
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            ["0.4", "Capsule: [[0.4 mg]] are olive green", "Capsules: [[0.4 mg]]"],
        ],
    },
    "fda-trazodone": {
        "starting_dose": [
            "150",
            "Starting dose: [[150 mg]] in divided doses daily",
            "An initial dose of [[150 mg/day]] in divided doses",
        ],
        # outpatients; inpatients "up to but not in excess of 600 mg/day"
        "max_daily_dose": [
            "400",
            "Maximum dose: [[400 mg]] per day",
            "The maximum dose for outpatients usually should not exceed [[400 mg/day]]",
        ],
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            ["50", "• [[50 mg]]: White to off white", "Functionally scored tablets: [[50 mg]]"],
        ],
    },
    "fda-prednisone": {
        "starting_dose": [
            "5",
            "Initial dose: Prednisone delayed-release tablets [[5 mg]] administered once per day",
            "may vary from [[5]] to 60 mg per day",
        ],
        # 60 mg is the top of the initial range; "higher initial doses may be required"
        "max_daily_dose": [None],
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "1",
                "Prednisone delayed release tablets, [[1 mg]]: White",
                "Delayed-release tablets: [[1 mg]], and 2 mg",
            ],
            [
                "2",
                "Prednisone delayed release tablets, [[2 mg]]: Light peach",
                "Delayed-release tablets: 1 mg, and [[2 mg]] prednisone",
            ],
        ],
    },
    "fda-carvedilol": {
        "starting_dose": [
            "3.125",
            "The recommended starting dose of Carvedilol tablets are [[3.125 mg]] twice daily",
        ],
        # heart failure: "A maximum dose of 50 mg twice daily has been administered" is a used
        # dose; "Total daily dose should not exceed 50 mg" is for hypertension (2.3)
        "max_daily_dose": [None],
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            ["3.125", "strengths: [[3.125 mg]]– debossed with Z and 1"],
            ["6.25", "[[6.25 mg]]–debossed with ZC40"],
            ["12.5", "[[12.5 mg]]–debossed with ZC41"],
            ["25", "[[25 mg]]–debossed with ZC42"],
        ],
    },
    "fda-potassium": {
        # sections 2.1 and 2.2 appear twice; each copy is reached from what follows it
        "starting_dose": [
            "40",
            "Treatment of hypokalemia:Typical dose range is [[40]]-100 mEq per day in divided doses",
            "Typical dose range is [[40]]-100 mEq per day. Prevention of hypokalemia:Typical dose is 20 mEq per day. 3 DOSAGE FORMS",
        ],
        # 100 mEq is the top of a "typical dose range", not a stated maximum
        "max_daily_dose": [None],
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            ["10", "[[10 mEq]] (750mg) : White", "[[10 mEq]] (750mg) oral tablets (3)"],
            ["15", "[[15 mEq]] (1125 mg): Yellow", "[[15 mEq]] (1125 mg) oral tablet (3)"],
            ["20", "[[20 mEq]] (1500 mg): White", "[[20 mEq]] (1500 mg) oral tablets (3)"],
        ],
    },
    "fda-famotidine": {
        # active duodenal ulcer: "40 mg once daily; or 20 mg twice daily"
        "starting_dose": [
            "40",
            "Active DU [[40 mg]] once daily; or",
            "ulcer (DU) [[40 mg]] once daily; or 20 mg",
        ],
        "max_daily_dose": [None],
        # pediatric dosing is given by weight (40 kg and greater), not age
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            ["20", "• [[20 mg]] tablets: round", "Tablets: [[20 mg]], 40 mg (3)"],
            ["40", "• [[40 mg]] tablets: round", "Tablets: 20 mg, [[40 mg]] (3)"],
        ],
    },
}
