"""Score one admission outcome per sealed request."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from groundgate.calibrate.stats import upper_95
from groundgate.model import Outcome
from groundgate.text import normalize_ws

from .extract import unit_code

Json = dict[str, Any]


@dataclass(frozen=True)
class Answer:
    outcome: Outcome = "rejected"
    value: Any = None
    unit: str | None = None
    invalid: bool = False


def normal(kind: str, value: Any) -> Any:
    if kind == "number":
        return Decimal(value)
    if kind == "passage":
        return normalize_ws(value)
    if kind == "record":
        return [
            {k: None if v is None else normalize_ws(v) for k, v in row.items()} for row in value
        ]
    return value


@dataclass
class Counts:
    slots: int = 0
    with_value: int = 0
    admitted_right: int = 0
    escapes: int = 0
    reviews: int = 0
    missed: int = 0
    invalid: int = 0

    def add(self, answer: Answer, present: bool, right: bool) -> None:
        self.slots += 1
        self.with_value += present
        self.admitted_right += right
        self.escapes += answer.outcome == "admitted" and not right
        self.reviews += answer.outcome == "needs_verification"
        self.missed += present and not right
        self.invalid += answer.invalid

    def result(self) -> Json:
        admitted = self.admitted_right + self.escapes
        return asdict(self) | {
            "admitted": admitted,
            "miss_rate": None if not self.with_value else round(self.missed / self.with_value, 4),
            "admitted_error_upper_95": upper_95(self.escapes, admitted),
        }


def score(slots: list[Json], labels: dict[str, Json], answers: dict[str, Answer]) -> Json:
    if labels.keys() != answers.keys() or labels.keys() != {s["slot"] for s in slots}:
        raise ValueError("slots, labels and admission outcomes differ")
    fields, kinds = {}, {}
    total = Counts()
    for slot in slots:
        key, kind = slot["slot"], slot["kind"]
        label, answer = labels[key], answers[key]
        present = label["status"] == "value"
        admitted = answer.outcome == "admitted"
        right = (
            present
            and admitted
            and normal(kind, answer.value) == normal(kind, label["value"])
            and (kind != "number" or answer.unit == unit_code(label["unit"]))
        )
        for bucket in (
            total,
            fields.setdefault(slot["field"], Counts()),
            kinds.setdefault(kind, Counts()),
        ):
            bucket.add(answer, present, right)
    return {
        "total": total.result(),
        "fields": {k: v.result() for k, v in sorted(fields.items())},
        "kinds": {k: v.result() for k, v in sorted(kinds.items())},
    }


def markdown(results: Json, intro: str | None = None) -> str:
    run = results["run"]
    lines = [
        "# Regulatory held-out results",
        "",
        f"The run covers {len(run['documents'])} held-out parts. "
        + (intro or "This family has its own bound for #686. The bound for #548 is separate."),
        "",
        "The miss rate counts labels with a value that got no admitted right value. "
        "The bound is the one-sided 95% upper bound on the admitted error rate.",
        "",
        "| Group | Slots | With value | Admitted right | Escapes | Reviews | Invalid | "
        "Miss rate | Bound |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    rows = [("Total", results["total"])]
    rows.extend((f"Field: {name}", row) for name, row in results["fields"].items())
    rows.extend((f"Kind: {name}", row) for name, row in results["kinds"].items())
    for name, row in rows:
        miss = row["miss_rate"]
        lines.append(
            f"| {name} | {row['slots']} | {row['with_value']} | {row['admitted_right']} | "
            f"{row['escapes']} | {row['reviews']} | {row['invalid']} | "
            f"{'-' if miss is None else format(miss, '.2%')} | "
            f"{row['admitted_error_upper_95']:.2%} |"
        )
    return "\n".join(lines) + "\n"
