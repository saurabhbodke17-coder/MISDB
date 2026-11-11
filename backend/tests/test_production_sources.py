from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import analytics, db, records


def test_unavailable_optional_metric_does_not_break_dashboard(monkeypatch):
    def missing(*args, **kwargs):
        raise HTTPException(409, "Production source unavailable")

    monkeypatch.setattr(records, "source_query", missing)
    assert analytics.optional_source_count("tasks", analytics.Filters()) is None


def test_optional_metric_does_not_hide_unexpected_errors(monkeypatch):
    def broken(*args, **kwargs):
        raise HTTPException(500, "Unexpected failure")

    monkeypatch.setattr(records, "source_query", broken)
    with pytest.raises(HTTPException) as exc:
        analytics.optional_source_count("tasks", analytics.Filters())
    assert exc.value.status_code == 500


def test_production_connection_never_falls_back_when_pool_missing(monkeypatch):
    monkeypatch.setattr(db, "settings", lambda: SimpleNamespace(source_database_url="configured"))
    monkeypatch.setattr(db, "source_pool", None)
    with pytest.raises(RuntimeError, match="fallback is disabled"):
        with db.read_connection('SELECT count(*) FROM "LMS".users'):
            pytest.fail("No production pool must mean no academic query")


def test_external_filters_use_identity_and_do_not_duplicate_rows(monkeypatch):
    monkeypatch.setattr(records, "settings", lambda: SimpleNamespace(source_database_url="configured"))
    monkeypatch.setattr(records, "metric_settings", lambda: {})
    batch = uuid4()
    _, sql, params = records.source_query("ojt_allocations", analytics.Filters(batch_id=batch))
    assert 'lower(trim(u.email))=r.student_email' in sql
    assert 'EXISTS (' in sql
    assert params["batch_id"] == batch
    assert "mis." not in sql


def test_placements_reject_unmapped_mentor_filter(monkeypatch):
    monkeypatch.setattr(records, "settings", lambda: SimpleNamespace(source_database_url="configured"))
    monkeypatch.setattr(records, "metric_settings", lambda: {})
    with pytest.raises(HTTPException) as exc:
        records.source_query("internship_placements", analytics.Filters(mentor_id=uuid4()))
    assert exc.value.status_code == 409


def test_linking_fields_are_not_returned_in_registers():
    assert records.visible({"id": "1", "student_email": "private", "mentor_emails": []}) == {"id": "1"}
