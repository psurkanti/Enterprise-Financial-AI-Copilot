from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import pandas as pd


def _currency(value: float) -> str:
    return f"${value:,.2f}"


def _records(frame: pd.DataFrame, limit: int = 100) -> List[Dict[str, Any]]:
    selected = frame.head(limit).copy()
    selected["due_date"] = selected["due_date"].astype(str)
    return selected.to_dict(orient="records")


def summarize(frame: pd.DataFrame) -> Dict[str, Any]:
    today = pd.Timestamp.utcnow().date()
    overdue = frame[(frame["due_date"].notna()) & (frame["due_date"].dt.date < today) & (frame["status"].str.lower() != "paid")]
    high_risk = frame[frame["risk_score"] >= 70]
    by_region = (
        frame.groupby("region", as_index=False)["invoice_amount_due"]
        .sum()
        .sort_values("invoice_amount_due", ascending=False)
    )
    top_region = by_region.iloc[0]["region"] if not by_region.empty else "N/A"
    return {
        "total_due": round(float(frame["invoice_amount_due"].sum()), 2),
        "total_invoices": int(len(frame)),
        "overdue_invoices": int(len(overdue)),
        "high_risk_customers": int(high_risk["customer_name"].nunique()),
        "top_region_by_balance": top_region,
    }


def invoice_list(
    frame: pd.DataFrame,
    limit: int = 100,
    min_amount: Optional[float] = None,
    overdue_only: bool = False,
    region: Optional[str] = None,
) -> List[Dict[str, Any]]:
    filtered = frame
    if min_amount is not None:
        filtered = filtered[filtered["invoice_amount_due"] >= min_amount]
    if overdue_only:
        today = pd.Timestamp.utcnow().date()
        filtered = filtered[
            (filtered["due_date"].notna())
            & (filtered["due_date"].dt.date < today)
            & (filtered["status"].str.lower() != "paid")
        ]
    if region:
        filtered = filtered[filtered["region"].str.lower() == region.lower()]
    return _records(filtered, limit=limit)


def _extract_amount(question: str) -> Optional[float]:
    match = re.search(r"(\$?\s*\d+(?:,\d{3})*(?:\.\d+)?)\s*([kKmM]?)", question)
    if not match:
        return None
    raw = match.group(1).replace("$", "").replace(",", "").strip()
    value = float(raw)
    suffix = match.group(2).lower()
    if suffix == "k":
        value *= 1000
    if suffix == "m":
        value *= 1_000_000
    return value


def ask(frame: pd.DataFrame, question: str) -> Dict[str, Any]:
    q = question.lower().strip()
    today = pd.Timestamp.utcnow().date()

    default_action = "Review matching invoices and prioritize outreach based on risk and aging."
    matching = frame.copy()
    summary = ""
    findings: List[str] = []
    recommended_action = default_action

    overdue = frame[(frame["due_date"].notna()) & (frame["due_date"].dt.date < today) & (frame["status"].str.lower() != "paid")]

    if "total due" in q or ("total" in q and "outstanding" in q):
        total = float(frame["invoice_amount_due"].sum())
        summary = f"Total outstanding amount is {_currency(total)} across {len(frame)} invoices."
        matching = frame.sort_values("invoice_amount_due", ascending=False)
        findings = [
            f"{len(overdue)} invoices are overdue.",
            f"{int(frame[frame['risk_score'] >= 70]['customer_name'].nunique())} customers are high risk.",
        ]
        recommended_action = "Start collection with overdue and high-risk invoices first."
    elif "overdue" in q:
        amount = float(overdue["invoice_amount_due"].sum())
        summary = f"There are {len(overdue)} overdue invoices totaling {_currency(amount)}."
        matching = overdue.sort_values("invoice_amount_due", ascending=False)
        region_overdue = (
            overdue.groupby("region", as_index=False)["invoice_amount_due"]
            .sum()
            .sort_values("invoice_amount_due", ascending=False)
        )
        if not region_overdue.empty:
            findings.append(
                f"{region_overdue.iloc[0]['region']} has the highest overdue balance."
            )
        findings.append(f"{len(overdue[overdue['risk_score'] >= 70])} overdue invoices are high risk.")
        recommended_action = "Prioritize follow-ups for oldest overdue and highest-risk accounts."
    elif "high risk" in q:
        matching = frame[frame["risk_score"] >= 70].sort_values("invoice_amount_due", ascending=False)
        summary = f"There are {len(matching)} high-risk invoices in the current dataset."
        findings = [
            f"{matching['customer_name'].nunique()} customers are marked high risk.",
            f"High-risk exposure totals {_currency(float(matching['invoice_amount_due'].sum()))}.",
        ]
        recommended_action = "Escalate top high-risk customers to priority collection queue."
    elif "region" in q and ("highest" in q or "top" in q):
        by_region = (
            frame.groupby("region", as_index=False)["invoice_amount_due"]
            .sum()
            .sort_values("invoice_amount_due", ascending=False)
        )
        if by_region.empty:
            summary = "No regional data found."
            matching = frame.head(0)
        else:
            top = by_region.iloc[0]
            summary = f"{top['region']} has the highest outstanding balance at {_currency(float(top['invoice_amount_due']))}."
            findings = [f"Total regions analyzed: {len(by_region)}."]
            matching = frame[frame["region"] == top["region"]].sort_values("invoice_amount_due", ascending=False)
        recommended_action = "Focus regional strategy and collection staffing on the highest exposure region."
    elif "collection priority" in q:
        matching = frame.copy()
        matching["priority_score"] = matching["risk_score"] * 0.7 + matching["invoice_amount_due"] / 1000 * 0.3
        matching = matching.sort_values("priority_score", ascending=False)
        summary = "Collection priority customers identified using risk and amount due."
        findings = [
            f"Top customer: {matching.iloc[0]['customer_name'] if not matching.empty else 'N/A'}.",
            f"Priority list includes {len(matching)} invoices.",
        ]
        recommended_action = "Start collection calls from the top 10 priority-score customers."
    elif "customers list" in q or "customer list" in q or "customers" in q:
        grouped = (
            frame.groupby("customer_name", as_index=False)["invoice_amount_due"]
            .sum()
            .sort_values("invoice_amount_due", ascending=False)
        )
        matching = grouped.rename(columns={"invoice_amount_due": "total_amount_due"})
        summary = f"Customer list generated with {len(grouped)} unique customers."
        findings = [
            f"Top customer by due amount: {grouped.iloc[0]['customer_name'] if not grouped.empty else 'N/A'}.",
            f"Total due across all customers is {_currency(float(frame['invoice_amount_due'].sum()))}.",
        ]
        recommended_action = "Use this customer list for segmentation by risk and overdue status."
    elif "above" in q and "$" in q or "above" in q and "k" in q:
        amount = _extract_amount(q)
        if amount is not None:
            matching = frame[frame["invoice_amount_due"] >= amount].sort_values("invoice_amount_due", ascending=False)
            summary = f"There are {len(matching)} invoices above {_currency(amount)}."
            findings = [
                f"Combined due amount for matching invoices is {_currency(float(matching['invoice_amount_due'].sum()))}.",
                f"{matching['customer_name'].nunique()} customers match this threshold.",
            ]
            recommended_action = "Assign senior collectors to high-value invoices first."
    else:
        summary = "Question analyzed using available invoice data."
        findings = [
            f"Dataset has {len(frame)} invoices.",
            f"Current total due is {_currency(float(frame['invoice_amount_due'].sum()))}.",
            "Try asking with terms like overdue, high risk, region, or amount threshold for sharper results.",
        ]
        recommended_action = "Refine your question with a metric, region, status, or amount condition."

    if not summary:
        summary = "No direct match found, but relevant records were returned."
    if not findings:
        findings = ["Relevant records have been identified from current invoice data."]

    return {
        "summary": summary,
        "key_findings": findings,
        "recommended_action": recommended_action,
        "matching_records": _records(matching, limit=100),
    }
