"""Render bench/results.json as bench/RESULTS.md and two SVG charts. Called by bench/score.py."""

from __future__ import annotations

from html import escape
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
