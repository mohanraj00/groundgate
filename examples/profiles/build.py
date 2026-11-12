"""Run the two example profiles through the same gate, and measure one route of invoice-v1.

    python build.py

For invoice-v1, the script makes 60 synthetic invoices with known labels (gold.json) and a
simulated extractor that makes known errors. It runs the gate with the profile, counts the
wrong `total` values that the gate admits, and writes the bound of that count into the route
row `total`/`checked` of profile.json, with the gold set digest. Then it writes the receipt of
one invoice and the receipt of the fee table. No model is called, and each output rebuilds
byte for byte.
"""

from __future__ import annotations

import hashlib
import json
import random
from decimal import Decimal
from pathlib import Path
from typing import Any

import groundgate as gg
from groundgate.calibrate.stats import upper_95
from groundgate.profile import check_profile

HERE = Path(__file__).parent
INVOICE = HERE / "invoice-v1"
FEES = HERE / "fee-schedule-v1"
DOCUMENTS = 60
MEASURED = "2026-11-12"  # the date of the measure in the route row
CUSTOMERS = ("Northwind Supply", "Harbor Tools", "Elm Street Bakery", "Gray Fox Labs")
ITEMS = ("Widgets", "Freight", "Bolts", "Service hours", "Brackets", "Cable")


def _write(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _money(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"


def _invoice(rng: random.Random, i: int) -> dict[str, Any]:
    """One synthetic invoice and its labels."""
    number = f"INV-{1000 + i}"
    lines = []
    subtotal = 0
    for name in rng.sample(ITEMS, rng.randint(2, 4)):
        qty, price = rng.randint(1, 40), rng.randint(5, 250) * 100
        lines.append(f"{name:<16}{qty:>4}   {_money(qty * price)}")
        subtotal += qty * price
    tax = subtotal * 8 // 100
    text = "\n".join(
        [
            "INVOICE",
            f"Invoice number: {number}",
            f"Bill to: {rng.choice(CUSTOMERS)}",
            "",
            "Item             Qty   Amount",
            *lines,
            "",
            f"Subtotal: {_money(subtotal)}",
            f"Sales tax (8%): {_money(tax)}",
            f"Total due: {_money(subtotal + tax)}",
            "",
        ]
    )
    labels = {
        "invoice_number": number,
        "subtotal": f"{subtotal / 100:.2f}",
        "tax": f"{tax / 100:.2f}",
        "total": f"{(subtotal + tax) / 100:.2f}",
    }
    return {"id": number, "text": text, "labels": labels}


def _candidates(rng: random.Random, doc: dict[str, Any]) -> list[dict[str, Any]]:
    """A simulated extractor: right on most fields, with known errors on `total`."""
    labels, out = doc["labels"], []
    words = {"subtotal": "Subtotal", "tax": "Sales tax", "total": "Total due"}
    out.append(
        {
            "id": f"{doc['id']}/invoice_number",
            "field": "invoice_number",
            "value": labels["invoice_number"],
            "evidence": [
                {"text": labels["invoice_number"]},
                {"role": "field", "text": "Invoice number"},
            ],
        }
    )
    for name in ("subtotal", "tax", "total"):
        value, cited = labels[name], labels[name]
        if name == "total":
            u = rng.random()
            if u >= 0.94:
                continue  # the extractor misses the field
            if u >= 0.88:
                value = cited = labels["subtotal"]  # the subtotal, given as the total
            elif u >= 0.80:
                value = f"{Decimal(labels['total']) + 9:.2f}"  # a wrong digit
        out.append(
            {
                "id": f"{doc['id']}/{name}",
                "field": name,
                "value": value,
                "unit": "USD",
                "evidence": [
                    {"text": _money(int(Decimal(cited) * 100))},
                    {"role": "field", "text": words[name]},
                ],
            }
        )
    return out


def measure(profile: dict[str, Any]) -> dict[str, Any]:
    """Write gold.json, and return the profile with the measured route and the gold digest."""
    rng = random.Random(639)
    gold = {"documents": [_invoice(rng, i) for i in range(DOCUMENTS)]}
    _write(INVOICE / "gold.json", gold)
    gold_sha256 = "sha256:" + hashlib.sha256((INVOICE / "gold.json").read_bytes()).hexdigest()
    terms = {**profile, "routes": [], "gold_sha256": None}
    admitted = wrong = 0
    for doc in gold["documents"]:
        receipt = gg.admit(doc["text"], None, _candidates(rng, doc), profile=terms)
        for d in receipt.decisions:
            if d.field == "total" and d.outcome == "admitted":
                admitted += 1
                wrong += Decimal(d.value or "NaN") != Decimal(doc["labels"]["total"])
    row = {
        "field": "total",
        "route": "checked",
        "status": "measured",
        "date": MEASURED,
        "documents": DOCUMENTS,
        "bound": f"{upper_95(wrong, admitted):.4f}",
    }
    print(f"invoice-v1 total/checked: {wrong} wrong of {admitted} admitted, bound {row['bound']}")
    return {**profile, "routes": [row], "gold_sha256": gold_sha256}


def receipt(folder: Path, profile: dict[str, Any], doc_id: str) -> None:
    text = (folder / "document.txt").read_text(encoding="utf-8")
    candidates = json.loads((folder / "candidates.json").read_text(encoding="utf-8"))
    out = gg.admit(text, None, candidates, document_id=doc_id, profile=profile).to_dict()
    _write(folder / "receipt.json", out)
    counts = out["summary"]
    print(f"{folder.name}: profile {out['profile']['sha256'][:19]}, {counts}")


def main() -> None:
    invoice = measure(json.loads((INVOICE / "profile.json").read_text(encoding="utf-8")))
    check_profile(invoice)
    _write(INVOICE / "profile.json", invoice)
    first = json.loads((INVOICE / "gold.json").read_text(encoding="utf-8"))["documents"][0]
    (INVOICE / "document.txt").write_text(first["text"], encoding="utf-8")
    _write(INVOICE / "candidates.json", _candidates(random.Random(1), first))
    receipt(INVOICE, invoice, first["id"])
    fees = json.loads((FEES / "profile.json").read_text(encoding="utf-8"))
    receipt(FEES, fees, "fr-2026-07250-appendix-a")


if __name__ == "__main__":
    main()
