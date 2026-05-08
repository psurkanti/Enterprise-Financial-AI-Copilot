from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

import pandas as pd

from backend.services.ai_provider import AIProviderRouter
from backend.services.chat_memory import ConversationState
from backend.services.query_utils import extract_amount, is_followup_question, is_region_catalog_question


class QuestionPlanner:
    def __init__(self, ai: AIProviderRouter) -> None:
        self._ai = ai

    def build_plan(self, frame: pd.DataFrame, question: str, memory: ConversationState) -> Dict[str, Any]:
        fallback = self.fallback_plan(frame, question, memory)
        llm_plan = self.llm_plan(frame, question, memory)
        if llm_plan:
            merged = dict(fallback)
            merged.update({k: v for k, v in llm_plan.items() if v is not None and v != [] and v != {}})
            if isinstance(llm_plan.get("filters"), dict):
                lf = {k: v for k, v in llm_plan["filters"].items() if v not in (None, [], {})}
                if lf:
                    base_f = dict(merged.get("filters") or {})
                    base_f.update(lf)
                    merged["filters"] = base_f
            return self.sanitize_plan(merged)
        return self.sanitize_plan(fallback)

    def llm_plan(self, frame: pd.DataFrame, question: str, memory: ConversationState) -> Dict[str, Any]:
        if not self._ai.available():
            return {}
        sample = frame.head(12).fillna("").to_dict(orient="records")
        history = [{"user": t.user_question, "copilot": t.copilot_summary} for t in memory.turns[-6:]]
        prompt = f"""
You are Enterprise Financial AI Copilot query planner.
Return ONLY strict JSON with keys:
{{
  "use_previous_subset": boolean,
  "analysis": "records|count_customers|count_regions|avg_amount|overview|collection_priority|top_customers|aging_bucket_risk|region_ar_summary",
  "filters": {{
    "status": [string],
    "region": [string],
    "customer_name": [string],
    "risk_min": number|null,
    "risk_max": number|null,
    "amount_min": number|null,
    "amount_max": number|null,
    "overdue_only": boolean|null
  }},
  "sort_by": string|null,
  "sort_desc": boolean,
  "limit": number|null,
  "intent": string
}}

Columns: {list(frame.columns)}
Recent conversation: {json.dumps(history)}
User question: {question}
Sample rows: {json.dumps(sample, default=str)}
"""
        parsed = self._ai.complete_json(
            system_prompt="Output valid JSON only.",
            user_prompt=prompt,
            temperature=0.1,
            max_tokens=550,
        )
        return parsed if isinstance(parsed, dict) else {}

    def fallback_plan(self, frame: pd.DataFrame, question: str, memory: ConversationState) -> Dict[str, Any]:
        q_raw = question.strip()
        q = q_raw.lower()
        regions = sorted(frame["region"].dropna().astype(str).unique().tolist()) if "region" in frame.columns else []
        statuses = sorted(frame["status"].dropna().astype(str).unique().tolist()) if "status" in frame.columns else []
        customers = sorted(frame["customer_name"].dropna().astype(str).unique().tolist()) if "customer_name" in frame.columns else []

        use_prev = any(
            tok in q
            for tok in ("those", "them", "these", "that list", "from that", "above result", "previous", "same ones")
        ) or (is_followup_question(question) and bool(memory.last_records))
        amount = extract_amount(q)
        region_guess = [r for r in regions if str(r).lower().strip() in q]
        status_guess = [s for s in statuses if s.lower() in q]
        filters: Dict[str, Any] = {
            "status": status_guess,
            "region": region_guess,
            "customer_name": [c for c in customers if c.lower() in q and len(c) > 2],
            "risk_min": 70 if "high risk" in q else None,
            "risk_max": None,
            "amount_min": amount if amount and any(t in q for t in ["above", "over", "more than", "greater than"]) else None,
            "amount_max": amount if amount and any(t in q for t in ["below", "under", "less than"]) else None,
            "overdue_only": True if "overdue" in q else None,
        }

        limit: Optional[int] = None
        m = re.search(r"\btop\s+(\d+)\b", q)
        if m:
            limit = int(m.group(1))
        analysis = "records"
        if re.search(r"\b(overview|summary|summarize|overall picture|portfolio)\b", q):
            analysis = "overview"
        elif re.search(r"\b(how many|count|number of)\s+customers?\b", q):
            analysis = "count_customers"
        elif is_region_catalog_question(q):
            analysis = "count_regions"
        elif re.search(r"\b(average|avg|mean)\b", q) and re.search(r"\b(invoice|amount|balance|due)\b", q):
            analysis = "avg_amount"
        elif re.search(r"\b(collection|priority|contact first|who to call)\b", q):
            analysis = "collection_priority"
        elif re.search(r"\b(aging|ageing)\b", q) and re.search(r"\b(risk|highest|worst)\b", q):
            analysis = "aging_bucket_risk"
        elif (re.search(r"\b(by|per)\s+region\b", q) and re.search(r"\b(risk|ar|breakdown|summarize|balance|outstanding)\b", q)) or (
            re.search(r"\bwhich\s+region\b", q) and re.search(r"\b(highest|most|largest|top)\b", q)
        ):
            analysis = "region_ar_summary"
        elif re.search(r"\btop\s+\d*\s*customers?\b", q) or re.search(r"\b(show|list)\s+(all\s+)?customers?\b", q):
            analysis = "top_customers"
            if limit is None and ("all customers" in q or "every customer" in q):
                limit = 500

        return {
            "use_previous_subset": use_prev and len(memory.last_records) > 0,
            "analysis": analysis,
            "filters": filters,
            "group_by": None,
            "sort_by": "invoice_amount_due",
            "sort_desc": True,
            "limit": limit,
            "intent": "dynamic-fallback",
        }

    @staticmethod
    def sanitize_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
        allowed_analysis = {
            "records",
            "count_customers",
            "count_regions",
            "avg_amount",
            "overview",
            "collection_priority",
            "top_customers",
            "aging_bucket_risk",
            "region_ar_summary",
        }
        out = dict(plan)
        analysis = out.get("analysis") or "records"
        if analysis not in allowed_analysis:
            analysis = "records"
        out["analysis"] = analysis
        return out
