import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from .analytics import BATCH_SCOPE, Filters, filters, metric_settings, params
from .auth import current_user
from .catalog import SOURCES, Source
from .config import settings
from .db import one, query, read_connection
from .production_sources import PROJECTIONS

router = APIRouter(prefix="/records", tags=["Registers"])
HIDDEN = {
    "student_id",
    "session_id",
    "batch_id",
    "batch_ids",
    "linked_batches",
    "mentor_id",
    "mentor_ids",
    "semester_id",
    "specialization_id",
    "graduation_year_id",
    "student_email",
    "mentor_emails",
}


def source_query(
    name,
    f,
    search="",
    status="",
    apply_dates=True,
    preset="",
    account_id=None,
    attendance_band="",
    score_band="",
    risk_status="",
):
    source = SOURCES.get(name)
    if name in PROJECTIONS:
        if not settings().source_database_url:
            raise HTTPException(409, "This source requires the production database connection.")
        source = Source(**PROJECTIONS[name], scope="external_student")
    if source is None:
        raise HTTPException(404, "Unknown register")
    if settings().source_database_url and "mis." in source.sql.lower():
        raise HTTPException(
            409,
            "This dataset is unavailable because production does not provide the required source tables. Local snapshot fallback is disabled.",
        )
    if name == "attendance" and status and status not in {"present", "absent"}:
        raise HTTPException(422, "Attendance status must be present or absent")
    if (
        name in {"sessions", "internship_sessions"}
        and status
        and status not in {"completed", "cancelled", "scheduled", "in_progress"}
    ):
        raise HTTPException(
            422, "Class delivery status must be completed, cancelled, scheduled or in progress"
        )
    attendance_filters = {
        "below40": "r.attendance<40",
        "40to59": "r.attendance>=40 AND r.attendance<60",
        "60to74": "r.attendance>=60 AND r.attendance<75",
        "75plus": "r.attendance>=75",
        "no_evidence": "r.attendance IS NULL",
    }
    score_filters = {
        "below40": "r.average_score<40",
        "40to59": "r.average_score>=40 AND r.average_score<60",
        "60to79": "r.average_score>=60 AND r.average_score<80",
        "80plus": "r.average_score>=80",
        "not_evaluated": "r.average_score IS NULL",
    }
    risk_statuses = {"High Risk", "No Risk", "No attendance evidence"}
    if name != "students" and any((attendance_band, score_band, risk_status)):
        raise HTTPException(422, "Student performance filters apply only to the student register")
    if attendance_band and attendance_band not in attendance_filters:
        raise HTTPException(422, "Unknown attendance band")
    if score_band and score_band not in score_filters:
        raise HTTPException(422, "Unknown score band")
    if risk_status and risk_status not in risk_statuses:
        raise HTTPException(422, "Unknown risk status")
    conditions = ["true"]
    p = (
        params(f)
        | metric_settings()
        | {
            "search": f"%{search}%",
            "status_filter": status,
            "risk_status_filter": risk_status,
        }
    )
    has_scope = any((f.batch_id, f.specialization_id, f.semester_id, f.graduation_year_id))
    if source.scope == "external_student":
        if has_scope:
            conditions.append("""EXISTS (
              SELECT 1 FROM "LMS".users u JOIN "LMS".student_batches sb ON sb.student_id=u.id
              WHERE lower(trim(u.email))=r.student_email AND sb.status='active'
                AND sb.batch_id IN (SELECT id FROM scoped_batches))""")
        if f.mentor_id:
            if name != "ojt_allocations":
                raise HTTPException(
                    409,
                    "This production source has no verified mentor relationship. Clear the Mentor filter to view these records.",
                )
            conditions.append("""EXISTS (SELECT 1 FROM "LMS".users u
              WHERE u.id=%(mentor_id)s AND lower(trim(u.email))=ANY(r.mentor_emails))""")
    if source.date_filter and apply_dates:
        conditions.append("r.date >= %(from_date)s::date AND r.date < %(to_date)s::date+1")
    if source.scope in {"batch", "student"}:
        batch_expr = "r.batch_id IN (SELECT id FROM scoped_batches)"
        if name in {"sessions", "internship_sessions"}:
            batch_expr = f"({batch_expr} OR r.linked_batches && ARRAY(SELECT id FROM scoped_batches))"
        conditions.append(batch_expr)
    if source.scope == "work" and has_scope:
        conditions.append("r.batch_id IN (SELECT id FROM scoped_batches)")
    if source.scope == "multi" and has_scope:
        conditions.append("r.batch_ids && ARRAY(SELECT id FROM scoped_batches)")
    if source.scope == "calendar" and has_scope:
        conditions.append(
            "EXISTS(SELECT 1 FROM batches b JOIN year_specializations ys ON ys.id=b.year_specialization_id WHERE b.id IN (SELECT id FROM scoped_batches) AND ys.graduation_year_id=r.graduation_year_id)"
        )
    if source.scope == "announcement" and has_scope:
        conditions.append("""(r.batch_id IN (SELECT id FROM scoped_batches) OR (r.batch_id IS NULL AND EXISTS (
            SELECT 1 FROM batches b JOIN year_specializations ys ON ys.id=b.year_specialization_id
            WHERE b.id IN (SELECT id FROM scoped_batches) AND ys.graduation_year_id=r.graduation_year_id
            AND (r.specialization_id IS NULL OR r.specialization_id=ys.specialization_id))))""")
    if source.scope == "batch":
        conditions.append("(%(semester_id)s::uuid IS NULL OR r.semester_id=%(semester_id)s)")
        conditions.append(
            "(%(mentor_id)s::uuid IS NULL OR "
            + ("%(mentor_id)s=ANY(r.mentor_ids)" if name == "assignments" else "r.mentor_id=%(mentor_id)s")
            + ")"
        )
    if source.scope == "student":
        conditions.append("(%(semester_id)s::uuid IS NULL OR r.semester_id=%(semester_id)s)")
    if source.scope == "calendar":
        conditions.append(
            "(%(semester_id)s::uuid IS NULL OR r.semester_id IS NULL OR r.semester_id=%(semester_id)s)"
        )
    if search:
        # Search only the same allowlisted fields presented in the register.
        conditions.append(
            "concat_ws(' '," + ",".join(f'r."{c}"::text' for c in source.columns) + ") ILIKE %(search)s"
        )
    if status and "status" in source.columns:
        conditions.append("r.status=%(status_filter)s")
    p["account_id"] = account_id
    if source.scope == "work":
        mode = preset.split(":")[-1]
        work_filters = {
            "mine": "r.owner_id=%(account_id)s::uuid",
            "overdue": "r.due_date<%(to_date)s AND r.status NOT IN ('Verified & closed','Done – awaiting verification')",
            "critical": "r.severity='Critical' AND r.status<>'Verified & closed'",
            "today": "r.due_date=%(to_date)s AND r.status<>'Verified & closed'",
            "week": "r.due_date BETWEEN %(to_date)s AND %(to_date)s::date+7 AND r.status<>'Verified & closed'",
            "verify": "r.status='Done – awaiting verification'",
            "reopened": "r.status='Reopened'",
            "blocked": "r.status='Blocked'",
        }
        if mode in work_filters:
            conditions.append(work_filters[mode])
            # Snapshot queues must include older due dates and future seven-day priorities.
            conditions = [
                c for c in conditions if c != "r.date >= %(from_date)s::date AND r.date < %(to_date)s::date+1"
            ]
    if name == "support":
        if preset == "tickets:breach":
            conditions.append("r.status<>'resolved' AND r.sla_due<%(to_date)s::date+1")
            conditions = [
                c for c in conditions if c != "r.date >= %(from_date)s::date AND r.date < %(to_date)s::date+1"
            ]
        elif preset == "tickets:feedback":
            conditions.append("r.status='resolved'")
        elif preset == "tickets:queue":
            conditions.append("r.status<>'resolved'")
    if name == "students" and attendance_band:
        conditions.append(attendance_filters[attendance_band])
    if name == "students" and score_band:
        conditions.append(score_filters[score_band])
    if name == "students" and risk_status:
        conditions.append("r.risk=%(risk_status_filter)s")
    if name == "students" and preset == "academic:risk":
        conditions.append("r.status='active'")
        if not attendance_band:
            conditions.append("r.attendance<%(risk_attendance)s")
    elif name == "students" and preset == "exceptions:students":
        conditions.append("r.status='active' AND cardinality(r.risk_reasons)>0")
    return (
        source,
        f"WITH scoped_batches AS ({BATCH_SCOPE}), r AS ({source.sql}) SELECT * FROM r WHERE "
        + " AND ".join(conditions),
        p,
    )


def visible(row):
    return {k: v for k, v in row.items() if k not in HIDDEN}


@router.get("/{name}")
def records(
    name: str,
    f: Filters = Depends(filters),
    search: str = Query(default="", max_length=200),
    status: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=100),
    sort: str = "date",
    direction: str = "desc",
    preset: str = Query(default="", max_length=80),
    attendance_band: str = Query(default="", max_length=40),
    score_band: str = Query(default="", max_length=40),
    risk_status: str = Query(default="", max_length=80),
    user=Depends(current_user),
):
    source, sql, p = source_query(
        name,
        f,
        search,
        status,
        preset=preset,
        account_id=user.get("id"),
        attendance_band=attendance_band,
        score_band=score_band,
        risk_status=risk_status,
    )
    sort = sort if sort in source.columns or sort == "date" else "date"
    direction = "ASC" if direction == "asc" else "DESC"
    total = one(f"SELECT count(*) AS total FROM ({sql}) counted", p)["total"]
    rows = query(
        sql + f' ORDER BY "{sort}" {direction} NULLS LAST,id LIMIT %(limit)s OFFSET %(offset)s',
        p | {"limit": page_size, "offset": (page - 1) * page_size},
    )
    return {
        "title": source.title,
        "columns": source.columns,
        "rows": [visible(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "note": source.note,
        "scope": source.scope,
    }


def csv_cell(value):
    text = "" if value is None else str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text


@router.get("/{name}/summary")
def summary(
    name: str,
    f: Filters = Depends(filters),
    search: str = Query(default="", max_length=200),
    status: str = "",
    preset: str = Query(default="", max_length=80),
    attendance_band: str = Query(default="", max_length=40),
    score_band: str = Query(default="", max_length=40),
    risk_status: str = Query(default="", max_length=80),
    user=Depends(current_user),
):
    source, sql, p = source_query(
        name,
        f,
        search,
        status,
        preset=preset,
        account_id=user.get("id"),
        attendance_band=attendance_band,
        score_band=score_band,
        risk_status=risk_status,
    )
    group = next(
        (k for k in ("status", "category", "severity", "approval_status", "batch") if k in source.columns),
        None,
    )
    groups = (
        query(
            f"SELECT coalesce(\"{group}\"::text,'Unspecified') AS name,count(*) AS value FROM ({sql}) x GROUP BY 1 ORDER BY 2 DESC LIMIT 20",
            p,
        )
        if group
        else []
    )
    daily = query(
        f"SELECT date::date AS date,count(*) AS value FROM ({sql}) x WHERE date IS NOT NULL GROUP BY 1 ORDER BY 1",
        p,
    )
    return {
        "groups": groups,
        "daily": daily,
        "group_by": group,
        "total": one(f"SELECT count(*) AS n FROM ({sql}) x", p)["n"],
    }


@router.get("/{name}/export")
def export(
    name: str,
    f: Filters = Depends(filters),
    search: str = Query(default="", max_length=200),
    status: str = "",
    preset: str = Query(default="", max_length=80),
    attendance_band: str = Query(default="", max_length=40),
    score_band: str = Query(default="", max_length=40),
    risk_status: str = Query(default="", max_length=80),
    user=Depends(current_user),
):
    source, sql, p = source_query(
        name,
        f,
        search,
        status,
        preset=preset,
        account_id=user.get("id"),
        attendance_band=attendance_band,
        score_band=score_band,
        risk_status=risk_status,
    )

    def generate_csv():
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(source.columns)
        yield stream.getvalue()
        stream.seek(0)
        stream.truncate(0)
        with read_connection(sql) as conn, conn.cursor(name=f"export_{name}") as cursor:
            cursor.execute(sql + " ORDER BY date DESC NULLS LAST,id", p)
            while rows := cursor.fetchmany(1000):
                for row in rows:
                    writer.writerow([csv_cell(row.get(c)) for c in source.columns])
                yield stream.getvalue()
                stream.seek(0)
                stream.truncate(0)

    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="polaris-{name}.csv"'},
    )


@router.get("/{name}/{record_id}")
def detail(name: str, record_id: str, f: Filters = Depends(filters), user=Depends(current_user)):
    if len(record_id) > 200:
        raise HTTPException(422, "Invalid record identifier")
    source, sql, p = source_query(name, f, apply_dates=False)
    row = one(f"SELECT * FROM ({sql}) selected WHERE id::text=%(record_id)s", p | {"record_id": record_id})
    if not row and name == "attendance":
        try:
            ses_source, ses_sql, ses_p = source_query("sessions", f, apply_dates=False)
            row = one(
                f"SELECT * FROM ({ses_sql}) selected WHERE id::text=%(record_id)s",
                ses_p | {"record_id": record_id},
            )
            if row:
                source = ses_source
                name = "sessions"
        except Exception:
            pass
    if not row:
        raise HTTPException(404, "Record not found in this filter scope")
    if name == "sessions":
        att_stats = one(
            """
            SELECT 
                count(*) FILTER(WHERE status='present' OR (%(late_counts_present)s AND status='late')) AS present_students,
                count(*) FILTER(WHERE status='absent') AS absent_students,
                count(*) FILTER(WHERE status IN ('present', 'late', 'absent')) AS total_students
            FROM attendance_records
            WHERE session_id = %(session_id)s::uuid
            """,
            metric_settings() | {"session_id": record_id},
        )
        if att_stats and att_stats.get("total_students"):
            total = att_stats["total_students"]
            present = att_stats["present_students"] or 0
            row["total_students"] = total
            row["present_students"] = present
            row["absent_students"] = att_stats["absent_students"] or 0
            row["attendance_rate"] = f"{round(present * 100.0 / total, 1)}%"
    return {"record": visible(row), "title": source.title}
