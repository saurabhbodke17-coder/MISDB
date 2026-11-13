from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException

from app import analytics
from app.analytics import rate
from app.records import csv_cell
from app.workflows import validate_transition


def test_empty_denominator_is_not_zero():
    assert rate(0, 0) is None
    assert rate(1, 3) == 33.3


@pytest.mark.parametrize("value", ["=SUM(A1:A2)", "+cmd", "-42", "@formula", "  =formula"])
def test_csv_formula_injection_is_neutralized(value):
    assert csv_cell(value).startswith("'")


def test_evidence_cannot_be_bypassed_by_status_save():
    with pytest.raises(HTTPException) as exc:
        validate_transition("Open", "Done – awaiting verification", "  ", "admin")
    assert exc.value.status_code == 422


def test_verification_requires_admin_and_prior_submission():
    with pytest.raises(HTTPException) as exc:
        validate_transition("Done – awaiting verification", "Verified & closed", "EVID-1", "operator")
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        validate_transition("Open", "Verified & closed", "EVID-1", "admin")
    assert exc.value.status_code == 409
    validate_transition("Done – awaiting verification", "Verified & closed", "EVID-1", "admin")


def test_closed_items_must_be_reopened():
    with pytest.raises(HTTPException):
        validate_transition("Verified & closed", "In progress", "EVID-1", "admin")
    validate_transition("Verified & closed", "Reopened", "", "admin")


def test_default_filters_use_ist_date(monkeypatch):
    class FakeDatetime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 12, 18, 30, 0, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(analytics, "datetime", FakeDatetime)
    f = analytics.filters()
    assert f.to_date == date(2026, 11, 13)
    assert f.from_date == date(2026, 10, 17)


def test_filters_options_includes_subjects(monkeypatch):
    monkeypatch.setattr(analytics, "query", lambda sql, p=None: [{"id": "s1", "name": "Operating Systems"}])
    monkeypatch.setattr(
        analytics, "one", lambda sql, p=None: {"first_date": date(2026, 1, 1), "last_date": date(2026, 11, 1)}
    )
    monkeypatch.setattr(analytics, "metric_settings", lambda: {})
    opts = analytics.options(user={"role": "viewer"})
    assert "subjects" in opts
    assert opts["subjects"][0]["name"] == "Operating Systems"


def test_session_detail_enriches_attendance_stats(monkeypatch):
    from app import records

    fake_session = {
        "id": "ses-123",
        "title": "DSA Session",
        "subject": "Data Structures",
        "mentor": "Mahathi",
        "batch": "Section A",
        "status": "completed",
    }
    monkeypatch.setattr(records, "metric_settings", lambda: {})
    monkeypatch.setattr(
        records,
        "one",
        lambda sql, p=None: (
            fake_session.copy()
            if "WHERE id::text=" in sql
            else {"present_students": 25, "absent_students": 5, "total_students": 30}
        ),
    )
    result = records.detail("sessions", "ses-123", f=analytics.Filters(), user={"role": "viewer"})
    assert result["record"]["title"] == "DSA Session"
    assert result["record"]["total_students"] == 30
    assert result["record"]["absent_students"] == 5
    assert result["record"]["attendance_rate"] == "83.3%"


def test_google_auth_flow(monkeypatch):
    from fastapi.testclient import TestClient
    from google.oauth2 import id_token

    from app import auth, config
    from app.main import app

    client = TestClient(app, headers={"X-Requested-With": "PolarisMIS"}, raise_server_exceptions=False)

    # 1. Config endpoint when unconfigured
    monkeypatch.setattr(config.settings(), "google_client_id", None)
    res = client.get("/api/auth/google/config")
    assert res.status_code == 200
    assert res.json()["enabled"] is False
    assert res.json()["client_id"] == ""
    assert "dev_mock" in res.json()

    # 2. Config endpoint when configured
    monkeypatch.setattr(config.settings(), "google_client_id", "test-client-id.apps.googleusercontent.com")
    res = client.get("/api/auth/google/config")
    assert res.status_code == 200
    assert res.json()["enabled"] is True
    assert res.json()["client_id"] == "test-client-id.apps.googleusercontent.com"
    assert res.json()["dev_mock"] is False

    # 3. 503 when client_id is None and credential is not dev mock
    monkeypatch.setattr(config.settings(), "google_client_id", None)
    res = client.post("/api/auth/google", json={"credential": "sample-dummy-token"})
    assert res.status_code == 503

    # 3b. Dev mock works when unconfigured in development
    class FakeCursor:
        def fetchone(self):
            return {
                "id": "acc-mock",
                "username": "demo.google@polaris.edu.in",
                "display_name": "Google Demo User",
                "role": "viewer",
            }

    class FakeConn:
        def execute(self, sql, p=None):
            return FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(auth, "connection", lambda: FakeConn())
    monkeypatch.setattr(config.settings(), "environment", "development")
    mock_res = client.post("/api/auth/google", json={"credential": "mock:demo.google@polaris.edu.in"})
    assert mock_res.status_code == 200
    assert mock_res.json()["username"] == "demo.google@polaris.edu.in"

    # 4. 401 when token verification fails
    monkeypatch.setattr(config.settings(), "google_client_id", "test-client-id")

    def mock_verify_fail(*args, **kwargs):
        raise ValueError("Invalid token signature")

    monkeypatch.setattr(id_token, "verify_oauth2_token", mock_verify_fail)
    res = client.post("/api/auth/google", json={"credential": "sample-dummy-token"})
    assert res.status_code == 401

    # 5. 403 when domain is restricted
    monkeypatch.setattr(config.settings(), "google_allowed_domains", ["polarisschool.com"])

    def mock_verify_success(*args, **kwargs):
        return {"email": "student@gmail.com", "email_verified": True, "name": "Jane Student"}

    monkeypatch.setattr(id_token, "verify_oauth2_token", mock_verify_success)
    res = client.post("/api/auth/google", json={"credential": "sample-dummy-token"})
    assert res.status_code == 403

    # 6. Success when valid email with allowed domain
    monkeypatch.setattr(config.settings(), "google_allowed_domains", ["polariscampus.com"])

    def mock_verify_domain_success(*args, **kwargs):
        return {"email": "student@polariscampus.com", "email_verified": True, "name": "Jane Student"}

    monkeypatch.setattr(id_token, "verify_oauth2_token", mock_verify_domain_success)

    class FakeValidCursor:
        def fetchone(self):
            return {
                "id": "acc-123",
                "username": "student@polariscampus.com",
                "display_name": "Jane Student",
                "role": "viewer",
            }

    class FakeValidConn:
        def execute(self, sql, p=None):
            return FakeValidCursor()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(auth, "connection", lambda: FakeValidConn())
    res = client.post("/api/auth/google", json={"credential": "sample-dummy-token"})
    assert res.status_code == 200
    assert res.json()["username"] == "student@polariscampus.com"
    assert "polaris_session" in res.cookies
