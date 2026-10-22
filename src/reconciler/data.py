"""Data loading and normalization for the reconciliation agent."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


@dataclass
class Record:
    """A single financial record, normalized across both sources."""

    source: str  # "ledger" or "statement"
    reference: str  # normalized reference / transaction id
    date: date
    description: str
    amount: float  # signed; positive = inflow, negative = outflow


_AMOUNT_RE = re.compile(r"\d[\d,]*\.?\d*")


def _parse_amount(raw: str) -> float:
    """Parse a currency string like '1,234.56' or '-$ 99.00' into a float."""
    text = (raw or "").strip()
    negative = False
    if text.startswith("(") and text.endswith(")"):  # accounting negative
        negative = True
        text = text[1:-1]
    # A leading minus (after currency symbols/spaces) also means negative.
    if re.match(r"[ \t$€£¥]*-", text):
        negative = True
    match = _AMOUNT_RE.search(text.replace(",", ""))
    if not match:
        raise ValueError(f"unparseable amount: {raw!r}")
    return -float(match.group(0)) if negative else float(match.group(0))


def _parse_date(raw: str) -> date:
    """Parse YYYY-MM-DD (preferred) or MM/DD/YYYY."""
    text = (raw or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {raw!r}")


def _normalize_reference(raw: str) -> str:
    """Normalize a reference id: uppercase, strip whitespace and separators."""
    return re.sub(r"[\s\-_/]", "", (raw or "").upper())


def load_records(path: str | Path, source: str) -> list[Record]:
    """Load and normalize a CSV of financial records.

    Expected columns (case-insensitive): reference/id, date, description, amount.
    """
    path = Path(path)
    records: list[Record] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        lowered = { (k or "").strip().lower(): k for k in (reader.fieldnames or []) }

        ref_col = lowered.get("reference") or lowered.get("id") or lowered.get("transaction_id")
        date_col = lowered.get("date")
        desc_col = lowered.get("description") or lowered.get("memo") or lowered.get("narration")
        amt_col = lowered.get("amount") or lowered.get("value")

        missing = [c for c in (ref_col, date_col, amt_col) if not c]
        if missing:
            raise ValueError(f"{path}: missing required columns {missing}")

        for line_no, row in enumerate(reader, start=2):
            try:
                records.append(
                    Record(
                        source=source,
                        reference=_normalize_reference(row[ref_col]),
                        date=_parse_date(row[date_col]),
                        description=(row.get(desc_col) or "").strip() if desc_col else "",
                        amount=_parse_amount(row[amt_col]),
                    )
                )
            except ValueError as exc:
                raise ValueError(f"{path} line {line_no}: {exc}") from exc

    return records
