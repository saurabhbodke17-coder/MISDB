import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
import psycopg

from app.config import settings
from app.db import start_pool, pool
from app.main import app

HEADERS = {"X-Requested-With": "PolarisMIS", "Origin": "http://127.0.0.1:5173"}

@pytest.fixture(scope="module")
def client():
    start_pool()
    c = TestClient(app)
    owner = settings().database_url
    admin_user = "test-admin-risk-dedicated"
    admin_pass = "Password123!"
    with psycopg.connect(owner) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM mis.accounts WHERE username=%s", (admin_user,))
            row = cur.fetchone()
            if not row:
                cur.execute(
                    "INSERT INTO mis.accounts(username,display_name,password_hash,role) VALUES (%s,%s,%s,%s)",
                    (admin_user, "Admin Risk Dedicated", PasswordHash.recommended().hash(admin_pass), "admin")
                )
            else:
                cur.execute(
                    "UPDATE mis.accounts SET password_hash=%s WHERE username=%s",
                    (PasswordHash.recommended().hash(admin_pass), admin_user)
                )
            conn.commit()

    res = c.post("/api/auth/login", json={"username": admin_user, "password": admin_pass}, headers=HEADERS)
    assert res.status_code == 200, f"Login failed: {res.text}"
    yield c


def test_attendance_risk_all_777_students_and_active_interns_excluded(client):
    res = client.get("/api/attendance/risk-students", headers=HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert data["threshold"] == 50.0
    summary = data["summary"]
    students = data["students"]

    assert summary["total_students"] == 777
    assert len(students) == 777
    assert summary["active_interns_count"] in {111, 112}
    assert summary["evaluated_students"] in {665, 666}
    assert summary["at_risk_count"] + summary["no_risk_count"] == summary["evaluated_students"]
    assert summary["dropped_interns_count"] == 17

    for s in students:
        assert "student_id" in s
        assert "student_name" in s
        assert "year" in s
        assert "batch" in s
        assert "semester" in s
        assert "enrollment_status" in s
        assert "is_active_intern" in s
        assert "is_dropped_intern" in s
        assert "risk_status" in s

        # Active interns and dropped interns must be mutually exclusive
        if s["is_active_intern"]:
            assert not s["is_dropped_intern"]
            assert s["risk_status"] == "Active Intern"
        else:
            att = s["attendance_percentage"]
            if att is None or att < 50.0:
                assert s["risk_status"] == "At risk"
            else:
                assert s["risk_status"] == "No risk"


def test_attendance_risk_dynamic_threshold_75(client):
    res_50 = client.get("/api/attendance/risk-students?threshold=50", headers=HEADERS)
    assert res_50.status_code == 200
    data_50 = res_50.json()

    res_75 = client.get("/api/attendance/risk-students?threshold=75", headers=HEADERS)
    assert res_75.status_code == 200
    data_75 = res_75.json()

    assert data_75["threshold"] == 75.0
    assert data_75["summary"]["total_students"] == 777
    assert data_75["summary"]["active_interns_count"] in {111, 112}
    assert data_75["summary"]["evaluated_students"] in {665, 666}
    assert data_75["summary"]["at_risk_count"] >= data_50["summary"]["at_risk_count"]

    for s in data_75["students"]:
        if s["is_active_intern"]:
            assert s["risk_status"] == "Active Intern"
        else:
            att = s["attendance_percentage"]
            if att is None or att < 75.0:
                assert s["risk_status"] == "At risk"
            else:
                assert s["risk_status"] == "No risk"


def test_command_center_kpi_total_students_777(client):
    res = client.get("/api/dashboard", headers=HEADERS)
    assert res.status_code == 200
    kpis = res.json()["kpis"]
    strength_kpi = next(k for k in kpis if k["key"] == "strength")
    assert strength_kpi["value"] == 777
    assert strength_kpi["label"] in {"Total students", "Total Enrolled Students"}


def test_academic_section_empty():
    import json
    with open("backend/app/chart_manifest.json") as f:
        manifest = json.load(f)

    academic_section = manifest["sections"]["academic"]
    assert academic_section["charts"] == []
    assert len(academic_section["tabs"]) == 1
    tab = academic_section["tabs"][0]
    assert "We do not currently store academic performance data in the database" in tab["missing"]

    attendance_tabs = manifest["sections"]["attendance"]["tabs"]
    assert attendance_tabs[0]["id"] == "risk"
    assert attendance_tabs[0]["label"] == "Students at Risk (Based on Attendance)"
    assert attendance_tabs[1]["id"] == "overall"
    assert attendance_tabs[1]["label"] == "Overall attendance"


def test_student_records_source_includes_all_777_students():
    from app.analytics import Filters
    from app.records import source_query
    from app.db import query

    f = Filters()
    _, sql, p = source_query("students", f, apply_dates=False)
    rows = query(sql, p)
    unique_ids = set(r["student_id"] for r in rows)
    assert len(unique_ids) == 777

    # Ensure unassigned students (without batch) are present
    unassigned = [r for r in rows if r["batch"] == "Unassigned"]
    assert len(unassigned) == 3

    # Ensure admin accounts (e.g. Swati Singh) are not included
    admin_matches = [r for r in rows if "swati" in r["student"].lower()]
    assert len(admin_matches) == 0


def test_overall_attendance_ignores_active_interns(client):
    from app.analytics import Filters
    from app.chart_data import charts

    f = Filters()
    res = charts("attendance", tab="overall", f=f)
    assert len(res["charts"]) == 1
    chart = res["charts"][0]
    assert chart["id"] == "attendance-overall"
    # Note mentions active interns excluded
    assert "Active internship students are excluded from the attendance pool" in chart["note"]


def test_kpi_and_chart_attendance_delivery_alignment_on_custom_dates(client):
    for test_date in ["2026-11-13", "2026-11-12"]:
        dash_res = client.get(f"/api/dashboard?from_date={test_date}&to_date={test_date}", headers=HEADERS)
        assert dash_res.status_code == 200
        dash = dash_res.json()
        kpis = {k["key"]: k for k in dash["kpis"]}

        chart_res = client.get(f"/api/charts/command/overview?from_date={test_date}&to_date={test_date}&granularity=daily", headers=HEADERS)
        assert chart_res.status_code == 200
        chart_data = {c["id"]: c for c in chart_res.json()["charts"]}

        # Attendance KPI must match chart point exactly
        att_kpi = kpis["attendance"]["value"]
        att_chart_val = float(chart_data["command-1"]["rows"][0]["value"])
        assert att_kpi == att_chart_val, f"Date {test_date}: Attendance KPI {att_kpi} != chart {att_chart_val}"

        # Delivery KPI must match chart point exactly
        del_kpi = kpis["delivery"]["value"]
        del_chart_val = float(chart_data["command-2"]["rows"][0]["value"])
        assert del_kpi == del_chart_val, f"Date {test_date}: Delivery KPI {del_kpi} != chart {del_chart_val}"


def test_classes_missed_or_cancelled_calculation(client):
    # Test Nov 13 has 1 missed session
    dash_13 = client.get("/api/dashboard?from_date=2026-11-13&to_date=2026-11-13", headers=HEADERS).json()
    missed_13 = next(k for k in dash_13["kpis"] if k["key"] == "missed")
    assert missed_13["value"] == 1
    assert "1 missed or cancelled" in missed_13["evidence"]

    # Test full available period has recorded missed sessions
    dash_all = client.get("/api/dashboard?from_date=2024-01-01&to_date=2027-01-01", headers=HEADERS).json()
    missed_all = next(k for k in dash_all["kpis"] if k["key"] == "missed")
    assert missed_all["value"] >= 133
    assert f"{missed_all['value']} missed or cancelled" in missed_all["evidence"]



