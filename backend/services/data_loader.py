from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional

import pandas as pd


REQUIRED_COLUMNS = {
    "customer_name",
    "invoice_amount_due",
    "due_date",
    "status",
    "region",
    "risk_score",
    "aging_bucket",
}

ALIASES = {
    "customer_name": {"customer", "customer_name", "customername", "client", "client_name"},
    "invoice_amount_due": {
        "invoice_amount_due",
        "invoiceamountdue",
        "amount_due",
        "due_amount",
        "invoice_amount",
        "outstanding_amount",
        "amount",
        "balance",
        "balance_remaining",
        "total_due",
        "open_balance",
        "ar_balance",
    },
    "amount_paid": {
        "amount_paid",
        "paid_amount",
        "payment_amount",
        "payment_received_amount",
    },
    "due_date": {"due_date", "duedate", "payment_due_date", "invoice_due_date"},
    "invoice_date": {"invoice_date", "invoicedate", "bill_date", "issued_date"},
    "status": {"status", "invoice_status"},
    "region": {"region", "sales_region", "customer_region"},
    "risk_score": {"risk_score", "riskscore", "risk"},
    "aging_bucket": {"aging_bucket", "aging", "ageing", "ageing_bucket"},
    "payment_method": {"payment_method", "paymentmode", "payment_type", "paid_via"},
    "collection_priority": {"collection_priority", "priority", "collection_tier"},
    "customer_segment": {"customer_segment", "segment", "customer_tier"},
    "assigned_collector": {"assigned_collector", "collector", "owner", "assigned_to"},
    "invoice_category": {"invoice_category", "category", "invoice_type"},
}


PAYMENT_DATE_ALIASES = frozenset(
    {
        "payment_date",
        "paid_date",
        "date_paid",
        "payment_received_date",
        "paid_on",
        "pay_date",
    }
)


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [_normalize_name(column) for column in frame.columns]
    return frame


def _remap_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    rename_map: Dict[str, str] = {}
    for source in frame.columns:
        source_compact = source.replace("_", "")
        for target, aliases in ALIASES.items():
            if source == target or source in aliases or source_compact in aliases:
                if target not in rename_map.values():
                    rename_map[source] = target
                break
    if rename_map:
        frame = frame.rename(columns=rename_map)
    return frame


def prepare_invoice_frame(frame: pd.DataFrame) -> pd.DataFrame:
    frame = _remap_columns(_normalize_columns(frame))
    if "risk_score" not in frame.columns:
        frame["risk_score"] = 0.0
    if "aging_bucket" not in frame.columns:
        frame["aging_bucket"] = ""
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError("CSV is missing required columns: " + ", ".join(sorted(missing)))

    frame["invoice_amount_due"] = pd.to_numeric(frame["invoice_amount_due"], errors="coerce").fillna(0.0)
    if "amount_paid" in frame.columns:
        frame["amount_paid"] = pd.to_numeric(frame["amount_paid"], errors="coerce").fillna(0.0)
    frame["risk_score"] = pd.to_numeric(frame["risk_score"], errors="coerce").fillna(0.0)
    frame["due_date"] = pd.to_datetime(frame["due_date"], errors="coerce")
    frame["status"] = frame["status"].astype(str).str.strip()
    frame["region"] = frame["region"].astype(str).str.strip()
    frame["customer_name"] = frame["customer_name"].astype(str).str.strip()
    frame["aging_bucket"] = frame["aging_bucket"].astype(str).str.strip()
    id_aliases = {"invoice_id", "invoiceid", "inv_number", "invoice_number", "inv_no"}
    for col in list(frame.columns):
        if col in id_aliases and "invoice_id" not in frame.columns:
            frame = frame.rename(columns={col: "invoice_id"})
            break
    if "invoice_id" in frame.columns:
        frame["invoice_id"] = frame["invoice_id"].astype(str).str.strip()
    for col in list(frame.columns):
        if col in PAYMENT_DATE_ALIASES and "payment_date" not in frame.columns:
            frame = frame.rename(columns={col: "payment_date"})
            break
    if "payment_date" in frame.columns:
        frame["payment_date"] = pd.to_datetime(frame["payment_date"], errors="coerce")
    if "invoice_date" in frame.columns:
        frame["invoice_date"] = pd.to_datetime(frame["invoice_date"], errors="coerce")
    return frame


def load_active_csv(upload_dir: Path, active_file: Optional[Path] = None) -> pd.DataFrame:
    """Load the canonical active dataset.

    When ``active_file`` is provided (as in production), **only** that path is read.
    If it is missing, callers must upload again—we never silently substitute another CSV
    from the uploads folder (which caused answers to look like the wrong/random dataset).
    """
    if active_file is not None:
        if not active_file.exists():
            raise FileNotFoundError(
                f"No active dataset at {active_file}. Upload a CSV on the Admin Upload Data page."
            )
        ext = active_file.suffix.lower()
        if ext in {".xlsx", ".xls"}:
            return prepare_invoice_frame(pd.read_excel(active_file))
        return prepare_invoice_frame(pd.read_csv(active_file))

    upload_dir.mkdir(parents=True, exist_ok=True)
    csv_files = sorted(upload_dir.glob("*.csv")) + sorted(upload_dir.glob("*.xlsx")) + sorted(upload_dir.glob("*.xls"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV/XLSX found in {upload_dir}. Please upload one.")
    first = csv_files[0]
    ext = first.suffix.lower()
    if ext in {".xlsx", ".xls"}:
        return prepare_invoice_frame(pd.read_excel(first))
    return prepare_invoice_frame(pd.read_csv(first))
