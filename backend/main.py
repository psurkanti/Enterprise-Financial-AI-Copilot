import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from backend.services.chat_memory import InMemoryChatMemory
from backend.services.copilot_engine import CopilotEngine
from backend.services.data_loader import load_active_csv
from backend.services.dataset_manager import DatasetManager
from backend.services.financial_analyzer import invoice_list, summarize

app = FastAPI(title="Enterprise Financial AI Copilot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(__file__).resolve().parent / "data" / "uploads"
_UI_ROOT = (Path(__file__).resolve().parent.parent / "frontend").resolve()


def _ui_file(rel: str) -> Path:
    """Resolve a path under frontend/; reject escapes."""
    base = _UI_ROOT
    candidate = (base / rel.lstrip("/")).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not Found") from exc
    return candidate


def _file_response(path: Path) -> FileResponse:
    suffix = path.suffix.lower()
    media = None
    if suffix == ".js":
        media = "application/javascript"
    elif suffix == ".css":
        media = "text/css"
    elif suffix == ".html":
        media = "text/html; charset=utf-8"
    return FileResponse(path, media_type=media)
ACTIVE_FILE = UPLOAD_DIR / "active_invoices.csv"
COPILOT_ENGINE = CopilotEngine()
CHAT_MEMORY = InMemoryChatMemory()
DATASET_MANAGER = DatasetManager(UPLOAD_DIR)


class AskRequest(BaseModel):
    question: str
    session_id: Optional[str] = None


def _load_data():
    active = DATASET_MANAGER.get_active()
    if active:
        active_path = UPLOAD_DIR / str(active.get("stored_name", ""))
        try:
            return load_active_csv(UPLOAD_DIR, active_file=active_path)
        except FileNotFoundError:
            pass
    try:
        return load_active_csv(UPLOAD_DIR, active_file=ACTIVE_FILE)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/summary")
def summary() -> Dict[str, Any]:
    frame = _load_data()
    return summarize(frame)


@app.get("/invoices")
def invoices(
    limit: int = Query(default=100, ge=1, le=500),
    min_amount: Optional[float] = Query(default=None, ge=0),
    overdue_only: bool = Query(default=False),
    region: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    frame = _load_data()
    rows = invoice_list(
        frame,
        limit=limit,
        min_amount=min_amount,
        overdue_only=overdue_only,
        region=region,
    )
    return {"count": len(rows), "records": rows}


@app.post("/upload-csv")
async def upload_csv(file: UploadFile = File(...)) -> Dict[str, Any]:
    if not file.filename.lower().endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only CSV/XLSX files are supported.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    # Write to a temp file, validate, then replace the active file in one step.
    # So a failed upload never wipes or partially overwrites the last good dataset.
    ext = Path(file.filename).suffix.lower() or ".csv"
    pending = UPLOAD_DIR / f".upload_pending_{uuid.uuid4().hex}{ext}"
    try:
        pending.write_bytes(content)
        frame = load_active_csv(UPLOAD_DIR, active_file=pending)
    except ValueError as exc:
        pending.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        pending.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    final_name = f"dataset_{uuid.uuid4().hex}{ext}"
    final_path = UPLOAD_DIR / final_name
    try:
        pending.replace(final_path)
    except OSError as exc:
        pending.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Could not save CSV: {exc}") from exc

    entry = DATASET_MANAGER.add_dataset(
        stored_name=final_name,
        original_name=file.filename,
        uploaded_by="admin",
        rows=int(len(frame)),
        columns=[str(c) for c in frame.columns],
        is_active=True,
    )

    CHAT_MEMORY.clear_all()

    return {"message": "Upload successful", "file": file.filename, "rows": int(len(frame))}


@app.post("/datasets/preview")
async def preview_dataset(
    file: UploadFile = File(...),
    uploaded_by: str = Form(default="admin"),
) -> Dict[str, Any]:
    if not file.filename.lower().endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only CSV/XLSX files are supported.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename).suffix.lower() or ".csv"
    pending_name = f"dataset_{uuid.uuid4().hex}{ext}"
    pending = UPLOAD_DIR / pending_name
    content = await file.read()
    try:
        pending.write_bytes(content)
        frame = load_active_csv(UPLOAD_DIR, active_file=pending)
    except ValueError as exc:
        pending.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        pending.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    entry = DATASET_MANAGER.add_dataset(
        stored_name=pending_name,
        original_name=file.filename,
        uploaded_by=uploaded_by,
        rows=int(len(frame)),
        columns=[str(c) for c in frame.columns],
        is_active=False,
    )
    preview_rows = frame.head(10).astype(str).to_dict(orient="records")
    return {
        "message": "Preview ready",
        "dataset": entry,
        "preview_columns": [str(c) for c in frame.columns],
        "preview_rows": preview_rows,
    }


@app.post("/datasets/activate")
def activate_dataset(dataset_id: str = Form(...)) -> Dict[str, Any]:
    try:
        active = DATASET_MANAGER.set_active(dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    CHAT_MEMORY.clear_all()
    return {"message": "Active dataset updated", "active_dataset": active}


@app.get("/datasets")
def list_datasets() -> Dict[str, Any]:
    datasets = DATASET_MANAGER.list_datasets()
    active = DATASET_MANAGER.get_active()
    return {"datasets": datasets, "active_dataset_id": (active or {}).get("dataset_id")}


@app.post("/ask")
def ask_question(payload: AskRequest) -> Dict[str, Any]:
    frame = _load_data()
    state = CHAT_MEMORY.get_or_create(payload.session_id)
    result = COPILOT_ENGINE.answer(frame, payload.question, state)
    CHAT_MEMORY.update(
        session_id=state.session_id,
        question=payload.question,
        summary=result.get("summary", ""),
        records=result.get("matching_records", []),
        result=result,
    )
    result["session_id"] = state.session_id
    return result


# Serve admin + team UI at /ui/* (explicit routes so shortcuts always work, even when
# app.mount StaticFiles behaved inconsistently across reload / import paths).


@app.get("/ui")
def ui_redirect_slash():
    return RedirectResponse(url="/ui/")


@app.get("/ui/")
def ui_index():
    index = _ui_file("index.html")
    if not index.is_file():
        raise HTTPException(status_code=500, detail=f"Missing UI: {_UI_ROOT}")
    return _file_response(index)


@app.get("/ui/{path:path}")
def ui_assets(path: str):
    """style.css, app.js, team-copilot.html, etc."""
    if not path or path.endswith("/"):
        index = _ui_file("index.html")
        return _file_response(index)
    target = _ui_file(path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Not Found")
    return _file_response(target)