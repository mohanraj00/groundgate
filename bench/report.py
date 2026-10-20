"""Render bench/results.json as bench/RESULTS.md and two SVG charts. Called by bench/score.py.

    python bench/report.py --compare bench/requested3/results.json bench/requested4/results.json

compares two requested sets: miss rate, escapes, incomplete documents and search_limit count
for each arm and kind. A search_limit count comes from results.json, or from a limits.json
beside it (bench/requested3 has one, from bench/requested/limits.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path
from typing import Any

SERIES = {
    "lx_all": ("LangExtract, every extraction", "#b8b8b8"),
    "lx_aligned": ("LangExtract, aligned", "#8c8c8c"),
    "lx_exact": ("LangExtract, MATCH_EXACT only", "#5b6b7f"),
    "groundgate": ("groundgate, admitted", "#1f7a4d"),
    "gg": ("groundgate", "#1f7a4d"),  # a chart whose rows are not all admissions
}
CORRECT = ("clean", "paraphrase")
ERRORS = (
    "value_x10",
    "text_and_value_x10",
    "near_miss_digit",
    "decimal_dropped",
    "comma_as_decimal",
    "unit_swap",
    "null_literal",
    "adjacent_value",
)
MEANING = ("qualifier_in_text", "scale_word_in_text")
WRONG_KEYS = ("wrong_value", "absent_field", "wrong_unit", "unparsable")
ERROR_NAMES = {
    "clean": "correct value, verbatim text",
    "paraphrase": "correct value, paraphrased text",
    "value_x10": "value attribute x10, text right",
    "text_and_value_x10": "value and text x10",
    "near_miss_digit": "one digit changed",
    "decimal_dropped": "decimal point dropped (0.4 read as 4)",
    "comma_as_decimal": "comma read as a decimal point (184,500 as 184.5)",
    "unit_swap": "wrong unit",
    "null_literal": '"null" as the value',
    "adjacent_value": "a nearby number with the same unit",
    "qualifier_in_text": '"more than" written before the value',
    "scale_word_in_text": '"million" written after the value',
}


def pct(r: dict[str, Any] | None, ci: bool = False) -> str:
    if not r or r["rate"] is None:
        return "n/a"
    s = f"{100 * r['rate']:.1f}% ({r['k']}/{r['n']})"
    if ci:
        s += f" [{100 * r['ci95'][0]:.0f}, {100 * r['ci95'][1]:.0f}]"
    return s


def share(k: int, n: int) -> str:
    return f"{100 * k / n:.1f}%" if n else "n/a"


# ------------------------------------------------------------------------------ charts


def bars(
    title: str,
    groups: list[tuple[str, list[tuple[str, float, tuple[float, float] | None]]]],
    note: str,
) -> str:
    """A horizontal grouped bar chart, 0 to 100%. groups: (label, [(series, rate, ci)])."""
    left, width, bar, gap = 250, 400, 14, 14
    rows = sum(len(b) for _, b in groups)
    used = sorted({s for _, b in groups for s, _, _ in b}, key=list(SERIES).index)
    height = 70 + rows * (bar + 3) + len(groups) * gap + 22 * ((len(used) + 1) // 2) + 30
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {left + width + 60} {height}" '
        f'font-family="-apple-system, Segoe UI, Helvetica, Arial, sans-serif" font-size="12">',
        '<rect width="100%" height="100%" rx="8" fill="#ffffff" stroke="#dddddd"/>',
        f'<text x="16" y="26" font-size="14" font-weight="600" fill="#111">{escape(title)}</text>',
    ]
    y = 46
    for tick in (0, 25, 50, 75, 100):
        x = left + width * tick / 100
        out.append(
            f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y + rows * (bar + 3) + len(groups) * gap}"'
            f' stroke="#eeeeee"/>'
        )
        out.append(f'<text x="{x}" y="{y - 4}" text-anchor="middle" fill="#777">{tick}%</text>')
    y += 6
    for label, series in groups:
        mid = y + len(series) * (bar + 3) / 2
        out.append(
            f'<text x="{left - 10}" y="{mid + 4}" text-anchor="end" fill="#222">'
            f"{escape(label)}</text>"
        )
        for s, value, ci in series:
            w = max(width * value, 1.5)
            out.append(
                f'<rect x="{left}" y="{y}" width="{w:.1f}" height="{bar}" fill="{SERIES[s][1]}"/>'
            )
            if ci:
                x0, x1, cy = left + width * ci[0], left + width * ci[1], y + bar / 2
                out.append(
                    f'<line x1="{x0:.1f}" y1="{cy}" x2="{x1:.1f}" y2="{cy}" '
                    f'stroke="#222" stroke-width="1"/>'
                )
            end = max(w, width * ci[1]) if ci else w
            out.append(
                f'<text x="{left + end + 5:.1f}" y="{y + bar - 3}" fill="#333" '
                f'font-size="11">{100 * value:.{1 if value < 0.1 else 0}f}%</text>'
            )
            y += bar + 3
        y += gap
    y += 8
    for i, s in enumerate(used):
        x, ly = 16 + (i % 2) * 330, y + (i // 2) * 22
        out.append(f'<rect x="{x}" y="{ly}" width="12" height="12" fill="{SERIES[s][1]}"/>')
        out.append(f'<text x="{x + 18}" y="{ly + 10}" fill="#222">{escape(SERIES[s][0])}</text>')
    y += 22 * ((len(used) + 1) // 2) + 6
    out.append(f'<text x="16" y="{y}" fill="#666" font-size="11">{escape(note)}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def chart_a(a: dict[str, Any]) -> str:
    groups = []
    for cls in (*ERRORS, *MEANING):
        if cls not in a:
            continue
        n = a[cls]["n"]
        groups.append(
            (
                ERROR_NAMES[cls].split(" (")[0],
                [(c, a[cls].get(f"{c}:accept", 0) / n, None) for c in ("lx_exact", "groundgate")],
            )
        )
    return bars(
        "Planted errors let through without review",
        groups,
        "Track A. One error planted per gold fact, aligned by LangExtract's own Resolver.",
    )


def chart_b(b: dict[str, Any]) -> str:
    groups = []
    for run, per in b["runs"].items():
        series = []
        for c in ("lx_all", "lx_exact", "groundgate"):
            r = per[c]["escape"]
            if r["rate"] is not None:
                series.append((c, r["rate"], tuple(r["ci95"])))
        if series:
            groups.append((run.replace(" @ ", ", buffer "), series))
    return bars(
        "Wrong model extractions accepted without review",
        groups,
        "Track B. Lines are 95% Wilson intervals.",
    )


POOLED = {
    "escape": "wrong extractions accepted without review",
    "false_reject": "correct extractions citing the right place, rejected",
    "review_load": "extractions sent to a person",
}


def chart_summary(b: dict[str, Any]) -> str:
    """The README chart: MATCH_EXACT against groundgate over every run."""
    groups = [
        (
            "correct extractions rejected*" if m == "false_reject" else label,
            [
                ("lx_exact", b["pooled"]["lx_exact"][m]["rate"], None),
                ("gg", b["pooled"]["groundgate"][m]["rate"], None),
            ],
        )
        for m, label in POOLED.items()
    ]
    n = b["pooled"]["groundgate"]["review_load"]["n"]
    return bars(
        "LangExtract MATCH_EXACT and groundgate, all runs",
        groups,
        f"Track B, {len(b['runs'])} runs, {n:,} extractions. Runs share documents: no intervals."
        " *Correct extractions citing the right place.",
    )


# ---------------------------------------------------------------------------- markdown


def table(head: list[str], rows: list[list[object]], right_from: int = 1) -> list[str]:
    align = ["---" if i < right_from else "---:" for i in range(len(head))]
    out = ["| " + " | ".join(head) + " |", "|" + "|".join(align) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return [*out, ""]


def render(res: dict[str, Any]) -> dict[str, str]:
    """File name (relative to bench/) -> content."""
    a, b, gold = res["track_a"], res["track_b"], res["gold"]
    md = ["# Benchmark results", ""]
    if gold["status"].startswith("draft"):
        md += [
            "> **Draft gold.** These numbers score against model-written labels that no person",
            "> has checked yet. They are for development only.",
            "",
        ]
    md += [
        "Generated by `bench/score.py` from the cached runs in `bench/runs`. "
        "[bench/README.md](README.md) explains the method.",
        "",
        f"Gold: {gold['documents']} documents, {gold['facts']} facts, "
        f"{gold['absent_fields']} fields confirmed absent, "
        f"{gold['excluded_fields']} excluded as ambiguous ({gold['status']}"
        + (f" in {gold['labeling_hours']} hours" if gold["labeling_hours"] else "")
        + ").",
        "",
        "## Track A: planted errors",
        "",
        "![Planted errors let through](charts/track_a.svg)",
        "",
    ]
    head = [
        "Planted",
        "n",
        "LangExtract, all",
        "aligned",
        "MATCH_EXACT",
        "groundgate admitted",
        "review",
        "rejected",
    ]
    for title, classes in (
        ("Correct extractions (higher is better)", CORRECT),
        ("Errors in the extraction (lower is better)", ERRORS),
        ("Errors in meaning: the text qualifies the value (lower is better)", MEANING),
    ):
        rows = []
        for cls in classes:
            if cls in a:
                r, n = a[cls], a[cls]["n"]
                cells = [share(r.get(f"{c}:accept", 0), n) for c in (*SERIES,)]
                cells += [share(r.get(f"groundgate:{v}", 0), n) for v in ("review", "reject")]
                rows.append([ERROR_NAMES[cls], n, *cells])
        md += [f"**{title}.** Share accepted without review.", "", *table(head, rows)]
        elsewhere = sum(a.get(c, {}).get("groundgate:accept_cited_elsewhere", 0) for c in classes)
        admitted = sum(a.get(c, {}).get("groundgate:accept", 0) for c in classes)
        if elsewhere:
            lead = f"All {admitted}" if elsewhere == admitted else f"{elsewhere} of the {admitted}"
            md += [
                f"{lead} admitted here cite another place where the same text appears without "
                "the planted word. LangExtract aligned the quote there, and that place does "
                "state the value.",
                "",
            ]
    md += [
        "## Track B: real model runs",
        "",
        "![Wrong extractions accepted](charts/track_b.svg)",
        "",
        "All runs pooled. The runs share documents, so a pooled rate has no honest interval.",
        "",
    ]
    md += table(
        ["", "LangExtract, all", "aligned", "MATCH_EXACT", "groundgate"],
        [
            [
                label,
                *(
                    pct(b["pooled"][c][m])
                    for c in ("lx_all", "lx_aligned", "lx_exact", "groundgate")
                ),
            ]
            for m, label in POOLED.items()
        ],
    )
    runs = list(b["runs"].items())
    md += table(
        [
            "Run",
            "docs",
            "candidates",
            "wrong",
            "escaped, LangExtract all",
            "escaped, MATCH_EXACT",
            "escaped, groundgate",
            "wrong sent to review",
            "false rejects",
            "review load",
            "recall, admitted",
            "recall, admitted or review",
        ],
        [
            [
                run,
                p["documents"],
                (g := p["groundgate"])["candidates"],
                g["wrong"],
                pct(p["lx_all"]["escape"]),
                pct(p["lx_exact"]["escape"]),
                pct(g["escape"], ci=True),
                pct(g["wrong_sent_to_review"]),
                pct(g["false_reject"]),
                pct(g["review_load"]),
                pct(g["recall"]["accepted"]),
                pct(g["recall"]["accepted_or_review"]),
            ]
            for run, p in runs
        ],
    )
    md += ["### What the wrong extractions were", ""]
    md += table(
        ["Run", "wrong value", "field absent from the document", "wrong unit", "not a number"],
        [
            [run, *(p["groundgate"]["wrong_by_class"].get(k, 0) for k in WRONG_KEYS)]
            for run, p in runs
        ],
    )
    codes = sorted({c for _, p in runs for c in p["caught_by"]})
    if codes:
        md += [
            "### What stopped them",
            "",
            "The first reason code on each wrong extraction groundgate rejected or sent to review.",
            "",
        ]
        md += table(
            ["Run", *(f"`{c}`" for c in codes)],
            [[run, *(p["caught_by"].get(c, 0) for c in codes)] for run, p in runs],
        )
    md += [
        "### Right value, wrong place",
        "",
        "Correct values groundgate admitted whose evidence does not overlap any gold evidence "
        "span, and correct values rejected because LangExtract aligned them to the wrong "
        "place.",
        "",
    ]
    md += table(
        ["Run", "admitted, cited elsewhere", "rejected, cited elsewhere"],
        [
            [
                run,
                pct(p["groundgate"]["accepted_correct_citing_wrong_place"]),
                pct(p["groundgate"]["rejected_right_value_wrong_place"]),
            ]
            for run, p in runs
        ],
    )
    md += ["### By source", ""]
    md += table(
        ["Run", "source", "wrong", "escaped, MATCH_EXACT", "escaped, groundgate"],
        [
            [
                run,
                kind,
                k["groundgate"]["wrong"],
                pct(k["lx_exact"]["escape"]),
                pct(k["groundgate"]["escape"]),
            ]
            for run, p in runs
            for kind, k in p["by_kind"].items()
            if k["groundgate"]["wrong"]
        ],
        right_from=2,
    )
    md += [
        "### Harness",
        "",
        "Chunks whose reply LangExtract could not parse are skipped by `lx.extract` and count "
        "against recall. Codex replies that used a tool, and Claude Code replies from another "
        "model or with more than one turn, were discarded and retried.",
        "",
    ]
    md += table(
        [
            "Run",
            "provider",
            "chunks",
            "unusable replies",
            "replies discarded by the harness check",
            "seconds per document",
        ],
        [
            [
                run,
                (h := p["harness"])["provider"],
                h.get("chunks", 0),
                h.get("unusable_chunks", 0),
                h.get("discarded", 0),
                round(h.get("seconds", 0) / p["documents"]),
            ]
            for run, p in runs
        ],
        right_from=2,
    )
    # every pair at the default chunk size, and all models together at each size
    pairs = [(n, p) for n, p in b["pairs"].items() if n.endswith("@ 1000")]
    groups = pairs + list(b["all_models"].items())
    if groups:
        md += [
            "### Several models through one gate",
            "",
            "Each group's candidates go into one `admit` call per document, so a "
            "disagreement on a single-valued field is flagged `CONFLICTING_CANDIDATES`. "
            '"Separately" admits the same candidates one model at a time. Pairs at 4,000 '
            "characters are in results.json.",
            "",
        ]
        md += table(
            [
                "Models",
                "docs",
                "wrong",
                "escaped, together",
                "escaped, separately",
                "review load, together",
                "review load, separately",
                "recall, admitted",
            ],
            [
                [
                    name,
                    p["documents"],
                    p["wrong"],
                    pct(p["escape"], ci=True),
                    pct(p["escape_when_admitted_separately"]),
                    pct(p["review_load"]),
                    pct(p["review_load_when_admitted_separately"]),
                    pct(p["recall"]["accepted"]),
                ]
                for name, p in groups
            ],
        )
    md += [
        "## Appendix: wrong and admitted",
        "",
        "Every wrong candidate groundgate admitted without review.",
        "",
    ]
    if b["escapes"]:
        md += table(
            ["Run", "doc", "field", "value", "gold", "why wrong", "text around the evidence"],
            [
                [
                    f"{e['model']}, {e['buffer']}",
                    e["doc"],
                    e["field"],
                    e["value"],
                    ", ".join(e["gold"]) or "absent",
                    e["label"],
                    (e["context"] or "").replace("|", "\\|"),
                ]
                for e in b["escapes"]
            ],
            right_from=99,
        )
    else:
        md += ["None.", ""]
    return {
        "RESULTS.md": "\n".join(md).rstrip("\n") + "\n",
        "charts/track_a.svg": chart_a(a),
        "charts/track_b.svg": chart_b(b),
        "charts/summary.svg": chart_summary(b),
    }


# ------------------------------------------------------------------------------ set 2

SPECS = (("groundgate_0.1", "0.1"), ("groundgate", "0.2"))
NEW_ERRORS = ("key_swap", "per_kg_as_absolute", "from_value")
ON_PATTERN = ("clean_change", "clean_negation", "clean_scale")
WRONG_KEYS2 = ("wrong_value", "absent_field", "wrong_key", "wrong_unit", "unparsable")
ERROR_NAMES2 = ERROR_NAMES | {
    "key_swap": "right value, another key of the field (#2)",
    "per_kg_as_absolute": "a weight-based dose given as an absolute one (#3)",
    "from_value": 'the old value of "from X to Y" (#4)',
    "clean_change": 'correct value inside "from X to Y" (#4)',
    "clean_negation": 'correct value after "not more than" and similar (#5)',
    "clean_scale": 'correct value written with a scale word, "$1.2 million" (#6)',
}


def both(get: Any) -> list[str]:
    """One cell per spec, 0.1 first."""
    return [get(config) for config, _ in SPECS]


def render_set2(res: dict[str, Any]) -> dict[str, str]:
    """Set 2: spec 0.1 and 0.2 side by side (#12). File name (relative to the set) -> content."""
    a, b, gold = res["track_a"], res["track_b"], res["gold"]
    md = ["# Benchmark set 2: spec 0.1 and 0.2 side by side", ""]
    if gold["control_items_not_judged"]:
        md += [
            f"> **Not final.** {gold['control_items_not_judged']} of the "
            f"{gold['control_items']} control items are not judged yet, so the controls section "
            "is incomplete.",
            "",
        ]
    md += [
        "Generated by `bench/score.py --set bench/set2` from the cached runs in `runs/`. "
        "[README.md](README.md) explains the set and [SELECTION.md](SELECTION.md) how it was "
        "picked. Every candidate is decided twice: by the released 0.2.0 wheel (spec 0.2), and by "
        "the released 0.1.0 wheel through `bench/decide.py`. Both see the same candidates.",
        "",
        f"Gold: {gold['documents']} documents checked in full, {gold['facts']} facts, "
        f"{gold['absent_fields']} fields confirmed absent, {gold['excluded_fields']} excluded "
        f"as ambiguous ({gold['status']} in {gold['labeling_hours']} hours). "
        f"{gold['control_documents']} control documents are judged only where the two specs "
        f"decide differently: {gold['control_items']} candidates. Three fields changed after "
        'the first scoring, with model output in view; README.md lists them under "Gold '
        'changes after scoring".',
        "",
        "## Track A: planted errors",
        "",
        "One error at a time, planted into each gold fact and aligned the way `lx.extract` "
        "would. The share is of the planted candidates; docs is how many documents they come "
        "from.",
        "",
    ]
    head = ["Planted", "n", "docs", "MATCH_EXACT accepted"]
    head += [f"{v} {s}" for v in ("admitted", "review", "rejected") for s in ("0.1", "0.2")]
    verdicts = ("accept", "review", "reject")
    for title, classes in (
        ("Correct extractions (higher admitted is better)", CORRECT),
        ("Correct extractions on the patterns 0.2 changed (higher admitted is better)", ON_PATTERN),
        ("Errors in the extraction (lower admitted is better)", ERRORS),
        ("New error classes (lower admitted is better)", NEW_ERRORS),
        ("Errors in meaning: the text qualifies the value (lower admitted is better)", MEANING),
    ):
        rows = []
        for cls in classes:
            if cls in a:
                r, n = a[cls], a[cls]["n"]
                cells = [share(r.get("lx_exact:accept", 0), n)]
                cells += [share(r.get(f"{c}:{v}", 0), n) for v in verdicts for c, _ in SPECS]
                rows.append([ERROR_NAMES2[cls], n, r.get("documents", 0), *cells])
        md += [f"**{title}.**", "", *table(head, rows)]
    models = {r.split(" @ ")[0] for r in b["runs"]}
    buffers = [f"{n:,}" for n in sorted({int(r.split(" @ ")[1]) for r in b["runs"]})]
    md += [
        "## Track B: real model runs",
        "",
        f"{len(b['runs'])} runs: {len(models)} models at buffers of {' and '.join(buffers)} "
        "characters. Rates are "
        f"over candidates on the {gold['documents']} documents checked in full; the controls "
        "follow below. All runs pooled first. The runs share documents, so a pooled rate has no "
        "honest interval.",
        "",
    ]
    md += table(
        ["", "LangExtract, all", "MATCH_EXACT", "groundgate 0.1", "groundgate 0.2"],
        [
            [
                label,
                *(
                    pct(b["pooled"][c][m])
                    for c in ("lx_all", "lx_exact", "groundgate_0.1", "groundgate")
                ),
            ]
            for m, label in POOLED.items()
        ],
    )
    runs = list(b["runs"].items())
    md += table(
        [
            "Run",
            "docs",
            "candidates",
            "wrong",
            "escaped, MATCH_EXACT",
            "escaped, 0.1",
            "escaped, 0.2",
            "review load, 0.1",
            "review load, 0.2",
            "false rejects, 0.1",
            "false rejects, 0.2",
            "recall admitted, 0.1",
            "recall admitted, 0.2",
        ],
        [
            [
                run,
                (g := p["groundgate"])["documents"],
                g["candidates"],
                g["wrong"],
                pct(p["lx_exact"]["escape"]),
                *both(lambda c, p=p: pct(p[c]["escape"])),
                *both(lambda c, p=p: pct(p[c]["review_load"])),
                *both(lambda c, p=p: pct(p[c]["false_reject"])),
                *both(lambda c, p=p: pct(p[c]["recall"]["accepted"])),
            ]
            for run, p in runs
        ],
    )
    md += ["### Escaped, by why they are wrong, all runs pooled", ""]
    md += table(
        ["Spec", "wrong value", "field absent", "wrong key", "wrong unit", "not a number"],
        [
            [
                spec,
                *(
                    sum(p[config]["escaped_by_class"].get(k, 0) for _, p in runs)
                    for k in WRONG_KEYS2
                ),
            ]
            for config, spec in SPECS
        ],
    )
    md += ["### What the wrong extractions were", ""]
    md += table(
        ["Run", "wrong value", "field absent", "wrong key", "wrong unit", "not a number"],
        [
            [run, *(p["groundgate"]["wrong_by_class"].get(k, 0) for k in WRONG_KEYS2)]
            for run, p in runs
        ],
    )
    for config, spec in SPECS:
        name = "caught_by" + config.removeprefix("groundgate")
        codes = sorted({c for _, p in runs for c in p[name]})
        md += [
            f"### What stopped them under {spec}",
            "",
            "The first reason code on each wrong extraction rejected or sent to review.",
            "",
        ]
        md += table(
            ["Run", *(f"`{c}`" for c in codes)],
            [[run, *(p[name].get(c, 0) for c in codes)] for run, p in runs],
        )
    for part, title in (("by_group", "By group"), ("by_kind", "By source")):
        md += [f"### {title}, all runs pooled", ""]
        md += [
            "docs is the number of documents in the group with a scored candidate. Per-run "
            "numbers are in results.json.",
            "",
        ]
        names = sorted({n for _, p in runs for n in p.get(part, {})})
        rows = []
        for n in names:
            parts = [p[part][n] for _, p in runs if n in p.get(part, {})]
            if not sum(x["groundgate"]["candidates"] for x in parts):
                continue
            docs = max(x["groundgate"]["documents"] for x in parts)
            cells = [n, docs, sum(x["groundgate"]["wrong"] for x in parts)]
            for metric in ("escape", "review_load", "false_reject"):
                cells += both(lambda c, m=metric, ps=parts: pooled(ps, c, m))
            rows.append(cells)
        md += table(
            [
                "",
                "docs",
                "wrong",
                "escaped, 0.1",
                "escaped, 0.2",
                "review load, 0.1",
                "review load, 0.2",
                "false rejects, 0.1",
                "false rejects, 0.2",
            ],
            rows,
        )
    md += [
        "## Controls",
        "",
        "Control documents (NTSB, IRS general and FDA labels in the general group only) are "
        "not checked in full. A person judged each candidate the two specs decide differently, "
        "without seeing either decision. The other control candidates are not scored.",
        "",
    ]
    md += table(
        [
            "",
            "judged",
            "wrong",
            "escaped, 0.1",
            "escaped, 0.2",
            "false rejects, 0.1",
            "false rejects, 0.2",
        ],
        [
            [
                "all runs",
                sum(p["controls"]["groundgate"]["candidates"] for _, p in runs),
                sum(p["controls"]["groundgate"]["wrong"] for _, p in runs),
                *(
                    pooled([p["controls"] for _, p in runs], c, m)
                    for m in ("escape", "false_reject")
                    for c, _ in SPECS
                ),
            ]
        ],
    )
    md += [
        "### Harness",
        "",
        "Chunks whose reply LangExtract could not parse are skipped by `lx.extract` and count "
        "against recall. Chunks Claude refused are recorded as skipped (#37), not as unusable.",
        "",
    ]
    kinds = ("fda", "irs", "fr", "ntsb")
    md += table(
        [
            "Run",
            "provider",
            "chunks",
            "refused",
            "unusable",
            *(f"unusable, {k}" for k in kinds),
            "seconds per document",
        ],
        [
            [
                run,
                (h := p["harness"])["provider"],
                h.get("chunks", 0),
                h.get("refused", 0),
                h.get("unusable_chunks", 0),
                *(f"{h.get(f'unusable_chunks:{k}', 0)}/{h.get(f'chunks:{k}', 0)}" for k in kinds),
                round(h.get("seconds", 0) / p["documents"]),
            ]
            for run, p in runs
        ],
        right_from=2,
    )
    pairs = [(n, p) for n, p in b["pairs"].items() if n.endswith("@ 1000")]
    groups = pairs + list(b["all_models"].items())
    if groups:
        md += [
            "### Several models through one gate",
            "",
            "Each group's candidates go into one `admit` call per document. Pairs at 4,000 "
            "characters are in results.json.",
            "",
        ]
        md += table(
            [
                "Models",
                "docs",
                "wrong",
                "escaped, 0.1",
                "escaped, 0.2",
                "review load, 0.1",
                "review load, 0.2",
            ],
            [
                [
                    name,
                    p["documents"],
                    p["wrong"],
                    pct(p["spec_0.1"]["escape"]),
                    pct(p["escape"]),
                    pct(p["spec_0.1"]["review_load"]),
                    pct(p["review_load"]),
                ]
                for name, p in groups
            ],
        )
    md += [
        "## Appendix: wrong and admitted",
        "",
        "Every wrong candidate admitted without review, one by one, under each spec.",
        "",
    ]
    for _, spec in SPECS:
        esc = [e for e in b["escapes"] if e["spec"] == spec]
        md += [f"### Spec {spec}: {len(esc)}", ""]
        if not esc:
            md += ["None.", ""]
            continue
        md += table(
            [
                "Run",
                "doc",
                "field",
                "key",
                "value",
                "gold",
                "why wrong",
                "text around the evidence",
            ],
            [
                [
                    f"{e['model']}, {e['buffer']}",
                    e["doc"],
                    e["field"],
                    e["key"] or "",
                    e["value"],
                    ", ".join(e["gold"]) or "absent",
                    e["label"],
                    (e["context"] or "").replace("|", "\\|"),
                ]
                for e in esc
            ],
            right_from=99,
        )
    return {"RESULTS.md": "\n".join(md).rstrip("\n") + "\n"}


def pooled(parts: list[dict[str, Any]], config: str, metric: str) -> str:
    """One rate summed over runs: k and n add, the interval is dropped."""
    k = sum(p[config][metric]["k"] for p in parts)
    n = sum(p[config][metric]["n"] for p in parts)
    return f"{share(k, n)} ({k}/{n})" if n else "n/a"


def render_requested(results: dict[str, Any]) -> str:
    """Render only requested-field results; all numbers come from results.json."""

    def percent(raw: float | None) -> str:
        return "n/a" if raw is None else f"{raw * 100:.2f}%"

    lines = [
        "# Requested-field results",
        "",
        "Generated by `bench/score.py --requested`.",
        "",
        "Labels: `" + results["labels_sha256"] + "`.",
        "",
        "Values are final distinct admissions. Misses count labeled values without an admitted "
        "match. An absence hit requires explicit not-found. Unclear slots are excluded. "
        "A silent miss is a labeled value that is not admitted and not sent to review. "
        "Rejected right counts silent misses that a final decision rejected. No right "
        "candidate counts silent misses with no decision that carries the value.",
        "",
        "Bounds are one-sided 95% upper bounds. The value bound uses a default design effect "
        "equal to the largest admitted cluster in its slice, at least 1. Effective trials "
        "round down; effective errors round up. The document bound has one trial for each "
        "document with an admitted value, and one error for each of those with a wrong admit. "
        "It is n/a without such a document. The combined bound is their maximum, and is n/a "
        "without value trials.",
        "",
    ]
    head = [
        "Slice",
        "Docs",
        "Kinds",
        "Admits",
        "Escapes",
        "Admitted error",
        "Value upper",
        "Document upper",
        "Docs with admits",
        "Docs with wrong admit",
        "Combined upper",
        "Present",
        "Hits",
        "Absence hits",
        "Reviews",
        "Silent misses",
        "Rejected right",
        "No right candidate",
        "Miss rate",
        "Right review share",
        "Silent share",
        "Rejected right share",
        "No candidate share",
        "Unclear",
        "Unreported absences",
        "Design effect",
        "Effective trials",
        "Effective errors",
    ]
    for name, run in sorted(results["runs"].items()):
        lines += ["## " + name.replace("|", "\\|"), "", "Split: " + run["split"] + ".", ""]
        slices = [("total", run["total"])]
        slices += [("kind: " + n, r) for n, r in run["by_kind"].items()]
        slices += [("field: " + n, r) for n, r in run["by_field"].items()]
        slices += [
            (k + "/" + f, r)
            for k, fields in run["by_kind_field"].items()
            for f, r in fields.items()
        ]
        rows = []
        for label, r in slices:
            b = r["bounds"]
            rows.append(
                [
                    label.replace("|", "\\|"),
                    r["documents"],
                    r["kinds"],
                    r["admitted"],
                    r["escapes"],
                    percent(r["admitted_error_rate"]["rate"]),
                    percent(b["value_upper95"]),
                    percent(b["document_upper95"]),
                    b["document_trials"],
                    b["document_errors"],
                    percent(b["combined_upper95"]),
                    r["present"],
                    r["hits"],
                    r["absence_hits"],
                    r["reviews"],
                    r["silent_misses"],
                    r["rejected_right_values"],
                    r["no_right_candidate"],
                    percent(r["miss_rate"]["rate"]),
                    percent(r["right_value_review_share"]["rate"]),
                    percent(r["silent_miss_share"]["rate"]),
                    percent(r["rejected_right_value_share"]["rate"]),
                    percent(r["no_right_candidate_share"]["rate"]),
                    r["excluded"],
                    r["unreported_absences"],
                    b["design_effect"],
                    b["effective_trials"],
                    b["effective_errors"],
                ]
            )
        lines += table(head, rows)
        states = run["document_states"]
        lines += [
            "Run state for each document. An incomplete document stopped at a harness limit or "
            "a failed call. Its present fields without an admitted value count as misses, and "
            "its absent fields count as unreported absences. Retries are archived transport "
            "errors that ran again.",
            "",
        ]
        # A run from #383 on also counts the fields that stopped at search_limit.
        limits = "search_limit_fields" in states["total"]
        if limits:
            lines += [
                "A search_limit document has at least one field whose targeted search found "
                "no region that fits the prompt budget.",
                "",
            ]
        lines += table(
            ["Kind", "Docs", "Incomplete", "Transport error", "Transport retries"]
            + (["search_limit docs", "search_limit fields"] if limits else []),
            [
                [
                    label.replace("|", "\\|"),
                    r["documents"],
                    r["incomplete"],
                    r["transport_error"],
                    r["transport_retries"],
                ]
                + ([r["search_limit_documents"], r["search_limit_fields"]] if limits else [])
                for label, r in [
                    ("total", states["total"]),
                    *sorted(states["by_kind"].items()),
                ]
            ],
        )
    if "diagnostics" in results:
        diagnostic = results["diagnostics"]
        lines += [
            "## Separate diagnostics",
            "",
            "Companion views share source documents. Their counts do not add primary trials "
            "or alter requested-field bounds.",
            "",
            "Diagnostic export: `" + diagnostic["export_sha256"] + "`.",
            "",
        ]
        pair = diagnostic["decision_pair"]
        lines += table(
            ["Decision transition", "Candidates"],
            [[name, count] for name, count in sorted(pair["transitions"].items())],
        )
        lines += ["", "Incomplete worker records: " + str(len(pair["failures"])) + ".", ""]
        for title, key in (
            ("Added reason codes", "added_codes"),
            ("Removed reason codes", "removed_codes"),
        ):
            lines += ["### " + title, ""]
            lines += table(
                ["Code", "Candidates"], [[name, count] for name, count in sorted(pair[key].items())]
            )
        lines += ["", "### Companion views", ""]
        view_rows = []
        for view, versions in sorted(pair["by_view"].items()):
            for version, stats in sorted(versions.items()):
                if stats.get("status") == "incomplete":
                    view_rows.append([view, version, "incomplete", "n/a", "n/a", "n/a"])
                else:
                    view_rows.append(
                        [
                            view,
                            version,
                            "complete",
                            stats["admitted"],
                            stats["escapes"],
                            stats["silent_misses"],
                        ]
                    )
        lines += table(
            ["View", "Decision", "Status", "Admits", "Escapes", "Silent misses"], view_rows
        )
        lines += [
            "",
            "### Observable reader layout",
            "",
            "Status: " + diagnostic["reader_layout"]["status"] + ".",
            "",
        ]
        if missing := diagnostic["reader_layout"].get("missing_observations"):
            lines += [
                f"{len(missing)} annotated documents have no reader observation. "
                "The table does not count their cases: " + ", ".join(missing) + ".",
                "",
            ]
        rows = []
        for route, row in sorted(diagnostic["reader_layout"]["routes"].items()):
            rows.append(
                [
                    route,
                    row["evaluated"],
                    row["correct"],
                    row["unclear"],
                    row["unassessed"],
                    row["not_applicable"],
                    row["unreviewed_pages"],
                    "n/a" if row["rate"] is None else percent(row["rate"]),
                ]
            )
        lines += table(
            [
                "Kind/reader/route",
                "Evaluated",
                "Correct",
                "Unclear",
                "Unassessed",
                "Not applicable",
                "Unreviewed pages",
                "Correct share",
            ],
            rows,
        )
        lines += [""] + diagnostic["reader_layout"]["limitations"] + [""]
    return "\n".join(lines) + "\n"


def _limits(path: Path, results: dict[str, Any]) -> dict[str, Any]:
    """search_limit states for each arm: from results.json, else from limits.json beside it.

    A limits.json counts only when its run digests are the cache digests in results.json.
    """
    found = {
        arm: run["document_states"]
        for arm, run in results["runs"].items()
        if "search_limit_fields" in run["document_states"]["total"]
    }
    side = path.parent / "limits.json"
    if side.is_file():
        limits = json.loads(side.read_text(encoding="utf-8"))
        if (
            limits.get("manifest_sha256") != results["manifest_sha256"]
            or limits.get("labels_sha256") != results["labels_sha256"]
        ):
            raise ValueError("limits.json is not for this results.json: " + str(side))
        for arm, run in limits["runs"].items():
            if arm in results["runs"] and arm not in found:
                if run["run_sha256"] != results["runs"][arm]["cache_sha256"]:
                    raise ValueError("limits.json is not for the run of arm " + arm)
                found[arm] = run["document_states"]
    return found


def render_compare(
    base: dict[str, Any], new: dict[str, Any], base_limits: dict[str, Any], new_limits: dict
) -> list[str]:
    """Each arm and kind of two requested sets side by side; every number from their files."""

    def miss(run: dict[str, Any] | None, kind: str) -> str:
        r = None if run is None else (run["total"] if kind == "total" else run["by_kind"].get(kind))
        if r is None or r["miss_rate"]["rate"] is None:
            return "n/a"
        m = r["miss_rate"]
        return f"{m['k']}/{m['n']} ({m['rate'] * 100:.2f}%)"

    def escapes(run: dict[str, Any] | None, kind: str) -> str:
        r = None if run is None else (run["total"] if kind == "total" else run["by_kind"].get(kind))
        return "n/a" if r is None else str(r["escapes"])

    def state(states: dict[str, Any] | None, kind: str, limit: bool) -> str:
        s = None
        if states is not None:
            s = states["total"] if kind == "total" else states["by_kind"].get(kind)
        if s is None:
            return "n/a"
        if limit:
            return f"{s['search_limit_documents']} docs, {s['search_limit_fields']} fields"
        return f"{s['incomplete']}/{s['documents']}"

    lines = [
        "Miss rate is reviews plus silent misses over present values. Incomplete is the "
        "documents that stopped at a limit or a failed call. search_limit counts the documents "
        "and fields whose targeted search found no region that fits the prompt budget.",
        "",
        "| Arm | Kind | Miss rate (base) | Miss rate (new) | Escapes (base) | Escapes (new) "
        "| Incomplete (base) | Incomplete (new) | search_limit (base) | search_limit (new) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in sorted(set(base["runs"]) | set(new["runs"])):
        b, n = base["runs"].get(arm), new["runs"].get(arm)
        kinds = set()
        for run in (b, n):
            if run is not None:
                kinds |= set(run["by_kind"])
        for kind in ["total", *sorted(kinds)]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        arm,
                        kind,
                        miss(b, kind),
                        miss(n, kind),
                        escapes(b, kind),
                        escapes(n, kind),
                        state(None if b is None else b["document_states"], kind, False),
                        state(None if n is None else n["document_states"], kind, False),
                        state(base_limits.get(arm), kind, True),
                        state(new_limits.get(arm), kind, True),
                    ]
                )
                + " |"
            )
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare two requested-set results.json files.")
    ap.add_argument("--compare", type=Path, required=True, help="base results.json, e.g. 0.10")
    ap.add_argument("results", type=Path, help="new results.json")
    ap.add_argument("--out", type=Path, help="write the table here instead of stdout")
    args = ap.parse_args()
    try:
        sets = []
        for path in (args.compare, args.results):
            results = json.loads(path.read_text(encoding="utf-8"))
            if results.get("format") != "requested-fields/1":
                raise ValueError("not a requested-field results.json: " + str(path))
            sets.append((path, results, _limits(path, results)))
    except (OSError, ValueError, KeyError) as exc:
        ap.error(str(exc))
    (base_path, base, base_limits), (new_path, new, new_limits) = sets
    lines = [
        "# Requested-field comparison",
        "",
        f"Generated by `bench/report.py --compare {base_path.as_posix()} {new_path.as_posix()}`.",
        "",
        f"Base: `{base_path.as_posix()}`, labels `{base['labels_sha256']}`.",
        f"New: `{new_path.as_posix()}`, labels `{new['labels_sha256']}`.",
        "",
        *render_compare(base, new, base_limits, new_limits),
    ]
    text = "\n".join(lines) + "\n"
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
