"""Set-2 gold drafts: FDA drug labels, batch 3. Written by a model (Claude) from reading
bench/set2/docs, after spec 0.2 was frozen. Not ground truth: a person checks every fact."""

from __future__ import annotations

from build import f

FIELDS = {
    "fda-divalproex": {
        "weight_based_dose": (
            f("number", "mg/kg/day"),
            "Recommended initial daily dose for mania, in mg/kg/day.",
        ),
    },
    "fda-levetiracetam": {
        "weight_based_dose": (
            f("number", "mg/kg"),
            "Starting dose per administration (given twice daily) for partial-onset seizures in "
            "pediatric patients 1 month to less than 6 months of age, in mg/kg.",
        ),
    },
    "fda-ciprofloxacin": {
        "weight_based_dose": (
            f("number", "mg/kg"),
            "Pediatric oral dose per administration for inhalational anthrax (post-exposure), in "
            "mg/kg.",
        ),
    },
    "fda-valsartan": {
        "weight_based_dose": (
            f("number", "mg/kg"),
            "Usual recommended starting dose for pediatric hypertension in patients 1 to 16 years "
            "of age, in mg/kg once daily.",
        ),
    },
    "fda-lamotrigine": {
        "weight_based_dose": (
            f("number", "mg/kg/day"),
            "Daily dose in weeks 1 and 2 of adjunctive epilepsy therapy for patients aged 2 to 12 "
            "years taking valproate, in mg/kg/day.",
        ),
    },
    "fda-topiramate": {
        "weight_based_dose": (
            f("number", "mg/kg"),
            "Lower end of the recommended total daily dose range for adjunctive epilepsy therapy "
            "in pediatric patients 2 to 16 years of age, in mg/kg.",
        ),
    },
    "fda-naproxen": {
        "weight_based_dose": (
            f("number", "mg/kg"),
            "Recommended total daily dose for polyarticular juvenile idiopathic arthritis in "
            "pediatric patients, in mg/kg.",
        ),
    },
    "fda-hydroxychloroquine": {
        "weight_based_dose": (
            f("number", "mg/kg"),
            "Weekly malaria prophylaxis dose for pediatric patients weighing 31 kg or more, in "
            "mg/kg.",
        ),
    },
}

UNITS = {
    "fda-divalproex": {"mg/kg/day": {"suffix": ["mg/kg/day"]}},
    "fda-levetiracetam": {"mg/kg": {"suffix": ["mg/kg", "mg per kg"]}},
    "fda-ciprofloxacin": {"mg/kg": {"suffix": ["mg/kg"]}},
    "fda-valsartan": {"mg/kg": {"suffix": ["mg/kg"]}},
    "fda-lamotrigine": {"mg/kg/day": {"suffix": ["mg/kg/day"]}},
    "fda-topiramate": {"mg/kg": {"suffix": ["mg/kg"]}},
    "fda-naproxen": {"mg/kg": {"suffix": ["mg/kg"]}},
    "fda-hydroxychloroquine": {"mg/kg": {"suffix": ["mg/kg"]}},
}

DRAFTS = {
    "fda-venlafaxine": {
        "starting_dose": {
            "Major Depressive Disorder": [
                "75",
                "Depressive Disorder [[75 mg]]/day (in some patients",
                "the recommended starting dose for Venlafaxine Hydrochloride Extended-Release Tablets is [[75 mg]]/day",
                "patients not responding to the initial [[75 mg]]/day dose",
            ],
            "Social Anxiety Disorder": [
                "75",
                "Social Anxiety Disorder [[75 mg]]/day No benefit",
                "The recommended dose is [[75 mg]]/day, administered in a single dose. There was no evidence",
            ],
        },
        "max_daily_dose": {
            "Major Depressive Disorder": [
                "225",
                "intervals of 4 days or longer [[225 mg]]/day Social",
                "may benefit from dose increases to a maximum of approximately [[225 mg]]/day",
            ],
            "Social Anxiety Disorder": [
                "75",
                "No benefit at higher doses [[75 mg]]/day",
            ],
        },
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            ["150", "[[150 mg]] tablets (white", "[[150 mg]] and 225 mg tablets (3)"],
            ["225", "[[225 mg]] tablets (white", "150 mg and [[225 mg]] tablets (3)"],
        ],
    },
    "fda-celecoxib": {
        "starting_dose": {
            "Osteoarthritis": [
                "200",
                "OA: [[200 mg]] once daily",
                "For OA, the dosage is [[200 mg]] per day",
            ],
            "Rheumatoid Arthritis": [
                "100",
                "RA: [[100 mg]] to 200 mg twice daily",
                "For RA, the dosage is [[100 mg]] to 200 mg twice daily.",
            ],
            "Ankylosing Spondylitis": [
                "200",
                "AS: [[200 mg]] once daily single dose",
                "For AS, the dosage of celecoxib capsules are [[200 mg]] daily",
            ],
            "Acute Pain": [
                "400",
                "AP and PD: [[400 mg]] initially",
                "Primary Dysmenorrhea, the dosage is [[400 mg]] initially",
            ],
            "Primary Dysmenorrhea": [
                "400",
                "AP and PD: [[400 mg]] initially",
                "Primary Dysmenorrhea, the dosage is [[400 mg]] initially",
            ],
        },
        "max_daily_dose": [None],
        "pediatric_min_age": ["2", "pediatric patients (age [[2 years]] and older)"],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "100",
                "[[100 mg]] white opaque cap",
                "Celecoxib capsules: [[100 mg]] ( 3)",
            ],
        ],
    },
    "fda-divalproex": {
        "starting_dose": {
            "Migraine": [
                "500",
                "Migraine: The recommended starting dose is [[500 mg]]/day for 1 week",
                "The recommended starting dose is [[500 mg]] once daily for 1 week",
            ],
        },
        "max_daily_dose": [None],
        "pediatric_min_age": [
            "10",
            "For adults and children [[10 years]] of age or older.",
            "pediatric patients [[10 years]] of age or older with epilepsy",
        ],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "250",
                "Divalproex sodium extended-release tablets USP, [[250 mg]] are available",
                "USP equivalent to [[250 mg]] of valproic acid",
                "Tablets: [[250 mg]] and 500 mg (3)",
            ],
            [
                "500",
                "Divalproex sodium extended-release tablets USP, [[500 mg]] are available",
                "USP equivalent to [[500 mg]] of valproic acid",
                "Tablets: 250 mg and [[500 mg]] (3)",
            ],
        ],
        "weight_based_dose": [
            "25",
            "Mania: Initial dose is [[25 mg/kg/day]]",
            "The recommended initial dose is [[25 mg/kg/day]] given once daily",
        ],
    },
    "fda-levetiracetam": {
        "starting_dose": {
            "Partial-Onset Seizures": [
                "1000",
                "Initiate treatment with a daily dose of [[1000 mg]]/day, given as twice-daily dosing",
            ],
            "Myoclonic Seizures in Patients with Juvenile Myoclonic Epilepsy": [
                "1000",
                "[[1000 mg]]/day, given as twice-daily dosing (500 mg twice daily). Increase the dosage by",
            ],
            "Primary Generalized Tonic-Clonic Seizures": [
                "1000",
                "[[1000 mg]]/day, given as twice-daily dosing (500 mg twice daily). Increase dosage by",
            ],
        },
        "max_daily_dose": {
            "Partial-Onset Seizures": [
                "3000",
                "to a maximum recommended daily dose of [[3000 mg]]. There is no evidence",
            ],
        },
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "500",
                "available containing [[500 mg]], 750 mg or 1000 mg",
                "The [[500 mg]] tablets are white",
                "[[500 mg]], 750 mg, and 1000 mg film-coated, scored tablets (3)",
            ],
            [
                "750",
                "available containing 500 mg, [[750 mg]] or 1000 mg",
                "The [[750 mg]] tablets are white",
                "500 mg, [[750 mg]], and 1000 mg film-coated, scored tablets (3)",
            ],
            [
                "1000",
                "available containing 500 mg, 750 mg or [[1000 mg]] of levetiracetam",
                "The [[1000 mg]] tablets are white",
                "500 mg, 750 mg, and [[1000 mg]] film-coated, scored tablets (3)",
            ],
        ],
        "weight_based_dose": [
            "7",
            "1 Month to < 6 Months: [[7 mg/kg]] twice daily; increase",
            "in 2 divided doses ([[7 mg/kg]] twice daily)",
        ],
    },
    "fda-ciprofloxacin": {
        "starting_dose": {
            "Skin and Skin Structure Infections": [
                "500",
                "Duration Skin and Skin Structure [[500 mg]] to 750 mg",
                "(post-exposure). Skin and Skin Structure [[500 mg]] to 750 mg",
            ],
            "Bone and Joint Infections": [
                "500",
                "Bone and Joint [[500 mg]] to 750 mg every 12 hours 4 to 8 weeks Complicated Intra-Abdominal 500 mg",
                "Bone and Joint [[500 mg]] to 750 mg every 12 hours 4 to 8 weeks Complicated Intra-AbdominalUsed",
            ],
            "Complicated Intra-Abdominal Infections": [
                "500",
                "Complicated Intra-Abdominal [[500 mg]] every 12 hours",
                "Used in conjunction with metronidazole. [[500 mg]] every 12 hours",
            ],
            "Infectious Diarrhea": [
                "500",
                "Infectious Diarrhea [[500 mg]] every 12 hours",
                "Infectios Diarrhea [[500 mg]] every 12 hours",
            ],
            "Typhoid Fever (Enteric Fever)": [
                "500",
                "Typhoid Fever [[500 mg]] every 12 hours 10 days Uncomplicated Gonorrhea",
                "Typhoid Fever [[500 mg]] every 12 hours 10 days Uncomplicated Urethral",
            ],
            "Uncomplicated Cervial and Urethral Gonorrhea": [
                "250",
                "Uncomplicated Gonorrhea [[250 mg]] single dose",
                "Cervical Gonococcal Infections [[250 mg]] single dose",
            ],
            "Inhalational Anthrax (Post-Exposure)": [
                "500",
                "Inhalational anthrax (post-exposure) [[500 mg]] every 12 hours",
                "suspected or confirmed exposure. [[500 mg]] every 12 hours 60 days",
            ],
            "Plague": [
                "500",
                "(post-exposure) 500 mg every 12 hours 60 days Plague [[500 mg]] to 750 mg",
                "confirmed exposure. 500 mg every 12 hours 60 days Plague [[500 mg]] to 750 mg",
            ],
            "Chronic Bacterial Prostatitis": [
                "500",
                "Chronic Bacterial Prostatitis [[500 mg]] every 12 hours 28 days Lower Respiratory Tract 500",
                "Chronic Bacterial Prostatitis [[500 mg]] every 12 hours 28 days Lower Respiratory Tract Infections",
            ],
            "Lower Respiratory Tract Infections": [
                "500",
                "Lower Respiratory Tract [[500 mg]] to 750 mg",
                "Lower Respiratory Tract Infections [[500 mg]] to 750 mg",
            ],
            "Urinary Tract Infections": [
                "250",
                "Urinary Tract [[250 mg]] to 500 mg",
                "Urinary Tract Infections [[250 mg]] to 500 mg",
            ],
            "Acute Sinusitis": [
                "500",
                "Acute Sinusitis [[500 mg]] every 12 hours 10 days Adults with",
                "Acute Sinusitis [[500 mg]] every 12 hours 10 days Conversion of IV",
            ],
        },
        "max_daily_dose": [None],
        "pediatric_min_age": [
            "1",
            "([[1]] to 17 years of age)",
            "(patients from [[1]] to 17 years of age)",
        ],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "250",
                "Tablets: [[250 mg]], 500 mg and 750 mg (3)",
                "Ciprofloxacin tablets [[250 mg]] are available",
            ],
            [
                "500",
                "Tablets: 250 mg, [[500 mg]] and 750 mg (3)",
                "Ciprofloxacin tablets [[500 mg]] are available",
            ],
            [
                "750",
                "Tablets: 250 mg, 500 mg and [[750 mg]] (3)",
                "Ciprofloxacin tablets [[750 mg]] are available",
            ],
        ],
        "weight_based_dose": [
            "15",
            "(Post-Exposure) [[15 mg/kg]] (maximum 500 mg per dose)",
            "[[15 mg/kg]] maximum 500 mg per dose)",
        ],
    },
    "fda-valsartan": {
        "starting_dose": [
            "80",
            "The recommended starting dose of valsartan tablet is [[80 mg]] or 160 mg once daily",
        ],
        "max_daily_dose": [
            "320",
            "used over a dose range of 80 mg to [[320 mg]] daily",
            "the dose may be increased to a maximum of [[320 mg]] or a diuretic may be added",
        ],
        "pediatric_min_age": ["1", "2.3 Pediatric Hypertension [[1]] to 16 Years of Age"],
        "hepatic_starting_dose": [None],
        "strengths": [
            ["40", "[[40 mg]] are yellow colored"],
            ["80", "[[80 mg]] are pale red colored"],
            ["160", "[[160 mg]] are grey-orange colored"],
            ["320", "[[320 mg]] are dark-grey-violet colored"],
        ],
        "weight_based_dose": [
            "1",
            "The usual recommended starting dose is [[1 mg/kg]] once daily",
        ],
    },
    "fda-lamotrigine": {
        "starting_dose": {
            "Epilepsy": [
                "25",
                "Weeks 1 and 2 [[25 mg]] every other day",
                "25 mg every other day [[25 mg]] every day 50 mg/day",
            ],
            "Bipolar Disorder": [
                "25",
                "Weeks 1 and 2 [[25 mg]] every otherday",
                "25 mg every otherday [[25 mg]] daily 50 mg daily Weeks 3",
            ],
        },
        "max_daily_dose": {
            "Bipolar Disorder": [
                "200",
                "Accordingly, doses above [[200 mg]]/day are not recommended.",
            ],
        },
        "pediatric_min_age": [
            "2",
            "Patients Aged [[2]] to 12 Years Recommended dosing",
            "Escalation Regimen for Lamotrigine in Patients Aged [[2]] to 12 Years with Epilepsy",
        ],
        "hepatic_starting_dose": [None],
        "strengths": [
            ["25", "Tablets: [[25 mg]], 100 mg, 150 mg, and 200 mg; scored."],
            ["100", "Tablets: 25 mg, [[100 mg]], 150 mg, and 200 mg; scored."],
            [
                "150",
                "Tablets: 25 mg, 100 mg, [[150 mg]], and 200 mg; scored.",
                "( 3.1, 16) 3.1 Tablets [[150-mg]],White",
            ],
            ["200", "Tablets: 25 mg, 100 mg, 150 mg, and [[200 mg]]; scored."],
        ],
        "weight_based_dose": ["0.15", "Weeks 1 and 2 [[0.15 mg/kg/day]]"],
    },
    "fda-topiramate": {
        "starting_dose": {
            "Monotherapy Epilepsy": ["50", "Week 6 [[50 mg]] 100 mg 150 mg"],
            "Adjunctive Therapy Epilepsy": [
                "25",
                "Initiate therapy at [[25 mg]] to 50 mg once daily",
            ],
            "Migraine": ["25", "Week 1 [[25 mg]] Week 2 50 mg"],
        },
        "max_daily_dose": [None],
        "pediatric_min_age": [
            "2",
            "Pediatric Patients [[2]] to 9 Years of Age Dosing",
            "Dosing in patients [[2]] to 9 years of age is based on weight",
            "Pediatric Patients [[2]] to 16 Years of Age The recommended",
            "pediatric patients [[2]] to 16 years of age with partial-onset",
        ],
        "hepatic_starting_dose": [None],
        "strengths": [
            ["25", "[[25 mg]]: flesh colored cap", "Extended-release capsules: [[25 mg]], 50 mg"],
            ["50", "[[50 mg]]: light orange cap", "capsules: 25 mg, [[50 mg]], 100 mg"],
            [
                "100",
                "[[100 mg]]: reddish orange cap",
                "25 mg, 50 mg, [[100 mg]], 150 mg, and 200 mg (3)",
            ],
            ["150", "[[150 mg]]: grey cap", "100 mg, [[150 mg]], and 200 mg (3)"],
            ["200", "[[200 mg]]: brown cap", "150 mg, and [[200 mg]] (3)"],
        ],
        "weight_based_dose": ["5", "approximately [[5 mg/kg]] to 9 mg/kg orally once daily"],
    },
    "fda-naproxen": {
        "starting_dose": [
            "250",
            "Naproxen tablets [[250 mg]] (one-half tablet) 500 mg",
            "Naproxen tablets [[250 mg]] (one half tablet)",
        ],
        "max_daily_dose": [
            "1500",
            "the dose may be increased to naproxen [[1500 mg]]/ day for up to 6 months",
            "the dose may be increased to naproxen [[1500 mg]]/day for limited periods",
            "When treating such patients with naproxen [[1500 mg]]/day",
        ],
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "250",
                "Naproxen Tablets, USP, [[250 mg]]: circular",
                "Naproxen Tablets, USP: [[250 mg]], 375 mg & 500 mg",
            ],
            [
                "375",
                "Naproxen Tablets, USP, [[375 mg]]: oval",
                "Naproxen Tablets, USP: 250 mg, [[375 mg]] & 500 mg",
            ],
            [
                "500",
                "Naproxen Tablets, USP, [[500 mg]]: capsule shaped",
                "Naproxen Tablets, USP: 250 mg, 375 mg & [[500 mg]]",
            ],
            [
                "275",
                "Naproxen Sodium Tablets, USP, [[275 mg]]: blue",
                "Naproxen Sodium Tablets, USP: [[275 mg]], 550 mg",
            ],
            [
                "550",
                "Naproxen Sodium Tablets, USP, [[550 mg]]: blue colored",
                "Naproxen Sodium Tablets, USP: 275 mg, [[550 mg]]",
            ],
        ],
        "weight_based_dose": [
            "10",
            "Recommended total daily dose of naproxen is approximately [[10 mg/kg]]",
            "The recommended total daily dose of naproxen is approximately [[10 mg/kg]]",
        ],
    },
    "fda-hydroxychloroquine": {
        "starting_dose": {
            "Malaria": [
                "400",
                "Adults: [[400 mg]] once a week",
                "Adult patients: [[400 mg]] once a week",
            ],
            "Rheumatoid Arthritis": [
                "400",
                "Rheumatoid Arthritis in Adults (2.3): • Initial dosage: [[400 mg]] to 600 mg daily",
                "Initial dosage: [[400 mg]] to 600 mg daily as a single daily dose",
            ],
            "Systemic Lupus Erythematosus": [
                "200",
                "Systemic Lupus Erythematosus in Adults (2.4): • [[200 mg]] once daily",
                "2.4 Dosage for Systemic Lupus Erythematosus in Adults The recommended dosage is [[200 mg]] given once daily",
            ],
            "Chronic Discoid Lupus Erythematosus": [
                "200",
                "Chronic Discoid Lupus Erythematosus in Adults (2.5): • [[200 mg]] once daily",
                "2.5 Dosage for Chronic Discoid Lupus Erythematosus in Adults The recommended dosage is [[200 mg]] given once daily",
            ],
        },
        "max_daily_dose": [None],
        "pediatric_min_age": [None],
        "hepatic_starting_dose": [None],
        "strengths": [
            [
                "100",
                "[[100 mg]]: Hydroxychloroquine Sulfate Tablets",
                "Tablets: [[100 mg]], 200 mg",
            ],
            [
                "200",
                "[[200 mg]]: Hydroxychloroquine Sulfate Tablets",
                "Tablets: 100 mg, [[200 mg]], 300 mg",
            ],
            [
                "300",
                "[[300 mg]]: Hydroxychloroquine Sulfate Tablets",
                "200 mg, [[300 mg]] and 400 mg of",
            ],
            [
                "400",
                "[[400 mg]]: Hydroxychloroquine Sulfate Tablets",
                "300 mg and [[400 mg]] of hydroxychloroquine sulfate (3)",
            ],
        ],
        "weight_based_dose": [
            "6.5",
            "Pediatric patients ≥ 31 kg: [[6.5 mg/kg]] up to 400 mg, once a week",
            "Pediatric patients ≥ 31kg: [[6.5 mg/kg]] actual body weight (up to 400 mg) once a week",
        ],
    },
}
