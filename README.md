# Data Reconciliation Agent

An LLM-powered agent that reconciles two financial data sources (e.g., an
accounting ledger vs. a bank statement), detects discrepancies, and proposes
human-review actions for each mismatch — using **function calling** so the model
can query structured helpers before deciding.

This is a small, honest, end-to-end demo of building production-style agents:
data loading, deterministic matching, an LLM reasoning layer with tools, and
report generation. It runs fully offline (rule-based fallback) and can use a real
LLM when an OpenAI-compatible API key is present.

## Why this exists

I built this to show how I approach agent work: not just "call an LLM", but
designing the data contract, the deterministic core, and the tool surface so the
model reasons over trustworthy primitives. It mirrors a real workflow I
implemented at TD Bank — automating a daily reconciliation flow that cut manual
effort by ~45%.

## How it works

```
ledger.csv ─┐
            ├─► load & normalize ─► reconcile (deterministic match) ─► discrepancies
statement ──┘                                                              │
                                                                           ▼
                                              agent (function calling) ─► proposed actions
                                                                           │
                                                                           ▼
                                                          reconciliation report (.txt / .md)
```

1. **Load & normalize** — parse CSVs, coerce amounts/dates, standardize fields.
2. **Reconcile** — match records by reference id, then by amount + date window.
   Everything that doesn't match cleanly is a discrepancy with a typed category.
3. **Agent** — for each discrepancy, an LLM agent with tools
   (`lookup_reference`, `classify_mismatch`, `suggest_action`) reasons over the
   record and proposes an action. Without a key, a deterministic rule agent
   produces the same structured output.
4. **Report** — a summary plus a per-discrepancy action list.

## Quick start

```bash
python3 -m pip install -r requirements.txt   # optional: pulls `openai` for real LLM
python3 run.py --ledger data/ledger.csv --statement data/statement.csv --out reports/
```

The demo data in `data/` is synthetic and self-contained, so you can run it
immediately with no API key.

### Using a real LLM

Set an OpenAI-compatible key and base URL:

```bash
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://your-endpoint/v1   # optional
python3 run.py --ledger data/ledger.csv --statement data/statement.csv --out reports/ --llm
```

Without `--llm` (or without a key), it uses the deterministic rule-based agent.

## Project layout

```
data-reconciliation-agent/
├── README.md
├── requirements.txt
├── run.py                      # CLI entry point
├── src/reconciler/
│   ├── __init__.py
│   ├── data.py                 # load & normalize CSVs
│   ├── reconcile.py            # deterministic matching + discrepancy typing
│   ├── agent.py                # LLM agent (function calling) + rule fallback
│   └── report.py               # report rendering
├── data/
│   ├── ledger.csv              # synthetic source-of-truth records
│   └── statement.csv           # synthetic bank-statement records
└── tests/
    └── test_reconcile.py       # pytest suite
```

## Tests

```bash
python3 -m pytest -q
```

## Design notes

- **Deterministic core, probabilistic layer.** Matching is rule-based and
  reproducible; the LLM only reasons over already-extracted discrepancies. This
  keeps results auditable and cheap to test.
- **Function calling as a contract.** The agent's tools are a small, explicit
  surface. The model must call them rather than hallucinate facts.
- **No keys required to demo.** The rule fallback lets anyone run the whole
  pipeline offline; the LLM path is opt-in.
