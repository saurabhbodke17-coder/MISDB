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
    admin_user = "test-admin-conflicts"
    admin_pass = "Password123!"
    with psycopg.connect(owner) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM mis.accounts WHERE username=%s", (admin_user,))
            row = cur.fetchone()
            if not row:
                cur.execute(
                    "INSERT INTO mis.accounts(username,display_name,password_hash,role) VALUES (%s,%s,%s,%s)",
                    (admin_user, "Admin Conflicts Test", PasswordHash.recommended().hash(admin_pass), "admin"),
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


def test_conflicts_unauthenticated():
    c = TestClient(app)
    res = c.get("/api/calendar/conflicts", headers=HEADERS)
    assert res.status_code == 401


def test_conflicts_all(client):
    res = client.get("/api/calendar/conflicts?from_date=2026-10-01&to_date=2026-11-20", headers=HEADERS)
    assert res.status_code == 200
    data = res.json()

    assert "summary" in data
    assert "batch_conflicts" in data
    assert "faculty_conflicts" in data
    assert "room_conflicts" in data

    summary = data["summary"]
    assert summary["total"] >= 0
    assert summary["batch_conflicts"] == len(data["batch_conflicts"])
    assert summary["faculty_conflicts"] == len(data["faculty_conflicts"])
    assert summary["room_conflicts"] == len(data["room_conflicts"])

    if data["batch_conflicts"]:
        b = data["batch_conflicts"][0]
        assert b["conflict_type"] == "batch"
        assert "overlap_minutes" in b
        assert "conflict_reason" in b
        assert "session_1" in b
        assert "session_2" in b

    if data["faculty_conflicts"]:
        f = data["faculty_conflicts"][0]
        assert f["conflict_type"] == "faculty"
        assert "overlap_minutes" in f
        assert "conflict_reason" in f
        assert "session_1" in f
        assert "session_2" in f

    if data["room_conflicts"]:
        r = data["room_conflicts"][0]
        assert r["conflict_type"] == "room"
        assert "overlap_minutes" in r
        assert "conflict_reason" in r
        assert "session_1" in r
        assert "session_2" in r


def test_conflicts_filter_by_type(client):
    res_b = client.get(
        "/api/calendar/conflicts?from_date=2026-10-01&to_date=2026-11-20&conflict_type=batch", headers=HEADERS
    )
    assert res_b.status_code == 200
    data_b = res_b.json()
    assert len(data_b["faculty_conflicts"]) == 0
    assert len(data_b["room_conflicts"]) == 0

    res_f = client.get(
        "/api/calendar/conflicts?from_date=2026-10-01&to_date=2026-11-20&conflict_type=faculty", headers=HEADERS
    )
    assert res_f.status_code == 200
    data_f = res_f.json()
    assert len(data_f["batch_conflicts"]) == 0
    assert len(data_f["room_conflicts"]) == 0

    res_r = client.get(
        "/api/calendar/conflicts?from_date=2026-10-01&to_date=2026-11-20&conflict_type=room", headers=HEADERS
    )
    assert res_r.status_code == 200
    data_r = res_r.json()
    assert len(data_r["batch_conflicts"]) == 0
    assert len(data_r["faculty_conflicts"]) == 0

