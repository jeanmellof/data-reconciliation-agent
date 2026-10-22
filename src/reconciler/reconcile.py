"""Deterministic reconciliation: match records and type discrepancies."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .data import Record


class DiscrepancyType:
    UNMATCHED_LEDGER = "unmatched_in_ledger"      # in ledger, not on statement
    UNMATCHED_STATEMENT = "unmatched_in_statement"  # on statement, not in ledger
    AMOUNT_MISMATCH = "amount_mismatch"           # same ref, different amount
    DATE_MISMATCH = "date_mismatch"               # same ref, different date (within window)
    MATCHED = "matched"


@dataclass
class Discrepancy:
    discrepancy_type: str
    ledger: Record | None
    statement: Record | None
    reference: str
    detail: str = ""
    suggested_action: str = ""  # filled by the agent layer


@dataclass
class ReconciliationResult:
    discrepancies: list[Discrepancy] = field(default_factory=list)
    matched_count: int = 0

    @property
    def total(self) -> int:
        return self.matched_count + len(self.discrepancies)


def _amount_close(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= tolerance


def _norm_ref(raw: str) -> str:
    """Normalize a reference for matching (uppercase, drop separators)."""
    return re.sub(r"[\s\-_/]", "", (raw or "").upper())


def reconcile(
    ledger: list[Record],
    statement: list[Record],
    date_window_days: int = 3,
    amount_tolerance: float = 0.0,
) -> ReconciliationResult:
    """Match ledger records against statement records.

    Matching order:
      1. Exact reference id + amount (within tolerance) + date within window.
      2. Exact reference id but amount differs -> AMOUNT_MISMATCH.
      3. Exact reference id but date differs beyond window -> DATE_MISMATCH.
    Anything left unmatched on either side is UNMATCHED_* .
    """
    result = ReconciliationResult()

    statement_by_ref: dict[str, list[tuple[int, Record]]] = {}
    for i, rec in enumerate(statement):
        statement_by_ref.setdefault(_norm_ref(rec.reference), []).append((i, rec))

    used_statement: set[int] = set()

    for led in ledger:
        key = _norm_ref(led.reference)
        candidates = [
            (i, rec) for (i, rec) in statement_by_ref.get(key, [])
            if i not in used_statement
        ]
        if not candidates:
            result.discrepancies.append(
                Discrepancy(
                    discrepancy_type=DiscrepancyType.UNMATCHED_LEDGER,
                    ledger=led,
                    statement=None,
                    reference=led.reference,
                    detail="present in ledger but missing from statement",
                )
            )
            continue

        # 1. clean match: amount within tolerance and date within window
        clean = [
            (i, rec) for (i, rec) in candidates
            if _amount_close(led.amount, rec.amount, amount_tolerance)
            and abs((rec.date - led.date).days) <= date_window_days
        ]
        if clean:
            i, rec = clean[0]
            used_statement.add(i)
            result.matched_count += 1
            continue

        # 2. amount mismatch (same ref, amounts differ)
        amt = [
            (i, rec) for (i, rec) in candidates
            if not _amount_close(led.amount, rec.amount, amount_tolerance)
        ]
        if amt:
            i, rec = amt[0]
            used_statement.add(i)
            result.discrepancies.append(
                Discrepancy(
                    discrepancy_type=DiscrepancyType.AMOUNT_MISMATCH,
                    ledger=led,
                    statement=rec,
                    reference=led.reference,
                    detail=(
                        f"ledger amount {led.amount:.2f} vs statement "
                        f"{rec.amount:.2f} (diff {led.amount - rec.amount:.2f})"
                    ),
                )
            )
            continue

        # 3. date mismatch (same ref, amount equal but outside window)
        i, rec = candidates[0]
        used_statement.add(i)
        result.discrepancies.append(
            Discrepancy(
                discrepancy_type=DiscrepancyType.DATE_MISMATCH,
                ledger=led,
                statement=rec,
                reference=led.reference,
                detail=(
                    f"dates differ by {(rec.date - led.date).days} days "
                    f"(ledger {led.date.isoformat()} vs statement {rec.date.isoformat()})"
                ),
            )
        )

    # anything on the statement we never used is unmatched
    for i, rec in enumerate(statement):
        if i not in used_statement:
            result.discrepancies.append(
                Discrepancy(
                    discrepancy_type=DiscrepancyType.UNMATCHED_STATEMENT,
                    ledger=None,
                    statement=rec,
                    reference=rec.reference,
                    detail="present on statement but missing from ledger",
                )
            )

    return result
