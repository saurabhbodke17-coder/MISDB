"""Opt-in tests against an isolated restored LMS database.

RUN_DB_TESTS=1 TEST_OWNER_DATABASE_URL=... pytest
Only test-created accounts, work items, audit entries and support reports are removed.
"""

import csv
import io
import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash

from app.catalog import SOURCES
from app.config import settings
from app.main import app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="Requires explicitly enabled isolated PostgreSQL test database"
)
HEADERS = {"X-Requested-With": "PolarisMIS", "Origin": "http://127.0.0.1:5173"}
PERIOD = {"from_date": "2026-07-01", "to_date": "2026-10-28"}


@pytest.fixture(scope="module")
def accounts():
    owner = os.environ.get("TEST_OWNER_DATABASE_URL", settings().database_url)
    suffix = uuid4().hex
    password = "Integration-only-" + suffix
    users = {}
    with psycopg.connect(owner) as c:
        for role in ["admin", "operator", "viewer"]:
            username = f"test-{role}-{suffix}"
            uid = c.execute(
                "INSERT INTO mis.accounts(username,display_name,password_hash,role) VALUES (%s,%s,%s,%s) RETURNING id",
                (username, "Integration test", PasswordHash.recommended().hash(password), role),
            ).fetchone()[0]
            users[role] = {"id": str(uid), "username": username, "password": password}
    yield users
    with psycopg.connect(owner) as c:
        ids = [u["id"] for u in users.values()]
        # Capture only records created by these test identities before removing their audit history.
        reports = c.execute(
            "SELECT entity_id::uuid FROM mis.audit_events WHERE actor_id=ANY(%s::uuid[]) AND entity_type='support' AND event='created'",
            (ids,),
        ).fetchall()
        for (rid,) in reports:
            c.execute("DELETE FROM mis.support_metadata WHERE report_id=%s", (rid,))
            c.execute("DELETE FROM support_reports WHERE id=%s", (rid,))
        c.execute("DELETE FROM mis.audit_events WHERE actor_id=ANY(%s::uuid[])", (ids,))
        c.execute("DELETE FROM mis.work_items WHERE created_by=ANY(%s::uuid[])", (ids,))
        c.execute("DELETE FROM mis.sessions WHERE account_id=ANY(%s::uuid[])", (ids,))
        c.execute(
            "DELETE FROM mis.login_attempts WHERE username=ANY(%s)",
            ([u["username"] for u in users.values()],),
        )
        c.execute("DELETE FROM mis.accounts WHERE id=ANY(%s::uuid[])", (ids,))


@pytest.fixture
def client(accounts):
    with TestClient(app) as client:
        client.headers.update(HEADERS)
        response = client.post(
            "/api/auth/login", json={k: accounts["admin"][k] for k in ["username", "password"]}
        )
        assert response.status_code == 200, response.text
        yield client


def test_auth_csrf_and_logout(accounts):
    with TestClient(app) as c:
        assert c.get("/api/dashboard").status_code == 401
        assert c.post("/api/auth/login", json={"username": "x", "password": "x"}).status_code == 403
        response = c.post(
            "/api/auth/login",
            headers=HEADERS,
            json={k: accounts["admin"][k] for k in ["username", "password"]},
        )
        assert response.status_code == 200
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert c.get("/api/auth/me").status_code == 200
        old_cookie = c.cookies.get("polaris_session")
        assert c.post("/api/auth/logout", headers=HEADERS).status_code == 204
        c.cookies.set("polaris_session", old_cookie)
        assert c.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize("source", list(SOURCES))
def test_every_register_summary_export_and_detail(client, source):
    response = client.get(f"/api/records/{source}", params=PERIOD)
    assert response.status_code == 200, response.text
    body = response.json()
    summary = client.get(f"/api/records/{source}/summary", params=PERIOD)
    assert summary.status_code == 200, summary.text
    assert summary.json()["total"] == body["total"]
    exported = client.get(f"/api/records/{source}/export", params=PERIOD)
    assert exported.status_code == 200, exported.text
    assert "text/csv" in exported.headers["content-type"]
    assert sum(1 for _ in csv.reader(io.StringIO(exported.text))) == body["total"] + 1
    if body["rows"]:
        detail = client.get(f"/api/records/{source}/{body['rows'][0]['id']}", params=PERIOD)
        assert detail.status_code == 200, detail.text
        assert (
            not {"password_hash", "refresh_token_hash", "phone", "identity_doc_no"}
            & detail.json()["record"].keys()
        )


def test_metrics_match_database_and_filters(client):
    response = client.get("/api/dashboard", params=PERIOD)
    assert response.status_code == 200, response.text
    kpis = {k["key"]: k for k in response.json()["kpis"]}
    with psycopg.connect(os.environ.get("TEST_OWNER_DATABASE_URL", settings().database_url)) as c:
        present, total = c.execute(
            "SELECT count(*) FILTER(WHERE status='present'),count(*) FILTER(WHERE status IN ('present','late','absent')) FROM attendance_records"
        ).fetchone()
    assert kpis["attendance"]["value"] == round(100 * present / total, 1)
    with psycopg.connect(os.environ.get("TEST_OWNER_DATABASE_URL", settings().database_url)) as c:
        on_time, telemetry = c.execute(
            """SELECT count(*) FILTER (WHERE ls.actual_start <= cs.scheduled_start AT TIME ZONE 'UTC' + interval '10 minutes'),
              count(ls.actual_start)
            FROM class_sessions cs
            LEFT JOIN live_sessions ls ON ls.class_session_id=cs.id
            WHERE cs.scheduled_start::date BETWEEN %s AND %s
              AND cs.scheduled_start < now() AT TIME ZONE 'UTC'""",
            (PERIOD["from_date"], PERIOD["to_date"]),
        ).fetchone()
    assert kpis["delivery"]["value"] == round(100 * on_time / telemetry, 1)
    assert kpis["delivery"]["numerator"] == on_time
    assert kpis["delivery"]["denominator"] == telemetry
    assert "10 min grace" in kpis["delivery"]["evidence"]
    with psycopg.connect(os.environ.get("TEST_OWNER_DATABASE_URL", settings().database_url)) as c:
        unresolved, elapsed = c.execute(
            """SELECT count(*) FILTER (WHERE cs.status='scheduled' AND ls.actual_start IS NULL
                AND ls.actual_end IS NULL AND NOT EXISTS(
                  SELECT 1 FROM attendance_records ar WHERE ar.session_id=cs.id
                )),count(*)
            FROM class_sessions cs
            LEFT JOIN live_sessions ls ON ls.class_session_id=cs.id
            WHERE cs.scheduled_start::date BETWEEN %s AND %s
              AND cs.scheduled_start < now() AT TIME ZONE 'UTC'""",
            (PERIOD["from_date"], PERIOD["to_date"]),
        ).fetchone()
    assert kpis["missed"]["value"] == unresolved
    assert kpis["missed"]["evidence"] == (
        f"{unresolved:,} unresolved · {100 * unresolved / elapsed:.1f}% of {elapsed:,} elapsed sessions"
    )
    with psycopg.connect(os.environ.get("TEST_OWNER_DATABASE_URL", settings().database_url)) as c:
        average_score, evaluated = c.execute(
            """SELECT avg(sub.marks/nullif(a.max_score,0)*100),count(*)
            FROM assignment_submissions sub JOIN assignments a ON a.id=sub.assignment_id
            WHERE a.due_at::date BETWEEN %s AND %s AND a.status='active'
              AND a.approval_status='approved' AND sub.graded_at IS NOT NULL
              AND sub.marks IS NOT NULL AND a.max_score>0""",
            (PERIOD["from_date"], PERIOD["to_date"]),
        ).fetchone()
    assert kpis["score"]["value"] == round(float(average_score), 1)
    assert kpis["score"]["denominator"] == evaluated
    assert kpis["score"]["evidence"] == f"{evaluated:,} graded submissions"
    options = client.get("/api/filters").json()
    for batch in options["batches"]:
        params = PERIOD | {"batch_id": batch["id"]}
        response = client.get("/api/dashboard", params=params)
        assert response.status_code == 200, response.text
        assert all(b["id"] == batch["id"] for b in response.json()["batches"])
    empty = client.get("/api/dashboard", params=PERIOD | {"batch_id": str(uuid4())}).json()
    assert all(k["value"] is None for k in empty["kpis"] if k["unit"] == "%")
    assert all(
        k["value"] == 0
        for k in empty["kpis"]
        if k["key"] in {"strength", "risk", "tasks", "issues", "breach"}
    )
    assert (
        client.get("/api/dashboard", params={"from_date": "2026-10-28", "to_date": "2026-07-01"}).status_code
        == 422
    )
    assert client.get("/api/records/users").status_code == 404
    assert (
        client.get("/api/records/attendance", params=PERIOD | {"sort": "id;DROP TABLE users"}).status_code
        == 200
    )
    for status in ("present", "absent"):
        response = client.get("/api/records/attendance", params=PERIOD | {"status": status})
        assert response.status_code == 200, response.text
        assert all(row["status"] == status for row in response.json()["rows"])
    invalid_status = client.get("/api/records/attendance", params=PERIOD | {"status": "late"})
    assert invalid_status.status_code == 422
    for status in ("completed", "cancelled", "scheduled", "in_progress"):
        response = client.get("/api/records/sessions", params=PERIOD | {"status": status})
        assert response.status_code == 200, response.text
        assert all(row["status"] == status for row in response.json()["rows"])
    invalid_delivery = client.get("/api/records/sessions", params=PERIOD | {"status": "active"})
    assert invalid_delivery.status_code == 422
    academic_risk = client.get(
        "/api/records/students", params=PERIOD | {"preset": "academic:risk", "page_size": 100}
    )
    assert academic_risk.status_code == 200, academic_risk.text
    assert academic_risk.json()["total"] > 0
    assert all(
        row["status"] == "active" and row["attendance"] is not None and row["attendance"] < 40
        for row in academic_risk.json()["rows"]
    )


def test_student_filters_and_csv_export_use_identical_scope(client):
    unfiltered = client.get("/api/records/students", params=PERIOD | {"page_size": 1})
    assert unfiltered.status_code == 200, unfiltered.text
    with psycopg.connect(os.environ.get("TEST_OWNER_DATABASE_URL", settings().database_url)) as c:
        assert unfiltered.json()["total"] == c.execute("SELECT count(*) FROM student_batches").fetchone()[0]

    cases = {
        "attendance_band": ("below40", "attendance", lambda value: value is not None and value < 40),
        "score_band": ("80plus", "average_score", lambda value: value is not None and value >= 80),
        "risk_status": (
            "High Risk",
            "risk",
            lambda value: value == "High Risk",
        ),
    }
    for parameter, (selected, field, predicate) in cases.items():
        query_params = PERIOD | {parameter: selected, "page_size": 100}
        response = client.get("/api/records/students", params=query_params)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] > 0
        assert all(predicate(row[field]) for row in body["rows"])
        exported = client.get("/api/records/students/export", params=PERIOD | {parameter: selected})
        assert exported.status_code == 200, exported.text
        csv_rows = list(csv.reader(io.StringIO(exported.text)))
        assert len(csv_rows) - 1 == body["total"]

    invalid = client.get("/api/records/students", params=PERIOD | {"attendance_band": "invalid"})
    assert invalid.status_code == 422
    for state in ("High Risk", "No Risk", "No attendance evidence"):
        response = client.get(
            "/api/records/students", params=PERIOD | {"risk_status": state, "page_size": 100}
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] > 0
        assert all(row["risk"] == state for row in response.json()["rows"])


def test_student_batch_labels_include_active_semester(client):
    options = client.get("/api/filters").json()
    semester_three = next(item for item in options["semesters"] if item["name"] == "Semester 3")
    response = client.get(
        "/api/records/students",
        params=PERIOD | {"semester_id": semester_three["id"], "page_size": 100},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] > 0
    assert all(row["batch"].startswith("Sem 3") for row in response.json()["rows"])
    academic_labels = {row["batch"] for row in response.json()["rows"] if "Internship" not in row["batch"]}
    assert {"Sem 3A", "Sem 3B", "Sem 3C"} <= academic_labels


def test_batch_filter_options_include_only_active_mapped_semesters(client):
    options = client.get("/api/filters")
    assert options.status_code == 200, options.text
    body = options.json()
    batches = {batch["id"]: set(batch["semester_ids"]) for batch in body["batches"]}
    with psycopg.connect(os.environ.get("TEST_OWNER_DATABASE_URL", settings().database_url)) as c:
        expected = c.execute(
            """SELECT bs.batch_id,yss.semester_id,s.number,b.name,bt.name,gy.start_year,gy.end_year
            FROM batch_semesters bs
            JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
            JOIN semesters s ON s.id=yss.semester_id
            JOIN batches b ON b.id=bs.batch_id
            JOIN batch_types bt ON bt.id=b.batch_type_id
            JOIN year_specializations ys ON ys.id=b.year_specialization_id
            JOIN graduation_years gy ON gy.id=ys.graduation_year_id
            WHERE b.status='active' AND bs.status='active' AND yss.is_active"""
        ).fetchall()
    expected_by_batch = {}
    expected_labels = {}
    for batch_id, semester_id, semester_number, batch_name, batch_type, start_year, end_year in expected:
        expected_by_batch.setdefault(str(batch_id), set()).add(str(semester_id))
        suffix = batch_name.removeprefix("Section ")
        expected_labels[str(batch_id)] = (
            f"{batch_name} · {start_year}–{end_year} · Sem {semester_number}"
            if batch_type == "internship"
            else f"Sem {semester_number}{suffix}"
        )
    assert batches == {batch_id: expected_by_batch.get(batch_id, set()) for batch_id in batches}
    assert {batch["id"]: batch["name"] for batch in body["batches"]} == {
        batch_id: expected_labels[batch_id] for batch_id in batches
    }
    for semester in body["semesters"]:
        eligible = {batch_id for batch_id, semester_ids in batches.items() if semester["id"] in semester_ids}
        assert eligible == {
            batch_id for batch_id, semester_ids in expected_by_batch.items() if semester["id"] in semester_ids
        }


def test_workflow_persistence_evidence_audit_and_concurrency(client, accounts):
    body = {
        "kind": "action",
        "title": "Integration verification action",
        "owner_id": accounts["admin"]["id"],
        "due_date": "2026-10-28",
        "severity": "High",
    }
    response = client.post("/api/work-items", json=body)
    assert response.status_code == 201, response.text
    uid = response.json()["id"]
    update = {
        "version": 1,
        "status": "Done – awaiting verification",
        "owner_id": accounts["admin"]["id"],
        "due_date": "2026-10-28",
        "severity": "High",
        "evidence": "",
    }
    assert client.patch(f"/api/work-items/{uid}", json=update).status_code == 422
    update["evidence"] = "Integration evidence reference"
    assert client.patch(f"/api/work-items/{uid}", json=update).status_code == 200
    assert client.patch(f"/api/work-items/{uid}", json=update).status_code == 409
    update.update(version=2, status="Verified & closed")
    assert client.patch(f"/api/work-items/{uid}", json=update).status_code == 200
    detail = client.get(f"/api/work-items/{uid}").json()
    assert detail["record"]["status"] == "Verified & closed"
    assert len(detail["history"]) == 3
    assert detail["record"]["closed_at"]
    client.post("/api/auth/logout")
    assert (
        client.post(
            "/api/auth/login", json={k: accounts["viewer"][k] for k in ["username", "password"]}
        ).status_code
        == 200
    )
    assert client.get(f"/api/work-items/{uid}").status_code == 200
    assert client.post("/api/work-items", json=body).status_code == 403
    assert client.patch(f"/api/work-items/{uid}", json=update).status_code == 403


def test_support_create_resolve_and_reopen(client, accounts):
    students = client.get("/api/support/students").json()
    response = client.post(
        "/api/support",
        json={
            "user_id": students[0]["id"],
            "category": "other",
            "description": "Integration test report",
            "severity": "High",
            "owner_id": accounts["admin"]["id"],
        },
    )
    assert response.status_code == 201, response.text
    rid = response.json()["id"]
    update = {
        "version": 1,
        "status": "resolved",
        "severity": "Critical",
        "owner_id": accounts["admin"]["id"],
        "note": "Integration resolution",
    }
    response = client.patch(f"/api/support/{rid}", json=update)
    assert response.status_code == 200, response.text
    assert client.patch(f"/api/support/{rid}", json=update).status_code == 409
    update.update(version=2, status="open", note="Integration reopen")
    assert client.patch(f"/api/support/{rid}", json=update).status_code == 200
    assert len(client.get(f"/api/support/{rid}/history").json()) == 3


def test_advanced_plots(client):
    for path in ["attendance-heatmap", "student-scatter", "task-timeline"]:
        response = client.get("/api/plots/" + path, params=PERIOD)
        assert response.status_code == 200, response.text


def test_student_attendance_matrix_pages_complete_active_roster(client):
    first_response = client.get("/api/charts/attendance/matrix", params=PERIOD | {"matrix_page": 1})
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()["charts"][0]
    assert first["page"] == 1
    assert first["page_size"] == 25
    assert first["total"] > first["page_size"]
    assert len(first["row_entities"]) == first["page_size"]
    assert {row["row_id"] for row in first["rows"]} <= {row["id"] for row in first["row_entities"]}

    last_page = (first["total"] + first["page_size"] - 1) // first["page_size"]
    last_response = client.get("/api/charts/attendance/matrix", params=PERIOD | {"matrix_page": last_page})
    assert last_response.status_code == 200, last_response.text
    last = last_response.json()["charts"][0]
    assert last["page"] == last_page
    assert len(last["row_entities"]) == first["total"] - (last_page - 1) * first["page_size"]
    assert {row["id"] for row in first["row_entities"]}.isdisjoint(
        {row["id"] for row in last["row_entities"]}
    )
    dropped = client.get("/api/charts/attendance/matrix", params=PERIOD | {"student_status": "dropped"})
    assert dropped.status_code == 200, dropped.text
    dropped_chart = dropped.json()["charts"][0]
    assert dropped_chart["total"] > 0
    assert "Dropped enrollments" in dropped_chart["note"]
    combined = client.get("/api/charts/attendance/matrix", params=PERIOD | {"student_status": "all"}).json()[
        "charts"
    ][0]
    assert combined["total"] >= max(first["total"], dropped_chart["total"])
    assert (
        client.get(
            "/api/charts/attendance/matrix", params=PERIOD | {"student_status": "inactive"}
        ).status_code
        == 422
    )


def test_attendance_heatmap_percentage_absolute_and_unique_modes(client):
    charts_by_mode = {}
    for mode in ("percentage", "absolute", "unique"):
        response = client.get(
            "/api/charts/trends/overview",
            params=PERIOD | {"metric": "att", "attendance_heatmap_mode": mode},
        )
        assert response.status_code == 200, response.text
        charts_by_mode[mode] = next(chart for chart in response.json()["charts"] if chart["id"] == "trends-5")
        assert charts_by_mode[mode]["heatmap_mode"] == mode

    assert charts_by_mode["percentage"]["unit"] == "%"
    absolute = charts_by_mode["absolute"]
    assert absolute["unit"] == " students"
    assert all(row["sessions"] for row in absolute["rows"])
    assert all(
        len({session["session_id"] for session in row["sessions"]}) == len(row["sessions"])
        for row in absolute["rows"]
    )

    unique = charts_by_mode["unique"]
    assert unique["unit"] == " students"
    sample = unique["rows"][0]
    late_counts_present = client.get("/api/filters").json()["settings"]["late_counts_present"]
    with psycopg.connect(os.environ.get("TEST_OWNER_DATABASE_URL", settings().database_url)) as c:
        expected = c.execute(
            """SELECT count(DISTINCT ar.student_id) FILTER(
              WHERE ar.status='present' OR (%s AND ar.status='late')
            )
            FROM attendance_records ar
            JOIN class_sessions cs ON cs.id=ar.session_id
            JOIN batch_semesters bs ON bs.id=cs.batch_semester_id
            WHERE cs.counts_for_attendance
              AND coalesce(ar.home_batch_id,bs.batch_id)=%s
              AND cs.scheduled_start::date=%s""",
            (late_counts_present, sample["batch_id"], sample["date"][:10]),
        ).fetchone()[0]
        expected_strength = c.execute(
            """SELECT count(DISTINCT student_id) FROM student_batches
            WHERE batch_id=%s AND status='active'""",
            (sample["batch_id"],),
        ).fetchone()[0]
    assert sample["value"] == expected
    assert sample["total_strength"] == expected_strength
    assert (
        client.get(
            "/api/charts/trends/overview",
            params=PERIOD | {"metric": "att", "attendance_heatmap_mode": "total"},
        ).status_code
        == 422
    )


def test_internship_module_uses_real_batches_students_and_sessions(client):
    summary = client.get("/api/internship-summary", params=PERIOD)
    assert summary.status_code == 200, summary.text
    students = client.get("/api/records/internship_students", params=PERIOD | {"page_size": 100})
    sessions = client.get("/api/records/internship_sessions", params=PERIOD | {"page_size": 100})
    assert students.status_code == 200, students.text
    assert sessions.status_code == 200, sessions.text
    with psycopg.connect(os.environ.get("TEST_OWNER_DATABASE_URL", settings().database_url)) as c:
        expected_students = c.execute(
            """SELECT count(*) FROM student_batches sb JOIN batches b ON b.id=sb.batch_id
            JOIN batch_types bt ON bt.id=b.batch_type_id WHERE bt.name='internship'"""
        ).fetchone()[0]
        expected_sessions = c.execute(
            """SELECT count(*) FROM class_sessions cs JOIN batch_semesters bs ON bs.id=cs.batch_semester_id
            JOIN batches b ON b.id=bs.batch_id JOIN batch_types bt ON bt.id=b.batch_type_id
            WHERE bt.name='internship' AND cs.scheduled_start::date BETWEEN %s AND %s""",
            (PERIOD["from_date"], PERIOD["to_date"]),
        ).fetchone()[0]
    assert students.json()["total"] == expected_students
    assert sessions.json()["total"] == expected_sessions
    assert summary.json()["sessions"] == expected_sessions
    charts = client.get("/api/charts/internship/overview", params=PERIOD)
    assert charts.status_code == 200, charts.text
    assert all(chart["status"] == "available" for chart in charts.json()["charts"])


def test_all_original_chart_panels_and_calendar(client):
    manifest = client.get("/api/charts/manifest")
    assert manifest.status_code == 200
    count = 0
    for view, section in manifest.json()["sections"].items():
        for tab in {c["tab"] for c in section["charts"]}:
            response = client.get(f"/api/charts/{view}/{tab}", params=PERIOD)
            assert response.status_code == 200, (view, tab, response.text)
            charts = response.json()["charts"]
            expected = [c for c in section["charts"] if c["tab"] == tab]
            assert {c["id"] for c in charts} == {c["id"] for c in expected}
            count += len(charts)
            for chart in charts:
                assert chart["status"] in {"available", "empty", "unavailable"}
                if chart["status"] == "unavailable":
                    assert chart["rows"] == []
                    assert chart["note"]
    assert count == 97
    calendar = client.get("/api/calendar", params=PERIOD)
    assert calendar.status_code == 200, calendar.text
    assert all(e["id"] and e["source"] for e in calendar.json()["events"])


@pytest.mark.parametrize(
    "metric", ["feedback", "att", "ontime", "missed", "assess", "score", "slaIssue", "taskOn"]
)
def test_trend_metric_intervals(client, metric):
    for interval in ["daily", "weekly", "monthly", "semester"]:
        response = client.get(
            "/api/charts/trends/overview", params=PERIOD | {"metric": metric, "granularity": interval}
        )
        assert response.status_code == 200, response.text
        assert len(response.json()["charts"]) == 5


def test_trend_mentor_and_subject_rankings_use_feedback_average(client):
    response = client.get("/api/charts/trends/overview", params=PERIOD | {"metric": "feedback"})
    assert response.status_code == 200, response.text
    charts = {chart["id"]: chart for chart in response.json()["charts"]}
    with psycopg.connect(os.environ.get("TEST_OWNER_DATABASE_URL", settings().database_url)) as c:
        expected_mentors = c.execute(
            """SELECT fac.name,round(sum(fr.response_text::numeric)/count(*),2),count(*)
            FROM session_feedback_responses fr
            JOIN session_questions sq ON sq.id=fr.session_question_id
            JOIN class_sessions cs ON cs.id=fr.session_id
            JOIN users fac ON fac.id=fr.faculty_id
            WHERE cs.scheduled_start >= %s::date AND cs.scheduled_start < %s::date+1
              AND sq.question_type='rating' AND fr.response_text ~ '^[1-5](\\.0+)?$'
            GROUP BY fac.name ORDER BY 2 DESC,1""",
            (PERIOD["from_date"], PERIOD["to_date"]),
        ).fetchall()
        expected_subjects = c.execute(
            """SELECT su.name,round(sum(fr.response_text::numeric)/count(*),2),count(*)
            FROM session_feedback_responses fr
            JOIN session_questions sq ON sq.id=fr.session_question_id
            JOIN class_sessions cs ON cs.id=fr.session_id
            JOIN subjects su ON su.id=cs.subject_id
            WHERE cs.scheduled_start >= %s::date AND cs.scheduled_start < %s::date+1
              AND sq.question_type='rating' AND fr.response_text ~ '^[1-5](\\.0+)?$'
            GROUP BY su.name ORDER BY 2 DESC,1""",
            (PERIOD["from_date"], PERIOD["to_date"]),
        ).fetchall()
    assert charts["trends-3"]["unit"] == "/5"
    assert charts["trends-3"]["plot_limit"] == 10
    assert [(r["name"], r["value"], r["feedback_count"]) for r in charts["trends-3"]["rows"]] == [
        (name, float(value), count) for name, value, count in expected_mentors
    ]
    assert charts["trends-4"]["unit"] == "/5"
    assert charts["trends-4"]["plot_limit"] == 10
    assert [(r["name"], r["value"], r["feedback_count"]) for r in charts["trends-4"]["rows"]] == [
        (name, float(value), count) for name, value, count in expected_subjects
    ]
    mentor_response = client.get("/api/charts/mentors/feedback", params=PERIOD)
    assert mentor_response.status_code == 200, mentor_response.text
    mentor_charts = mentor_response.json()["charts"]
    assert len(mentor_charts) == 2
    ranking = next(chart for chart in mentor_charts if chart["id"] == "mentors-4")
    assert ranking["id"] == "mentors-4"
    assert ranking["unit"] == "/5"
    assert ranking["plot_limit"] == 5
    assert [(r["name"], r["value"], r["feedback_count"]) for r in ranking["rows"]] == [
        (name, float(value), count) for name, value, count in expected_mentors
    ]
    distribution = next(chart for chart in mentor_charts if chart["id"] == "mentors-5")
    assert distribution["status"] == "available"
    assert {int(float(row["name"])) for row in distribution["rows"]} <= {1, 2, 3, 4, 5}


def test_backend_role_has_minimum_privileges():
    with psycopg.connect(settings().database_url) as c:
        role = c.execute("SELECT current_user").fetchone()[0]
        if role != "polaris_api":
            pytest.skip("Run with the provisioned runtime role to verify privilege boundaries")
        assert not c.execute(
            "SELECT has_table_privilege(current_user,'mis.audit_events','DELETE')"
        ).fetchone()[0]
        assert not c.execute(
            "SELECT has_table_privilege(current_user,'mis.audit_events','UPDATE')"
        ).fetchone()[0]
        assert not c.execute(
            "SELECT has_table_privilege(current_user,'public.auth_sessions','SELECT')"
        ).fetchone()[0]
        assert not c.execute("SELECT has_schema_privilege(current_user,'public','CREATE')").fetchone()[0]
