from __future__ import annotations

import os
import re
from typing import Any, Dict

from backend.services.ai_provider import AIProviderRouter


def _wants_recommendation(q: str) -> bool:
    return any(
        phrase in q
        for phrase in (
            "recommend",
            "should we",
            "what should",
            "advice",
            "next step",
            "strategy",
            "priorit",
            "what to do",
            "suggest",
            "best action",
            "collection priority",
            "contact first",
        )
    )


def _sanitize_answer_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return raw
    sentences = re.split(r"(?<=[.!?])\s+", raw)
    noise = re.compile(
        r"(?i)(enterprise financial ai copilot|our copilot|\bcopilot\b\s+found|found\s+\d+\s+matching|matching\s+records|total amount due)",
    )
    kept = [s.strip() for s in sentences if s.strip() and not noise.search(s)]
    t = " ".join(kept) if kept else raw
    t = re.sub(r"(?i)\s+", " ", t)
    return t.strip()


class ResponseFormatter:
    def __init__(self, ai: AIProviderRouter) -> None:
        self._ai = ai

    def polish_answer(self, question: str, draft: str, row_count: int) -> str:
        if not self._ai.available() or not (draft or "").strip():
            return ""
        return self._ai.complete_text(
            system_prompt=(
                "You answer finance questions in plain language only. "
                "Never mention product names, assistants, or dashboards. "
                "Never say 'found X matching records'. Answer directly in one or two short sentences. "
                "Use only facts from the draft; do not invent numbers."
            ),
            user_prompt=f"Question: {question}\nDraft: {draft}\nRows in scope: {row_count}",
            temperature=0.15,
            max_tokens=120,
        )

    def finalize_response(self, result: Dict[str, Any], question: str) -> Dict[str, Any]:
        out = dict(result)
        qlow = question.lower().strip()
        intent = str(out.get("intent") or "")
        style = out.get("response_style")
        if not style:
            if intent in (
                "records",
                "collection_priority",
                "top_customers",
                "aggregation_region",
                "list_high_risk_customers",
            ) and (out.get("matching_records") or []):
                style = "records"
            elif intent == "overview":
                style = "analytical"
            else:
                style = "direct"
            out["response_style"] = style

        recs = list(out.get("matching_records") or [])
        if style == "direct":
            out["matching_records"] = []
            out["key_findings"] = []
            out["recommended_action"] = ""
        elif style == "analytical":
            out["matching_records"] = []
            if not _wants_recommendation(qlow) and intent != "overview":
                out["recommended_action"] = ""
        else:
            if not _wants_recommendation(qlow):
                out["recommended_action"] = ""

        out.setdefault("key_findings", [])
        out.setdefault("recommended_action", "")

        enable_polish = os.getenv("COPILOT_ENABLE_LLM_POLISH", "").strip().lower() in ("1", "true", "yes")
        skip_polish = (
            (not enable_polish)
            or style == "direct"
            or intent.startswith("lookup")
            or intent
            in {
                "count_regions",
                "count_customers",
                "avg_amount",
                "aggregation_region",
                "count_high_risk",
                "list_high_risk_customers",
                "lookup_invoice_ids",
                "clarify",
                "overdue_customer_names",
                "total_paid",
                "paid_amount_window",
                "paid_amount_no_payment_date",
            }
        )
        polished = "" if skip_polish else self.polish_answer(question, str(out.get("summary", "")), len(recs))
        if polished:
            out["summary"] = polished

        out["summary"] = _sanitize_answer_text(out.get("summary", ""))
        if not out.get("response_type"):
            out["response_type"] = "SUMMARY"
        out["response_mode"] = "structured" if style in ("analytical", "records") else "concise"
        return out
