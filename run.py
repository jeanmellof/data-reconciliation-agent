#!/usr/bin/env python3
"""CLI entry point for the Data Reconciliation Agent.

Example:
    python3 run.py --ledger data/ledger.csv --statement data/statement.csv \
        --out reports/ [--llm] [--model gpt-4o-mini]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from src.reconciler import load_records, reconcile
from src.reconciler.agent import build_agent
from src.reconciler.report import build_markdown, build_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile two financial data sources with an agent.")
    parser.add_argument("--ledger", required=True, help="Path to the ledger CSV (source of truth).")
    parser.add_argument("--statement", required=True, help="Path to the statement CSV.")
    parser.add_argument("--out", default="reports", help="Output directory for the report.")
    parser.add_argument("--date-window-days", type=int, default=3, help="Date tolerance for matching.")
    parser.add_argument("--amount-tolerance", type=float, default=0.0, help="Amount tolerance for matching.")
    parser.add_argument("--llm", action="store_true", help="Use the real LLM agent (requires OPENAI_API_KEY).")
    parser.add_argument("--model", default="gpt-4o-mini", help="Model name when using --llm.")
    args = parser.parse_args()

    ledger = load_records(args.ledger, "ledger")
    statement = load_records(args.statement, "statement")
    print(f"Loaded {len(ledger)} ledger records and {len(statement)} statement records.")

    result = reconcile(
        ledger, statement,
        date_window_days=args.date_window_days,
        amount_tolerance=args.amount_tolerance,
    )
    print(f"Matched {result.matched_count}/{result.total} records; "
          f"{len(result.discrepancies)} discrepancies.")

    from src.reconciler.agent import LLMAgent, RuleAgent
    agent = build_agent(use_llm=args.llm, model=args.model)
    engine = "LLM (function calling)" if isinstance(agent, LLMAgent) else "rule-based (offline)"
    print(f"Agent engine: {engine}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.ledger).stem

    report_path = out_dir / f"{stem}_reconciliation.txt"
    report_path.write_text(build_report(result, agent), encoding="utf-8")
    print(f"Wrote report -> {report_path}")

    md_path = out_dir / f"{stem}_reconciliation.md"
    md_path.write_text(build_markdown(result, agent), encoding="utf-8")
    print(f"Wrote markdown -> {md_path}")


if __name__ == "__main__":
    main()
