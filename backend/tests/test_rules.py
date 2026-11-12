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
