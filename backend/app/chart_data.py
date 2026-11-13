"""Original chart contracts backed by allowlisted PostgreSQL projections.

Missing evidence is a first-class result, never a generated series or a zero substitute.
"""

import json
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from .analytics import BATCH_SCOPE, Filters, filters, metric_settings, params
from .auth import current_user
from .db import one, query
from .plots import attendance_heatmap, student_scatter, task_timeline
from .records import source_query

router = APIRouter(prefix="/charts", tags=["Original chart integration"])
MANIFEST = json.loads(Path(__file__).with_name("chart_manifest.json").read_text())


def unavailable(reason):
    return {"status": "unavailable", "rows": [], "series": [], "note": reason}


def dataset(rows, series=("value",), unit="", note="", **extra):
    return {
        "status": "available" if rows else "empty",
        "rows": rows,
        "series": list(series),
        "unit": unit,
        "note": note,
        **extra,
    }


def scoped(name, f, apply_dates=True):
    _, sql, p = source_query(name, f, apply_dates=apply_dates)
    return sql, p


def group_chart(
    name, f, group, expression="count(*)", where="true", unit="", series=None, apply_dates=True, note=""
):
    sql, p = scoped(name, f, apply_dates)
    fields = series or {"value": expression}
    select = ",".join(f'{expr} AS "{key}"' for key, expr in fields.items())
    rows = query(
        f"SELECT {group} AS name,{select} FROM ({sql}) x WHERE {where} GROUP BY 1 ORDER BY 1 LIMIT 1000", p
    )
    return dataset(rows, fields.keys(), unit, note)


def assessment_facts(f):
    sql = f"""WITH scoped_batches AS ({BATCH_SCOPE})
    SELECT a.id,a.title,a.due_at AS date,a.batch_id,b.name AS batch,su.name AS subject,
      sm.name AS semester,sb.student_id,sub.id AS submission_id,sub.submitted_at,sub.graded_at,
      sub.marks/nullif(a.max_score,0)*100 AS score,
      ARRAY(SELECT fs.faculty_id FROM faculty_subjects fs JOIN curriculum cu ON cu.id=fs.curriculum_id
            WHERE fs.batch_semester_id=a.batch_semester_id AND cu.subject_id=a.subject_id) AS mentor_ids
    FROM assignments a JOIN student_batches sb ON sb.batch_id=a.batch_id AND sb.status='active' AND sb.joined_at<=a.due_at
    JOIN batches b ON b.id=a.batch_id JOIN subjects su ON su.id=a.subject_id
    JOIN batch_semesters bs ON bs.id=a.batch_semester_id JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
    JOIN semesters sm ON sm.id=yss.semester_id
    LEFT JOIN assignment_submissions sub ON sub.assignment_id=a.id AND sub.student_id=sb.student_id
    WHERE a.batch_id IN (SELECT id FROM scoped_batches) AND a.due_at >= %(from_date)s::date AND a.due_at < %(to_date)s::date+1
      AND a.status='active' AND a.approval_status='approved'
      AND (%(semester_id)s::uuid IS NULL OR yss.semester_id=%(semester_id)s)
      AND (%(mentor_id)s::uuid IS NULL OR EXISTS (SELECT 1 FROM faculty_subjects fs JOIN curriculum cu ON cu.id=fs.curriculum_id
          WHERE fs.faculty_id=%(mentor_id)s AND fs.batch_semester_id=a.batch_semester_id AND cu.subject_id=a.subject_id))"""
    return sql, params(f) | metric_settings()


def score_facts(f):
    sql = f"""WITH scoped_batches AS ({BATCH_SCOPE})
    SELECT a.id,a.title,a.due_at AS date,a.batch_id,b.name AS batch,su.name AS subject,
      sm.name AS semester,sub.student_id,sub.id AS submission_id,sub.submitted_at,sub.graded_at,
      sub.marks/nullif(a.max_score,0)*100 AS score,
      ARRAY(SELECT fs.faculty_id FROM faculty_subjects fs JOIN curriculum cu ON cu.id=fs.curriculum_id
            WHERE fs.batch_semester_id=a.batch_semester_id AND cu.subject_id=a.subject_id) AS mentor_ids
    FROM assignment_submissions sub JOIN assignments a ON a.id=sub.assignment_id
    JOIN batches b ON b.id=a.batch_id JOIN subjects su ON su.id=a.subject_id
    JOIN batch_semesters bs ON bs.id=a.batch_semester_id
    JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
    JOIN semesters sm ON sm.id=yss.semester_id
    WHERE a.batch_id IN (SELECT id FROM scoped_batches)
      AND a.due_at >= %(from_date)s::date AND a.due_at < %(to_date)s::date+1
      AND a.status='active' AND a.approval_status='approved'
      AND sub.graded_at IS NOT NULL AND sub.marks IS NOT NULL AND a.max_score>0
      AND (%(semester_id)s::uuid IS NULL OR yss.semester_id=%(semester_id)s)
      AND (%(mentor_id)s::uuid IS NULL OR EXISTS (SELECT 1 FROM faculty_subjects fs JOIN curriculum cu ON cu.id=fs.curriculum_id
          WHERE fs.faculty_id=%(mentor_id)s AND fs.batch_semester_id=a.batch_semester_id AND cu.subject_id=a.subject_id))"""
    return sql, params(f) | metric_settings()


ATT_RATE = "round(100.0*count(*) FILTER(WHERE status='present' OR (%(late_counts_present)s AND status='late'))/nullif(count(*) FILTER(WHERE status IN ('present','late','absent')),0),1)"
ON_RATE = "round(100.0*count(*) FILTER(WHERE actual_start<=date AT TIME ZONE 'UTC'+make_interval(mins=>%(late_tolerance)s))/nullif(count(actual_start),0),1)"
COMP_RATE = "round(100.0*count(*) FILTER(WHERE submitted_at<=date)/nullif(count(*),0),1)"
SCORE_RATE = "round(avg(score) FILTER(WHERE graded_at IS NOT NULL),1)"
TIMING_GAP = "No actual-start telemetry exists for the selected sessions. Scheduled/completed status cannot establish punctuality or a mentor SLA breach."
ENROLLMENT_NOTE = "Uses active batch memberships that joined by assignment deadline. The source has no historic enrollment transition log."


class ChartContext:
    def __init__(
        self,
        f,
        user,
        metric="feedback",
        granularity="weekly",
        breakdown="institution",
        matrix_page=1,
        student_status="active",
        attendance_heatmap_mode="percentage",
    ):
        self.f = f
        self.user = user
        self.metric = metric
        self.granularity = granularity
        self.breakdown = breakdown
        self.matrix_page = matrix_page
        self.student_status = student_status
        self.attendance_heatmap_mode = attendance_heatmap_mode

    def metric_data(self, metric, dimension="time", previous=False):
        f = self.f
        if previous:
            size = (f.to_date - f.from_date).days + 1
            f = f.model_copy(
                update={
                    "from_date": f.from_date - timedelta(days=size),
                    "to_date": f.from_date - timedelta(days=1),
                }
            )
        bucket = {"daily": "day", "weekly": "week", "monthly": "month", "semester": "month"}[self.granularity]
        time = f"date_trunc('{bucket}',date)::date"
        if metric == "feedback":
            group = {
                "time": time,
                "batch": "batch",
                "mentor": "mentor",
                "subject": "subject",
                "semester": "semester",
            }.get(dimension, time)
            sql, p = scoped("mentor_feedback", f)
            sql = (
                f"SELECT x.*,sm.name AS semester FROM ({sql}) x LEFT JOIN semesters sm ON sm.id=x.semester_id"
            )
            order = "value DESC,name" if dimension in {"batch", "mentor", "subject", "semester"} else "name"
            rows = query(
                f"""SELECT {group} AS name,
                  round(avg(rating), 2) AS value,
                  count(*) AS feedback_count
                FROM ({sql}) x
                GROUP BY 1 ORDER BY {order}""",
                p,
            )
            return dataset(
                rows,
                unit="/5",
                note="Average mentor-feedback rating = mean of student session ratings.",
            )
        if metric == "att":
            group = {
                "time": time,
                "batch": "batch",
                "mentor": "mentor",
                "subject": "subject",
                "semester": "semester",
            }.get(dimension, time)
            sql, p = scoped("attendance", f)
            # Mentor/semester labels join the actual scoped attendance projection.
            sql = f"SELECT x.*,u.name AS mentor,sm.name AS semester FROM ({sql}) x LEFT JOIN users u ON u.id=x.mentor_id LEFT JOIN semesters sm ON sm.id=x.semester_id"
            return dataset(
                query(f"SELECT {group} AS name,{ATT_RATE} AS value FROM ({sql}) x GROUP BY 1 ORDER BY 1", p),
                unit="%",
            )
        if metric == "ontime":
            sql, p = scoped("sessions", f)
            rows = query(
                f"SELECT count(*) AS total,count(actual_start) AS timed FROM ({sql}) x WHERE date<now() AT TIME ZONE 'UTC'",
                p,
            )
            if rows[0]["total"] and not rows[0]["timed"]:
                return unavailable(TIMING_GAP)
            group = {
                "time": time,
                "batch": "batch",
                "mentor": "mentor",
                "subject": "subject",
                "semester": "semester",
            }.get(dimension, time)
            sql = (
                f"SELECT x.*,sm.name AS semester FROM ({sql}) x LEFT JOIN semesters sm ON sm.id=x.semester_id"
            )
            return dataset(
                query(
                    f"SELECT {group} AS name,{ON_RATE} AS value FROM ({sql}) x WHERE date<now() AT TIME ZONE 'UTC' GROUP BY 1 ORDER BY 1",
                    p,
                ),
                unit="%",
                note=f"On time means actual-start telemetry at or before scheduled UTC start plus {p['late_tolerance']} minutes. Sessions without start telemetry are excluded.",
            )
        if metric == "missed":
            sql, p = scoped("sessions", f)
            group = {
                "time": time,
                "batch": "batch",
                "mentor": "mentor",
                "subject": "subject",
                "semester": "semester",
            }.get(dimension, time)
            sql = (
                f"SELECT x.*,sm.name AS semester FROM ({sql}) x LEFT JOIN semesters sm ON sm.id=x.semester_id"
            )
            rows = query(
                f"""SELECT {group} AS name,
                round(100.0*count(*) FILTER(WHERE status='scheduled' AND actual_start IS NULL
                  AND actual_end IS NULL AND NOT EXISTS(
                    SELECT 1 FROM attendance_records ar WHERE ar.session_id=x.id
                  ))/nullif(count(*),0),1) AS value
                FROM ({sql}) x
                WHERE date<now() AT TIME ZONE 'UTC'
                GROUP BY 1 ORDER BY 1""",
                p,
            )
            return dataset(
                rows,
                unit="%",
                note="Unresolved delivery evidence: elapsed sessions still scheduled with no start/end telemetry or attendance. The source does not identify confirmed or approved cancellations.",
            )
        if metric in {"assess", "score"}:
            sql, p = score_facts(f) if metric == "score" else assessment_facts(f)
            expression = COMP_RATE if metric == "assess" else SCORE_RATE
            group = {"time": time, "batch": "batch", "subject": "subject", "semester": "semester"}.get(
                dimension, time
            )
            if dimension == "mentor":
                sql = f"SELECT x.*,u.name AS mentor FROM ({sql}) x CROSS JOIN LATERAL unnest(x.mentor_ids) mid JOIN users u ON u.id=mid"
                group = "mentor"
            rows = query(
                f"SELECT {group} AS name,{expression} AS value FROM ({sql}) x GROUP BY 1 ORDER BY 1", p
            )
            return dataset(rows, unit="%", note=ENROLLMENT_NOTE)
        if metric == "slaIssue":
            sql, p = scoped("support", f, False)
            group = {
                "time": f"date_trunc('{bucket}',resolved_at)::date",
                "batch": "'Institution'",
                "subject": "category",
            }.get(dimension)
            if not group:
                return unavailable(
                    "Issue SLA is not attributable to mentors or academic semesters in the source."
                )
            rows = query(
                f"SELECT {group} AS name,round(100.0*count(*) FILTER(WHERE resolved_at<=sla_due)/nullif(count(*),0),1) AS value FROM ({sql}) x WHERE sla_due IS NOT NULL AND resolved_at >= %(from_date)s::date AND resolved_at<%(to_date)s::date+1 GROUP BY 1 ORDER BY 1",
                p,
            )
            return dataset(
                rows,
                unit="%",
                note="Only triaged reports with an explicit SLA deadline and recorded resolution are eligible.",
            )
        if metric == "taskOn":
            sql, p = scoped("tasks", f)
            group = {"time": time, "subject": "function_name", "batch": "batch"}.get(dimension)
            if not group:
                return unavailable(
                    "Operational task completion is not attributable to mentors or academic semesters."
                )
            rows = query(
                f"SELECT {group} AS name,round(100.0*count(*) FILTER(WHERE completed_at::date<=due_date)/nullif(count(*),0),1) AS value FROM ({sql}) x WHERE due_date<=%(to_date)s GROUP BY 1 ORDER BY 1",
                p,
            )
            return dataset(
                rows,
                unit="%",
                note="Recorded completion date versus due date for MIS tasks; no synthetic task history.",
            )
        return unavailable("Metric source is not configured.")

    def metric_heatmap(self, metric):
        if metric == "att":
            if self.attendance_heatmap_mode != "percentage":
                sql, p = scoped("attendance", self.f)
                present = "status='present' OR (%(late_counts_present)s AND status='late')"
                if self.attendance_heatmap_mode == "absolute":
                    rows = query(
                        f"""WITH attendance AS ({sql}), sessions AS (
                          SELECT batch,batch_id,date::date AS day,session_id,min(subject) AS subject,
                            min(session) AS session,
                            count(*) FILTER(WHERE {present}) AS attended,
                            count(*) FILTER(WHERE status IN ('present','late','absent')) AS eligible
                          FROM attendance GROUP BY batch,batch_id,date::date,session_id
                        )
                        SELECT batch AS row,day AS column,sum(attended) AS value,batch_id,day AS date,
                          jsonb_agg(jsonb_build_object(
                            'session_id',session_id,'subject',subject,'session',session,
                            'attended',attended,'eligible',eligible
                          ) ORDER BY session,session_id) AS sessions
                        FROM sessions GROUP BY batch,batch_id,day ORDER BY batch,day""",
                        p,
                    )
                    return dataset(
                        rows,
                        unit=" students",
                        title="Absolute attendance · batch × day",
                        heatmap_mode="absolute",
                        note="Each subject-session is shown separately. Repeated subjects on the same day remain separate, with their own attended and eligible counts.",
                    )
                rows = query(
                    f"""WITH attendance AS ({sql})
                    SELECT batch AS row,date::date AS column,
                      count(DISTINCT student_id) FILTER(WHERE {present}) AS value,
                      (SELECT count(DISTINCT sb.student_id)
                       FROM student_batches sb
                       WHERE sb.batch_id=attendance.batch_id AND sb.status='active') AS total_strength,
                      batch_id,date::date AS date
                    FROM attendance GROUP BY batch,batch_id,date::date ORDER BY batch,date::date""",
                    p,
                )
                return dataset(
                    rows,
                    unit=" students",
                    title="Unique attenders · batch × day",
                    heatmap_mode="unique",
                    note="Each cell shows distinct students marked present / current active batch strength. A student attending multiple sessions that day is counted once.",
                )
            rows = attendance_heatmap(self.f, self.user)
            return dataset(
                [
                    {
                        "row": r["batch"],
                        "column": str(r["week"]),
                        "value": r["attendance"],
                        "batch_id": r["batch_id"],
                        "date": r["week"],
                    }
                    for r in rows
                ],
                unit="%",
                heatmap_mode="percentage",
            )
        if metric == "ontime" and self.metric_data("ontime")["status"] == "unavailable":
            return unavailable(TIMING_GAP)
        if metric == "feedback":
            sql, p = scoped("mentor_feedback", self.f)
            expr = "round(avg(rating), 2)"
            condition = ""
        elif metric in {"assess", "score"}:
            sql, p = score_facts(self.f) if metric == "score" else assessment_facts(self.f)
            expr = COMP_RATE if metric == "assess" else SCORE_RATE
            condition = ""
        elif metric == "ontime":
            sql, p = scoped("sessions", self.f)
            expr = ON_RATE
            condition = ""
        elif metric == "missed":
            sql, p = scoped("sessions", self.f)
            expr = """round(100.0*count(*) FILTER(WHERE status='scheduled' AND actual_start IS NULL
              AND actual_end IS NULL AND NOT EXISTS(
                SELECT 1 FROM attendance_records ar WHERE ar.session_id=x.id
              ))/nullif(count(*),0),1)"""
            condition = ""
        else:
            return unavailable(
                "The selected metric has no batch-by-week source with the required denominator."
            )
        rows = query(
            f"SELECT batch AS row,date_trunc('week',date)::date AS column,{expr} AS value FROM ({sql}) x {condition} GROUP BY 1,2 ORDER BY 1,2",
            p,
        )
        return dataset(rows, unit="/5" if metric == "feedback" else "%")

    def get(self, key):
        domain, mode = key.split(".", 1)
        f = self.f
        if domain == "production":
            if mode == "concern_category":
                return group_chart(
                    "concerns",
                    f,
                    "coalesce(category,'Unspecified')",
                    note="Production LMS concerns by category. These records do not contain support-ticket owner, resolution timestamp or SLA deadline fields.",
                )
            if mode == "concern_status":
                return group_chart(
                    "concerns",
                    f,
                    "status",
                    note="Current status of concerns created during the selected period; not historical resolution throughput.",
                )
            if mode == "concern_weekly":
                return group_chart(
                    "concerns",
                    f,
                    "date_trunc('week',date)::date",
                    note="Production concerns raised each week. Resolution dates are not recorded, so a resolved-per-week series cannot be calculated.",
                )
            if mode == "companies":
                data = group_chart(
                    "internship_placements",
                    f,
                    "coalesce(nullif(trim(company),''),'Company not recorded')",
                    note="Placement records by company, not unique students. Dates use record creation. View chart data contains every company.",
                )
                data["rows"].sort(key=lambda r: (-r["value"], r["name"]))
                return data | {"plot_limit": 10}
            if mode == "evaluation_status":
                return group_chart(
                    "ojt_evaluations",
                    f,
                    "status",
                    note="Counts only recorded OJT evaluation rows. Evaluated means final marks and evaluated_at are both present; this is not a completion rate for all eligible students.",
                )
            if mode == "allocation_status":
                return group_chart(
                    "ojt_allocations",
                    f,
                    "status",
                    note="Current production OJT allocation status; one row per allocation in the selected creation-date range.",
                )
            if mode == "allocations_by_batch":
                return group_chart(
                    "ojt_allocations",
                    f,
                    "coalesce(batch,'Unspecified')",
                    note="Allocation counts by OJT source batch. Completion is not inferred from allocation existence.",
                )
            if mode == "milestones":
                sql, p = scoped("ojt_allocations", f)
                rows = query(
                    f"""SELECT milestone AS name,count(*) FILTER(WHERE done) AS value
                    FROM ({sql}) x CROSS JOIN LATERAL (VALUES
                    ('Industry alignment',milestone_industry_alignment),
                    ('Problem statement',milestone_problem_statement),
                    ('End users defined',milestone_end_users_defined),
                    ('Feature list',milestone_feature_list),
                    ('Tech stack selection',milestone_tech_stack_selection),
                    ('Proposal approved',milestone_proposal_approved)) flags(milestone,done)
                    GROUP BY milestone ORDER BY milestone""",
                    p,
                )
                return dataset(
                    rows,
                    note="Recorded milestone flags on scoped allocations. Milestones are independent checks, not a sequential funnel or proof of demo readiness.",
                )
        if domain == "trends":
            if mode == "heatmap":
                return self.metric_heatmap(self.metric)
            if mode != "series":
                result = self.metric_data(self.metric, mode)
                if mode in {"mentor", "subject"} and result["status"] == "available":
                    result["rows"].sort(key=lambda row: (-(row["value"] or 0), str(row["name"])))
                return result
            if self.granularity == "semester":
                return self.metric_data(self.metric, "semester")
            current = self.metric_data(self.metric)
            prior = self.metric_data(self.metric, previous=True)
            if current["status"] == "unavailable":
                return current
            priorrows = prior.get("rows", [])
            rows = [
                {
                    "name": r["name"],
                    "Current period": r["value"],
                    "Previous period": priorrows[i]["value"] if i < len(priorrows) else None,
                }
                for i, r in enumerate(current["rows"])
            ]
            return dataset(
                rows,
                ["Current period", "Previous period"],
                current.get("unit", ""),
                current.get("note", "")
                + " Previous buckets are aligned by ordinal position within the preceding equal-length period.",
            )
        if domain == "internship":
            if mode in {"enrollment_status", "batch_strength", "joined", "attendance_band"}:
                sql, p = scoped("internship_students", f, apply_dates=False)
                if mode == "enrollment_status":
                    return dataset(
                        query(
                            f"SELECT initcap(status) AS name,count(*) AS value FROM ({sql}) x GROUP BY status ORDER BY status",
                            p,
                        ),
                        note="Current internship-batch membership status from student_batches; one student membership is one record.",
                    )
                if mode == "batch_strength":
                    rows = query(
                        f"""SELECT batch AS name,
                          count(*) FILTER(WHERE status='active') AS "Active",
                          count(*) FILTER(WHERE status='dropped') AS "Dropped"
                        FROM ({sql}) x GROUP BY batch ORDER BY batch""",
                        p,
                    )
                    return dataset(
                        rows,
                        ["Active", "Dropped"],
                        stacked=True,
                        note="Internship batches are separated by cohort so batches with the same source name remain distinct.",
                    )
                if mode == "joined":
                    return dataset(
                        query(
                            f"SELECT date_trunc('week',date)::date AS name,count(*) AS value FROM ({sql}) x WHERE date IS NOT NULL GROUP BY 1 ORDER BY 1",
                            p,
                        ),
                        note="Internship batch memberships grouped by their recorded joined_at timestamp.",
                    )
                return dataset(
                    query(
                        f"""SELECT CASE
                          WHEN academic_attendance IS NULL THEN 'No academic attendance evidence'
                          WHEN academic_attendance<40 THEN 'Below 40%%'
                          WHEN academic_attendance<75 THEN '40–74.9%%'
                          ELSE '75%% and above' END AS name,count(*) AS value
                        FROM ({sql}) x WHERE status='active' GROUP BY 1 ORDER BY 1""",
                        p,
                    ),
                    note="Contextual academic attendance for active internship-batch students in the selected period. The dump contains no attendance records against internship sessions.",
                )
            if mode in {
                "delivery_status",
                "delivery_trend",
                "completion_by_batch",
                "timing",
                "subjects",
                "mentors",
            }:
                sql, p = scoped("internship_sessions", f)
                if mode == "delivery_status":
                    return dataset(
                        query(
                            f"SELECT initcap(replace(status,'_',' ')) AS name,count(*) AS value FROM ({sql}) x GROUP BY status ORDER BY status",
                            p,
                        ),
                        note="Source class-session status for internship batches in the selected period.",
                    )
                if mode == "delivery_trend":
                    return dataset(
                        query(
                            f"""SELECT date_trunc('week',date)::date AS name,count(*) AS "Scheduled",
                              count(*) FILTER(WHERE status='completed') AS "Completed"
                            FROM ({sql}) x GROUP BY 1 ORDER BY 1""",
                            p,
                        ),
                        ["Scheduled", "Completed"],
                        note="Scheduled and source-completed internship sessions by week.",
                    )
                if mode == "completion_by_batch":
                    return dataset(
                        query(
                            f"SELECT batch AS name,round(100.0*count(*) FILTER(WHERE status='completed')/nullif(count(*),0),1) AS value FROM ({sql}) x GROUP BY batch ORDER BY batch",
                            p,
                        ),
                        unit="%",
                        note="Completed source status / all scheduled internship sessions in the selected period.",
                    )
                if mode == "timing":
                    return dataset(
                        query(
                            f"SELECT delivery_timing AS name,count(*) AS value FROM ({sql}) x GROUP BY delivery_timing ORDER BY delivery_timing",
                            p,
                        ),
                        note=f"On time means actual start at or before scheduled start plus {p['late_tolerance']} minutes. No-telemetry sessions remain separate.",
                    )
                if mode == "subjects":
                    return dataset(
                        query(
                            f"SELECT subject AS name,count(*) AS value FROM ({sql}) x GROUP BY subject ORDER BY value DESC,subject",
                            p,
                        ),
                        note="All internship-batch sessions by scheduled subject; chart data and CSV retain the complete list.",
                        plot_limit=10,
                    )
                return dataset(
                    query(
                        f"SELECT mentor AS name,count(*) AS value FROM ({sql}) x GROUP BY mentor ORDER BY value DESC,mentor",
                        p,
                    ),
                    note="All internship-batch sessions by assigned mentor; chart data and CSV retain the complete list.",
                    plot_limit=10,
                )
        if domain == "attendance":
            if mode == "overall_daily":
                sql = f"""WITH scoped_batches AS ({BATCH_SCOPE}),
                internship_students AS (
                    SELECT DISTINCT sb.student_id
                    FROM student_batches sb
                    JOIN batches b ON b.id = sb.batch_id
                    JOIN batch_types bt ON bt.id = b.batch_type_id
                    WHERE bt.name = 'internship' AND sb.status = 'active'
                ),
                student_daily AS (
                    SELECT 
                        cs.scheduled_start::date AS date,
                        ar.student_id,
                        count(*) AS sessions_count,
                        count(*) FILTER (WHERE ar.status = 'absent') AS absent_sessions,
                        count(*) FILTER (WHERE ar.status = 'present' OR (%(late_counts_present)s AND ar.status = 'late')) AS present_sessions
                    FROM attendance_records ar
                    JOIN class_sessions cs ON cs.id = ar.session_id
                    JOIN batch_semesters bs ON bs.id = cs.batch_semester_id
                    JOIN year_specialization_semesters yss ON yss.id = bs.year_specialization_semester_id
                    WHERE cs.counts_for_attendance
                      AND cs.scheduled_start >= %(from_date)s::date AND cs.scheduled_start < %(to_date)s::date + 1
                      AND bs.batch_id IN (SELECT id FROM scoped_batches)
                      AND (%(semester_id)s::uuid IS NULL OR yss.semester_id = %(semester_id)s)
                      AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id = %(mentor_id)s)
                    GROUP BY cs.scheduled_start::date, ar.student_id
                )
                SELECT 
                    sd.date,
                    count(DISTINCT sd.student_id) AS total_students,
                    count(DISTINCT sd.student_id) FILTER (
                        WHERE sd.absent_sessions > 0 
                          AND sd.student_id NOT IN (SELECT student_id FROM internship_students)
                    ) AS absent_students,
                    count(DISTINCT sd.student_id) FILTER (
                        WHERE (sd.absent_sessions = 0 AND sd.present_sessions > 0)
                           OR sd.student_id IN (SELECT student_id FROM internship_students)
                    ) AS present_students
                FROM student_daily sd
                GROUP BY sd.date
                ORDER BY sd.date"""
                p = params(f) | metric_settings()
                raw_rows = query(sql, p)

                active_base_sql = f"""WITH scoped_batches AS ({BATCH_SCOPE})
                SELECT count(DISTINCT sb.student_id)
                FROM student_batches sb
                WHERE sb.status = 'active'
                  AND sb.batch_id IN (SELECT id FROM scoped_batches)"""
                active_res = query(active_base_sql, params(f))
                total_active = active_res[0]["count"] if active_res else 753

                formatted_rows = []
                total_absent_sum = 0
                total_present_sum = 0
                for r in raw_rows:
                    absent_cnt = int(r["absent_students"] or 0)
                    present_cnt = int(r["present_students"] or 0)
                    tot_cnt = int(r["total_students"] or 0)
                    total_absent_sum += absent_cnt
                    total_present_sum += present_cnt
                    formatted_rows.append(
                        {
                            "name": str(r["date"]),
                            "date": str(r["date"]),
                            "value": absent_cnt,
                            "absent_students": absent_cnt,
                            "present_students": present_cnt,
                            "total_students": tot_cnt,
                        }
                    )

                count_days = len(formatted_rows)
                avg_absent = round(total_absent_sum / count_days) if count_days else 0
                avg_present = round(total_present_sum / count_days) if count_days else 0

                return dataset(
                    formatted_rows,
                    series=["absent_students"],
                    unit="",
                    note="Daily count of absent students across the institution. A student is counted as absent if they missed one or more scheduled sessions on that day. Students in internship batches are default present.",
                    summary={
                        "avg_absent": avg_absent,
                        "avg_present": avg_present,
                        "total_students": total_active,
                        "days_count": count_days,
                    },
                )
            if mode in {"daily", "weekly"}:
                if self.breakdown == "batch":
                    sql, p = scoped("attendance", f)
                    bucket = "day" if mode == "daily" else "week"
                    rows = query(
                        f"SELECT date_trunc('{bucket}',date)::date AS name,batch,{ATT_RATE} AS value FROM ({sql}) x GROUP BY 1,2 ORDER BY 1,2",
                        p,
                    )
                    batches = sorted({r["batch"] for r in rows})
                    grouped = {}
                    for row in rows:
                        grouped.setdefault(str(row["name"]), {"name": row["name"]})[row["batch"]] = row[
                            "value"
                        ]
                    return dataset(list(grouped.values()), batches, unit="%")
                gran = self.granularity
                self.granularity = mode
                result = self.metric_data("att")
                self.granularity = gran
                return result
            if mode == "absences":
                sql = f"""WITH scoped_batches AS ({BATCH_SCOPE})
                SELECT 
                    cs.scheduled_start::date AS date,
                    cs.id AS session_id,
                    coalesce(cs.title, su.name) AS title,
                    su.name AS subject,
                    su.id AS subject_id,
                    b.name AS batch,
                    b.id AS batch_id,
                    concat('Sem ', sm.number) AS semester,
                    sm.number AS semester_number,
                    sm.id AS semester_id,
                    concat(gy.start_year, '–', gy.end_year) AS cohort,
                    gy.id AS graduation_year_id,
                    count(*) FILTER(WHERE ar.status = 'absent') AS absent,
                    count(*) FILTER(WHERE ar.status = 'present' OR (%(late_counts_present)s AND ar.status = 'late')) AS present,
                    count(*) FILTER(WHERE ar.status IN ('present', 'late', 'absent')) AS total
                FROM attendance_records ar
                JOIN class_sessions cs ON cs.id = ar.session_id
                JOIN batch_semesters bs ON bs.id = cs.batch_semester_id
                JOIN batches b ON b.id = coalesce(ar.home_batch_id, bs.batch_id)
                JOIN year_specialization_semesters yss ON yss.id = bs.year_specialization_semester_id
                JOIN semesters sm ON sm.id = yss.semester_id
                JOIN year_specializations ys ON ys.id = yss.year_specialization_id
                JOIN graduation_years gy ON gy.id = ys.graduation_year_id
                JOIN subjects su ON su.id = cs.subject_id
                WHERE cs.counts_for_attendance
                  AND cs.scheduled_start >= %(from_date)s::date AND cs.scheduled_start < %(to_date)s::date + 1
                  AND bs.batch_id IN (SELECT id FROM scoped_batches)
                  AND (%(semester_id)s::uuid IS NULL OR yss.semester_id = %(semester_id)s)
                  AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id = %(mentor_id)s)
                GROUP BY cs.scheduled_start::date, cs.id, coalesce(cs.title, su.name), su.name, su.id, b.name, b.id, sm.number, sm.id, gy.start_year, gy.end_year, gy.id
                ORDER BY cs.scheduled_start::date, sm.number, b.name, su.name"""
                p = params(f) | metric_settings()
                raw_rows = query(sql, p)
                dates_map = {}
                subjects_map = {}
                cohorts_map = {}
                semesters_map = {}
                batches_map = {}
                for r in raw_rows:
                    d = str(r["date"])
                    if d not in dates_map:
                        dates_map[d] = {
                            "name": d,
                            "value": 0,
                            "total_students": 0,
                            "present_count": 0,
                            "classes": [],
                        }
                    dates_map[d]["value"] += int(r["absent"] or 0)
                    dates_map[d]["total_students"] += int(r["total"] or 0)
                    dates_map[d]["present_count"] += int(r["present"] or 0)
                    dates_map[d]["classes"].append(
                        {
                            "id": str(r["session_id"]),
                            "session_id": str(r["session_id"]),
                            "title": r["title"],
                            "subject": r["subject"],
                            "subject_id": str(r["subject_id"]),
                            "batch": r["batch"],
                            "batch_id": str(r["batch_id"]),
                            "semester": r["semester"],
                            "semester_number": r["semester_number"],
                            "semester_id": str(r["semester_id"]),
                            "cohort": r["cohort"],
                            "graduation_year_id": str(r["graduation_year_id"]),
                            "absent": int(r["absent"] or 0),
                            "present": int(r["present"] or 0),
                            "total": int(r["total"] or 0),
                            "rate": round(r["present"] * 100.0 / r["total"], 1) if r["total"] else 0.0,
                        }
                    )
                    subjects_map[str(r["subject_id"])] = r["subject"]
                    cohorts_map[str(r["graduation_year_id"])] = r["cohort"]
                    semesters_map[str(r["semester_id"])] = (r["semester"], r["semester_number"])
                    batches_map[str(r["batch_id"])] = r["batch"]

                return dataset(
                    list(dates_map.values()),
                    unit="",
                    note="Daily class attendance and absence breakdown. Hover over each class section for class-specific attendance records.",
                    available_subjects=[
                        {"id": k, "name": v} for k, v in sorted(subjects_map.items(), key=lambda x: x[1])
                    ],
                    available_cohorts=[
                        {"id": k, "name": v} for k, v in sorted(cohorts_map.items(), key=lambda x: x[1])
                    ],
                    available_semesters=[
                        {"id": k, "name": v[0], "number": v[1]}
                        for k, v in sorted(semesters_map.items(), key=lambda x: x[1][1])
                    ],
                    available_batches=[
                        {"id": k, "name": v} for k, v in sorted(batches_map.items(), key=lambda x: x[1])
                    ],
                    render_as="class_absences",
                )
            if mode == "heatmap":
                return self.metric_heatmap("att")
            sql, p = scoped("attendance", f)
            if mode == "student_trends":
                student_sql, student_params = scoped("students", f, apply_dates=False)
                rows = query(
                    f"""WITH attendance AS ({sql}), risk_students AS (
                      SELECT student_id,batch_id FROM ({student_sql}) students
                      WHERE status='active' AND cardinality(risk_reasons)>0
                    )
                    SELECT a.student AS row,a.date::date AS column,{ATT_RATE} AS value
                    FROM attendance a JOIN risk_students r USING(student_id,batch_id)
                    GROUP BY 1,2 ORDER BY 1,2 LIMIT 5000""",
                    p | student_params,
                )
                return dataset(
                    rows,
                    unit="%",
                    note="Attendance trends for active students below the 40% attendance threshold. Missing attendance evidence does not create an assumed risk.",
                )
            page_size = 25
            student_sql, student_params = scoped("students", f, apply_dates=False)
            roster_sql = f"""SELECT student_id,min(student) AS student
              FROM ({student_sql}) students
              WHERE (%(matrix_student_status)s='all' OR status=%(matrix_student_status)s)
              GROUP BY student_id"""
            student_params = student_params | {"matrix_student_status": self.student_status}
            total = query(f"SELECT count(*) AS total FROM ({roster_sql}) roster", student_params)[0]["total"]
            page_students = query(
                f"""SELECT student_id,student FROM ({roster_sql}) roster
                ORDER BY lower(student),student_id
                LIMIT %(matrix_limit)s OFFSET %(matrix_offset)s""",
                student_params
                | {
                    "matrix_limit": page_size,
                    "matrix_offset": (self.matrix_page - 1) * page_size,
                },
            )
            student_ids = [row["student_id"] for row in page_students]
            rows = query(
                f"""WITH attendance AS ({sql})
                SELECT a.student_id::text AS row_id,min(a.student) AS row,a.date::date AS column,
                  {ATT_RATE} AS value
                FROM attendance a
                WHERE a.student_id=ANY(%(matrix_student_ids)s::uuid[])
                GROUP BY a.student_id,a.date::date
                ORDER BY lower(min(a.student)),a.student_id,a.date::date""",
                p | {"matrix_student_ids": student_ids},
            )
            result = dataset(
                rows,
                unit="%",
                page=self.matrix_page,
                page_size=page_size,
                total=total,
                row_entities=[
                    {"id": str(row["student_id"]), "name": row["student"]} for row in page_students
                ],
                note=f"{self.student_status.title() if self.student_status != 'all' else 'All'} enrollments in the selected semester and batch, including students without attendance evidence, paged by student name.",
            )
            if page_students:
                result["status"] = "available"
            return result
        if domain == "delivery":
            if mode in {"weekly", "daily_sla"}:
                if mode == "daily_sla":
                    self.granularity = "daily"
                return self.metric_data("ontime")
            if mode == "daily":
                return group_chart(
                    "sessions",
                    f,
                    "date::date",
                    series={
                        "Scheduled": "count(*)",
                        "Delivered": "count(*) FILTER(WHERE status='completed')",
                    },
                    note="Delivered is the source completed status, not evidence of on-time delivery.",
                )
            if mode == "workload":
                sql, p = scoped("sessions", f)
                rows = query(
                    f"SELECT mentor,batch,count(*) AS value FROM ({sql}) x GROUP BY 1,2 ORDER BY 1,2", p
                )
                batches = sorted({r["batch"] for r in rows})
                grouped = {}
                for row in rows:
                    grouped.setdefault(row["mentor"], {"name": row["mentor"]})[row["batch"]] = row["value"]
                return dataset(
                    list(grouped.values()),
                    batches,
                    note="Scheduled class workload by mentor and primary batch; linked classes count once per session.",
                    stacked=True,
                )
            if mode == "weekly_outcomes":
                if self.metric_data("ontime")["status"] == "unavailable":
                    return unavailable(TIMING_GAP)
                return group_chart(
                    "sessions",
                    f,
                    "date_trunc('week',date)::date",
                    series={
                        "Delivered": "count(*) FILTER(WHERE status='completed')",
                        "Late starts": "count(*) FILTER(WHERE actual_start>date AT TIME ZONE 'UTC'+make_interval(mins=>%(late_tolerance)s))",
                    },
                )
            if mode in {"batch", "mentor"}:
                return self.metric_data("ontime", mode)
            if self.metric_data("ontime")["status"] == "unavailable":
                return unavailable(TIMING_GAP)
            if mode in {"slot", "weekday"}:
                return group_chart(
                    "sessions",
                    f,
                    "to_char(date,'HH24:MI')" if mode == "slot" else "to_char(date,'Dy')",
                    ON_RATE,
                    unit="%",
                )
            sql, p = scoped("sessions", f)
            group = "subject" if mode == "subject_heatmap" else "to_char(date,'Dy')"
            return dataset(
                query(
                    f"SELECT {group} AS row,date_trunc('week',date)::date AS column,{ON_RATE} AS value FROM ({sql}) x GROUP BY 1,2 ORDER BY 1,2",
                    p,
                ),
                unit="%",
            )
        if domain == "assessment":
            if mode in {"completion", "score", "semester", "batch_score"}:
                return self.metric_data(
                    "assess" if mode == "completion" else "score",
                    {"semester": "semester", "batch_score": "batch"}.get(mode, "time"),
                )
            if mode == "scatter":
                rows = student_scatter(f, self.user)
                return dataset(
                    [
                        {"id": r["id"], "name": r["student"], "x": r["attendance"], "y": r["average_score"]}
                        for r in rows
                    ],
                    ["x", "y"],
                    "%",
                    note="Attendance vs evaluated assignment scores for the same student and period; up to 500 students.",
                )
            if mode == "histogram":
                sql, p = score_facts(f)
                return dataset(
                    query(
                        f"SELECT CASE WHEN score<40 THEN '0–39' WHEN score<60 THEN '40–59' WHEN score<80 THEN '60–79' ELSE '80–100' END AS name,count(*) AS value FROM ({sql}) x WHERE graded_at IS NOT NULL AND score IS NOT NULL GROUP BY 1 ORDER BY 1",
                        p,
                    ),
                    note="Normalized graded assignment scores, consistent with the average-score KPI.",
                )
            if mode == "batch_pass":
                sql, p = score_facts(f)
                return dataset(
                    query(
                        f"SELECT batch AS name,round(100.0*count(*) FILTER(WHERE score>=%(pass_mark)s)/nullif(count(*),0),1) AS value FROM ({sql}) x WHERE graded_at IS NOT NULL AND score IS NOT NULL GROUP BY 1 ORDER BY 1",
                        p,
                    ),
                    unit="%",
                )
            if mode == "subject_heatmap":
                sql, p = score_facts(f)
                return dataset(
                    query(
                        f"SELECT subject AS row,batch AS column,{SCORE_RATE} AS value FROM ({sql}) x GROUP BY 1,2 ORDER BY 1,2",
                        p,
                    ),
                    unit="%",
                )
            if mode == "evaluation":
                return group_chart(
                    "assignments",
                    f,
                    "title",
                    "round(100.0*sum(evaluated)/nullif(sum(submissions),0),1)",
                    unit="%",
                    note="Graded / submitted assignments. Zero submissions produce an unavailable rate.",
                )
            if mode == "progress_heatmap":
                sql, p = assessment_facts(f)
                return dataset(
                    query(
                        f"SELECT semester AS row,batch AS column,round(100.0*count(graded_at)/nullif(count(submission_id),0),1) AS value FROM ({sql}) x GROUP BY 1,2 ORDER BY 1,2",
                        p,
                    ),
                    unit="%",
                    note="Evaluation progress by semester and batch; full examination lifecycle stages are not available.",
                )
        if domain == "quality":
            group = {"area": "category", "severity": "severity", "pareto": "title"}[mode]
            result = group_chart(
                "data_quality",
                f,
                group,
                note="Computed checks: completed sessions without actual start and unmatched examination results. These are not historical audit samples.",
            )
            if mode == "pareto":
                rows = sorted(result["rows"], key=lambda r: r["value"], reverse=True)
                total = sum(r["value"] for r in rows)
                running = 0
                for r in rows:
                    running += r["value"]
                    r["cumulative"] = round(running / total * 100, 1) if total else None
                result["rows"] = rows
                result["series"] = ["value", "cumulative"]
            return result
        if domain == "risk":
            sql, p = scoped("students", f)
            rows = query(
                f"SELECT reason AS name,count(DISTINCT student_id) AS value FROM ({sql}) x CROSS JOIN LATERAL unnest(risk_reasons) reason WHERE status='active' GROUP BY reason ORDER BY value DESC",
                p,
            )
            return dataset(
                rows,
                note="Five explicit risk rules. A student may trigger more than one rule; the student-risk KPI counts distinct students.",
            )
        if domain == "feedback":
            # Ranking and distribution share the mentor_feedback projection (student average ratings).
            if mode == "ranking":
                result = self.metric_data("feedback", "mentor")
                if result["status"] == "available":
                    result["rows"].sort(key=lambda row: (-(row["value"] or 0), str(row["name"])))
                    result["plot_limit"] = 5
                    result["note"] = (
                        "Average feedback = mean of student session ratings. "
                        "The chart shows the top five mentors; View all contains every mentor in the selected filters."
                    )
                return result
            sql, p = scoped("mentor_feedback", f)
            if mode == "selected" and not f.mentor_id:
                return unavailable("Select a mentor to see that mentor’s feedback distribution.")
            if mode == "trend":
                rows = query(
                    f"SELECT date_trunc('week',date)::date AS name,round(avg(rating),2) AS value FROM ({sql}) x GROUP BY 1 ORDER BY 1",
                    p,
                )
                return dataset(
                    rows,
                    unit="/5",
                    note="Weekly average student feedback rating.",
                )
            extra = {}
            if f.mentor_id:
                mentor_row = one("SELECT name FROM users WHERE id=%s", (f.mentor_id,))
                if mentor_row and mentor_row.get("name"):
                    extra["title"] = f"Feedback distribution · {mentor_row['name']}"
            rows = query(
                f"SELECT round(rating)::int AS name,count(*) AS value FROM ({sql}) x GROUP BY 1 ORDER BY 1",
                p,
            )
            count_map = {int(r["name"]): int(r["value"]) for r in rows if r.get("name") is not None}
            rows = [{"name": score, "value": count_map.get(score, 0)} for score in range(1, 6)]
            return dataset(
                rows,
                note="Distribution of student session ratings (1 row per student submission). Matches the records in the register below.",
                **extra,
            )
        if domain == "communications":
            source = "parents" if mode.endswith("parent") else "announcements"
            if mode.startswith("weekly_"):
                return group_chart(
                    source,
                    f,
                    "date_trunc('week',date)::date",
                    series={"Published": "count(*)", "Acknowledged": "NULL::numeric"},
                    note="Only publication timestamps are present. Acknowledgement is unavailable; publication is not proof of delivery or receipt.",
                )
            return group_chart(
                source,
                f,
                "'Portal publication'",
                note="These source tables contain portal publications only. Email, SMS, WhatsApp and call delivery histories are not supplied.",
            )
        if domain == "support":
            return self.support(mode)
        if domain == "tasks":
            return self.tasks(mode)
        if domain == "calendar":
            return self.conflicts()
        if domain in {"actions", "projects", "compliance"}:
            source = domain
            if mode == "status":
                return group_chart(source, f, "status")
            if mode == "roots":
                return group_chart(source, f, "nullif(root_cause,'')", where="root_cause<>''")
            if mode == "root_heatmap":
                sql, p = scoped(source, f)
                return dataset(
                    query(
                        f"SELECT function_name AS row,root_cause AS column,count(*) AS value FROM ({sql}) x WHERE root_cause<>'' GROUP BY 1,2 ORDER BY 1,2",
                        p,
                    )
                )
            group = {
                "batch": "batch",
                "category": "category",
                "closure_owner": "owner",
                "closure_function": "function_name",
            }[mode]
            return group_chart(
                source,
                f,
                group,
                "round(100.0*count(*) FILTER(WHERE status='Verified & closed')/nullif(count(*),0),1)",
                unit="%",
                note="Verified closure rate of new MIS register records. No imported historical workflow data exists.",
            )
        return unavailable("No verified data adapter is available for this chart.")

    def support(self, mode):
        if mode == "sla":
            return self.metric_data("slaIssue")
        f = self.f
        sql, p = scoped("support", f, False)
        open_condition = (
            "date<%(to_date)s::date+1 AND (resolved_at IS NULL OR resolved_at>=%(to_date)s::date+1)"
        )
        if mode in {"category", "open_category", "owner", "batch", "aging"}:
            group = {
                "category": "category",
                "open_category": "category",
                "owner": "coalesce(owner,'Unassigned')",
                "batch": "batch",
                "aging": "CASE WHEN %(to_date)s::date-date::date<2 THEN '0–1 days' WHEN %(to_date)s::date-date::date<7 THEN '2–6 days' WHEN %(to_date)s::date-date::date<15 THEN '7–14 days' ELSE '15+ days' END",
            }[mode]
            if mode == "batch":
                sql = f"SELECT x.*,coalesce(b.name,'Unassigned') AS batch FROM ({sql}) x LEFT JOIN LATERAL unnest(x.batch_ids) bid ON true LEFT JOIN batches b ON b.id=bid"
            condition = (
                "date >= %(from_date)s::date AND date < %(to_date)s::date+1"
                if mode == "category"
                else open_condition
            )
            return dataset(
                query(
                    f"SELECT {group} AS name,count(DISTINCT id) AS value FROM ({sql}) x WHERE {condition} GROUP BY 1 ORDER BY 1",
                    p,
                ),
                note="Source support reports; current resolution timestamps determine open-as-of state. Multi-batch students can appear in more than one batch group.",
            )
        weeks = "SELECT generate_series(date_trunc('week',%(from_date)s::date),date_trunc('week',%(to_date)s::date),interval '1 week') AS w"
        if mode == "created_resolved":
            rows = query(
                f"WITH reports AS ({sql}), weeks AS ({weeks}) SELECT w::date AS name,count(r.id) FILTER(WHERE r.date>=greatest(w,%(from_date)s::date) AND r.date<least(w+interval '7 days',%(to_date)s::date+1)) AS \"Created\",count(r.id) FILTER(WHERE r.resolved_at>=greatest(w,%(from_date)s::date) AND r.resolved_at<least(w+interval '7 days',%(to_date)s::date+1)) AS \"Resolved\" FROM weeks LEFT JOIN reports r ON true GROUP BY 1 ORDER BY 1",
                p,
            )
            # Do not turn the complete absence of reports into a fabricated-looking series.
            if not query(f"SELECT id FROM ({sql}) x LIMIT 1", p):
                return dataset([])
            return dataset(
                rows,
                ["Created", "Resolved"],
                note="Latest recorded resolution timestamp. Historical reopen cycles are not reconstructed from source support reports.",
            )
        rows = query(
            f"WITH reports AS ({sql}),weeks AS ({weeks}) SELECT w::date AS name,count(r.id) FILTER(WHERE r.date<least(w+interval '7 days',%(to_date)s::date+1) AND (r.resolved_at IS NULL OR r.resolved_at>=least(w+interval '7 days',%(to_date)s::date+1))) AS \"Open\",count(r.id) FILTER(WHERE r.resolved_at>=greatest(w,%(from_date)s::date) AND r.resolved_at<least(w+interval '7 days',%(to_date)s::date+1)) AS \"Resolved\" FROM weeks LEFT JOIN reports r ON true GROUP BY 1 ORDER BY 1",
            p,
        )
        if not query(f"SELECT id FROM ({sql}) x LIMIT 1", p):
            return dataset([])
        return dataset(
            rows,
            ["Open", "Resolved"],
            note="Open snapshot at each bucket end and resolution flow within the bucket. Historical reopen cycles are unavailable in imported reports.",
        )

    def tasks(self, mode):
        f = self.f
        if mode == "on_time":
            return self.metric_data("taskOn")
        if mode == "gantt":
            return dataset(
                task_timeline(f, self.user),
                note="Creation-to-due-date timeline for recorded tasks. No invented process milestones or dependencies.",
            )
        if mode == "due_completed":
            return group_chart(
                "tasks",
                f,
                "date_trunc('week',date)::date",
                series={
                    "Due": "count(*)",
                    "Completed on time": "count(*) FILTER(WHERE completed_at::date<=due_date)",
                },
            )
        sql, p = scoped("tasks", f, False)
        if mode == "overdue_trend":
            if not query(f"SELECT id FROM ({sql}) x LIMIT 1", p):
                return dataset([])
            rows = query(
                f"WITH tasks AS ({sql}),weeks AS (SELECT generate_series(date_trunc('week',%(from_date)s::date),date_trunc('week',%(to_date)s::date),interval '1 week') AS w) SELECT w::date AS name,count(t.id) FILTER(WHERE t.created_at<least(w+interval '7 days',%(to_date)s::date+1) AND t.due_date<least(w+interval '7 days',%(to_date)s::date+1)::date AND (t.completed_at IS NULL OR t.completed_at>=least(w+interval '7 days',%(to_date)s::date+1))) AS value FROM weeks LEFT JOIN tasks t ON true GROUP BY 1 ORDER BY 1",
                p,
            )
            return dataset(
                rows,
                note="Task creation, due and completion timestamps; historical reopen cycles require audit reconstruction.",
            )
        group = {
            "overdue_function": "function_name",
            "overdue_owner": "owner",
            "escalation": "'Level ' || escalation_level",
            "aging": "CASE WHEN %(to_date)s::date-due_date<8 THEN '1–7 days' WHEN %(to_date)s::date-due_date<15 THEN '8–14 days' WHEN %(to_date)s::date-due_date<31 THEN '15–30 days' ELSE '31+ days' END",
        }[mode]
        rows = query(
            f"SELECT {group} AS name,count(*) AS value FROM ({sql}) x WHERE created_at<%(to_date)s::date+1 AND due_date<%(to_date)s AND (completed_at IS NULL OR completed_at>=%(to_date)s::date+1) GROUP BY 1 ORDER BY 1",
            p,
        )
        return dataset(rows, note="New MIS task register; dates and classifications are persisted inputs.")

    def conflicts(self):
        sql, p = scoped("sessions", self.f)
        rows = query(
            f"""WITH sessions AS ({sql}) SELECT a.id::text AS source_id,a.title AS row,b.title AS column,1 AS value,
          CASE WHEN a.mentor_id=b.mentor_id THEN 'Mentor overlap' ELSE 'Batch overlap' END AS reason
          FROM sessions a JOIN sessions b ON a.id<b.id AND a.date<b.scheduled_end AND b.date<a.scheduled_end
          AND (a.mentor_id=b.mentor_id OR a.batch_id=b.batch_id) ORDER BY a.date,b.date LIMIT 500""",
            p,
        )
        return dataset(
            rows,
            note="Overlapping scheduled intervals with the same primary batch or mentor. Room/resource and linked-batch conflict coverage is still limited.",
        )


@router.get("/manifest")
def manifest(user=Depends(current_user)):
    return MANIFEST


@router.get("/{view}/{tab}")
def charts(
    view: str,
    tab: str,
    f: Filters = Depends(filters),
    metric: str = Query(
        default="feedback", pattern="^(feedback|att|ontime|missed|assess|score|slaIssue|taskOn)$"
    ),
    granularity: str = Query(default="weekly", pattern="^(daily|weekly|monthly|semester)$"),
    breakdown: str = Query(default="institution", pattern="^(institution|batch|student|question)$"),
    matrix_page: int = Query(default=1, ge=1),
    student_status: str = Query(default="active", pattern="^(active|dropped|all)$"),
    attendance_heatmap_mode: str = Query(default="percentage", pattern="^(percentage|absolute|unique)$"),
    user=Depends(current_user),
):
    section = MANIFEST["sections"].get(view)
    if not section:
        raise HTTPException(404, "Unknown chart section")
    context = ChartContext(
        f,
        user,
        metric,
        granularity,
        breakdown,
        matrix_page,
        student_status,
        attendance_heatmap_mode,
    )
    result = []
    for spec in section["charts"]:
        if spec["tab"] != tab:
            continue
        provider = spec["provider"]
        if view == "command" and spec["title"] == "Attendance":
            provider = "attendance." + ("daily" if granularity == "daily" else "weekly")
        try:
            data = context.get(provider) if provider else unavailable(spec["reason"])
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            data = unavailable(str(exc.detail))
        cfg = metric_settings()
        if data.get("unit") == "%":
            target_key = (
                "attendance_target"
                if provider and provider.startswith("attendance.")
                else "delivery_target"
                if provider and provider.startswith("delivery.")
                else "completion_target"
                if provider == "assessment.completion"
                else "sla_target"
                if provider == "support.sla"
                else "task_target"
                if provider == "tasks.on_time"
                else None
            )
            if view == "trends":
                target_key = {
                    "att": "attendance_target",
                    "ontime": "delivery_target",
                    "assess": "completion_target",
                    "slaIssue": "sla_target",
                    "taskOn": "task_target",
                }.get(metric)
            data["target"] = cfg.get(target_key) if target_key else None
        result.append(spec | data)
    return {"charts": result, "metric": metric, "granularity": granularity}
