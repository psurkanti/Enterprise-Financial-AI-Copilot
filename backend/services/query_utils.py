from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import pandas as pd


def currency(v: float) -> str:
    return f"${v:,.2f}"


def to_records(frame: pd.DataFrame, limit: int = 100) -> List[Dict[str, Any]]:
    selected = frame.head(limit).copy()
    for col in selected.columns:
        if pd.api.types.is_datetime64_any_dtype(selected[col]) or pd.api.types.is_timedelta64_dtype(selected[col]):
            selected[col] = selected[col].astype(str)
    selected = selected.where(pd.notna(selected), None)
    if "due_date" in selected.columns:
        selected["due_date"] = selected["due_date"].astype(str)
    return selected.to_dict(orient="records")


def extract_amount(text: str) -> Optional[float]:
    m = re.search(r"\$?\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*([kKmM]?)", text)
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    suffix = m.group(2).lower()
    if suffix == "k":
        value *= 1000
    elif suffix == "m":
        value *= 1_000_000
    return value


def is_followup_question(question: str) -> bool:
    q = question.strip().lower()
    if len(q) <= 3:
        return True
    return bool(
        re.search(
            r"^(and|also|what about|how about|about those|about them|for those|for them|same|same for|now|then)\b",
            q,
        )
    )


def is_count_question(q: str) -> bool:
    q = q.lower()
    return (
        "how many" in q
        or re.search(r"\bcount\b", q) is not None
        or "number of" in q
        or re.search(r"\btotal\s+number\b", q) is not None
    )


def has_financial_invoice_context(q: str) -> bool:
    ql = q.lower()
    if "invoice" in ql or "invoices" in ql:
        return True
    if any(w in ql for w in ("amount", "balance", "overdue", "risk", "aging", "collect", "outstanding", "unpaid")):
        return True
    if re.search(r"\bpaid\b", ql) or re.search(r"\bpay\b", ql):
        return True
    if re.search(r"\bdue\b", ql) or re.search(r"\bdue date\b", ql):
        return True
    if " average" in ql or " avg" in ql or re.search(r"\bavg\b", ql) or re.search(r"\bmean\b", ql):
        return True
    if "per region" in ql or "by region" in ql:
        return True
    return False


def is_region_catalog_question(q: str) -> bool:
    if "region" not in q and "regions" not in q:
        return False
    if "customer" in q:
        return False
    if "invoice" in q and ("per region" in q or "by region" in q):
        return False
    if any(
        x in q
        for x in (
            "highest",
            "largest",
            "lowest",
            "least",
            "summarize",
            "breakdown",
            "ar risk",
            "outstanding balance",
            "total due",
            "average ",
            "avg ",
            "mean ",
            "collection ",
            "overdue ",
        )
    ):
        return False
    if "which region" in q and any(x in q for x in ("highest", "most", "largest", "best", "worst", "least")):
        return False
    if has_financial_invoice_context(q):
        return False
    return any(
        phrase in q
        for phrase in (
            "how many",
            "number of",
            "count ",
            "count of",
            "what region",
            "which region",
            "list region",
            "list regions",
            "name the region",
            "region names",
            "every region",
            "all region",
            "all regions",
            "we have",
        )
    )


def aggregation_by_region_question(q: str) -> bool:
    q = q.lower()
    if "region" not in q and "regions" not in q:
        return False
    if is_region_catalog_question(q):
        return False
    if not any(x in q for x in ("by region", "per region", "each region", "grouped by region")):
        return False
    if re.search(r"\bdue\b", q) or re.search(r"\bar\b", q):
        return True
    return any(x in q for x in ("total", "sum", "balance", "outstanding", "amount"))


def extract_invoice_token(question: str) -> Optional[str]:
    m = re.search(r"\b(INV-?\d+)\b", question.upper())
    return m.group(1).upper() if m else None


def high_risk_mask(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0) >= 70.0


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


def extract_recent_days_window(q: str) -> Optional[int]:
    ql = q.lower()
    if "last week" in ql or "past week" in ql:
        return 7
    m = re.search(r"\b(?:last|past|previous)\s+(\d{1,3})\s+days?\b", ql)
    if m:
        n = int(m.group(1))
        return n if n > 0 else None
    m2 = re.search(r"\b(?:last|past|previous)\s+([a-z]+)\s+days?\b", ql)
    if m2 and m2.group(1) in _DAY_WORDS:
        return _DAY_WORDS[m2.group(1)]
    return None


def format_due_date(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "unknown"
    if hasattr(val, "date"):
        try:
            return str(val.date())
        except Exception:
            return str(val)[:10]
    s = str(val)
    return s[:10] if s else "unknown"
