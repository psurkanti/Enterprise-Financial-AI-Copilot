from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class DatasetManager:
    def __init__(self, upload_dir: Path) -> None:
        self.upload_dir = upload_dir
        self.catalog_file = upload_dir / "dataset_catalog.json"

    def _load_catalog(self) -> Dict[str, Any]:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        if not self.catalog_file.exists():
            return {"datasets": []}
        try:
            return json.loads(self.catalog_file.read_text(encoding="utf-8"))
        except Exception:
            return {"datasets": []}

    def _save_catalog(self, catalog: Dict[str, Any]) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_file.write_text(json.dumps(catalog, indent=2), encoding="utf-8")

    def add_dataset(
        self,
        *,
        stored_name: str,
        original_name: str,
        uploaded_by: str,
        rows: int,
        columns: List[str],
        is_active: bool = False,
    ) -> Dict[str, Any]:
        catalog = self._load_catalog()
        now = datetime.now(timezone.utc).isoformat()
        entry = {
            "dataset_id": uuid.uuid4().hex,
            "stored_name": stored_name,
            "dataset_name": original_name,
            "uploaded_at": now,
            "uploaded_by": uploaded_by or "admin",
            "rows": int(rows),
            "columns": columns,
            "is_active": bool(is_active),
        }
        if is_active:
            for ds in catalog.get("datasets", []):
                ds["is_active"] = False
        catalog.setdefault("datasets", []).insert(0, entry)
        self._save_catalog(catalog)
        return entry

    def list_datasets(self) -> List[Dict[str, Any]]:
        catalog = self._load_catalog()
        return list(catalog.get("datasets", []))

    def get_dataset(self, dataset_id: str) -> Optional[Dict[str, Any]]:
        for ds in self.list_datasets():
            if ds.get("dataset_id") == dataset_id:
                return ds
        return None

    def set_active(self, dataset_id: str) -> Dict[str, Any]:
        catalog = self._load_catalog()
        active = None
        for ds in catalog.get("datasets", []):
            is_target = ds.get("dataset_id") == dataset_id
            ds["is_active"] = bool(is_target)
            if is_target:
                active = ds
        if not active:
            raise ValueError("Dataset not found.")
        self._save_catalog(catalog)
        return active

    def get_active(self) -> Optional[Dict[str, Any]]:
        for ds in self.list_datasets():
            if ds.get("is_active"):
                return ds
        return None
