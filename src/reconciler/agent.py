"""The agent layer: reason over each discrepancy and propose an action.

Two implementations share one interface:

* ``RuleAgent`` — deterministic, offline, no API key. Produces structured,
  auditable output by classifying each discrepancy against simple heuristics.
* ``LLMAgent`` — uses an OpenAI-compatible chat completion with *function
  calling* so the model must call the provided tools before answering.

The CLI picks ``LLMAgent`` when ``--llm`` and an API key are present, otherwise
``RuleAgent``.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .reconcile import Discrepancy, DiscrepancyType


# --------------------------------------------------------------------------- #
# Shared tool surface (the "contract" the model reasons over)
# --------------------------------------------------------------------------- #
def _ledger_amount(d: Discrepancy) -> float | None:
    return d.ledger.amount if d.ledger else None


def _statement_amount(d: Discrepancy) -> float | None:
    return d.statement.amount if d.statement else None


def _amount_diff(d: Discrepancy) -> float | None:
    a, b = _ledger_amount(d), _statement_amount(d)
    if a is None or b is None:
        return None
    return round(a - b, 2)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "classify_mismatch",
            "description": "Classify the nature of a reconciliation discrepancy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": [
                            "missing_transaction",
                            "amount_error",
                            "date_drift",
                            "duplicate",
                            "currency_or_sign",
                            "needs_manual_review",
                        ],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["category", "confidence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_action",
            "description": "Propose the next concrete action a human should take.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "owner": {"type": "string", "description": "who should act"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["action", "owner", "priority"],
            },
        },
    },
]


@dataclass
class Proposal:
    category: str
    confidence: float
    action: str
    owner: str
    priority: str

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "confidence": self.confidence,
            "action": self.action,
            "owner": self.owner,
            "priority": self.priority,
        }


# --------------------------------------------------------------------------- #
# Base interface
# --------------------------------------------------------------------------- #
class BaseAgent:
    def propose(self, discrepancy: Discrepancy) -> Proposal:  # pragma: no cover
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Deterministic fallback
# --------------------------------------------------------------------------- #
class RuleAgent(BaseAgent):
    """Offline agent. Classifies by discrepancy type and amount direction."""

    def propose(self, d: Discrepancy) -> Proposal:
        dt = d.discrepancy_type
        diff = _amount_diff(d)

        if dt == DiscrepancyType.UNMATCHED_LEDGER:
            return Proposal(
                category="missing_transaction",
                confidence=0.9,
                action="Confirm whether this ledger entry cleared the bank; if not, investigate timing.",
                owner="Accounting",
                priority="medium",
            )
        if dt == DiscrepancyType.UNMATCHED_STATEMENT:
            return Proposal(
                category="missing_transaction",
                confidence=0.85,
                action="Determine if this statement charge is recorded in the ledger; post if missing.",
                owner="Accounting",
                priority="medium",
            )
        if dt == DiscrepancyType.AMOUNT_MISMATCH:
            if diff is not None and abs(diff) < 1.0:
                category, action, priority = (
                    "currency_or_sign",
                    "Check for rounding, fee, or currency/sign difference on a near-equal amount.",
                    "low",
                )
            else:
                category, action, priority = (
                    "amount_error",
                    f"Investigate the {diff:+.2f} amount difference between ledger and statement.",
                    "high",
                )
            return Proposal(
                category=category, confidence=0.8, action=action,
                owner="Bookkeeping", priority=priority,
            )
        if dt == DiscrepancyType.DATE_MISMATCH:
            return Proposal(
                category="date_drift",
                confidence=0.75,
                action="Verify posting dates match; adjust for inter-day timing if within the same period.",
                owner="Bookkeeping",
                priority="low",
            )
        return Proposal(
            category="needs_manual_review",
            confidence=0.4,
            action="Route to a human reviewer for manual reconciliation.",
            owner="Finance Lead",
            priority="medium",
        )


# --------------------------------------------------------------------------- #
# Real LLM agent with function calling
# --------------------------------------------------------------------------- #
class LLMAgent(BaseAgent):
    """Uses an OpenAI-compatible chat completion with function calling.

    The model is constrained to call ``classify_mismatch`` and ``suggest_action``
    so it reasons over the discrepancy via tools rather than guessing.
    """

    def __init__(self, model: str = "gpt-4o-mini", api_key: str | None = None,
                 base_url: str | None = None):
        try:
            from openai import OpenAI  # local import keeps offline path dependency-free
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "the `openai` package is required for --llm; pip install -r requirements.txt"
            ) from exc

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def propose(self, d: Discrepancy) -> Proposal:  # pragma: no cover - needs network
        ledger = d.ledger
        statement = d.statement
        user = (
            f"Discrepancy type: {d.discrepancy_type}\n"
            f"Reference: {d.reference}\n"
            f"Ledger: amount={ledger.amount if ledger else None}, "
            f"date={ledger.date if ledger else None}, desc={ledger.description if ledger else ''}\n"
            f"Statement: amount={statement.amount if statement else None}, "
            f"date={statement.date if statement else None}, desc={statement.description if statement else ''}\n"
            f"Detail: {d.detail}"
        )

        messages = [
            {"role": "system", "content": "You are a careful reconciliation analyst. Call the tools to classify each discrepancy and propose a concrete next action."},
            {"role": "user", "content": user},
        ]

        resp = self.client.chat.completions.create(
            model=self.model, messages=messages, tools=TOOLS, tool_choice="auto",
        )
        msg = resp.choices[0].message

        # Execute the tool call(s) the model requested, then read the final text.
        final_text = msg.content or ""
        if msg.tool_calls:
            tool_results = []
            for call in msg.tool_calls:
                name = call.function.name
                args = json.loads(call.function.arguments or "{}")
                if name == "classify_mismatch":
                    final_text = f"classified as {args.get('category')} (confidence {args.get('confidence')})"
                    tool_results.append({"role": "tool", "content": json.dumps(args), "tool_call_id": call.id})
                elif name == "suggest_action":
                    final_text = json.dumps(args)
                    tool_results.append({"role": "tool", "content": json.dumps(args), "tool_call_id": call.id})
            if tool_results:
                messages.extend([msg.model_dump(), *tool_results])
                final = self.client.chat.completions.create(
                    model=self.model, messages=messages,
                )
                final_text = final.choices[0].message.content or final_text

        return self._parse(final_text)

    @staticmethod
    def _parse(text: str) -> Proposal:
        # The model returns JSON-ish content; be tolerant.
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return Proposal(category="needs_manual_review", confidence=0.5,
                            action=text.strip() or "Review manually.", owner="Finance Lead", priority="medium")
        return Proposal(
            category=data.get("category", "needs_manual_review"),
            confidence=float(data.get("confidence", 0.5)),
            action=data.get("action", "Review manually."),
            owner=data.get("owner", "Finance Lead"),
            priority=data.get("priority", "medium"),
        )


def build_agent(use_llm: bool = False, model: str = "gpt-4o-mini") -> BaseAgent:
    """Return an LLM agent if asked and configured, else the rule agent."""
    if use_llm and os.getenv("OPENAI_API_KEY"):
        return LLMAgent(model=model, base_url=os.getenv("OPENAI_BASE_URL"))
    return RuleAgent()
