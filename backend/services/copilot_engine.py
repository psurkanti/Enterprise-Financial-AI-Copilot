from __future__ import annotations

import json
import os
import re
from datetime import timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from backend.services.ai_provider import AIProviderRouter
from backend.services.chat_memory import ConversationState
from backend.services.query_executor import QueryExecutor
from backend.services.query_intents import QueryIntentRouter
from backend.services.query_planner import QuestionPlanner
from backend.services.query_utils import (
    aggregation_by_region_question as util_aggregation_by_region_question,
    currency as util_currency,
    extract_amount as util_extract_amount,
    extract_invoice_token as util_extract_invoice_token,
    extract_recent_days_window as util_extract_recent_days_window,
    format_due_date as util_format_due_date,
    has_financial_invoice_context as util_has_financial_invoice_context,
    high_risk_mask as util_high_risk_mask,
    is_count_question as util_is_count_question,
    is_region_catalog_question as util_is_region_catalog_question,
    to_records as util_to_records,
)
from backend.services.response_formatter import ResponseFormatter


def _currency(v: float) -> str:
    return util_currency(v)


def _to_records(frame: pd.DataFrame, limit: int = 100) -> List[Dict[str, Any]]:
    return util_to_records(frame, limit=limit)


def _extract_amount(text: str) -> Optional[float]:
    return util_extract_amount(text)


CLARIFY_MESSAGE = (
    "I can only answer questions related to uploaded financial datasets. "
    "Please ask about columns like customer_name, invoice_id, due_date, payment_date, status, region, or risk_score."
)

_FINANCE_TOPIC_PATTERN = re.compile(
    r"invoice|invoices|customer|customers|region|regions|due|amount|balance|overdue|"
    r"risk|aging|ageing|\bar\b|outstanding|total|average|avg|mean|count|how many|which|what|show|list|"
    r"display|table|paid|pending|status|summarize|overview|portfolio|collection|"
    r"collector|segment|category|payment method|priority|invoice date|payment date|"
    r"high risk|per region|by region",
    re.I,
)

_INV_TOKEN_PATTERN = re.compile(r"\b(INV-?\d+)\b", re.I)


def _question_covers_finance(q: str) -> bool:
    q = q.strip()
    if len(q) < 2:
        return False
    return bool(_FINANCE_TOPIC_PATTERN.search(q))


def _is_followup_question(question: str) -> bool:
    q = question.strip().lower()
    if len(q) <= 3:
        return True
    return bool(
        re.search(
            r"^(and|also|what about|how about|about those|about them|for those|for them|same|same for|now|then)\b",
            q,
        )
    )


def _user_wants_tabular_invoice_list(q: str) -> bool:
    """True when the user explicitly (or clearly) wants invoice/record rows, not just a number or fact."""
    q = q.lower()
    if any(
        phrase in q
        for phrase in (
            "show ",
            "show me",
            "list ",
            "display",
            "give me the invoices",
            "give me invoices",
            "as a table",
            "in a table",
            "pull up",
            "every invoice",
            "all invoices",
            "all the invoices",
            "top ",
        )
    ):
        return True
    if "records" in q and any(w in q for w in ("show", "give", "list", "send", "display")):
        return True
    if re.search(r"\btop\s+\d+\b", q) and any(w in q for w in ("invoice", "customer", "show", "list")):
        return True
    if any(w in q for w in ("which invoices", "what invoices", "which invoice", "what invoice")):
        if "how many" not in q and "count" not in q:
            return True
    return False


def _is_count_question(q: str) -> bool:
    return util_is_count_question(q)


def _aggregation_by_region_question(q: str) -> bool:
    return util_aggregation_by_region_question(q)


def _extract_invoice_token(question: str) -> Optional[str]:
    return util_extract_invoice_token(question)


def _high_risk_mask(series: pd.Series) -> pd.Series:
    return util_high_risk_mask(series)


def _sanitize_answer_text(text: str) -> str:
    """Strip accidental marketing / templated phrasing (LLM or legacy paths)."""
    raw = str(text or "").strip()
    if not raw:
        return raw
    sentences = re.split(r"(?<=[.!?])\s+", raw)
    noise = re.compile(
        r"(?i)(enterprise financial ai copilot|our copilot|\bcopilot\b\s+found|found\s+\d+\s+matching|matching\s+records|total amount due)",
    )
    kept = [s.strip() for s in sentences if s.strip() and not noise.search(s)]
    t = " ".join(kept) if kept else raw
    t = re.sub(
        r"(?is)^(Enterprise Financial AI Copilot|Our copilot)\s+(found|identified|located)\s+.{0,400}?(\.(?:\s|$))",
        "",
        t,
    )
    t = re.sub(r"(?is)^(Enterprise Financial AI Copilot|Our copilot)\s+", "", t)
    t = re.sub(r"(?is)\bfound\s+\d+\s+matching records\b[^.]*\.?", "", t)
    t = re.sub(r"(?i)\s+", " ", t)
    return t.strip()


def _customers_mentioned(frame: pd.DataFrame, question: str) -> List[str]:
    if "customer_name" not in frame.columns:
        return []
    qlow = question.lower()
    names = sorted(
        {str(x).strip() for x in frame["customer_name"].dropna().astype(str).unique() if str(x).strip()},
        key=lambda x: -len(x),
    )
    out: List[str] = []
    for name in names:
        if len(name) > 2 and name.lower() in qlow:
            out.append(name)
    return out


def _has_financial_invoice_context(q: str) -> bool:
    return util_has_financial_invoice_context(q)


_DAY_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
}


def _extract_recent_days_window(q: str) -> Optional[int]:
    return util_extract_recent_days_window(q)


def _format_due_date(val: Any) -> str:
    return util_format_due_date(val)


def _is_region_catalog_question(q: str) -> bool:
    return util_is_region_catalog_question(q)


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


def _relevant_columns_for_question(frame: pd.DataFrame, question: str) -> List[str]:
    q = question.lower()
    preferred: List[str] = []
    if "customer" in q and "customer_name" in frame.columns:
        preferred.append("customer_name")
    if ("invoice" in q or "id" in q) and "invoice_id" in frame.columns:
        preferred.append("invoice_id")
    if any(t in q for t in ("amount", "balance", "due", "outstanding")) and "invoice_amount_due" in frame.columns:
        preferred.append("invoice_amount_due")
    if "amount paid" in q and "amount_paid" in frame.columns:
        preferred.append("amount_paid")
    if "balance remaining" in q and "balance_remaining" in frame.columns:
        preferred.append("balance_remaining")
    if "invoice date" in q and "invoice_date" in frame.columns:
        preferred.append("invoice_date")
    if any(t in q for t in ("due date", "due this week", "when due", "this week")) and "due_date" in frame.columns:
        preferred.append("due_date")
    if "payment date" in q and "payment_date" in frame.columns:
        preferred.append("payment_date")
    if "status" in q and "status" in frame.columns:
        preferred.append("status")
    if "region" in q and "region" in frame.columns:
        preferred.append("region")
    if "risk" in q and "risk_score" in frame.columns:
        preferred.append("risk_score")
    if "aging" in q and "aging_bucket" in frame.columns:
        preferred.append("aging_bucket")
    if "payment method" in q and "payment_method" in frame.columns:
        preferred.append("payment_method")
    if "priority" in q and "collection_priority" in frame.columns:
        preferred.append("collection_priority")
    if "segment" in q and "customer_segment" in frame.columns:
        preferred.append("customer_segment")
    if ("collector" in q or "assigned" in q) and "assigned_collector" in frame.columns:
        preferred.append("assigned_collector")
    if "category" in q and "invoice_category" in frame.columns:
        preferred.append("invoice_category")
    base_defaults = [c for c in ("customer_name", "invoice_id", "invoice_amount_due", "due_date", "status") if c in frame.columns]
    cols = preferred or base_defaults
    seen = set()
    out: List[str] = []
    for c in cols:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _regions_from_question(q: str, regions: List[str]) -> List[str]:
    q_low = q.lower()
    matched: List[str] = []
    for r in regions:
        if not r:
            continue
        rl = str(r).lower().strip()
        if len(rl) >= 3 and rl in q_low:
            matched.append(str(r))
    for key in ("europe", "asia", "america", "africa"):
        if key in q_low:
            for r in regions:
                rs = str(r).lower()
                if key in rs and r not in matched:
                    matched.append(str(r))
    seen = set()
    out = []
    for r in matched:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


class CopilotEngine:
    def __init__(self) -> None:
        self._ai = AIProviderRouter()
        self._planner = QuestionPlanner(self._ai)
        self._executor = QueryExecutor()
        self._formatter = ResponseFormatter(self._ai)
        self._intents = QueryIntentRouter(
            payload_direct_fn=self._payload_direct,
            count_regions_fn=self._count_regions,
            answer_paid_amount_fn=self._answer_paid_amount_question,
            to_records_fn=_to_records,
            relevant_columns_fn=_relevant_columns_for_question,
            extract_invoice_token_fn=_extract_invoice_token,
            customers_mentioned_fn=_customers_mentioned,
            high_risk_mask_fn=_high_risk_mask,
            is_region_catalog_question_fn=_is_region_catalog_question,
            aggregation_by_region_question_fn=_aggregation_by_region_question,
            currency_fn=_currency,
            format_due_date_fn=_format_due_date,
            user_wants_tabular_fn=_user_wants_tabular_invoice_list,
        )

    @staticmethod
    def _payload_direct(summary: str, intent: str, response_type: str) -> Dict[str, Any]:
        return {
            "summary": summary,
            "key_findings": [],
            "recommended_action": "",
            "matching_records": [],
            "intent": intent,
            "response_type": response_type,
            "response_style": "direct",
        }

    def _answer_paid_amount_question(
        self, frame: pd.DataFrame, question: str
    ) -> Optional[Dict[str, Any]]:
        qlow = question.lower().strip()
        if "status" not in frame.columns or "invoice_amount_due" not in frame.columns:
            return None
        if not re.search(r"\b(paid|payment|pay)\b", qlow):
            return None
        if not (
            any(
                x in qlow
                for x in (
                    "how much",
                    "how many",
                    "total",
                    "amount",
                    "value",
                    "sum",
                    "invoice",
                    "invoices",
                    "till",
                    "so far",
                    "to date",
                    "have we",
                    "we have",
                )
            )
            or re.search(r"\b(received|collected)\b", qlow)
        ):
            return None

        paid_mask = frame["status"].astype(str).str.lower().str.strip() == "paid"
        paid = frame[paid_mask]
        days = _extract_recent_days_window(qlow)
        today = pd.Timestamp.utcnow().date()
        # Prefer the actual paid amount column when available.
        # Some CSVs only have invoice_amount_due; in that case we fall back.
        value_col = "amount_paid" if "amount_paid" in paid.columns else "invoice_amount_due"

        if "payment_date" in paid.columns:
            pdt = pd.to_datetime(paid["payment_date"], errors="coerce").dt.date
            if days is not None:
                start = today - timedelta(days=days - 1)
                win = paid[(pdt.notna()) & (pdt >= start) & (pdt <= today)]
                total = float(pd.to_numeric(win[value_col], errors="coerce").fillna(0).sum())
                n = len(win)
                return self._payload_direct(
                    f"Paid total in the last {days} days (payment_date from {start} through {today}): "
                    f"{_currency(total)} ({n} invoice(s)).",
                    "paid_amount_window",
                    "AGGREGATION",
                )
            total_all = float(pd.to_numeric(paid[value_col], errors="coerce").fillna(0).sum())
            n_all = len(paid)
            return self._payload_direct(
                f"Invoices marked Paid total {_currency(total_all)} ({n_all} invoice(s)).",
                "total_paid",
                "AGGREGATION",
            )

        total_all = float(pd.to_numeric(paid[value_col], errors="coerce").fillna(0).sum())
        n_all = len(paid)
        if days is not None:
            return self._payload_direct(
                f"This dataset has no payment_date column, so paid totals cannot be filtered to the last {days} days. "
                f"All rows marked Paid add up to {_currency(total_all)} ({n_all} invoice(s)). "
                f"Add payment_date (or paid_date) to answer paid-in-period questions accurately.",
                "paid_amount_no_payment_date",
                "AGGREGATION",
            )
        return self._payload_direct(
            f"Invoices marked Paid total {_currency(total_all)} ({n_all} invoice(s)).",
            "total_paid",
            "AGGREGATION",
        )

    def _try_intent_based_answer(
        self, frame: pd.DataFrame, question: str, memory: ConversationState
    ) -> Optional[Dict[str, Any]]:
        return self._intents.route(frame, question, memory)

    def _llm_polish_answer(self, question: str, draft: str, row_count: int) -> str:
        if not self._ai.available() or not (draft or "").strip():
            return ""
        try:
            text = self._ai.complete_text(
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
            return text if text else ""
        except Exception:
            return ""

    def _finalize_response(self, result: Dict[str, Any], question: str) -> Dict[str, Any]:
        out = dict(result)
        qlow = question.lower().strip()
        intent = str(out.get("intent") or "")
        style = out.get("response_style")
        if not style:
            if intent in ("records", "collection_priority", "top_customers", "aggregation_region", "list_high_risk_customers") and (
                out.get("matching_records") or []
            ):
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

        recs = list(out.get("matching_records") or [])
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
        polished = (
            "" if skip_polish else self._llm_polish_answer(question, str(out.get("summary", "")), len(recs))
        )
        if polished:
            out["summary"] = polished

        out["summary"] = _sanitize_answer_text(out.get("summary", ""))

        if not out.get("response_type"):
            out["response_type"] = "SUMMARY"

        out["response_mode"] = "structured" if style in ("analytical", "records") else "concise"
        return out

    def _direct_records_summary(self, question: str, df: pd.DataFrame) -> str:
        q = question.lower().strip()
        if df.empty:
            if any(w in q for w in ("how many", "count", "number of")):
                return "None — no matching invoices."
            return "No matching invoices."

        n = len(df)
        amt = (
            pd.to_numeric(df["invoice_amount_due"], errors="coerce").fillna(0)
            if "invoice_amount_due" in df.columns
            else pd.Series([0.0] * n)
        )
        total_due = float(amt.sum())

        if any(w in q for w in ("how many", "number of", "count")):
            if "customer" in q and "invoice" not in q and "row" not in q:
                nu = int(df["customer_name"].nunique()) if "customer_name" in df.columns else 0
                return f"{nu} customers ({n} invoices)."
            if "region" in q:
                nu = int(df["region"].nunique()) if "region" in df.columns else 0
                return f"{nu} regions ({n} invoices)."
            return f"{n} invoices, {_currency(total_due)} total due."

        if any(w in q for w in ("total", "sum", "combined", "add up")) and any(
            w in q for w in ("due", "balance", "outstanding", "amount", "ar", "owe", "owed")
        ):
            return f"{_currency(total_due)} total due ({n} invoices)."

        if any(w in q for w in ("average", "avg", "mean")):
            return f"{_currency(float(amt.mean()))} average ({n} invoices)."

        if "customer" in q and any(
            w in q for w in ("who", "which", "list", "names", "show everyone", "give me")
        ):
            if "customer_name" not in df.columns:
                return f"{n} invoices."
            names = sorted({str(x).strip() for x in df["customer_name"].dropna().astype(str).unique().tolist()})
            if not names:
                return f"{n} invoices."
            if len(names) <= 25:
                return ", ".join(names)
            return ", ".join(names[:20]) + f" (+{len(names) - 20} more)."

        if any(w in q for w in ("largest", "biggest", "max ", "highest invoice")):
            if "customer_name" in df.columns and len(amt):
                idx = int(amt.idxmax())
                cust = str(df.iloc[idx]["customer_name"])
                return f"{cust}, {_currency(float(amt.max()))}."

        return f"{n} invoices, {_currency(total_due)} total due."

    def _llm_plan(self, frame: pd.DataFrame, question: str, memory: ConversationState) -> Dict[str, Any]:
        if not self._ai.available():
            return {}

        sample = frame.head(12).fillna("").to_dict(orient="records")
        history = [
            {"user": turn.user_question, "copilot": turn.copilot_summary}
            for turn in memory.turns[-6:]
        ]
        previous_record_count = len(memory.last_records or [])
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
  "group_by": string|null,
  "sort_by": string|null,
  "sort_desc": boolean,
  "limit": number|null,
  "intent": string
}}

analysis rules:
- "overview" for high-level portfolio / summarize dataset / AR risk overview questions (use full dataframe, not previous subset unless user refers to prior results).
- "count_customers" for how many unique customers.
- "count_regions" for how many geographic regions and/or listing regions only (no invoice rows).
- "avg_amount" for average invoice or mean balance.
- "collection_priority" for who collections should call first (rank by risk and exposure).
- "top_customers" for top N customers by balance.
- "aging_bucket_risk" for which aging band has highest typical risk.
- "region_ar_summary" for summarize metrics grouped by region.
- "records" for listing filtered invoice rows (default).

If question references "those", "them", "previous", set use_previous_subset=true.
Use only known columns. No extra keys.

Columns: {list(frame.columns)}
Recent conversation: {json.dumps(history)}
Previous record count: {previous_record_count}
User question: {question}
Sample rows: {json.dumps(sample, default=str)}
"""
        try:
            parsed = self._ai.complete_json(
                system_prompt="Output valid JSON only.",
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=550,
            )
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {}

    def _fallback_plan(self, frame: pd.DataFrame, question: str, memory: ConversationState) -> Dict[str, Any]:
        q_raw = question.strip()
        q = q_raw.lower()
        regions = sorted(frame["region"].dropna().astype(str).unique().tolist()) if "region" in frame.columns else []
        statuses = sorted(frame["status"].dropna().astype(str).unique().tolist()) if "status" in frame.columns else []
        customers = sorted(frame["customer_name"].dropna().astype(str).unique().tolist()) if "customer_name" in frame.columns else []

        use_prev = any(
            tok in q
            for tok in (
                "those",
                "them",
                "these",
                "that list",
                "from that",
                "above result",
                "previous",
                "same ones",
                "same customers",
            )
        ) or (_is_followup_question(question) and bool(memory.last_records))
        amount = _extract_amount(q)

        region_guess = [r for r in _regions_from_question(q, regions)]
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
        if "top 5" in q or "five " in q:
            limit = 5
        elif "top 10" in q or "ten " in q:
            limit = 10

        analysis = "records"
        if re.search(r"\b(overview|summary|summarize|overall picture|portfolio)\b", q):
            analysis = "overview"
        elif re.search(r"\b(how many|count|number of)\s+customers?\b", q):
            analysis = "count_customers"
        elif _is_region_catalog_question(q):
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
        elif (re.search(r"\btop\s+\d*\s*customers?\b", q) is not None) or re.search(
            r"\b(show|list)\s+(all\s+)?customers?\b",
            q,
        ):
            analysis = "top_customers"
            if limit is None and ("all customers" in q or "every customer" in q):
                limit = 500

        sort_by = "invoice_amount_due"
        if analysis == "collection_priority":
            sort_by = "invoice_amount_due"

        return {
            "use_previous_subset": use_prev and len(memory.last_records) > 0,
            "analysis": analysis,
            "filters": filters,
            "group_by": None,
            "sort_by": sort_by,
            "sort_desc": True,
            "limit": limit,
            "intent": "dynamic-fallback",
        }

    def _apply_filters(
        self, working: pd.DataFrame, filters: Dict[str, Any]
    ) -> pd.DataFrame:
        def _in(col: str, values: List[str]) -> None:
            nonlocal working
            if col in working.columns and values:
                lower_values = {v.lower() for v in values}
                working = working[working[col].astype(str).str.lower().isin(lower_values)]

        _in("status", filters.get("status") or [])
        _in("region", filters.get("region") or [])
        _in("customer_name", filters.get("customer_name") or [])

        if "risk_score" in working.columns:
            if filters.get("risk_min") is not None:
                working = working[pd.to_numeric(working["risk_score"], errors="coerce") >= float(filters["risk_min"])]
            if filters.get("risk_max") is not None:
                working = working[pd.to_numeric(working["risk_score"], errors="coerce") <= float(filters["risk_max"])]

        if "invoice_amount_due" in working.columns:
            if filters.get("amount_min") is not None:
                working = working[
                    pd.to_numeric(working["invoice_amount_due"], errors="coerce") >= float(filters["amount_min"])
                ]
            if filters.get("amount_max") is not None:
                working = working[
                    pd.to_numeric(working["invoice_amount_due"], errors="coerce") <= float(filters["amount_max"])
                ]

        if filters.get("overdue_only") and {"due_date", "status"}.issubset(working.columns):
            today = pd.Timestamp.utcnow().date()
            working = working[
                working["due_date"].notna()
                & (pd.to_datetime(working["due_date"], errors="coerce").dt.date < today)
                & (working["status"].astype(str).str.lower() != "paid")
            ]

        return working

    def _narrow_frame(self, frame: pd.DataFrame, plan: Dict[str, Any], memory: ConversationState) -> pd.DataFrame:
        if plan.get("use_previous_subset") and memory.last_records:
            try:
                working = pd.DataFrame(memory.last_records)
                if "invoice_amount_due" in working.columns:
                    working["invoice_amount_due"] = pd.to_numeric(working["invoice_amount_due"], errors="coerce").fillna(0.0)
                if "risk_score" in working.columns:
                    working["risk_score"] = pd.to_numeric(working["risk_score"], errors="coerce").fillna(0.0)
                if "due_date" in working.columns:
                    working["due_date"] = pd.to_datetime(working["due_date"], errors="coerce")
            except Exception:
                working = frame.copy()
        else:
            working = frame.copy()

        filters = plan.get("filters") or {}
        return self._apply_filters(working, filters)

    def _apply_sort_limit(self, working: pd.DataFrame, plan: Dict[str, Any]) -> pd.DataFrame:
        sort_by = plan.get("sort_by")
        if sort_by and sort_by in working.columns:
            working = working.sort_values(sort_by, ascending=not bool(plan.get("sort_desc", True)))
        limit = plan.get("limit")
        if isinstance(limit, int) and limit > 0:
            working = working.head(limit)
        return working

    def _today(self) -> Any:
        return pd.Timestamp.utcnow().date()

    def _build_from_records(
        self, filtered: pd.DataFrame, plan: Dict[str, Any], frame: pd.DataFrame, question: str
    ) -> Dict[str, Any]:
        qlow = question.lower().strip()
        if _is_region_catalog_question(qlow):
            return self._count_regions(filtered, plan, question)
        sorted_limited = self._apply_sort_limit(filtered, plan)
        if any(t in qlow for t in ("trend", "over time", "month over month", "weekly")):
            date_col = "payment_date" if "payment_date" in sorted_limited.columns else ("invoice_date" if "invoice_date" in sorted_limited.columns else None)
            if date_col and "invoice_amount_due" in sorted_limited.columns:
                work = sorted_limited.copy()
                work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
                work = work[work[date_col].notna()]
                if not work.empty:
                    trend = (
                        work.assign(period=work[date_col].dt.to_period("M").astype(str))
                        .groupby("period", as_index=False)["invoice_amount_due"]
                        .sum()
                        .rename(columns={"invoice_amount_due": "total_amount"})
                        .sort_values("period")
                    )
                    summary = f"Trend shows {len(trend)} periods. Latest period amount is {_currency(float(trend.iloc[-1]['total_amount']))}."
                    want_table = _user_wants_tabular_invoice_list(qlow)
                    return {
                        "summary": summary,
                        "key_findings": [],
                        "recommended_action": "",
                        "matching_records": _to_records(trend, limit=100) if want_table else [],
                        "intent": "trend",
                        "response_type": "TREND",
                        "response_style": "records" if want_table else "direct",
                        "chart_data": {
                            "kind": "line",
                            "title": "Trend Over Time",
                            "labels": [str(x) for x in trend["period"].tolist()],
                            "values": [float(x) for x in trend["total_amount"].tolist()],
                        },
                    }
        summary = self._direct_records_summary(question, sorted_limited)
        want_table = _user_wants_tabular_invoice_list(qlow)
        if want_table:
            cols = _relevant_columns_for_question(sorted_limited, question)
            slim = sorted_limited[cols] if cols else sorted_limited
            recs: List[Dict[str, Any]] = _to_records(slim, limit=100)
        else:
            recs = []
        return {
            "summary": summary,
            "key_findings": [],
            "recommended_action": "",
            "matching_records": recs,
            "intent": "records",
            "response_type": "FILTERED_RECORDS" if want_table else "COUNT",
            "response_style": "records" if want_table else "direct",
        }

    def _overview(self, frame: pd.DataFrame) -> Dict[str, Any]:
        today = self._today()
        overdue = frame[
            (frame["due_date"].notna())
            & (frame["due_date"].dt.date < today)
            & (frame["status"].astype(str).str.lower() != "paid")
        ]
        total_due = float(frame["invoice_amount_due"].sum())
        summary = (
            f"{_currency(total_due)} open across {len(frame)} invoices, "
            f"{int(frame['customer_name'].nunique())} customers; {len(overdue)} overdue."
        )
        risk_num = (
            pd.to_numeric(frame["risk_score"], errors="coerce").fillna(0)
            if "risk_score" in frame.columns
            else pd.Series([0] * len(frame))
        )
        high_risk_cust = (
            int(frame.loc[risk_num >= 70, "customer_name"].nunique()) if "customer_name" in frame.columns else 0
        )
        findings = [
            f"{len(overdue)} invoices are overdue.",
            f"{high_risk_cust} customers are high risk (risk_score ≥ 70).",
        ]
        return {
            "summary": summary,
            "key_findings": findings,
            "recommended_action": "Review overdue balances and prioritize high-risk accounts for collections outreach.",
            "matching_records": [],
            "intent": "overview",
            "response_type": "SUMMARY",
            "response_style": "analytical",
        }

    def _count_customers(self, filtered: pd.DataFrame, plan: Dict[str, Any], question: str) -> Dict[str, Any]:
        if "customer_name" not in filtered.columns:
            return self._build_from_records(filtered, plan, filtered, question)

        n = int(filtered["customer_name"].nunique())
        qlow = question.lower().strip()
        if _is_count_question(qlow) and not _user_wants_tabular_invoice_list(qlow):
            return {
                "summary": f"{n} customers",
                "key_findings": [],
                "recommended_action": "",
                "matching_records": [],
                "intent": "count_customers",
                "response_type": "COUNT",
                "response_style": "direct",
            }

        per_customer = (
            filtered.groupby("customer_name", as_index=False)["invoice_amount_due"]
            .sum()
            .sort_values("invoice_amount_due", ascending=False)
            if "invoice_amount_due" in filtered.columns
            else filtered.drop_duplicates("customer_name")
        )
        summary = f"{n} customers."
        show = self._apply_sort_limit(
            per_customer.rename(columns={"invoice_amount_due": "total_amount_due"}),
            {"sort_by": "total_amount_due", "sort_desc": True, "limit": plan.get("limit") or 100},
        )
        return {
            "summary": summary,
            "key_findings": [],
            "recommended_action": "",
            "matching_records": _to_records(show, limit=100),
            "intent": "count_customers",
            "response_type": "FILTERED_RECORDS",
            "response_style": "records",
        }

    def _count_regions(self, filtered: pd.DataFrame, plan: Dict[str, Any], question: str = "") -> Dict[str, Any]:
        qlow = question.lower().strip()
        if "region" not in filtered.columns:
            return {
                "summary": "No region column is available in this dataset.",
                "key_findings": [],
                "recommended_action": "",
                "matching_records": [],
                "intent": "count_regions",
                "response_type": "UNIQUE_VALUES",
                "response_style": "direct",
            }
        names = sorted(
            {str(r).strip() for r in filtered["region"].dropna().astype(str).tolist() if str(r).strip()},
            key=str.lower,
        )
        n = len(names)
        if n == 0:
            summary = "There are no regions in the current data scope."
        elif n == 1:
            summary = f"There is 1 unique region: {names[0]}."
        else:
            joined = ", ".join(names)
            if ("what are the region" in qlow or "what regions" in qlow) and "how many" not in qlow:
                summary = f"The dataset contains these regions: {joined}."
            else:
                summary = f"There are {n} unique regions: {joined}."
        return {
            "summary": summary,
            "key_findings": [],
            "recommended_action": "",
            "matching_records": [],
            "intent": "count_regions",
            "response_type": "UNIQUE_VALUES",
            "response_style": "direct",
        }

    def _avg_amount(self, filtered: pd.DataFrame, plan: Dict[str, Any], question: str) -> Dict[str, Any]:
        if "invoice_amount_due" not in filtered.columns or filtered.empty:
            return self._build_from_records(filtered, plan, filtered, question)
        s = pd.to_numeric(filtered["invoice_amount_due"], errors="coerce")
        avg_v = float(s.mean())
        summary = f"{_currency(avg_v)} average across {len(filtered)} invoices."
        return {
            "summary": summary,
            "key_findings": [],
            "recommended_action": "",
            "matching_records": [],
            "intent": "avg_amount",
            "response_type": "AGGREGATION",
            "response_style": "direct",
        }

    def _collection_priority(self, filtered: pd.DataFrame, plan: Dict[str, Any], question: str) -> Dict[str, Any]:
        if filtered.empty or "invoice_amount_due" not in filtered.columns:
            return self._build_from_records(filtered, plan, filtered, question)
        work = filtered.copy()
        amt = pd.to_numeric(work["invoice_amount_due"], errors="coerce").fillna(0.0)
        risk = pd.to_numeric(work["risk_score"], errors="coerce").fillna(0.0) if "risk_score" in work.columns else 0.0
        denom = float(amt.max()) or 1.0
        work = work.assign(
            _priority_score=risk * 0.65 + (amt / denom) * 100 * 0.35,
        ).sort_values("_priority_score", ascending=False)
        limit = plan.get("limit") or 15
        show = work.head(limit)
        if show.empty:
            summary = "No rows to rank."
        else:
            top_amt = float(pd.to_numeric(show.iloc[0]["invoice_amount_due"], errors="coerce") or 0.0)
            summary = f"First in queue: {show.iloc[0]['customer_name']} ({_currency(top_amt)}); {len(show)} accounts listed."
        want_table = _user_wants_tabular_invoice_list(question.lower())
        cols = _relevant_columns_for_question(show, question)
        show_out = show[cols] if (want_table and cols) else show
        out = show.drop(columns=["_priority_score"], errors="ignore")
        return {
            "summary": summary,
            "key_findings": [],
            "recommended_action": "",
            "matching_records": _to_records(show_out.drop(columns=["_priority_score"], errors="ignore"), limit=100)
            if want_table
            else [],
            "intent": "collection_priority",
            "response_type": "FILTERED_RECORDS" if want_table else "SUMMARY",
            "response_style": "records" if want_table else "direct",
        }

    def _top_customers(self, filtered: pd.DataFrame, plan: Dict[str, Any], question: str) -> Dict[str, Any]:
        if "customer_name" not in filtered.columns:
            return self._build_from_records(filtered, plan, filtered, question)
        if "invoice_amount_due" not in filtered.columns:
            u = filtered.drop_duplicates("customer_name").head(plan.get("limit") or 100)
            return {
                "summary": f"{len(u)} customers.",
                "key_findings": [],
                "recommended_action": "",
                "matching_records": _to_records(u, limit=100),
                "intent": "top_customers",
                "response_type": "FILTERED_RECORDS",
                "response_style": "records",
            }
        grouped = (
            filtered.groupby("customer_name", as_index=False)["invoice_amount_due"]
            .sum()
            .rename(columns={"invoice_amount_due": "total_balance_due"})
            .sort_values("total_balance_due", ascending=False)
        )
        lim = plan.get("limit") or 10
        show = grouped.head(lim)
        if show.empty:
            summary = "No customers in scope."
        else:
            parts = [
                f"{r['customer_name']} {_currency(float(r['total_balance_due']))}"
                for _, r in show.iterrows()
            ]
            summary = "; ".join(parts[:5]) if len(parts) > 5 else "; ".join(parts)
        want_table = _user_wants_tabular_invoice_list(question.lower())
        return {
            "summary": summary,
            "key_findings": [],
            "recommended_action": "",
            "matching_records": _to_records(show, limit=100) if want_table else [],
            "intent": "top_customers",
            "response_type": "FILTERED_RECORDS" if want_table else "AGGREGATION",
            "response_style": "records" if want_table else "direct",
            "chart_data": {
                "kind": "bar",
                "title": "Top Customers by Balance",
                "labels": [str(x) for x in show["customer_name"].tolist()],
                "values": [float(x) for x in show["total_balance_due"].tolist()],
            },
        }

    def _aging_bucket_risk(self, filtered: pd.DataFrame, plan: Dict[str, Any], question: str) -> Dict[str, Any]:
        if "aging_bucket" not in filtered.columns or filtered.empty:
            return self._build_from_records(filtered, plan, filtered, question)
        g = (
            filtered.groupby("aging_bucket", as_index=False)["risk_score"]
            .mean()
            .rename(columns={"risk_score": "avg_risk_score"})
            .sort_values("avg_risk_score", ascending=False)
        )
        if g.empty:
            return self._build_from_records(filtered, plan, filtered, question)
        top = g.iloc[0]
        summary = (
            f"Highest average risk: '{top['aging_bucket']}' (score {float(top['avg_risk_score']):.1f})."
        )
        want_table = _user_wants_tabular_invoice_list(question.lower())
        return {
            "summary": summary,
            "key_findings": [],
            "recommended_action": "",
            "matching_records": _to_records(g, limit=100) if want_table else [],
            "intent": "aging_bucket_risk",
            "response_type": "AGGREGATION",
            "response_style": "records" if want_table else "direct",
            "chart_data": {
                "kind": "bar",
                "title": "Average Risk by Aging Bucket",
                "labels": [str(x) for x in g["aging_bucket"].tolist()],
                "values": [float(x) for x in g["avg_risk_score"].tolist()],
            },
        }

    def _region_ar_summary(self, filtered: pd.DataFrame, plan: Dict[str, Any], question: str) -> Dict[str, Any]:
        if "region" not in filtered.columns or filtered.empty:
            return self._build_from_records(filtered, plan, filtered, question)
        today = self._today()
        rows = []
        for reg, chunk in filtered.groupby("region"):
            if {"due_date", "status"}.issubset(chunk.columns):
                om = (
                    chunk["due_date"].notna()
                    & (pd.to_datetime(chunk["due_date"], errors="coerce").dt.date < today)
                    & (chunk["status"].astype(str).str.lower() != "paid")
                )
                overdue_amt = float(pd.to_numeric(chunk.loc[om, "invoice_amount_due"], errors="coerce").fillna(0).sum())
            else:
                overdue_amt = 0.0
            rows.append(
                {
                    "region": reg,
                    "total_ar": float(pd.to_numeric(chunk["invoice_amount_due"], errors="coerce").fillna(0).sum()),
                    "avg_risk": float(pd.to_numeric(chunk["risk_score"], errors="coerce").fillna(0).mean()) if "risk_score" in chunk.columns else 0.0,
                    "overdue_balance": overdue_amt,
                    "invoice_count": int(len(chunk)),
                }
            )
        g = pd.DataFrame(rows).sort_values("total_ar", ascending=False)
        summary = "No regional rows."
        if not g.empty:
            top = g.iloc[0]
            summary = (
                f"Largest AR is {top['region']} at {_currency(float(top['total_ar']))} "
                f"({int(top['invoice_count'])} invoices, avg risk {float(top['avg_risk']):.1f})."
            )
        want_table = _user_wants_tabular_invoice_list(question.lower())
        return {
            "summary": summary,
            "key_findings": [],
            "recommended_action": "",
            "matching_records": _to_records(g, limit=100) if want_table else [],
            "intent": "region_ar_summary",
            "response_type": "AGGREGATION",
            "response_style": "records" if want_table else "direct",
            "chart_data": {
                "kind": "bar",
                "title": "AR by Region",
                "labels": [str(x) for x in g["region"].tolist()],
                "values": [float(x) for x in g["total_ar"].tolist()],
            },
        }

    def _sanitize_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
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
        analysis = plan.get("analysis") or "records"
        if analysis not in allowed_analysis:
            analysis = "records"
        plan = dict(plan)
        plan["analysis"] = analysis
        return plan

    def answer(self, frame: pd.DataFrame, question: str, memory: ConversationState) -> Dict[str, Any]:
        qlow = question.strip().lower()
        if not _question_covers_finance(qlow):
            return self._formatter.finalize_response(
                {
                    "summary": CLARIFY_MESSAGE,
                    "key_findings": [],
                    "recommended_action": "",
                    "matching_records": [],
                    "intent": "clarify",
                    "response_type": "SUMMARY",
                    "response_style": "direct",
                },
                question,
            )

        routed = self._try_intent_based_answer(frame, question, memory)
        if routed is not None:
            return self._formatter.finalize_response(routed, question)

        plan = self._planner.build_plan(frame, question, memory)

        if _is_region_catalog_question(qlow):
            plan["analysis"] = "count_regions"

        analysis = plan["analysis"]
        if analysis == "overview" and not plan.get("use_previous_subset"):
            raw = self._overview(frame)
        else:
            filtered = self._executor.narrow_frame(frame, plan, memory)
            if analysis == "overview":
                raw = self._overview(filtered)
            elif analysis == "count_customers":
                raw = self._count_customers(filtered, plan, question)
            elif analysis == "count_regions":
                raw = self._count_regions(filtered, plan, question)
            elif analysis == "avg_amount":
                raw = self._avg_amount(filtered, plan, question)
            elif analysis == "collection_priority":
                raw = self._collection_priority(filtered, plan, question)
            elif analysis == "top_customers":
                raw = self._top_customers(filtered, plan, question)
            elif analysis == "aging_bucket_risk":
                raw = self._aging_bucket_risk(filtered, plan, question)
            elif analysis == "region_ar_summary":
                raw = self._region_ar_summary(filtered, plan, question)
            else:
                raw = self._build_from_records(filtered, plan, frame, question)

        return self._formatter.finalize_response(raw, question)

