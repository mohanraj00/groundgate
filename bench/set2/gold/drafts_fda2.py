"""Set-2 gold drafts: FDA drug labels, batch fda2. Written by a model (Claude) from reading
bench/set2/docs, after spec 0.2 was frozen. Not ground truth: a person checks every fact."""

from __future__ import annotations

from build import f

FIELDS = {
    "fda-amoxicillin": {
        "weight_based_dose": (
            f("number", "mg/kg/day"),
            "Recommended dosage for pediatric patients aged 3 months and older weighing less "
            "than 40 kg with mild or moderate ear/nose/throat, skin/skin structure or "
            "genitourinary tract infections, given in divided doses every 12 hours.",
        ),
    },
    "fda-azithromycin": {
        "weight_based_dose": (
            f("number", "mg/kg"),
            "Single-dose regimen for acute otitis media in pediatric patients 6 months of age "
            "and older.",
        ),
    },
    "fda-pregabalin": {
        "weight_based_dose": (
            f("number", "mg/kg/day"),
            "Recommended initial dosage for adjunctive therapy of partial-onset seizures in "
            "pediatric patients weighing 30 kg or more.",
        ),
    },
    "fda-cephalexin": {
        "weight_based_dose": (
            f("number", "mg/kg"),
            "Recommended total daily dose for pediatric patients over 1 year of age, for "
            "indications other than otitis media and severe infections. The label gives a "
            "range; its lower bound.",
        ),
    },
}

UNITS = {
    "fda-amoxicillin": {"mg/kg/day": {"suffix": ["mg/kg/day"]}},
    "fda-azithromycin": {"mg/kg": {"suffix": ["mg/kg"]}},
    "fda-pregabalin": {"mg/kg/day": {"suffix": ["mg/kg/day"]}},
    "fda-cephalexin": {"mg/kg": {"suffix": ["mg/kg"]}},
}

DRAFTS = {
    "fda-clopidogrel": {
        # ACS starting dose: the 300 mg loading dose, not the 75 mg maintenance dose.
        "starting_dose": {
            "Acute Coronary Syndrome (ACS)": [
                "300",
                "Initiate clopidogrel with a single [[300-mg]] oral loading dose",
                "initiate clopidogrel tablets with a single [[300 mg]] oral loading dose",
            ],
            "Recent MI, Recent Stroke, or Established Peripheral Arterial Disease": [
                "75",
                "peripheral arterial disease: [[75 mg]] once daily orally without a loading dose (2.2)",
                "[[75 mg]] once daily orally without a loading dose [see",
            ],
        },
        "max_daily_dose": [None],
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "75",
                "Clopidogrel tablets, USP [[75 mg]] are pink",
                "Film-coated tablets: [[75 mg]], 300 mg (3)",
            ],
            [
                "300",
                "Clopidogrel tablets, USP [[300 mg]] are pink",
                "Film-coated tablets: 75 mg, [[300 mg]] (3)",
            ],
        ],
    },
    "fda-montelukast": {
        # One fixed adult dose (10 mg) per indication, drafted as the starting dose.
        "starting_dose": {
            "Asthma": [
                "10",
                "Table 1: Recommended Dosage in Asthma Age Dose Adult and adolescent patients 15 years of age and older one [[10 mg]] tablet",
                "15 years and older: one [[10-mg]] tablet (2).",
            ],
            "Exercise-Induced Bronchoconstriction (EIB)": [
                "10",
                "one [[10 mg]] tablet Pediatric patients 6 to 14 years of age*",
                "15 years and older: one [[10-mg]] tablet (2).",
            ],
            "Allergic Rhinitis": [
                "10",
                "allergic rhinitis have not been established Age Dose Adult and adolescent patients 15 years of age and older one [[10 mg]] tablet",
                "Table 4: Recommended Dosage in Perennial Allergic Rhinitis Age Dose Adult and adolescent patients 15 years of age and older one [[10 mg]] tablet",
                "15 years and older: one [[10-mg]] tablet (2).",
            ],
        },
        "max_daily_dose": [None],
        "pediatric_min_age": [
            "2",
            "Asthma : Once daily in the evening for patients [[2 years]] and older (2.1).",
            "Seasonal allergic rhinitis: Once daily for patients [[2 years]] and older (2.3).",
            "Perennial allergic rhinitis: Once daily for patients [[2 years]] and older (2.3).",
            "[[2]] to 5 years: one 4-mg chewable tablet (2).",
            "Pediatric patients [[2]] to 5 years of age one 4 mg chewable tablet Patients who miss a dose should take the next dose at their regular time and should not take 2 doses at the same time. 2.2",
            "Pediatric patients [[2]] to 5 years of age*",
            "Pediatric patients [[2]] to 5 years of age one 4 mg chewable tablet Patients who miss a dose should take the next dose at their regular time and should not take 2 doses at the same time. 2.4",
        ],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "10",
                "Montelukast sodium tablets USP, [[10 mg]] are pale",
                "Montelukast sodium tablets USP, [[10 mg]] (3)",
            ],
            [
                "5",
                "Montelukast sodium chewable tablets USP, [[5 mg]] are light",
                "Montelukast sodium chewable tablets USP, [[5 mg]] and 4 mg (3)",
            ],
            [
                "4",
                "Montelukast sodium chewable tablets USP, [[4 mg]] are light",
                "chewable tablets USP, 5 mg and [[4 mg]] (3)",
            ],
        ],
    },
    "fda-quetiapine": {
        "starting_dose": {
            "Schizophrenia": [
                "25",
                "Schizophrenia-Adults (2.2) [[25 mg]] twice daily",
                "Schizophrenia-Adults Day 1: [[25 mg]] twice daily.",
            ],
            # Bipolar mania and bipolar depression in adults both start at 50 mg.
            "Bipolar Disorder": [
                "50",
                "divalproex (2.2) [[50 mg]] twice daily",
                "Bipolar Depression-Adults (2.2) [[50 mg]] once daily at bedtime",
                "Administer once daily at bedtime. Day 1: [[50 mg]]",
            ],
        },
        # Schizophrenia: 750 mg/day for adults (acute); the maintenance row says 800 mg/day.
        # Bipolar: 800 mg/day for mania and maintenance; bipolar depression is 300 mg/day.
        "max_daily_dose": {
            "Schizophrenia": [
                "750",
                "[[750 mg/day]] Schizophrenia-Adolescents (13 to 17 years) (2.2)",
                "[[750 mg/day]] Schizophrenia-Adolescents (13 to 17 years) Day 1",
            ],
            "Bipolar Disorder": [
                "800",
                "[[800 mg/day]] Bipolar Mania-Children and Adolescents (10 to 17 years), Monotherapy (2.2)",
                "[[800 mg/day]] Bipolar Mania-Children and Adolescents (10 to 17 years), Monotherapy Day 1",
                "Further dosage adjustments up to [[800 mg/day]] by Day 6",
                "[[800 mg/day]] Maintenance Treatment for Schizophrenia",
            ],
        },
        "pediatric_min_age": [
            "10",
            "Bipolar Mania-Children and Adolescents ([[10]] to 17 years), Monotherapy (2.2)",
            "Bipolar Mania-Children and Adolescents ([[10]] to 17 years), Monotherapy Day 1",
        ],
        "hepatic_starting_dose": [
            "25",
            "Hepatic Impairment :Lower starting dose ([[25 mg/day]])",
            "Patients with hepatic impairment should be started on [[25 mg/day]].",
        ],
        "strengths": [
            [
                "25",
                "Tablets: [[25 mg]], 50 mg, 100 mg and 200 mg (3)",
                "Quetiapine tablets USP, [[25 mg]] (as quetiapine)",
            ],
            [
                "50",
                "Tablets: 25 mg, [[50 mg]], 100 mg and 200 mg (3)",
                "Quetiapine tablets USP, [[50 mg]] (as quetiapine)",
            ],
            [
                "100",
                "Tablets: 25 mg, 50 mg, [[100 mg]] and 200 mg (3)",
                "Quetiapine tablets USP, [[100 mg]] (as quetiapine)",
            ],
            [
                "200",
                "Tablets: 25 mg, 50 mg, 100 mg and [[200 mg]] (3)",
                "Quetiapine tablets USP, [[200 mg]] (as quetiapine)",
            ],
        ],
    },
    "fda-amoxicillin": {
        # No titration; the adult range's lower bound. Alternative reading: the first
        # indication in Table 1 (ENT, mild/moderate) is 500 mg every 12 hours or 250 mg
        # every 8 hours.
        "starting_dose": ["750", "In Adults, [[750 to 1750 mg/day]] in divided doses"],
        # 1750 mg/day is only the top of a range, not a stated maximum.
        "max_daily_dose": [None],
        # Pediatric dosing is given only in months (over 3 months, 3 months or younger).
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "125",
                "[[125 mg]]: Each white to off-white, capsule-shaped tablet",
                "Tablets (Chewable): [[125 mg]], 250 mg ( 3)",
            ],
            [
                "250",
                "[[250 mg]]: Each white to off-white, capsule-shaped tablet",
                "Tablets (Chewable): 125 mg, [[250 mg]] ( 3)",
                "[[250 mg]]: Opaque caramel cap",
                "Capsules: [[250 mg]], 500 mg ( 3)",
            ],
            [
                "500",
                "[[500 mg]]: Each tablet contains 500 mg",
                "Tablets: [[500 mg]], 875 mg ( 3)",
                "[[500 mg]]: Opaque buff cap",
                "Capsules: 250 mg, [[500 mg]] ( 3)",
            ],
            [
                "875",
                "[[875 mg]]: Each tablet contains 875 mg",
                "Tablets: 500 mg, [[875 mg]] ( 3)",
            ],
        ],
        "weight_based_dose": [
            "25",
            "[[25 mg/kg/day]] in divided doses every 12 hours",
        ],
    },
    "fda-spironolactone": {
        "starting_dose": {
            "Heart Failure": [
                "25",
                "Heart Failure: Initiate treatment at [[25 mg]] once daily ( 2.2).",
                "eGFR >50 mL/min/1.73 m ^2, initiate treatment at [[25 mg]] once daily.",
            ],
            "Hypertension": [
                "25",
                "Hypertension: Initiate treatment at [[25 mg to 100 mg]] daily",
                "The recommended initial daily dose is [[25 mg to 100 mg]] of spironolactone",
            ],
            "Edema Associated with Hepatic Cirrhosis or Nephrotic Syndrome": [
                "100",
                "The recommended initial daily dose is [[100 mg]] in single or divided doses ( 2.4).",
                "The recommended initial daily dosage is [[100 mg]] of spironolactone",
            ],
            "Primary Hyperaldosteronism": [
                "100",
                "Primary hyperaldosteronism: Initiate treatment at [[100 mg to 400 mg]] in preparation for surgery.",
                "Administer spironolactone in doses of [[100 mg to 400 mg]] daily in preparation for surgery.",
            ],
        },
        # No stated maximum. Hypertension says doses above 100 mg/day "generally do not
        # provide additional reductions"; edema and hyperaldosteronism give only ranges.
        "max_daily_dose": [None],
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "100",
                "Tablets: [[100 mg]] are white",
                "Tablets: [[100 mg]] ( 3)",
            ],
        ],
    },
    "fda-alendronate": {
        # Each indication offers a once-weekly or a once-daily dose; drafted the daily dose.
        "starting_dose": {
            "Treatment of Osteoporosis in Postmenopausal Women": [
                "10",
                "Treatment of osteoporosis in postmenopausal women and in men: [[10 mg]] daily",
                "●one [[10 mg]] tablet once daily",
            ],
            "Prevention of Osteoporosis in Postmenopausal Women": [
                "5",
                "Prevention of osteoporosis in postmenopausal women: [[5 mg]] daily",
                "• one [[5 mg]] tablet once daily",
            ],
            "Treatment to Increase Bone Mass in Men with Osteoporosis": [
                "10",
                "Treatment of osteoporosis in postmenopausal women and in men: [[10 mg]] daily",
                "• one [[10 mg]] tablet once daily",
            ],
            "Treatment of Glucocorticoid-Induced Osteoporosis": [
                "5",
                "Glucocorticoid-induced osteoporosis: [[5 mg]] daily;",
                "The recommended dosage is one [[5 mg]] tablet once daily, except",
            ],
            "Treatment of Paget's Disease of Bone": [
                "40",
                "Paget's disease: [[40 mg]] daily for six months.",
                "The recommended treatment regimen is [[40 mg]] once a day",
            ],
        },
        "max_daily_dose": [None],
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "35",
                "Alendronate Sodium Tablets, USP [[35 mg]] are white",
                "Tablets: [[35mg]] ( 3 )",
            ],
        ],
    },
    "fda-azithromycin": {
        "starting_dose": {
            "Indications in Adult Patients": [
                "500",
                "(uncomplicated) [[500 mg]] as a single dose on Day 1, followed by 250 mg once daily on Days 2 through 5. Acute",
                "(uncomplicated) [[500 mg]] as a single dose on Day 1, followed by 250 mg once daily on Days 2 through 5 Acute bacterial exacerbations of chronic obstructive",
            ],
        },
        "max_daily_dose": [None],
        # Youngest pediatric dosing is 6 months (given in months); pharyngitis is 2 years.
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "250",
                "Azithromycin Tablets USP, [[250 mg]] are white",
                "Azithromycin tablets USP [[250 mg]] ( 3)",
            ],
        ],
        "weight_based_dose": [
            "30",
            "Acute otitis media (6 months of age and older) [[30 mg/kg]] as a single dose",
            "Acute otitis media [[30 mg/kg]] as a single dose",
            "Dosing Calculated on [[30 mg/kg]] as a single dose.",
        ],
    },
    "fda-pregabalin": {
        # First indication: DPN. Drafted the daily total (150 mg/day); per dose it is
        # 50 mg three times a day.
        "starting_dose": [
            "150",
            "For adult indications, begin dosing at [[150 mg/day]].",
            "Begin dosing at 50 mg three times a day ([[150 mg/day]]).",
        ],
        "max_daily_dose": [
            "300",
            "DPN Pain (2.2) 3 divided doses per day [[300 mg/day]] within 1 week.",
            "The maximum recommended dose of pregabalin capsules is 100 mg three times a day ([[300 mg/day]])",
            "treatment with doses above [[300 mg/day]] is not recommended",
        ],
        # Pediatric dosing starts at 1 month of age (given in months).
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "75",
                "Capsules: [[75 mg]] [see Description",
                "Capsules: [[75 mg]] ( 3)",
            ],
        ],
        "weight_based_dose": [
            "2.5",
            "Pediatric patients weighing 30 kg or more [[2.5 mg/kg/day]]",
        ],
    },
    "fda-cephalexin": {
        # The adult dose is not given per indication: "the usual dose is 250 mg every
        # 6 hours" for adults and patients at least 15 years. Drafted for every indication key.
        "starting_dose": {
            key: [
                "250",
                "Adults and patients at least 15 years of age The usual dose is [[250 mg]] every 6 hours",
                "The usual dose of oral Cephalexin capsule, USP is [[250 mg]] every 6 hours",
            ]
            for key in (
                "Respiratory Tract Infections",
                "Otitis Media",
                "Skin and Skin Structure Infections",
                "Bone Infections",
                "Genitourinary Tract Infections",
            )
        },
        # "up to 4 grams daily" is stated in grams, not mg, and not per indication.
        "max_daily_dose": [None],
        "pediatric_min_age": [
            "1",
            "Pediatric patients (over [[1 year]] of age) Otitis media",
            "2.2 Pediatric Patients (over [[1 year]] of age) The recommended",
        ],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "250",
                "[[250 mg]] capsules: a white",
                "Capsules: [[250 mg]], 333 mg, 500 mg and 750 mg ( 3)",
            ],
            [
                "333",
                "[[333 mg]] capsules: a white",
                "Capsules: 250 mg, [[333 mg]], 500 mg and 750 mg ( 3)",
            ],
            [
                "500",
                "[[500 mg]] capsules: a white",
                "Capsules: 250 mg, 333 mg, [[500 mg]] and 750 mg ( 3)",
            ],
            [
                "750",
                "[[750 mg]] capsules: a white",
                "Capsules: 250 mg, 333 mg, 500 mg and [[750 mg]] ( 3)",
            ],
        ],
        "weight_based_dose": [
            "25",
            "All other indications: [[25 to 50 mg/kg]] given in equally divided doses ( 2.2)",
            "for pediatric patients is [[25 to 50 mg/kg]] given in equally divided doses",
        ],
    },
    "fda-rivaroxaban": {
        "starting_dose": {
            "Reduction of Risk of Major Cardiovascular Events in Patients with Coronary Artery Disease (CAD)": [
                "2.5",
                "CAD or PAD:[[2.5 mg]] orally twice daily",
                "in CAD No dose adjustment needed based on CrCl [[2.5 mg]] twice daily",
            ],
            "Reduction of Risk of Major Thrombotic Vascular Events in Patients with Peripheral Artery Disease (PAD), Including Patients after Lower Extremity Revascularization due to Symptomatic PAD": [
                "2.5",
                "CAD or PAD:[[2.5 mg]] orally twice daily",
                "Symptomatic PAD No dose adjustment needed based on CrCl [[2.5 mg]] twice daily",
            ],
        },
        "max_daily_dose": [None],
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "2.5",
                "[[2.5 mg]] tablets: Round, light yellow",
                "Tablets: [[2.5 mg]] ( 3)",
            ],
        ],
    },
    "fda-diltiazem": {
        "starting_dose": {
            "Hypertension": [
                "180",
                "Hypertension: Initial adult dose is [[180 to 240 mg]] once daily.",
                "Initiate dosing at [[180 to 240 mg]] once daily, although",
            ],
            "Angina": [
                "180",
                "Angina: Initial adult dose is [[180 mg]] once daily.",
                "Initiate dosing at [[180 mg]] once daily and increase",
            ],
        },
        "max_daily_dose": {
            "Hypertension": [
                "540",
                "blood pressure response to a maximum of [[540 mg]] daily. ( 2.1)",
                "Titrate according to blood pressure to a maximum of [[540 mg]] daily.",
            ],
            "Angina": [
                "360",
                "Adjust dose according to response to a maximum of [[360 mg]]. ( 2.2)",
                "if adequate response is not obtained, to a maximum of [[360 mg]].",
            ],
        },
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "120",
                "Extended-release tablets with [[120 mg]], 180 mg, 240 mg, 300 mg, 360 mg, or 420 mg diltiazem hydrochloride per tablet. Diltiazem",
                "Diltiazem Hydrochloride Extended-Release Tablets, [[120 mg]] are white",
                "Extended-release tablets with [[120 mg]], 180 mg, 240 mg, 300 mg, 360 mg, or 420 mg diltiazem hydrochloride per tablet. ( 3)",
            ],
            [
                "180",
                "Extended-release tablets with 120 mg, [[180 mg]], 240 mg, 300 mg, 360 mg, or 420 mg diltiazem hydrochloride per tablet. Diltiazem",
                "Diltiazem Hydrochloride Extended-Release Tablets, [[180 mg]] are white",
                "Extended-release tablets with 120 mg, [[180 mg]], 240 mg, 300 mg, 360 mg, or 420 mg diltiazem hydrochloride per tablet. ( 3)",
            ],
            [
                "240",
                "Extended-release tablets with 120 mg, 180 mg, [[240 mg]], 300 mg, 360 mg, or 420 mg diltiazem hydrochloride per tablet. Diltiazem",
                "Diltiazem Hydrochloride Extended-Release Tablets, [[240 mg]] are white",
                "Extended-release tablets with 120 mg, 180 mg, [[240 mg]], 300 mg, 360 mg, or 420 mg diltiazem hydrochloride per tablet. ( 3)",
            ],
            [
                "300",
                "Extended-release tablets with 120 mg, 180 mg, 240 mg, [[300 mg]], 360 mg, or 420 mg diltiazem hydrochloride per tablet. Diltiazem",
                "Diltiazem Hydrochloride Extended-Release Tablets, [[300 mg]] are white",
                "Extended-release tablets with 120 mg, 180 mg, 240 mg, [[300 mg]], 360 mg, or 420 mg diltiazem hydrochloride per tablet. ( 3)",
            ],
            [
                "360",
                "Extended-release tablets with 120 mg, 180 mg, 240 mg, 300 mg, [[360 mg]], or 420 mg diltiazem hydrochloride per tablet. Diltiazem",
                "Diltiazem Hydrochloride Extended-Release Tablets, [[360 mg]] are white",
                "Extended-release tablets with 120 mg, 180 mg, 240 mg, 300 mg, [[360 mg]], or 420 mg diltiazem hydrochloride per tablet. ( 3)",
            ],
            [
                "420",
                "Extended-release tablets with 120 mg, 180 mg, 240 mg, 300 mg, 360 mg, or [[420 mg]] diltiazem hydrochloride per tablet. Diltiazem",
                "Diltiazem Hydrochloride Extended-Release Tablets, [[420 mg]] are white",
                "Extended-release tablets with 120 mg, 180 mg, 240 mg, 300 mg, 360 mg, or [[420 mg]] diltiazem hydrochloride per tablet. ( 3)",
            ],
        ],
    },
}
