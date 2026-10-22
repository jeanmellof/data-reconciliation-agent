"""Tests for the deterministic reconciliation core and rule agent."""
from __future__ import annotations

from datetime import date

import pytest

from src.reconciler import DiscrepancyType, load_records, reconcile
from src.reconciler.agent import RuleAgent, build_agent
from src.reconciler.data import Record, _parse_amount, _parse_date, _normalize_reference
from src.reconciler.reconcile import reconcile as _reconcile


# --------------------------------------------------------------------------- #
# Unit: normalization helpers
# --------------------------------------------------------------------------- #
def test_parse_amount_variants():
    assert _parse_amount("1,234.56") == 1234.56
    assert _parse_amount("-$ 99.00") == -99.0
    assert _parse_amount("(50.00)") == -50.0  # accounting negative


def test_parse_date_formats():
    assert _parse_date("2026-09-01") == date(2026, 9, 1)
    assert _parse_date("09/01/2026") == date(2026, 9, 1)


def test_normalize_reference():
    assert _normalize_reference("led-0001") == "LED0001"
    assert _normalize_reference(" ref / 0002 ") == "REF0002"


# --------------------------------------------------------------------------- #
# Unit: record model
# --------------------------------------------------------------------------- #
def make_record(source="ledger", ref="A1", day=1, amount=100.0):
    return Record(source=source, reference=ref, date=date(2026, 9, day),
                  description="x", amount=amount)


# --------------------------------------------------------------------------- #
# Integration: reconciliation logic
# --------------------------------------------------------------------------- #
def test_clean_match():
    ledger = [make_record("ledger", "A1", 1, 100.0)]
    statement = [make_record("statement", "A1", 2, 100.0)]  # 1 day apart -> match
    result = _reconcile(ledger, statement, date_window_days=3)
    assert result.matched_count == 1
    assert len(result.discrepancies) == 0


def test_amount_mismatch():
    ledger = [make_record("ledger", "A1", 1, 100.0)]
    statement = [make_record("statement", "A1", 1, 90.0)]
    result = _reconcile(ledger, statement)
    assert result.matched_count == 0
    assert result.discrepancies[0].discrepancy_type == DiscrepancyType.AMOUNT_MISMATCH


def test_unmatched_ledger_and_statement():
    ledger = [make_record("ledger", "A1", 1, 100.0)]
    statement = [make_record("statement", "B1", 1, 50.0)]
    result = _reconcile(ledger, statement)
    types = {d.discrepancy_type for d in result.discrepancies}
    assert DiscrepancyType.UNMATCHED_LEDGER in types
    assert DiscrepancyType.UNMATCHED_STATEMENT in types


def test_date_drift_beyond_window():
    ledger = [make_record("ledger", "A1", 1, 100.0)]
    statement = [make_record("statement", "A1", 10, 100.0)]  # 9 days apart
    result = _reconcile(ledger, statement, date_window_days=3)
    assert result.discrepancies[0].discrepancy_type == DiscrepancyType.DATE_MISMATCH


def test_reference_normalization_matches():
    ledger = [Record("ledger", "LED-0001", date(2026, 9, 1), "x", 100.0)]
    statement = [Record("statement", "led 0001", date(2026, 9, 1), "x", 100.0)]
    result = _reconcile(ledger, statement)
    assert result.matched_count == 1


# --------------------------------------------------------------------------- #
# Agent layer
# --------------------------------------------------------------------------- #
def test_rule_agent_proposes_for_each_type():
    agent = RuleAgent()
    ledger = [make_record("ledger", "A1", 1, 100.0)]
    statement = [make_record("statement", "B1", 1, 50.0)]
    result = _reconcile(ledger, statement)
    for d in result.discrepancies:
        p = agent.propose(d)
        assert p.category
        assert p.action
        assert p.owner
        assert p.priority in {"low", "medium", "high"}


def test_build_agent_defaults_to_rule():
    assert isinstance(build_agent(use_llm=False), RuleAgent)


# --------------------------------------------------------------------------- #
# End-to-end on the shipped sample data
# --------------------------------------------------------------------------- #
def test_sample_data_reconciles():
    import pathlib

    here = pathlib.Path(__file__).resolve().parents[1]
    ledger = load_records(here / "data" / "ledger.csv", "ledger")
    statement = load_records(here / "data" / "statement.csv", "statement")

    assert len(ledger) == 14
    assert len(statement) == 14

    result = reconcile(ledger, statement)
    # 11 clean matches. 4 discrepancies:
    #   - LED-0004 and LED-0011: sign flipped on statement (+189.40 / +3400.00)
    #   - LED-0010: in ledger, missing from statement
    #   - REF-0099: on statement, missing from ledger
    assert result.matched_count == 11
    assert len(result.discrepancies) == 4
    types = {d.discrepancy_type for d in result.discrepancies}
    assert DiscrepancyType.AMOUNT_MISMATCH in types
    assert DiscrepancyType.UNMATCHED_LEDGER in types
    assert DiscrepancyType.UNMATCHED_STATEMENT in types
