from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from backend.services.chat_memory import ConversationState


class QueryIntentRouter:
    """Dedicated intent routing for direct question handlers."""

    def __init__(
        self,
        *,
        payload_direct_fn: Callable[[str, str, str], Dict[str, Any]],
        count_regions_fn: Callable[[pd.DataFrame, Dict[str, Any], str], Dict[str, Any]],
        answer_paid_amount_fn: Callable[[pd.DataFrame, str], Optional[Dict[str, Any]]],
        to_records_fn: Callable[[pd.DataFrame, int], List[Dict[str, Any]]],
        relevant_columns_fn: Callable[[pd.DataFrame, str], List[str]],
        extract_invoice_token_fn: Callable[[str], Optional[str]],
        customers_mentioned_fn: Callable[[pd.DataFrame, str], List[str]],
        high_risk_mask_fn: Callable[[pd.Series], pd.Series],
        is_region_catalog_question_fn: Callable[[str], bool],
        aggregation_by_region_question_fn: Callable[[str], bool],
        currency_fn: Callable[[float], str],
        format_due_date_fn: Callable[[Any], str],
        user_wants_tabular_fn: Callable[[str], bool],
    ) -> None:
        self._payload_direct = payload_direct_fn
        self._count_regions = count_regions_fn
        self._answer_paid_amount = answer_paid_amount_fn
        self._to_records = to_records_fn
        self._relevant_columns = relevant_columns_fn
        self._extract_invoice_token = extract_invoice_token_fn
        self._customers_mentioned = customers_mentioned_fn
        self._high_risk_mask = high_risk_mask_fn
        self._is_region_catalog_question = is_region_catalog_question_fn
        self._aggregation_by_region_question = aggregation_by_region_question_fn
        self._currency = currency_fn
        self._format_due_date = format_due_date_fn
        self._user_wants_tabular = user_wants_tabular_fn

    def route(
        self, frame: pd.DataFrame, question: str, memory: ConversationState
    ) -> Optional[Dict[str, Any]]:
        del memory  # reserved for future intent-specific follow-up routing
        qlow = question.lower().strip()
        want_table = self._user_wants_tabular(qlow)

        if (
            re.search(r"\bwhich\s+region\b", qlow)
            and re.search(r"\b(highest|most|largest|top)\b", qlow)
            and re.search(r"\b(balance|outstanding|due|ar|amount)\b", qlow)
            and {"region", "invoice_amount_due"}.issubset(frame.columns)
        ):
            g = (
                frame.groupby("region", as_index=False)["invoice_amount_due"]
                .sum()
                .rename(columns={"invoice_amount_due": "total_due"})
                .sort_values("total_due", ascending=False)
            )
            if g.empty:
                return self._payload_direct("No regional balances were found.", "highest_region_balance", "LOOKUP")
            top = g.iloc[0]
            if not want_table:
                return self._payload_direct(
                    f"{top['region']} has the highest outstanding balance at {self._currency(float(top['total_due']))}.",
                    "highest_region_balance",
                    "LOOKUP",
                )
            return {
                "summary": f"{top['region']} has the highest outstanding balance at {self._currency(float(top['total_due']))}.",
                "key_findings": [],
                "recommended_action": "",
                "matching_records": self._to_records(g, limit=100),
                "intent": "highest_region_balance",
                "response_type": "AGGREGATION",
                "response_style": "records",
            }

        if ("due this week" in qlow or "due in this week" in qlow or "this week's due" in qlow) and "due_date" in frame.columns:
            start = pd.Timestamp.utcnow().normalize()
            end = start + pd.Timedelta(days=7)
            due = frame[(frame["due_date"].notna()) & (frame["due_date"] >= start) & (frame["due_date"] < end)]
            due = due.sort_values("due_date", ascending=True)
            total = (
                float(pd.to_numeric(due.get("invoice_amount_due"), errors="coerce").fillna(0).sum())
                if "invoice_amount_due" in due.columns
                else 0.0
            )
            cols = self._relevant_columns(due, question)
            due_show = due[cols] if cols else due
            if not want_table:
                return self._payload_direct(
                    f"{len(due)} invoices are due this week totaling {self._currency(total)}.",
                    "due_this_week",
                    "AGGREGATION",
                )
            return {
                "summary": f"{len(due)} invoices are due this week totaling {self._currency(total)}.",
                "key_findings": [],
                "recommended_action": "",
                "matching_records": self._to_records(due_show, limit=100),
                "intent": "due_this_week",
                "response_type": "FILTERED_RECORDS",
                "response_style": "records",
            }

        if any(x in qlow for x in ("highest risk customer", "customer has highest risk", "which customer has highest risk")):
            if "risk_score" in frame.columns and "customer_name" in frame.columns:
                work = frame.copy()
                work["risk_score"] = pd.to_numeric(work["risk_score"], errors="coerce").fillna(0)
                idx = int(work["risk_score"].idxmax()) if not work.empty else -1
                if idx >= 0:
                    row = work.loc[idx]
                    due_amt = float(pd.to_numeric(row.get("invoice_amount_due"), errors="coerce") or 0.0)
                    return self._payload_direct(
                        f"{row.get('customer_name', 'Unknown')} has the highest risk score ({float(row['risk_score']):.1f}) with invoice exposure {self._currency(due_amt)}.",
                        "highest_risk_customer",
                        "LOOKUP",
                    )

        if "overdue exposure" in qlow:
            if {"due_date", "status", "invoice_amount_due"}.issubset(frame.columns):
                today = pd.Timestamp.utcnow().date()
                overdue = frame[
                    frame["due_date"].notna()
                    & (pd.to_datetime(frame["due_date"], errors="coerce").dt.date < today)
                    & (frame["status"].astype(str).str.lower().str.strip() != "paid")
                ]
                total = float(pd.to_numeric(overdue["invoice_amount_due"], errors="coerce").fillna(0).sum())
                return self._payload_direct(
                    f"Overdue exposure is {self._currency(total)} across {len(overdue)} invoices.",
                    "overdue_exposure",
                    "AGGREGATION",
                )

        if self._is_region_catalog_question(qlow):
            return self._count_regions(frame, {}, question)

        if self._aggregation_by_region_question(qlow):
            if "region" in frame.columns and "invoice_amount_due" in frame.columns:
                g = (
                    frame.groupby("region", as_index=False)["invoice_amount_due"]
                    .sum()
                    .rename(columns={"invoice_amount_due": "total_due"})
                    .sort_values("total_due", ascending=False)
                )
                summary = "Total due by region: " + "; ".join(
                    f"{str(r['region']).strip()} {self._currency(float(r['total_due']))}" for _, r in g.iterrows()
                )
                return {
                    "summary": summary,
                    "key_findings": [],
                    "recommended_action": "",
                    "matching_records": self._to_records(g, limit=100),
                    "intent": "aggregation_region",
                    "response_type": "AGGREGATION",
                    "response_style": "records",
                }

        if "overdue" in qlow and "customer" in qlow and any(
            x in qlow for x in ("name", "names", "list", "who", "which", "give", "show", "tell")
        ):
            if {"due_date", "status"}.issubset(frame.columns) and "customer_name" in frame.columns:
                today = pd.Timestamp.utcnow().date()
                od = frame[
                    frame["due_date"].notna()
                    & (pd.to_datetime(frame["due_date"], errors="coerce").dt.date < today)
                    & (frame["status"].astype(str).str.lower().str.strip() != "paid")
                ]
                if od.empty:
                    return self._payload_direct(
                        "There are no overdue invoices in the current data.",
                        "overdue_customers",
                        "UNIQUE_VALUES",
                    )
                names = sorted(
                    {str(x).strip() for x in od["customer_name"].dropna().astype(str).unique() if str(x).strip()}
                )
                listed = ", ".join(names[:80])
                tail = f" (+{len(names) - 80} more)" if len(names) > 80 else ""
                return self._payload_direct(
                    f"Overdue customers: {listed}{tail}.",
                    "overdue_customer_names",
                    "UNIQUE_VALUES",
                )

        paid_reply = self._answer_paid_amount(frame, question)
        if paid_reply is not None:
            return paid_reply

        inv = self._extract_invoice_token(question)
        if inv and "invoice_id" in frame.columns:
            rows = frame[frame["invoice_id"].astype(str).str.upper().str.strip() == inv]
            if not rows.empty:
                r = rows.iloc[0]
                if any(k in qlow for k in ("due date", "when is", "when does")) or ("due" in qlow and "date" in qlow):
                    dd = self._format_due_date(r.get("due_date"))
                    return self._payload_direct(
                        f"The due date for invoice {inv} is {dd}.",
                        "lookup_due_date",
                        "LOOKUP",
                    )
                if any(k in qlow for k in ("amount", "balance")) and "customer" not in qlow:
                    amt = float(pd.to_numeric(r.get("invoice_amount_due"), errors="coerce") or 0)
                    return self._payload_direct(
                        f"The amount due for invoice {inv} is {self._currency(amt)}.",
                        "lookup_amount",
                        "LOOKUP",
                    )
                if "status" in qlow:
                    st = str(r.get("status", ""))
                    return self._payload_direct(
                        f"The status for invoice {inv} is {st}.",
                        "lookup_status",
                        "LOOKUP",
                    )
                if "customer" in qlow or "who" in qlow:
                    cn = str(r.get("customer_name", ""))
                    return self._payload_direct(
                        f"Invoice {inv} is for customer {cn}.",
                        "lookup_customer",
                        "LOOKUP",
                    )

        if ("invoice id" in qlow or "invoice number" in qlow) and "customer_name" in frame.columns:
            cnames = self._customers_mentioned(frame, question)
            if cnames and "invoice_id" in frame.columns:
                sub = frame[frame["customer_name"].isin(cnames)]
                if not sub.empty:
                    ids = sorted(
                        {str(x).strip() for x in sub["invoice_id"].dropna().astype(str).unique() if str(x).strip()}
                    )
                    if ids:
                        cust = cnames[0]
                        if len(ids) == 1:
                            return self._payload_direct(
                                f"The invoice ID for {cust} is {ids[0]}.",
                                "lookup_invoice_ids",
                                "LOOKUP",
                            )
                        joined = ", ".join(ids[:20])
                        extra = f" (+{len(ids) - 20} more)" if len(ids) > 20 else ""
                        return {
                            "summary": f"Invoice IDs for {cust}: {joined}{extra}.",
                            "key_findings": [],
                            "recommended_action": "",
                            "matching_records": [{"invoice_id": i, "customer_name": cust} for i in ids[:80]],
                            "intent": "lookup_invoice_ids",
                            "response_type": "LOOKUP",
                            "response_style": "records",
                        }

        if "high risk" in qlow or "high-risk" in qlow:
            if "risk_score" not in frame.columns:
                return None
            hr = frame[self._high_risk_mask(frame["risk_score"])]
            if hr.empty:
                return self._payload_direct(
                    "There are no high-risk rows in this dataset (risk_score ≥ 70).",
                    "count_high_risk",
                    "COUNT",
                )
            nu = int(hr["customer_name"].nunique()) if "customer_name" in hr.columns else len(hr)
            if "customer" in qlow and any(tok in qlow for tok in ("how many", "count", "number")):
                return self._payload_direct(
                    f"There are {nu} high-risk customers.",
                    "count_high_risk",
                    "COUNT",
                )
            if any(w in qlow for w in ("which", "who", "what customers", "list", "show", "name")):
                cols = [c for c in ("customer_name", "risk_score", "region") if c in hr.columns]
                slim = hr.drop_duplicates(subset=["customer_name"])[cols].head(200) if "customer_name" in hr.columns else hr[cols].head(200)
                names = sorted({str(x) for x in hr["customer_name"].dropna().astype(str).unique()})
                tail = f" (+{len(names) - 20} more)" if len(names) > 20 else ""
                show_names = ", ".join(names[:20])
                return {
                    "summary": f"High-risk customers (risk_score ≥ 70): {show_names}{tail}.",
                    "key_findings": [],
                    "recommended_action": "",
                    "matching_records": self._to_records(slim, limit=100),
                    "intent": "list_high_risk_customers",
                    "response_type": "FILTERED_RECORDS",
                    "response_style": "records",
                }
        return None
