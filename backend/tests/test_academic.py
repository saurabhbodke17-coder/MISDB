import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
import psycopg

from app.config import settings
from app.db import start_pool
from app.main import app

HEADERS = {"X-Requested-With": "PolarisMIS", "Origin": "http://127.0.0.1:5173"}


@pytest.fixture(scope="module")
def client():
    start_pool()
    c = TestClient(app)
    owner = settings().database_url
    admin_user = "test-admin-academic"
    admin_pass = "Password123!"
    with psycopg.connect(owner) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM mis.accounts WHERE username=%s", (admin_user,))
            row = cur.fetchone()
            if not row:
                cur.execute(
                    "INSERT INTO mis.accounts(username,display_name,password_hash,role) VALUES (%s,%s,%s,%s)",
                    (admin_user, "Admin Academic Test", PasswordHash.recommended().hash(admin_pass), "admin"),
                )
            else:
                cur.execute(
                    "UPDATE mis.accounts SET password_hash=%s WHERE username=%s",
                    (PasswordHash.recommended().hash(admin_pass), admin_user),
                )
            conn.commit()

    res = c.post("/api/auth/login", json={"username": admin_user, "password": admin_pass}, headers=HEADERS)
    assert res.status_code == 200, f"Login failed: {res.text}"
    yield c


def test_academic_unauthenticated():
    c = TestClient(app)
    res = c.get("/api/academic/performance", headers=HEADERS)
    assert res.status_code == 401


def test_academic_performance_all(client):
    res = client.get("/api/academic/performance?from_date=2024-01-01&to_date=2026-12-31", headers=HEADERS)
    assert res.status_code == 200
    data = res.json()

    # Validate structure
    assert "kpis" in data
    assert "subject_cards" in data
    assert "charts" in data
    assert "records" in data
    assert "pagination" in data
    assert "filter_options" in data

    # Validate subject cards
    assert len(data["subject_cards"]) >= 10
    card = data["subject_cards"][0]
    assert "subject_name" in card
    assert "semester" in card
    assert "eval_avg" in card
    assert "midsem_avg" in card
    assert "endsem_avg" in card
    assert "overall_avg" in card
    assert "tier" in card
    assert "red_flags" in card

    # Validate KPI values
    kpis = data["kpis"]
    assert kpis["total_submissions"] > 20000
    assert kpis["unique_students"] > 400
    assert kpis["unique_subjects"] >= 10
    assert 0 < kpis["avg_score_pct"] < 100

    # Validate charts
    charts = data["charts"]
    assert len(charts["grade_distribution"]) == 4
    assert len(charts["subject_performance"]) >= 10
    assert len(charts["assessment_types"]) >= 3
    assert len(charts["batch_comparison"]) == 4

    # Validate records
    assert len(data["records"]) <= 25
    record = data["records"][0]
    assert "student_name" in record
    assert "marks_scored" in record
    assert "maximum_marks" in record
    assert "score_pct" in record
    assert "tier" in record


def test_academic_performance_filter_exam_type(client):
    res = client.get("/api/academic/performance?from_date=2024-01-01&to_date=2026-12-31&exam_type=Viva", headers=HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert data["kpis"]["total_submissions"] > 5000
    for r in data["records"]:
        assert r["exam_type"] == "Viva"


def test_trends_score_metric(client):
    res = client.get("/api/charts/trends/overview?metric=score&from_date=2024-01-01&to_date=2026-12-31&granularity=weekly", headers=HEADERS)
    assert res.status_code == 200
    payload = res.json()
    charts = payload.get("charts", [])
    assert len(charts) == 5
    for chart in charts:
        assert chart["status"] == "available"
        assert len(chart["rows"]) > 0
