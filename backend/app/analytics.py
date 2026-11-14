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
SELECT cs.*, bs.batch_id FROM class_sessions cs
JOIN batch_semesters bs ON bs.id=cs.batch_semester_id
JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
WHERE cs.scheduled_start >= %(from_date)s::date AND cs.scheduled_start < %(to_date)s::date+1
AND bs.batch_id IN (SELECT id FROM scoped_batches)
AND (%(semester_id)s::uuid IS NULL OR yss.semester_id=%(semester_id)s)
AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id=%(mentor_id)s)
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
            "SELECT DISTINCT su.id, su.name FROM subjects su JOIN class_sessions cs ON cs.subject_id=su.id ORDER BY su.name"
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


def aggregates(f):
    p = params(f) | metric_settings()
    return one(
        f"""WITH scoped_batches AS ({BATCH_SCOPE}), scoped_sessions AS ({SESSION_SCOPE}),
    attendance_session_dates AS (
      SELECT DISTINCT cs.scheduled_start::date AS date
      FROM attendance_records ar
      JOIN class_sessions cs ON cs.id = ar.session_id
      JOIN batch_semesters bs ON bs.id = cs.batch_semester_id
      JOIN year_specialization_semesters yss ON yss.id = bs.year_specialization_semester_id
      WHERE cs.counts_for_attendance
        AND cs.scheduled_start >= %(from_date)s::date AND cs.scheduled_start < %(to_date)s::date + 1
        AND bs.batch_id IN (SELECT id FROM scoped_batches)
        AND (%(semester_id)s::uuid IS NULL OR yss.semester_id = %(semester_id)s)
        AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id = %(mentor_id)s)
    ),
    intern_joins AS (
      SELECT sb.student_id, min(sb.joined_at::date) AS intern_join_date
      FROM student_batches sb
      JOIN batches b ON b.id = sb.batch_id
      JOIN batch_types bt ON bt.id = b.batch_type_id
      WHERE bt.name = 'internship' AND sb.status = 'active'
      GROUP BY sb.student_id
    ),
    academic_memberships AS (
      SELECT sb.student_id, min(bs.start_date) AS start_date
      FROM student_batches sb
      JOIN batches b ON b.id = sb.batch_id
      JOIN batch_types bt ON bt.id = b.batch_type_id
      JOIN batch_semesters bs ON bs.batch_id = b.id
      JOIN year_specialization_semesters yss ON yss.id = bs.year_specialization_semester_id
      WHERE sb.status = 'active'
        AND bt.name = 'academics'
        AND b.id IN (SELECT id FROM scoped_batches)
        AND (%(semester_id)s::uuid IS NULL OR yss.semester_id = %(semester_id)s)
        AND (%(mentor_id)s::uuid IS NULL OR EXISTS (
            SELECT 1 FROM class_sessions mcs 
            WHERE mcs.batch_semester_id = bs.id AND mcs.faculty_id = %(mentor_id)s
        ))
      GROUP BY sb.student_id
    ),
    daily_eligible AS (
      SELECT 
        sd.date,
        count(DISTINCT am.student_id) AS total_students
      FROM attendance_session_dates sd
      JOIN academic_memberships am ON am.start_date <= sd.date
      LEFT JOIN intern_joins ij ON ij.student_id = am.student_id
      WHERE ij.intern_join_date IS NULL OR ij.intern_join_date >= sd.date
      GROUP BY sd.date
    ),
    daily_absent AS (
      SELECT 
        cs.scheduled_start::date AS date,
        count(DISTINCT ar.student_id) AS absent_students
      FROM attendance_records ar
      JOIN class_sessions cs ON cs.id = ar.session_id
      JOIN batch_semesters bs ON bs.id = cs.batch_semester_id
      JOIN year_specialization_semesters yss ON yss.id = bs.year_specialization_semester_id
      JOIN academic_memberships am ON am.student_id = ar.student_id AND am.start_date <= cs.scheduled_start::date
      LEFT JOIN intern_joins ij ON ij.student_id = ar.student_id
      WHERE cs.counts_for_attendance
        AND (ar.status = 'absent' OR (NOT %(late_counts_present)s AND ar.status = 'late'))
        AND cs.scheduled_start >= %(from_date)s::date AND cs.scheduled_start < %(to_date)s::date + 1
        AND bs.batch_id IN (SELECT id FROM scoped_batches)
        AND (%(semester_id)s::uuid IS NULL OR yss.semester_id = %(semester_id)s)
        AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id = %(mentor_id)s)
        AND (ij.intern_join_date IS NULL OR ij.intern_join_date >= cs.scheduled_start::date)
      GROUP BY cs.scheduled_start::date
    ),
    daily_combined AS (
      SELECT 
        de.date,
        de.total_students,
        coalesce(da.absent_students, 0) AS absent_students,
        greatest(0, de.total_students - coalesce(da.absent_students, 0)) AS present_students
      FROM daily_eligible de
      LEFT JOIN daily_absent da ON da.date = de.date
    ),
    attendance AS (
      SELECT 
        coalesce(sum(present_students), 0) AS present,
        coalesce(sum(total_students), 0) AS eligible,
        coalesce(sum(absent_students), 0) AS absent,
        count(*) AS days_count,
        count(*) AS recorded
      FROM daily_combined
    )
    ,delivery AS (
      SELECT count(*) AS scheduled, count(*) FILTER (WHERE s.status='completed') AS completed,
      count(*) FILTER (WHERE l.actual_start IS NOT NULL OR s.status='completed') AS actual_recorded,
      count(*) FILTER (WHERE (l.actual_start IS NOT NULL OR s.status='completed') AND NOT (l.actual_start IS NOT NULL AND l.actual_start > s.scheduled_start AT TIME ZONE 'UTC' + make_interval(mins=>%(late_tolerance)s))) AS on_time,
      count(*) FILTER (WHERE s.status='scheduled' AND l.actual_start IS NULL AND l.actual_end IS NULL
        AND NOT EXISTS (SELECT 1 FROM attendance_records ar WHERE ar.session_id=s.id)) AS unresolved
      FROM scoped_sessions s LEFT JOIN LATERAL (
        SELECT min(actual_start) AS actual_start,max(actual_end) AS actual_end
        FROM live_sessions WHERE class_session_id=s.id
      ) l ON true
      WHERE s.scheduled_start < now() AT TIME ZONE 'UTC')
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
                "label": "Student attendance",
                "value": rate(r["present"], r["eligible"]),
                "unit": "%",
                "target": cfg["attendance_target"],
                "numerator": r["present"],
                "denominator": r["eligible"],
                "evidence": (
                    f"{r['present']:,} / {r['eligible']:,} present student-days across {r['days_count']} days"
                    if r.get("days_count")
                    else f"{r['present']:,} / {r['eligible']:,} present student-days"
                ),
                "definition": "Weighted institutional attendance rate based on daily presence. A student is counted as present only if they attended all scheduled sessions on that day; interns and unstarted cohorts are excluded.",
                "module": "attendance",
            },
            {
                "key": "delivery",
                "label": "On-time class delivery",
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
                "label": "Assessment completion",
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
                "label": "Average assignment score",
                "value": round(float(r["score"]), 1) if r["score"] is not None else None,
                "unit": "%",
                "target": None,
                "denominator": r["evaluated"],
                "evidence": f"{r['evaluated']:,} graded submissions",
                "definition": "Mean of assignment-submission marks divided by each assignment's maximum score, evaluated submissions only. This uses recorded graded submissions regardless of the student's current enrollment status; examination results are presented separately.",
                "module": "academic",
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
    from .records import source_query

    _, student_sql, student_params = source_query("students", f, apply_dates=False)
    student_counts = one(
        f"SELECT count(DISTINCT student_id) FILTER(WHERE status='active' AND date<%(to_date)s::date+1) AS strength, count(DISTINCT student_id) FILTER(WHERE status='active' AND attendance<%(risk_attendance)s) AS risk FROM ({student_sql}) x",
        student_params,
    )
    extras = [
        (
            "strength",
            "Student strength",
            student_counts["strength"],
            "attendance",
            "Current active enrollments joined by period end. Historic enrollment changes and intake capacity are not supplied.",
        ),
        (
            "missed",
            "Classes missed or cancelled",
            current["unresolved"],
            "sla",
            "Elapsed sessions still marked scheduled with no actual start/end telemetry and no attendance records. This is an unresolved delivery-evidence indicator; the source has no explicit cancellation outcome or approval reason, so these are not asserted as confirmed cancellations.",
        ),
        (
            "risk",
            "Students at risk",
            student_counts["risk"],
            "academic",
            f"Distinct active students with recorded attendance below {cfg['risk_attendance']:g}% in the selected period. Attendance at or above the threshold is No Risk; missing attendance is No attendance evidence.",
        ),
    ]
    for key, label, value, view, definition in extras:
        result.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "unit": "",
                "target": None,
                "delta": None,
                "definition": definition,
                "module": view,
                **(
                    {
                        "evidence": f"{value:,} unresolved · {rate(value, current['scheduled']) or 0:.1f}% of {current['scheduled']:,} elapsed sessions"
                    }
                    if key == "missed"
                    else {}
                ),
            }
        )
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
