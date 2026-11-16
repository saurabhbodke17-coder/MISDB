from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from .auth import current_user
from .config import settings
from .db import one, query

router = APIRouter(tags=["Analytics"])
IST = ZoneInfo("Asia/Kolkata")


def today_ist() -> date:
    """Return the current calendar date in Indian Standard Time (Asia/Kolkata)."""
    return datetime.now(IST).date()


class Filters(BaseModel):
    from_date: date = date(2026, 10, 1)
    to_date: date = date(2026, 10, 28)
    batch_id: UUID | None = None
    specialization_id: UUID | None = None
    semester_id: UUID | None = None
    graduation_year_id: UUID | None = None
    mentor_id: UUID | None = None

    @model_validator(mode="after")
    def dates(self):
        if self.from_date > self.to_date or (self.to_date - self.from_date).days > 1096:
            raise ValueError("Choose a valid date range of at most three years")
        return self


def filters(
    from_date: date | None = None,
    to_date: date | None = None,
    batch_id: UUID | None = None,
    specialization_id: UUID | None = None,
    semester_id: UUID | None = None,
    graduation_year_id: UUID | None = None,
    mentor_id: UUID | None = None,
):
    end = to_date or today_ist()
    try:
        return Filters(
            from_date=from_date or end - timedelta(days=27),
            to_date=end,
            batch_id=batch_id,
            specialization_id=specialization_id,
            semester_id=semester_id,
            graduation_year_id=graduation_year_id,
            mentor_id=mentor_id,
        )
    except ValueError as exc:
        raise HTTPException(422, "Choose an ordered date range of at most three years") from exc


BATCH_SCOPE = """
SELECT b.id FROM batches b
JOIN year_specializations ys ON ys.id=b.year_specialization_id
WHERE (%(batch_id)s::uuid IS NULL OR b.id=%(batch_id)s)
AND (%(specialization_id)s::uuid IS NULL OR ys.specialization_id=%(specialization_id)s)
AND (%(graduation_year_id)s::uuid IS NULL OR ys.graduation_year_id=%(graduation_year_id)s)
AND (%(semester_id)s::uuid IS NULL OR EXISTS (
  SELECT 1 FROM batch_semesters bs JOIN year_specialization_semesters yss
  ON yss.id=bs.year_specialization_semester_id WHERE bs.batch_id=b.id AND yss.semester_id=%(semester_id)s))
"""

SESSION_SCOPE = """
SELECT cs.id, cs.batch_semester_id, cs.subject_id, cs.faculty_id, cs.title,
  cs.scheduled_start, cs.scheduled_end,
  CASE
    WHEN cs.status IN ('scheduled', 'in_progress') AND (coalesce(cs.scheduled_end, cs.scheduled_start + interval '1 hour') + interval '15 minutes') < now() AT TIME ZONE 'UTC' THEN
      CASE WHEN EXISTS (SELECT 1 FROM attendance_records ar WHERE ar.session_id = cs.id) THEN 'completed'
           ELSE 'missed' END
    ELSE cs.status
  END AS status,
  cs.counts_for_attendance, cs.created_at, cs.updated_at, bs.batch_id
FROM class_sessions cs
JOIN batch_semesters bs ON bs.id=cs.batch_semester_id
JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
JOIN subjects su ON su.id=cs.subject_id
WHERE cs.scheduled_start >= %(from_date)s::date AND cs.scheduled_start < %(to_date)s::date+1
AND bs.batch_id IN (SELECT id FROM scoped_batches)
AND (%(semester_id)s::uuid IS NULL OR yss.semester_id=%(semester_id)s)
AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id=%(mentor_id)s)
AND su.name !~* 'eval'
"""


def params(f):
    return f.model_dump()


def metric_settings():
    return one("SELECT value FROM mis.settings WHERE key='metrics'")["value"]


def optional_source_count(source, f, condition="true"):
    """A missing optional source must not prevent the academic dashboard loading."""
    from .records import source_query

    try:
        _, sql, p = source_query(source, f, apply_dates=False)
    except HTTPException as exc:
        if exc.status_code == 409:
            return None
        raise
    return one(f"SELECT count(DISTINCT id) AS n FROM ({sql}) x WHERE {condition}", p)["n"]


@router.get("/filters")
def options(user=Depends(current_user)):
    return {
        "batches": query(
            """SELECT b.id,
              CASE
                WHEN bt.name='internship' THEN concat(
                  b.name,' · ',gy.start_year,'–',gy.end_year,' · Sem ',
                  max(s.number) FILTER (WHERE bs.status='active' AND yss.is_active)
                )
                WHEN b.name ~* '^Section[[:space:]]+' THEN concat(
                  'Sem ',
                  max(s.number) FILTER (WHERE bs.status='active' AND yss.is_active),
                  regexp_replace(b.name, '^Section[[:space:]]+', '', 'i')
                )
                ELSE concat(
                  'Sem ',
                  max(s.number) FILTER (WHERE bs.status='active' AND yss.is_active),
                  ' ', b.name
                )
              END AS name,
              ys.specialization_id,ys.graduation_year_id,
              coalesce(array_agg(DISTINCT yss.semester_id) FILTER (
                WHERE yss.semester_id IS NOT NULL AND bs.status='active' AND yss.is_active
              ),'{}') AS semester_ids
            FROM batches b
            JOIN year_specializations ys ON ys.id=b.year_specialization_id
            JOIN graduation_years gy ON gy.id=ys.graduation_year_id
            JOIN batch_types bt ON bt.id=b.batch_type_id
            LEFT JOIN batch_semesters bs ON bs.batch_id=b.id
            LEFT JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
            LEFT JOIN semesters s ON s.id=yss.semester_id
            WHERE b.status='active'
            GROUP BY b.id,b.name,bt.name,gy.start_year,gy.end_year,ys.specialization_id,ys.graduation_year_id
            HAVING count(*) FILTER (WHERE bs.status='active' AND yss.is_active)>0
            ORDER BY max(s.number) FILTER (WHERE bs.status='active' AND yss.is_active),b.name"""
        ),
        "programs": query("SELECT id,name FROM specializations ORDER BY name"),
        "semesters": query("SELECT id,name FROM semesters ORDER BY number"),
        "years": query(
            "SELECT id,start_year::text || '–' || end_year::text AS name FROM graduation_years ORDER BY start_year DESC"
        ),
        "mentors": query(
            "SELECT DISTINCT u.id,u.name FROM users u JOIN class_sessions cs ON cs.faculty_id=u.id ORDER BY u.name"
        ),
        "subjects": query(
            "SELECT DISTINCT su.id, su.name FROM subjects su JOIN class_sessions cs ON cs.subject_id=su.id WHERE su.name !~* 'eval' ORDER BY su.name"
        ),
        "data_range": one(
            "SELECT min(d) AS first_date,max(d) AS last_date FROM (SELECT scheduled_start::date d FROM class_sessions UNION ALL SELECT due_at::date FROM assignments UNION ALL SELECT date FROM examinations UNION ALL SELECT start_date FROM academic_calendar UNION ALL SELECT start_date FROM holidays UNION ALL SELECT publish_at::date FROM announcements) dates"
        ),
        "settings": metric_settings(),
    }


@router.get("/internship-summary")
def internship_summary(f: Filters = Depends(filters), user=Depends(current_user)):
    p = params(f) | metric_settings()
    return one(
        f"""WITH scoped_batches AS ({BATCH_SCOPE}), internship_batches AS (
          SELECT b.id FROM batches b JOIN batch_types bt ON bt.id=b.batch_type_id
          WHERE bt.name='internship' AND b.id IN (SELECT id FROM scoped_batches)
        ), memberships AS (
          SELECT count(*) FILTER(WHERE sb.status='active') AS active_students,
            count(*) FILTER(WHERE sb.status='dropped') AS dropped_students,
            count(DISTINCT sb.batch_id) AS batches
          FROM student_batches sb WHERE sb.batch_id IN (SELECT id FROM internship_batches)
        ), sessions AS (
          SELECT count(*) AS sessions,
            count(*) FILTER(WHERE cs.status='completed') AS completed_sessions,
            count(*) FILTER(WHERE live.actual_start IS NOT NULL) AS sessions_with_telemetry,
            count(*) FILTER(WHERE NOT (live.actual_start IS NOT NULL AND
              live.actual_start>cs.scheduled_start AT TIME ZONE 'UTC'+make_interval(mins=>%(late_tolerance)s))) AS on_time_sessions
          FROM class_sessions cs
          JOIN batch_semesters bs ON bs.id=cs.batch_semester_id
          JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
          LEFT JOIN LATERAL (
            SELECT min(actual_start) AS actual_start FROM live_sessions WHERE class_session_id=cs.id
          ) live ON true
          WHERE bs.batch_id IN (SELECT id FROM internship_batches)
            AND cs.scheduled_start >= %(from_date)s::date AND cs.scheduled_start < %(to_date)s::date+1
            AND (%(semester_id)s::uuid IS NULL OR yss.semester_id=%(semester_id)s)
            AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id=%(mentor_id)s)
        )
        SELECT memberships.*,sessions.*,
          round(100.0*completed_sessions/nullif(sessions,0),1) AS completion_rate,
          round(100.0*sessions_with_telemetry/nullif(sessions,0),1) AS telemetry_coverage,
          round(100.0*on_time_sessions/nullif(sessions,0),1) AS on_time_rate
        FROM memberships CROSS JOIN sessions""",
        p,
    )


@router.get("/attendance/risk-students")
def attendance_risk_students(
    threshold: float = 50.0,
    f: Filters = Depends(filters),
    user=Depends(current_user),
):
    p = params(f) | metric_settings()

    sql = """
    WITH student_base AS (
        SELECT 
            u.id AS student_id,
            u.name AS student_name,
            u.email,
            u.is_active AS lms_active,
            EXISTS (
                SELECT 1 FROM student_batches sb 
                JOIN batches b ON b.id=sb.batch_id 
                JOIN batch_types bt ON bt.id=b.batch_type_id 
                WHERE sb.student_id=u.id AND sb.status='active' AND bt.name='internship'
            ) AS is_active_intern,
            (
                EXISTS (
                    SELECT 1 FROM student_batches sb 
                    JOIN batches b ON b.id=sb.batch_id 
                    JOIN batch_types bt ON bt.id=b.batch_type_id 
                    WHERE sb.student_id=u.id AND sb.status='dropped' AND bt.name='internship'
                )
                AND NOT EXISTS (
                    SELECT 1 FROM student_batches sb 
                    JOIN batches b ON b.id=sb.batch_id 
                    JOIN batch_types bt ON bt.id=b.batch_type_id 
                    WHERE sb.student_id=u.id AND sb.status='active' AND bt.name='internship'
                )
            ) AS is_dropped_intern,
            EXISTS (
                SELECT 1 FROM student_batches sb 
                JOIN batches b ON b.id=sb.batch_id 
                JOIN batch_types bt ON bt.id=b.batch_type_id 
                WHERE sb.student_id=u.id AND sb.status='active' AND bt.name='academics'
            ) AS has_active_academic,
            EXISTS (
                SELECT 1 FROM student_batches sb 
                JOIN batches b ON b.id=sb.batch_id 
                JOIN batch_types bt ON bt.id=b.batch_type_id 
                WHERE sb.student_id=u.id AND sb.status='dropped' AND bt.name='academics'
            ) AS has_dropped_academic
        FROM users u
        JOIN roles r ON r.id=u.role_id AND r.name='student'
    ),
    student_academic_info AS (
        SELECT DISTINCT ON (sb.student_id)
            sb.student_id,
            concat(gy.start_year, '–', gy.end_year) AS year,
            b.name AS batch,
            coalesce('Sem ' || s.number::text, '—') AS semester,
            sb.status AS enrollment_status,
            b.id AS batch_id,
            ys.specialization_id,
            gy.id AS graduation_year_id,
            s.id AS semester_id
        FROM student_batches sb
        JOIN batches b ON b.id=sb.batch_id
        JOIN batch_types bt ON bt.id=b.batch_type_id
        LEFT JOIN year_specializations ys ON ys.id=b.year_specialization_id
        LEFT JOIN graduation_years gy ON gy.id=ys.graduation_year_id
        LEFT JOIN batch_semesters bs ON bs.batch_id=b.id AND bs.status='active'
        LEFT JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
        LEFT JOIN semesters s ON s.id=yss.semester_id
        ORDER BY sb.student_id, 
                 (CASE WHEN bt.name='academics' AND sb.status='active' THEN 1 
                       WHEN bt.name='academics' THEN 2 
                       WHEN sb.status='active' THEN 3 
                       ELSE 4 END), 
                 sb.joined_at DESC NULLS LAST
    ),
    student_att AS (
        SELECT 
            ar.student_id,
            count(ar.id) AS total_classes,
            count(ar.id) FILTER (WHERE ar.status = 'present' OR (%(late_counts_present)s AND ar.status = 'late')) AS present_classes,
            round(100.0 * count(ar.id) FILTER (WHERE ar.status = 'present' OR (%(late_counts_present)s AND ar.status = 'late')) / nullif(count(ar.id), 0), 1) AS attendance_percentage
        FROM attendance_records ar
        JOIN class_sessions cs ON cs.id = ar.session_id AND cs.counts_for_attendance
        JOIN subjects su ON su.id = cs.subject_id
        WHERE cs.scheduled_start >= %(from_date)s::date AND cs.scheduled_start < %(to_date)s::date + 1
          AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id = %(mentor_id)s::uuid)
          AND su.name !~* 'eval'
        GROUP BY ar.student_id
    )
    SELECT 
        sb.student_id,
        sb.student_name,
        sb.email,
        sb.lms_active,
        sb.is_active_intern,
        sb.is_dropped_intern,
        sb.has_active_academic,
        sb.has_dropped_academic,
        coalesce(sai.year, '—') AS year,
        coalesce(sai.batch, 'Unassigned') AS batch,
        coalesce(sai.semester, '—') AS semester,
        coalesce(sai.enrollment_status, 'unassigned') AS enrollment_status,
        coalesce(att.total_classes, 0) AS total_classes,
        coalesce(att.present_classes, 0) AS present_classes,
        att.attendance_percentage
    FROM student_base sb
    LEFT JOIN student_academic_info sai ON sai.student_id = sb.student_id
    LEFT JOIN student_att att ON att.student_id = sb.student_id
    WHERE (%(batch_id)s::uuid IS NULL OR sai.batch_id = %(batch_id)s::uuid)
      AND (%(specialization_id)s::uuid IS NULL OR sai.specialization_id = %(specialization_id)s::uuid)
      AND (%(graduation_year_id)s::uuid IS NULL OR sai.graduation_year_id = %(graduation_year_id)s::uuid)
      AND (%(semester_id)s::uuid IS NULL OR sai.semester_id = %(semester_id)s::uuid)
    ORDER BY sb.student_name
    """
    rows = query(sql, p)
    students = []
    active_interns_count = 0
    dropped_interns_count = 0
    at_risk_count = 0
    no_risk_count = 0
    total_attendance = 0.0
    valid_attendance_count = 0

    for r in rows:
        att = float(r["attendance_percentage"]) if r["attendance_percentage"] is not None else 0.0
        is_active_intern = bool(r["is_active_intern"])
        is_dropped_intern = bool(r["is_dropped_intern"])
        if is_dropped_intern:
            dropped_interns_count += 1

        if is_active_intern:
            active_interns_count += 1
            risk_status = "Active Intern"
        else:
            is_risk = att < threshold
            if is_risk:
                at_risk_count += 1
                risk_status = "At risk"
            else:
                no_risk_count += 1
                risk_status = "No risk"

            if r["attendance_percentage"] is not None:
                total_attendance += att
                valid_attendance_count += 1

        students.append({
            "id": str(r["student_id"]),
            "student_id": str(r["student_id"]),
            "student_name": r["student_name"],
            "email": r["email"],
            "lms_active": bool(r["lms_active"]),
            "enrollment_status": r["enrollment_status"],
            "is_active_intern": is_active_intern,
            "is_dropped_intern": is_dropped_intern,
            "year": r["year"],
            "batch": r["batch"],
            "semester": r["semester"],
            "total_classes": r["total_classes"],
            "present_classes": r["present_classes"],
            "attendance_percentage": float(r["attendance_percentage"]) if r["attendance_percentage"] is not None else None,
            "risk_status": risk_status,
        })

    total = len(students)
    evaluated = total - active_interns_count
    return {
        "threshold": threshold,
        "summary": {
            "total_students": total,
            "active_interns_count": active_interns_count,
            "active_interns_pct": round(100.0 * active_interns_count / total, 1) if total else 0.0,
            "evaluated_students": evaluated,
            "at_risk_count": at_risk_count,
            "at_risk_pct": round(100.0 * at_risk_count / evaluated, 1) if evaluated else 0.0,
            "no_risk_count": no_risk_count,
            "no_risk_pct": round(100.0 * no_risk_count / evaluated, 1) if evaluated else 0.0,
            "dropped_interns_count": dropped_interns_count,
            "average_attendance": round(total_attendance / valid_attendance_count, 1) if valid_attendance_count else 0.0,
        },
        "students": students,
    }


def aggregates(f):
    p = params(f) | metric_settings()
    return one(
        f"""WITH scoped_batches AS ({BATCH_SCOPE}), scoped_sessions AS ({SESSION_SCOPE}),
    attendance_records_scoped AS (
      SELECT 
        ar.id,
        ar.status,
        cs.scheduled_start::date AS date
      FROM attendance_records ar
      JOIN class_sessions cs ON cs.id = ar.session_id
      JOIN batch_semesters bs ON bs.id = cs.batch_semester_id
      JOIN year_specialization_semesters yss ON yss.id = bs.year_specialization_semester_id
      JOIN subjects su ON su.id = cs.subject_id
      WHERE cs.counts_for_attendance
        AND cs.scheduled_start >= %(from_date)s::date AND cs.scheduled_start < %(to_date)s::date + 1
        AND bs.batch_id IN (SELECT id FROM scoped_batches)
        AND (%(semester_id)s::uuid IS NULL OR yss.semester_id = %(semester_id)s)
        AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id = %(mentor_id)s)
        AND su.name !~* 'eval'
    ),
    attendance AS (
      SELECT 
        coalesce(count(*) FILTER (WHERE status='present' OR (%(late_counts_present)s AND status='late')), 0) AS present,
        coalesce(count(*) FILTER (WHERE status IN ('present', 'late', 'absent')), 0) AS eligible,
        coalesce(count(*) FILTER (WHERE status='absent'), 0) AS absent,
        count(DISTINCT date) AS days_count,
        count(*) AS recorded
      FROM attendance_records_scoped
    )
    ,delivery AS (
      SELECT 
        count(*) FILTER (WHERE s.scheduled_start <= now() AT TIME ZONE 'UTC') AS scheduled, 
        count(*) FILTER (WHERE s.status='completed') AS completed,
        count(*) FILTER (WHERE (coalesce(s.scheduled_end, s.scheduled_start + interval '1 hour') + interval '15 minutes') < now() AT TIME ZONE 'UTC' AND (l.actual_start IS NOT NULL OR s.status='completed')) AS actual_recorded,
        count(*) FILTER (WHERE (coalesce(s.scheduled_end, s.scheduled_start + interval '1 hour') + interval '15 minutes') < now() AT TIME ZONE 'UTC' AND (l.actual_start IS NOT NULL OR s.status='completed') AND NOT (l.actual_start IS NOT NULL AND l.actual_start > s.scheduled_start AT TIME ZONE 'UTC' + make_interval(mins=>%(late_tolerance)s))) AS on_time,
        count(*) FILTER (WHERE s.scheduled_start <= now() AT TIME ZONE 'UTC' AND (s.status IN ('missed', 'cancelled') OR (s.status='scheduled' AND l.actual_start IS NULL AND l.actual_end IS NULL
          AND NOT EXISTS (SELECT 1 FROM attendance_records ar WHERE ar.session_id=s.id)))) AS unresolved
      FROM scoped_sessions s LEFT JOIN LATERAL (
        SELECT min(actual_start) AS actual_start,max(actual_end) AS actual_end
        FROM live_sessions WHERE class_session_id=s.id
      ) l ON true)
    ,assessment AS (
      SELECT count(*) AS due, count(*) FILTER (WHERE sub.submitted_at<=a.due_at) AS assessment_on_time,
        count(sub.id) AS submitted
      FROM assignments a JOIN student_batches sb ON sb.batch_id=a.batch_id AND sb.status='active' AND sb.joined_at<=a.due_at
      LEFT JOIN assignment_submissions sub ON sub.assignment_id=a.id AND sub.student_id=sb.student_id
      JOIN batch_semesters bs ON bs.id=a.batch_semester_id
      JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
      WHERE a.batch_id IN (SELECT id FROM scoped_batches) AND a.due_at >= %(from_date)s::date
      AND a.due_at < %(to_date)s::date+1 AND a.status='active' AND a.approval_status='approved'
      AND (%(semester_id)s::uuid IS NULL OR yss.semester_id=%(semester_id)s)
      AND (%(mentor_id)s::uuid IS NULL OR EXISTS (SELECT 1 FROM faculty_subjects fs JOIN curriculum cu ON cu.id=fs.curriculum_id WHERE fs.faculty_id=%(mentor_id)s AND fs.batch_semester_id=a.batch_semester_id AND cu.subject_id=a.subject_id)))
    ,scoring AS (
      SELECT avg(sub.marks/nullif(a.max_score,0)*100) AS score,count(*) AS evaluated
      FROM assignment_submissions sub JOIN assignments a ON a.id=sub.assignment_id
      JOIN batch_semesters bs ON bs.id=a.batch_semester_id
      JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
      WHERE a.batch_id IN (SELECT id FROM scoped_batches) AND a.due_at >= %(from_date)s::date
      AND a.due_at < %(to_date)s::date+1 AND a.status='active' AND a.approval_status='approved'
      AND sub.graded_at IS NOT NULL AND sub.marks IS NOT NULL AND a.max_score>0
      AND (%(semester_id)s::uuid IS NULL OR yss.semester_id=%(semester_id)s)
      AND (%(mentor_id)s::uuid IS NULL OR EXISTS (SELECT 1 FROM faculty_subjects fs JOIN curriculum cu ON cu.id=fs.curriculum_id WHERE fs.faculty_id=%(mentor_id)s AND fs.batch_semester_id=a.batch_semester_id AND cu.subject_id=a.subject_id)))
    SELECT * FROM attendance CROSS JOIN delivery CROSS JOIN assessment CROSS JOIN scoring""",
        p,
    )


def rate(n, d):
    return round(float(n) * 100 / float(d), 1) if d else None


@router.get("/dashboard")
def dashboard(f: Filters = Depends(filters), user=Depends(current_user)):
    p = params(f) | metric_settings()
    current = aggregates(f)
    length = (f.to_date - f.from_date).days + 1
    previous = aggregates(
        f.model_copy(
            update={
                "from_date": f.from_date - timedelta(days=length),
                "to_date": f.from_date - timedelta(days=1),
            }
        )
    )
    cfg = metric_settings()

    def cards(r):
        return [
            {
                "key": "attendance",
                "label": "Student Attendance Rate",
                "value": rate(r["present"], r["eligible"]),
                "unit": "%",
                "target": cfg["attendance_target"],
                "numerator": r["present"],
                "denominator": r["eligible"],
                "evidence": (
                    f"{r['present']:,} / {r['eligible']:,} present across {r['days_count']} days"
                    if r.get("days_count")
                    else f"{r['present']:,} / {r['eligible']:,} present"
                ),
                "definition": "Student attendance rate across scheduled classes in the selected period. Late arrivals count as present according to institutional policy.",
                "module": "attendance",
            },
            {
                "key": "delivery",
                "label": "On-Time Class Delivery",
                "value": rate(r["on_time"], r["actual_recorded"]),
                "unit": "%",
                "target": cfg["delivery_target"],
                "numerator": r["on_time"],
                "denominator": r["actual_recorded"],
                "evidence": f"{r['on_time']:,} / {r['actual_recorded']:,} timed sessions · {cfg['late_tolerance']} min grace",
                "definition": f"Timed classes started within {cfg['late_tolerance']} minutes of scheduled start. Sessions completed without start telemetry are counted as timed sessions. Sessions delayed by more than {cfg['late_tolerance']} minutes reduce on-time rate.",
                "module": "sla",
            },
            {
                "key": "completion",
                "label": "Assignment Completion Rate",
                "value": rate(r["assessment_on_time"], r["due"]),
                "unit": "%",
                "target": cfg["completion_target"],
                "numerator": r["assessment_on_time"],
                "denominator": r["due"],
                "evidence": f"{r['assessment_on_time']:,} on time / {r['due']:,} eligible",
                "definition": "On-time submissions / assignments due for currently active batch enrollments that joined by deadline. Historic enrollment status is not available.",
                "module": "assess",
            },
            {
                "key": "score",
                "label": "Average Assignment Score",
                "value": round(float(r["score"]), 1) if r["score"] is not None else None,
                "unit": "%",
                "target": None,
                "denominator": r["evaluated"],
                "evidence": f"{r['evaluated']:,} graded submissions",
                "definition": "Mean of assignment-submission marks divided by each assignment's maximum score, evaluated submissions only. This uses recorded graded submissions regardless of the student's current enrollment status; examination results are presented separately.",
                "module": "assess",
            },
        ]

    result = cards(current)
    old = {c["key"]: c for c in cards(previous)}
    for c in result:
        prior = old[c["key"]]["value"]
        c["delta"] = round(c["value"] - prior, 1) if c["value"] is not None and prior is not None else None
    trends = query(
        f"""WITH scoped_batches AS ({BATCH_SCOPE}), scoped_sessions AS ({SESSION_SCOPE})
        SELECT s.scheduled_start::date AS date,
          round(100.0*count(*) FILTER (WHERE ar.status='present' OR (%(late_counts_present)s AND ar.status='late'))/
          nullif(count(*) FILTER (WHERE ar.status IN ('present','late','absent')),0),1) AS attendance,
          count(DISTINCT s.id) AS sessions,
          count(*) FILTER (WHERE ar.status='absent') AS absent
        FROM scoped_sessions s LEFT JOIN attendance_records ar ON ar.session_id=s.id
        WHERE s.counts_for_attendance AND (ar.id IS NULL OR ar.home_batch_id IN (SELECT id FROM scoped_batches) OR
          (ar.home_batch_id IS NULL AND EXISTS(SELECT 1 FROM student_batches sb WHERE sb.student_id=ar.student_id AND sb.batch_id IN (SELECT id FROM scoped_batches))))
        GROUP BY 1 ORDER BY 1""",
        p,
    )
    health = query(
        f"""WITH scoped_batches AS ({BATCH_SCOPE}), scoped_sessions AS ({SESSION_SCOPE})
        SELECT b.id,b.name,count(DISTINCT s.id) AS sessions,
          count(DISTINCT ar.student_id) AS students,
          round(100.0*count(*) FILTER(WHERE ar.status='present' OR (%(late_counts_present)s AND ar.status='late'))/
                nullif(count(*) FILTER(WHERE ar.status IN ('present','late','absent')),0),1) AS attendance
        FROM batches b LEFT JOIN scoped_sessions s ON s.batch_id=b.id
        LEFT JOIN attendance_records ar ON ar.session_id=s.id AND EXISTS(SELECT 1 FROM student_batches sb WHERE sb.student_id=ar.student_id AND sb.batch_id=b.id)
        WHERE b.id IN (SELECT id FROM scoped_batches) GROUP BY b.id,b.name ORDER BY b.name""",
        p,
    )
    scores = query(
        f"""WITH scoped_batches AS ({BATCH_SCOPE})
        SELECT CASE WHEN r.percentage<40 THEN 'Below 40' WHEN r.percentage<60 THEN '40–59'
          WHEN r.percentage<80 THEN '60–79' ELSE '80–100' END AS name,count(*) AS value
        FROM examination_results r JOIN examinations e ON e.id=r.examination_id JOIN batch_semesters bs ON bs.id=e.batch_semester_id
        JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
        WHERE bs.batch_id IN (SELECT id FROM scoped_batches) AND e.date BETWEEN %(from_date)s AND %(to_date)s
          AND r.percentage IS NOT NULL AND (%(mentor_id)s::uuid IS NULL OR e.faculty=%(mentor_id)s)
          AND (%(semester_id)s::uuid IS NULL OR yss.semester_id=%(semester_id)s)
        GROUP BY 1 ORDER BY 1""",
        p,
    )
    total_students_count = one(
        """SELECT count(DISTINCT u.id) as total
        FROM users u
        JOIN roles r ON r.id = u.role_id AND r.name = 'student'
        LEFT JOIN student_batches sb ON sb.student_id = u.id
        LEFT JOIN batches b ON b.id = sb.batch_id
        LEFT JOIN year_specializations ys ON ys.id = b.year_specialization_id
        LEFT JOIN batch_semesters bs ON bs.batch_id = b.id
        LEFT JOIN year_specialization_semesters yss ON yss.id = bs.year_specialization_semester_id
        WHERE (%(batch_id)s::uuid IS NULL OR b.id = %(batch_id)s::uuid)
          AND (%(specialization_id)s::uuid IS NULL OR ys.specialization_id = %(specialization_id)s::uuid)
          AND (%(graduation_year_id)s::uuid IS NULL OR ys.graduation_year_id = %(graduation_year_id)s::uuid)
          AND (%(semester_id)s::uuid IS NULL OR yss.semester_id = %(semester_id)s::uuid)
        """,
        p,
    )["total"]

    risk_students_count = one(
        """
        WITH non_intern_students AS (
            SELECT u.id AS student_id
            FROM users u
            JOIN roles r ON r.id = u.role_id AND r.name = 'student'
            LEFT JOIN student_batches sb ON sb.student_id = u.id
            LEFT JOIN batches b ON b.id = sb.batch_id
            LEFT JOIN year_specializations ys ON ys.id = b.year_specialization_id
            LEFT JOIN batch_semesters bs ON bs.batch_id = b.id
            LEFT JOIN year_specialization_semesters yss ON yss.id = bs.year_specialization_semester_id
            WHERE (%(batch_id)s::uuid IS NULL OR b.id = %(batch_id)s::uuid)
              AND (%(specialization_id)s::uuid IS NULL OR ys.specialization_id = %(specialization_id)s::uuid)
              AND (%(graduation_year_id)s::uuid IS NULL OR ys.graduation_year_id = %(graduation_year_id)s::uuid)
              AND (%(semester_id)s::uuid IS NULL OR yss.semester_id = %(semester_id)s::uuid)
              AND NOT EXISTS (
                  SELECT 1 FROM student_batches sb_int
                  JOIN batches b_int ON b_int.id = sb_int.batch_id
                  JOIN batch_types bt_int ON bt_int.id = b_int.batch_type_id AND bt_int.name = 'internship'
                  WHERE sb_int.student_id = u.id AND sb_int.status = 'active'
              )
            GROUP BY u.id
        ),
        student_att AS (
            SELECT 
                ar.student_id,
                round(100.0 * count(ar.id) FILTER (WHERE ar.status = 'present' OR (%(late_counts_present)s AND ar.status = 'late')) / nullif(count(ar.id), 0), 1) AS attendance_percentage
            FROM attendance_records ar
            JOIN class_sessions cs ON cs.id = ar.session_id AND cs.counts_for_attendance
            JOIN subjects su ON su.id = cs.subject_id
            WHERE cs.scheduled_start >= %(from_date)s::date AND cs.scheduled_start < %(to_date)s::date + 1
              AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id = %(mentor_id)s::uuid)
              AND su.name !~* 'eval'
            GROUP BY ar.student_id
        )
        SELECT count(*) AS total_risk
        FROM non_intern_students nis
        LEFT JOIN student_att att ON att.student_id = nis.student_id
        WHERE coalesce(att.attendance_percentage, 0) < %(risk_attendance)s
        """,
        p,
    )["total_risk"]

    feedback_stats = one(
        f"""
        WITH scoped_batches AS ({BATCH_SCOPE}),
        student_session_feedback AS (
            SELECT 
                fr.student_id,
                fr.session_id,
                cs.scheduled_start,
                avg(fr.response_text::numeric) AS student_avg_rating
            FROM session_feedback_responses fr
            JOIN session_questions sq ON sq.id = fr.session_question_id
            JOIN class_sessions cs ON cs.id = fr.session_id
            JOIN batch_semesters bs ON bs.id = cs.batch_semester_id
            JOIN subjects su ON su.id = cs.subject_id
            WHERE sq.question_type = 'rating'
              AND fr.response_text ~ '^[1-5](\\.[0-9]+)?$'
              AND su.name !~* 'eval'
              AND bs.batch_id IN (SELECT id FROM scoped_batches)
              AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id = %(mentor_id)s::uuid)
              AND cs.scheduled_start >= (SELECT max(scheduled_start) - INTERVAL '90 days' FROM class_sessions)
            GROUP BY fr.student_id, fr.session_id, cs.scheduled_start
        )
        SELECT 
            round(avg(student_avg_rating), 2) AS avg_rating,
            count(*) AS total_submissions,
            count(DISTINCT student_id) AS student_count
        FROM student_session_feedback
        """,
        p,
    )

    prior_feedback = one(
        f"""
        WITH scoped_batches AS ({BATCH_SCOPE}),
        student_session_feedback AS (
            SELECT 
                fr.student_id,
                fr.session_id,
                cs.scheduled_start,
                avg(fr.response_text::numeric) AS student_avg_rating
            FROM session_feedback_responses fr
            JOIN session_questions sq ON sq.id = fr.session_question_id
            JOIN class_sessions cs ON cs.id = fr.session_id
            JOIN batch_semesters bs ON bs.id = cs.batch_semester_id
            JOIN subjects su ON su.id = cs.subject_id
            WHERE sq.question_type = 'rating'
              AND fr.response_text ~ '^[1-5](\\.[0-9]+)?$'
              AND su.name !~* 'eval'
              AND bs.batch_id IN (SELECT id FROM scoped_batches)
              AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id = %(mentor_id)s::uuid)
              AND cs.scheduled_start < (SELECT max(scheduled_start) - INTERVAL '90 days' FROM class_sessions)
              AND cs.scheduled_start >= (SELECT max(scheduled_start) - INTERVAL '180 days' FROM class_sessions)
            GROUP BY fr.student_id, fr.session_id, cs.scheduled_start
        )
        SELECT round(avg(student_avg_rating), 2) AS prior_avg_rating
        FROM student_session_feedback
        """,
        p,
    )

    feedback_avg = (
        float(feedback_stats["avg_rating"])
        if feedback_stats and feedback_stats.get("avg_rating") is not None
        else None
    )
    prior_avg = (
        float(prior_feedback["prior_avg_rating"])
        if prior_feedback and prior_feedback.get("prior_avg_rating") is not None
        else None
    )
    feedback_delta = (
        round(feedback_avg - prior_avg, 2)
        if feedback_avg is not None and prior_avg is not None
        else None
    )

    extras = [
        (
            "strength",
            "Total Enrolled Students",
            total_students_count,
            "attendance",
            "Total registered student strength in database across active, inactive, internship, dropped, and test records (777 students).",
        ),
        (
            "missed",
            "Classes Missed or Cancelled",
            current["unresolved"],
            "sla",
            "Classes cancelled or missed out of total classes scheduled till now (including ongoing sessions). Elapsed sessions past 15 min grace without attendance records are marked missed.",
        ),
        (
            "risk",
            "Students at Attendance Risk",
            risk_students_count,
            "attendance",
            f"Distinct non-intern students with recorded attendance below {cfg['risk_attendance']:g}% in the selected period (active interns excluded; dropped students evaluated).",
        ),
        (
            "mentor_feedback",
            "Institute-Wide Mentor Feedback",
            feedback_avg,
            "mentors",
            "Mean of student-session average feedback ratings across all mentors and classes over the last 3 months (90 days). Counts total student session feedback submissions and distinct participating students.",
        ),
        (
            "tasks",
            "Overdue Operational Tasks",
            None,
            "operations",
            "Overdue entries in the new MIS task register; no historical process records were supplied.",
        ),
        (
            "issues",
            "Open Student & Parent Issues",
            None,
            "tickets",
            "Open support reports at period end based on recorded creation and current resolution timestamps. Student concerns remain a separate source.",
        ),
        (
            "breach",
            "Issues Breaching SLA",
            None,
            "tickets",
            "Open reports with explicitly assigned SLA deadlines before period end. Untriaged reports are not assumed compliant.",
        ),
        (
            "comp",
            "Compliance Milestones at Risk",
            None,
            "compliance",
            "University submission stage and acknowledgement history were not supplied. Generic compliance follow-up items do not establish submitted-versus-unsubmitted milestones.",
        ),
    ]
    for key, label, value, view, definition in extras:
        extra_kpi = {
            "key": key,
            "label": label,
            "value": value,
            "unit": "/ 5" if key == "mentor_feedback" else "",
            "target": 4.0 if key == "mentor_feedback" else None,
            "delta": feedback_delta if key == "mentor_feedback" else None,
            "definition": definition,
            "module": view,
        }
        if key == "missed":
            extra_kpi["numerator"] = value
            extra_kpi["denominator"] = current["scheduled"]
            extra_kpi["evidence"] = (
                f"{value:,} missed or cancelled · {rate(value, current['scheduled']) or 0:.1f}% of {current['scheduled']:,} total classes till now"
            )
        elif key == "mentor_feedback":
            total_subs = feedback_stats["total_submissions"] if feedback_stats else 0
            stu_count = feedback_stats["student_count"] if feedback_stats else 0
            extra_kpi["evidence"] = f"{total_subs:,} ratings · {stu_count:,} students"
        result.append(extra_kpi)
    from .chart_data import ChartContext

    chart_context = ChartContext(f, user)
    for card in result:
        metric = {"attendance": "att", "delivery": "ontime", "completion": "assess", "score": "score"}.get(
            card["key"]
        )
        if metric:
            card["spark"] = [r["value"] for r in chart_context.metric_data(metric).get("rows", [])]
    return {
        "kpis": result,
        "trends": trends,
        "batches": health,
        "scores": scores,
        "delivery": {
            "scheduled": current["scheduled"],
            "completed": current["completed"],
            "actual_recorded": current["actual_recorded"],
        },
        "coverage": (
            f"{settings().source_dump} · {settings().source_snapshot}. "
            "Production access is read-only; missing operational sources are shown as unavailable."
        ),
        "period": {"from": f.from_date, "to": f.to_date},
    }
