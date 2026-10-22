"""Render a reconciliation report from a result + agent proposals."""
from __future__ import annotations

from collections import Counter

from .agent import BaseAgent
from .reconcile import Discrepancy, ReconciliationResult


def _fmt(rec) -> str:
    if rec is None:
        return "-"
    return f"{rec.reference} | {rec.date.isoformat()} | {rec.amount:>10.2f} | {rec.description}"


def build_report(result: ReconciliationResult, agent: BaseAgent) -> str:
    """Produce a plain-text reconciliation report with per-discrepancy actions."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("RECONCILIATION REPORT")
    lines.append("=" * 72)
    lines.append(f"Total records considered : {result.total}")
    lines.append(f"Matched                  : {result.matched_count}")
    lines.append(f"Discrepancies            : {len(result.discrepancies)}")

    by_type = Counter(d.discrepancy_type for d in result.discrepancies)
    if by_type:
        lines.append("")
        lines.append("Discrepancies by type:")
        for dtype, count in sorted(by_type.items()):
            lines.append(f"  - {dtype}: {count}")

    if result.discrepancies:
        lines.append("")
        lines.append("-" * 72)
        lines.append("PROPOSED ACTIONS")
        lines.append("-" * 72)
        for i, d in enumerate(sorted(result.discrepancies, key=lambda x: x.reference), 1):
            p = agent.propose(d)
            lines.append(f"\n[{i}] {d.reference}  ({d.discrepancy_type})")
            lines.append(f"    Ledger    : {_fmt(d.ledger)}")
            lines.append(f"    Statement : {_fmt(d.statement)}")
            lines.append(f"    Detail    : {d.detail}")
            lines.append(f"    Category  : {p.category}  (confidence {p.confidence:.2f})")
            lines.append(f"    Action    : {p.action}")
            lines.append(f"    Owner     : {p.owner}   Priority: {p.priority}")

    lines.append("")
    lines.append("=" * 72)
    lines.append("End of report")
    return "\n".join(lines) + "\n"


def build_markdown(result: ReconciliationResult, agent: BaseAgent) -> str:
    """A compact Markdown version for quick viewing in a PR/README."""
    md = ["# Reconciliation Report", ""]
    md.append(f"- Total records: **{result.total}**")
    md.append(f"- Matched: **{result.matched_count}**")
    md.append(f"- Discrepancies: **{len(result.discrepancies)}**")
    md.append("")

    if result.discrepancies:
        md.append("| # | Reference | Type | Category | Priority | Proposed action |")
        md.append("|---|-----------|------|----------|----------|-----------------|")
        for i, d in enumerate(sorted(result.discrepancies, key=lambda x: x.reference), 1):
            p = agent.propose(d)
            md.append(
                f"| {i} | `{d.reference}` | {d.discrepancy_type} | {p.category} | "
                f"{p.priority} | {p.action} |"
            )
        md.append("")
    return "\n".join(md)
