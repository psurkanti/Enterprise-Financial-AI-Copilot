# Enterprise Financial AI Copilot

Portfolio-ready demo that combines:
- ChatGPT-style financial Q&A
- Finance KPI dashboard
- Invoice analysis from uploaded CSV data

## Features

- FastAPI backend with rule-based financial copilot (no OpenAI dependency)
- CSV upload and active dataset management
- KPI summary API (`/summary`)
- Invoice listing API (`/invoices`)
- Natural language copilot API (`/ask`)
- Enterprise-style frontend with:
  - Sidebar navigation
  - Dashboard page
  - Admin Upload page
  - Financial Copilot page
  - Quick action buttons
  - Answer panel and matching records table

## Project Structure

```text
backend/
  main.py
  services/
    data_loader.py
    financial_analyzer.py
  data/
    uploads/

frontend/
  index.html
  style.css
  app.js
```

## CSV Required Columns

The uploaded CSV must include (or alias to) these columns:
- `customer_name`
- `invoice_amount_due`
- `due_date`
- `status`
- `region`
- `risk_score`
- `aging_bucket`

Common alias headers (like `amount_due`, `customer`, `due date`, `risk`) are supported.

## Setup

1. Create and activate virtualenv (optional but recommended)
2. Install dependencies:

```bash
pip install -r requirements.txt
```

## Run

Start backend:

```bash
uvicorn backend.main:app --reload
```

Serve frontend (separate static server):

```bash
python3 -m http.server 5500 --directory frontend
```

Open:
- Frontend: `http://127.0.0.1:5500`
- Finance Team Copilot Page: `http://127.0.0.1:5500/team-copilot.html`
- API docs: `http://127.0.0.1:8000/docs`

## OpenAI Upgrade (Conversational Copilot)

The Financial Copilot now supports OpenAI-powered query planning with conversation memory.

Set environment variables before starting backend:

```bash
export OPENAI_API_KEY="your_key_here"
export OPENAI_MODEL="gpt-4.1-mini"
```

If `OPENAI_API_KEY` is not set, the Copilot uses a local dynamic fallback planner (still session-aware).

## API Endpoints

- `GET /health`
- `GET /summary`
- `GET /invoices`
- `POST /upload-csv`
- `POST /ask`

## Example Questions

- What is the total due amount?
- Show overdue invoices
- Which customers are high risk?
- Which region has highest outstanding balance?
- Show invoices above $50,000
- Give me collection priority customers
