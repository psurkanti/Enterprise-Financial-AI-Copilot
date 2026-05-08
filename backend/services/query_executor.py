from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from backend.services.chat_memory import ConversationState


class QueryExecutor:
    """Pandas execution layer for filtering/narrowing/sorting."""

    def apply_filters(self, working: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
        def _in(col: str, values: List[str]) -> None:
            nonlocal working
            if col in working.columns and values:
                lower_values = {str(v).lower() for v in values}
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

    def narrow_frame(self, frame: pd.DataFrame, plan: Dict[str, Any], memory: ConversationState) -> pd.DataFrame:
        if plan.get("use_previous_subset") and memory.last_records:
            try:
                working = pd.DataFrame(memory.last_records)
                if "invoice_amount_due" in working.columns:
                    working["invoice_amount_due"] = pd.to_numeric(
                        working["invoice_amount_due"], errors="coerce"
                    ).fillna(0.0)
                if "risk_score" in working.columns:
                    working["risk_score"] = pd.to_numeric(working["risk_score"], errors="coerce").fillna(0.0)
                if "due_date" in working.columns:
                    working["due_date"] = pd.to_datetime(working["due_date"], errors="coerce")
            except Exception:
                working = frame.copy()
        else:
            working = frame.copy()
        filters = plan.get("filters") or {}
        return self.apply_filters(working, filters)

    def apply_sort_limit(self, working: pd.DataFrame, plan: Dict[str, Any]) -> pd.DataFrame:
        sort_by = plan.get("sort_by")
        if sort_by and sort_by in working.columns:
            working = working.sort_values(sort_by, ascending=not bool(plan.get("sort_desc", True)))
        limit = plan.get("limit")
        if isinstance(limit, int) and limit > 0:
            working = working.head(limit)
        return working
