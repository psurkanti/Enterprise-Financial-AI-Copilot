import pytest
from datetime import timedelta

import pandas as pd
from fastapi.testclient import TestClient

import backend.main as main


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Tests must never write to the real admin CSV — that file is the user's data."""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True)
    active_file = upload_dir / "active_invoices.csv"
    monkeypatch.setattr(main, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(main, "ACTIVE_FILE", active_file)
    return TestClient(main.app)


def _upload_fixture_csv(client: TestClient):
    csv_content = (
        "customer_name,invoice_amount_due,due_date,status,region,risk_score,aging_bucket\n"
        "Acme Corp,120000,2026-04-10,Pending,North America,82,31-60\n"
        "Beta LLC,45000,2026-05-01,Overdue,Europe,65,1-30\n"
        "Crest Inc,98000,2026-03-20,Overdue,North America,91,61-90\n"
        "Delta Ltd,22000,2026-06-15,Pending,Asia,40,Current\n"
    )
    response = client.post(
        "/upload-csv",
        files={"file": ("sample.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 200


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_summary(client):
    _upload_fixture_csv(client)
    response = client.get("/summary")
    assert response.status_code == 200
    body = response.json()
    assert "total_due" in body
    assert "total_invoices" in body
    assert "overdue_invoices" in body
    assert "high_risk_customers" in body
    assert "top_region_by_balance" in body


def test_invoices(client):
    _upload_fixture_csv(client)
    response = client.get("/invoices?min_amount=50000")
    assert response.status_code == 200
    body = response.json()
    assert "records" in body
    assert body["count"] >= 1


def test_ask(client):
    _upload_fixture_csv(client)
    response = client.post("/ask", json={"question": "What is the total due amount?"})
    assert response.status_code == 200
    body = response.json()
    assert "summary" in body
    assert "key_findings" in body
    assert "recommended_action" in body
    assert "matching_records" in body


def test_ask_with_session_follow_up(client):
    _upload_fixture_csv(client)
    first = client.post(
        "/ask",
        json={"question": "Show overdue invoices above $50K"},
    )
    assert first.status_code == 200
    sid = first.json().get("session_id")
    assert sid

    second = client.post(
        "/ask",
        json={"question": "Show those customers", "session_id": sid},
    )
    assert second.status_code == 200
    body = second.json()
    assert body.get("session_id") == sid
    assert "summary" in body


def test_ask_customer_count(client):
    _upload_fixture_csv(client)
    response = client.post("/ask", json={"question": "how many customers in total?"})
    assert response.status_code == 200
    body = response.json()
    assert "4 customers" in body["summary"] or "customers" in body["summary"]


def test_ask_region_catalog_concise(client):
    _upload_fixture_csv(client)
    response = client.post("/ask", json={"question": "How many regions in total and what are they?"})
    assert response.status_code == 200
    body = response.json()
    assert body.get("response_mode") == "concise"
    assert body.get("response_style") == "direct"
    assert "region" in body["summary"].lower()
    assert body.get("intent") == "count_regions"
    recs = body.get("matching_records") or []
    assert len(recs) == 0


def test_clarify_off_topic_question(client):
    _upload_fixture_csv(client)
    response = client.post("/ask", json={"question": "xyzzy plugh"})
    assert response.status_code == 200
    body = response.json()
    assert body.get("intent") == "clarify"
    assert "customer_name" in body["summary"]


def test_ask_how_many_regions_in_total_not_invoice_dump(client):
    _upload_fixture_csv(client)
    r = client.post("/ask", json={"question": "how many regions in total"})
    assert r.status_code == 200
    body = r.json()
    assert ("3" in body["summary"] or "three" in body["summary"].lower())
    assert not body.get("matching_records")


def test_paid_last_days_filters_by_payment_date(client):
    today = pd.Timestamp.utcnow().date()
    d_recent = (today - timedelta(days=1)).isoformat()
    d_old = (today - timedelta(days=40)).isoformat()
    csv_content = (
        "customer_name,invoice_amount_due,due_date,status,payment_date,region,risk_score,aging_bucket\n"
        f"RecentCo,100,2026-01-01,Paid,{d_recent},North America,10,0-30\n"
        f"OldCo,999999,2026-01-01,Paid,{d_old},North America,10,0-30\n"
    )
    assert client.post("/upload-csv", files={"file": ("p.csv", csv_content, "text/csv")}).status_code == 200
    r = client.post("/ask", json={"question": "How much was paid in the last 2 days?"})
    assert r.status_code == 200
    summ = r.json()["summary"]
    assert "100" in summ
    assert "999999" not in summ


def test_paid_last_days_without_payment_date_explains(client):
    csv_content = (
        "customer_name,invoice_amount_due,due_date,status,region,risk_score,aging_bucket\n"
        "OnlyPaid,50,2026-01-01,Paid,North America,10,0-30\n"
    )
    assert client.post("/upload-csv", files={"file": ("np.csv", csv_content, "text/csv")}).status_code == 200
    r = client.post("/ask", json={"question": "How much invoice paid in last 10 days?"})
    assert r.status_code == 200
    body = r.json()
    assert "payment_date" in body["summary"].lower()
    assert "50" in body["summary"]


def test_lookup_invoice_due_date(client):
    csv_content = (
        "customer_name,invoice_id,invoice_amount_due,due_date,status,region,risk_score,aging_bucket\n"
        "Acme Corp,INV1005,29173,2026-01-24,Pending,North America,40,0-30\n"
    )
    up = client.post("/upload-csv", files={"file": ("t.csv", csv_content, "text/csv")})
    assert up.status_code == 200
    r = client.post("/ask", json={"question": "What is the due date of invoice INV1005?"})
    assert r.status_code == 200
    body = r.json()
    assert "2026-01-24" in body["summary"]
    assert body.get("response_style") == "direct"
    assert not body.get("matching_records")


def test_invalid_upload_does_not_wipe_prior_dataset(client):
    _upload_fixture_csv(client)
    before = client.get("/invoices?limit=50")
    assert before.status_code == 200
    assert any(r.get("customer_name") == "Acme Corp" for r in before.json()["records"])

    bad = client.post(
        "/upload-csv",
        files={"file": ("bad.csv", "a,b,c\n1,2,3\n", "text/csv")},
    )
    assert bad.status_code == 400

    after = client.get("/invoices?limit=50")
    assert after.status_code == 200
    assert any(r.get("customer_name") == "Acme Corp" for r in after.json()["records"])
