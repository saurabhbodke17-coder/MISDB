"""Allowlisted reporting projections. Never expose arbitrary source tables or credential fields."""

from dataclasses import dataclass, replace

from .risk_projection import risk_projection


@dataclass(frozen=True)
class Source:
    title: str
    sql: str
    columns: tuple[str, ...]
    scope: str = "batch"
    note: str = ""
    date_filter: bool = True


SOURCES = {
    "attendance": Source(
        "Attendance register",
        """
        SELECT ar.id,ar.student_id,cs.id AS session_id,u.name AS student,coalesce(cs.title,su.name) AS session,b.name AS batch,
          su.name AS subject, ar.status, cs.scheduled_start AS date, ar.marked_at,
          ar.override_reason, ar.is_guest,
          coalesce(ar.home_batch_id,bs.batch_id) AS batch_id, cs.faculty_id AS mentor_id, yss.semester_id
        FROM attendance_records ar JOIN users u ON u.id=ar.student_id
        JOIN class_sessions cs ON cs.id=ar.session_id JOIN batch_semesters bs ON bs.id=cs.batch_semester_id
        JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
        JOIN batches b ON b.id=coalesce(ar.home_batch_id,bs.batch_id) JOIN subjects su ON su.id=cs.subject_id
        WHERE cs.counts_for_attendance
    """,
        ("student", "batch", "subject", "date", "status"),
    ),
    "sessions": Source(
        "Class delivery register",
        """
        SELECT cs.id,coalesce(cs.title,su.name) AS title,su.name AS subject,u.name AS mentor,b.name AS batch,
          cs.scheduled_start AS date,cs.scheduled_end,cs.status,ls.actual_start,ls.actual_end,
          cs.counts_for_attendance,bs.batch_id,cs.faculty_id AS mentor_id,yss.semester_id,
          ARRAY[]::uuid[] AS linked_batches
        FROM class_sessions cs JOIN batch_semesters bs ON bs.id=cs.batch_semester_id
        JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
        JOIN batches b ON b.id=bs.batch_id JOIN subjects su ON su.id=cs.subject_id JOIN users u ON u.id=cs.faculty_id
        LEFT JOIN LATERAL (SELECT min(actual_start) AS actual_start,max(actual_end) AS actual_end FROM live_sessions WHERE class_session_id=cs.id) ls ON true
    """,
        ("title", "batch", "mentor", "date", "status", "actual_start"),
        note="Scheduled timestamps are stored as UTC. Actual starts come from live-session telemetry; completion and punctuality are separate measures.",
    ),
    "students": Source(
        "Student performance",
        """
        SELECT sb.id,u.id AS student_id,u.name AS student,
          CASE WHEN current_sem.number IS NULL THEN b.name
            WHEN b.name ~* '^Section[[:space:]]+' THEN
              'Sem ' || current_sem.number::text || regexp_replace(b.name,'^Section[[:space:]]+','','i')
            ELSE 'Sem ' || current_sem.number::text || ' ' || b.name END AS batch,
          sb.status,sb.joined_at AS date,sb.batch_id,NULL::uuid AS mentor_id,current_sem.id AS semester_id,
          att.attendance,att.recorded,marks.average_score,marks.evaluated,
          CASE WHEN att.attendance < %(risk_attendance)s THEN 'Attendance follow-up' ELSE 'No attendance flag' END AS risk
        FROM student_batches sb JOIN users u ON u.id=sb.student_id JOIN batches b ON b.id=sb.batch_id
        LEFT JOIN LATERAL (
          SELECT s.id,s.number FROM batch_semesters active_bs
          JOIN year_specialization_semesters yss ON yss.id=active_bs.year_specialization_semester_id
          JOIN semesters s ON s.id=yss.semester_id
          WHERE active_bs.batch_id=b.id AND active_bs.status='active' AND yss.is_active
          ORDER BY active_bs.start_date DESC NULLS LAST,s.number DESC LIMIT 1
        ) current_sem ON true
        LEFT JOIN LATERAL (
          SELECT round(100.0*count(*) FILTER(WHERE ar.status='present' OR (%(late_counts_present)s AND ar.status='late'))/
              nullif(count(*) FILTER(WHERE ar.status IN ('present','late','absent')),0),1) AS attendance,count(*) AS recorded
          FROM attendance_records ar JOIN class_sessions cs ON cs.id=ar.session_id
          JOIN batch_semesters bs ON bs.id=cs.batch_semester_id
          JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
          WHERE ar.student_id=u.id AND cs.counts_for_attendance
            AND (coalesce(ar.home_batch_id,bs.batch_id)=sb.batch_id)
            AND cs.scheduled_start >= %(from_date)s::date AND cs.scheduled_start < %(to_date)s::date+1
            AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id=%(mentor_id)s)
            AND (%(semester_id)s::uuid IS NULL OR yss.semester_id=%(semester_id)s)
        ) att ON true
        LEFT JOIN LATERAL (
          SELECT round(avg(sub.marks/nullif(a.max_score,0)*100),1) AS average_score,count(*) AS evaluated
          FROM assignment_submissions sub JOIN assignments a ON a.id=sub.assignment_id
          WHERE sub.student_id=u.id AND a.batch_id=sb.batch_id AND sub.graded_at IS NOT NULL AND sub.marks IS NOT NULL
            AND a.due_at >= %(from_date)s::date AND a.due_at < %(to_date)s::date+1
            AND (%(mentor_id)s::uuid IS NULL OR EXISTS (SELECT 1 FROM faculty_subjects fs JOIN curriculum cu ON cu.id=fs.curriculum_id WHERE fs.faculty_id=%(mentor_id)s AND fs.batch_semester_id=a.batch_semester_id AND cu.subject_id=a.subject_id))
            AND (%(semester_id)s::uuid IS NULL OR EXISTS (SELECT 1 FROM batch_semesters bs JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id WHERE bs.id=a.batch_semester_id AND yss.semester_id=%(semester_id)s))
        ) marks ON true
    """,
        ("student", "batch", "status", "attendance", "average_score", "risk"),
        "student",
        "Period attendance and evaluated assignment scores. Batch labels combine the active semester and section, for example Sem 3A. Current enrollment status is a snapshot; attendance follow-up is a rule flag, not an academic decision.",
        False,
    ),
    "internship_students": Source(
        "Internship batch students",
        """
        SELECT sb.id,u.id AS student_id,u.name AS student,
          concat(b.name,' · ',gy.start_year,'–',gy.end_year) AS batch,
          sp.name AS program,concat(gy.start_year,'–',gy.end_year) AS cohort,
          concat('Semester ',sem.number) AS semester,sb.status,sb.joined_at AS date,
          sb.batch_id,NULL::uuid AS mentor_id,sem.id AS semester_id,
          academic.academic_batch,academic.academic_batch_ids,
          attendance.academic_attendance,attendance.attendance_records
        FROM student_batches sb
        JOIN users u ON u.id=sb.student_id
        JOIN batches b ON b.id=sb.batch_id
        JOIN batch_types bt ON bt.id=b.batch_type_id AND bt.name='internship'
        JOIN year_specializations ys ON ys.id=b.year_specialization_id
        JOIN specializations sp ON sp.id=ys.specialization_id
        JOIN graduation_years gy ON gy.id=ys.graduation_year_id
        LEFT JOIN LATERAL (
          SELECT s.id,s.number FROM batch_semesters ibs
          JOIN year_specialization_semesters yss ON yss.id=ibs.year_specialization_semester_id
          JOIN semesters s ON s.id=yss.semester_id
          WHERE ibs.batch_id=b.id AND ibs.status='active' AND yss.is_active
          ORDER BY ibs.start_date DESC NULLS LAST,s.number DESC LIMIT 1
        ) sem ON true
        LEFT JOIN LATERAL (
          SELECT string_agg(DISTINCT concat(
                   CASE WHEN ab.name ~* '^Section[[:space:]]+' THEN regexp_replace(ab.name,'^Section[[:space:]]+','','i') ELSE ab.name END,
                   CASE WHEN asem.number IS NOT NULL THEN concat(' · Sem ',asem.number) ELSE '' END
                 ),', ' ORDER BY concat(
                   CASE WHEN ab.name ~* '^Section[[:space:]]+' THEN regexp_replace(ab.name,'^Section[[:space:]]+','','i') ELSE ab.name END,
                   CASE WHEN asem.number IS NOT NULL THEN concat(' · Sem ',asem.number) ELSE '' END
                 )) AS academic_batch,
                 array_agg(DISTINCT asb.batch_id) AS academic_batch_ids
          FROM student_batches asb
          JOIN batches ab ON ab.id=asb.batch_id
          JOIN batch_types abt ON abt.id=ab.batch_type_id AND abt.name='academics'
          LEFT JOIN LATERAL (
            SELECT s.number FROM batch_semesters abs
            JOIN year_specialization_semesters ayss ON ayss.id=abs.year_specialization_semester_id
            JOIN semesters s ON s.id=ayss.semester_id
            WHERE abs.batch_id=ab.id AND abs.status='active' AND ayss.is_active
            ORDER BY abs.start_date DESC NULLS LAST,s.number DESC LIMIT 1
          ) asem ON true
          WHERE asb.student_id=u.id AND asb.status='active'
        ) academic ON true
        LEFT JOIN LATERAL (
          SELECT round(100.0*count(*) FILTER(WHERE ar.status='present' OR (%(late_counts_present)s AND ar.status='late'))/
              nullif(count(*) FILTER(WHERE ar.status IN ('present','late','absent')),0),1) AS academic_attendance,
              count(*) FILTER(WHERE ar.status IN ('present','late','absent')) AS attendance_records
          FROM attendance_records ar JOIN class_sessions cs ON cs.id=ar.session_id
          WHERE ar.student_id=u.id AND cs.counts_for_attendance
            AND cs.scheduled_start >= %(from_date)s::date AND cs.scheduled_start < %(to_date)s::date+1
            AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id=%(mentor_id)s)
        ) attendance ON true
    """,
        (
            "student",
            "batch",
            "program",
            "cohort",
            "semester",
            "academic_batch",
            "status",
            "academic_attendance",
            "date",
        ),
        "student",
        "Real internship-batch memberships. Academic batch and attendance are contextual LMS evidence for the same students; the dump contains no attendance records against internship sessions.",
        False,
    ),
    "internship_sessions": Source(
        "Internship class delivery",
        """
        SELECT cs.id,coalesce(cs.title,su.name) AS title,
          concat(b.name,' · ',gy.start_year,'–',gy.end_year) AS batch,
          sp.name AS program,concat(gy.start_year,'–',gy.end_year) AS cohort,
          concat('Semester ',sem.number) AS semester,su.name AS subject,u.name AS mentor,
          cs.scheduled_start AS date,cs.scheduled_end,cs.status,
          live.actual_start,live.actual_end,
          CASE WHEN live.actual_start IS NULL THEN 'No telemetry'
               WHEN live.actual_start<=cs.scheduled_start AT TIME ZONE 'UTC'+make_interval(mins=>%(late_tolerance)s) THEN 'On time'
               ELSE 'Delayed' END AS delivery_timing,
          bs.batch_id,cs.faculty_id AS mentor_id,sem.id AS semester_id,
          ARRAY[]::uuid[] AS linked_batches
        FROM class_sessions cs
        JOIN batch_semesters bs ON bs.id=cs.batch_semester_id
        JOIN batches b ON b.id=bs.batch_id
        JOIN batch_types bt ON bt.id=b.batch_type_id AND bt.name='internship'
        JOIN year_specializations ys ON ys.id=b.year_specialization_id
        JOIN specializations sp ON sp.id=ys.specialization_id
        JOIN graduation_years gy ON gy.id=ys.graduation_year_id
        JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
        JOIN semesters sem ON sem.id=yss.semester_id
        JOIN subjects su ON su.id=cs.subject_id JOIN users u ON u.id=cs.faculty_id
        LEFT JOIN LATERAL (
          SELECT min(actual_start) AS actual_start,max(actual_end) AS actual_end
          FROM live_sessions WHERE class_session_id=cs.id
        ) live ON true
    """,
        (
            "title",
            "batch",
            "program",
            "cohort",
            "semester",
            "subject",
            "mentor",
            "date",
            "status",
            "delivery_timing",
        ),
        note="Scheduled internship-batch sessions and live-session telemetry. No attendance was marked for these sessions in the supplied dump; completion and punctuality do not imply student attendance.",
    ),
    "assignments": Source(
        "Assignment lifecycle",
        """
        SELECT a.id,a.title,b.name AS batch,su.name AS subject,a.due_at AS date,a.status,a.type,
          a.approval_status,a.max_score,a.description,a.instructions,
          (SELECT count(*) FROM assignment_submissions ss WHERE ss.assignment_id=a.id) AS submissions,
          (SELECT count(*) FROM assignment_submissions ss WHERE ss.assignment_id=a.id AND ss.graded_at IS NOT NULL) AS evaluated,
          a.batch_id,NULL::uuid AS mentor_id,yss.semester_id,
          ARRAY(SELECT fs.faculty_id FROM faculty_subjects fs JOIN curriculum cu ON cu.id=fs.curriculum_id WHERE fs.batch_semester_id=a.batch_semester_id AND cu.subject_id=a.subject_id) AS mentor_ids
        FROM assignments a JOIN batches b ON b.id=a.batch_id JOIN subjects su ON su.id=a.subject_id
        JOIN batch_semesters bs ON bs.id=a.batch_semester_id JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
    """,
        ("title", "batch", "subject", "date", "submissions", "evaluated", "approval_status"),
    ),
    "results": Source(
        "Examination results",
        """
        SELECT r.id,coalesce(u.name,r.student_name,'Unmatched student') AS student,e.title,su.name AS subject,b.name AS batch,
          e.date,r.marks_obtained,r.total_marks,r.percentage,r.match_status AS status,r.tier,
          bs.batch_id,e.faculty AS mentor_id,yss.semester_id
        FROM examination_results r JOIN examinations e ON e.id=r.examination_id
        LEFT JOIN users u ON u.id=r.student_id JOIN batch_semesters bs ON bs.id=e.batch_semester_id
        JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
        JOIN batches b ON b.id=bs.batch_id LEFT JOIN subjects su ON su.id=e.subject_id
    """,
        ("student", "title", "batch", "marks_obtained", "total_marks", "percentage", "status"),
    ),
    "examinations": Source(
        "Examination schedule",
        """
        SELECT e.id::text AS id,e.title,b.name AS batch,su.name AS subject,e.date,e.start_time,e.duration,e.marks,
          e.type AS status,e.evaluation_type,bs.batch_id,e.faculty AS mentor_id,yss.semester_id
        FROM examinations e JOIN batch_semesters bs ON bs.id=e.batch_semester_id
        JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
        JOIN batches b ON b.id=bs.batch_id LEFT JOIN subjects su ON su.id=e.subject_id
    """,
        ("title", "batch", "subject", "date", "start_time", "status"),
    ),
    "mentors": Source(
        "Mentor delivery",
        """
        SELECT u.id,u.name AS mentor,count(cs.id) AS sessions,
          count(cs.id) FILTER(WHERE cs.status='completed') AS completed,
          count(ls.actual_start) AS timed_sessions,
          NULL::date AS date,NULL::uuid AS batch_id,u.id AS mentor_id,NULL::uuid AS semester_id
        FROM users u JOIN class_sessions cs ON cs.faculty_id=u.id
        JOIN batch_semesters bs ON bs.id=cs.batch_semester_id
        JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
        LEFT JOIN LATERAL (SELECT min(actual_start) AS actual_start FROM live_sessions WHERE class_session_id=cs.id) ls ON true
        WHERE cs.scheduled_start >= %(from_date)s::date AND cs.scheduled_start < %(to_date)s::date+1
        AND bs.batch_id IN (SELECT id FROM scoped_batches)
        AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id=%(mentor_id)s)
        AND (%(semester_id)s::uuid IS NULL OR yss.semester_id=%(semester_id)s)
        GROUP BY u.id,u.name
    """,
        ("mentor", "sessions", "completed", "timed_sessions"),
        "aggregate",
        "Delivery workload from class sessions. No synthetic feedback or SLA scores.",
        False,
    ),
    "feedback": Source(
        "Session feedback",
        """
        SELECT fr.id,stu.name AS student,u.name AS mentor,coalesce(cs.title,su.name) AS session,
          su.name AS subject,
          sq.question_text AS question,sq.question_type,fr.response_text AS response,
          b.name AS batch,cs.scheduled_start AS date,fr.submitted_at,bs.batch_id,fr.faculty_id AS mentor_id,yss.semester_id
        FROM session_feedback_responses fr JOIN class_sessions cs ON cs.id=fr.session_id
        JOIN batch_semesters bs ON bs.id=cs.batch_semester_id JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
        JOIN batches b ON b.id=bs.batch_id JOIN subjects su ON su.id=cs.subject_id
        JOIN users u ON u.id=fr.faculty_id JOIN users stu ON stu.id=fr.student_id
        JOIN session_questions sq ON sq.id=fr.session_question_id
    """,
        ("student", "mentor", "session", "batch", "question", "response", "date"),
    ),
    "mentor_feedback": Source(
        "Student ratings & feedback",
        """
        SELECT fr.student_id::text || ':' || fr.session_id::text || ':' || fr.faculty_id::text AS id,
          stu.name AS student,fac.name AS mentor,coalesce(cs.title,su.name) AS session,b.name AS batch,
          round(avg(fr.response_text::numeric) FILTER (
            WHERE sq.question_type='rating' AND fr.response_text ~ '^[1-5](\\.0+)?$'
          ),2) AS rating,
          string_agg(fr.response_text,E'\n' ORDER BY sq.display_order) FILTER (
            WHERE sq.question_type='long_text' AND nullif(trim(fr.response_text),'') IS NOT NULL
          ) AS feedback,
          cs.scheduled_start AS date,max(fr.submitted_at) AS submitted_at,bs.batch_id,fr.faculty_id AS mentor_id,yss.semester_id
        FROM session_feedback_responses fr
        JOIN session_questions sq ON sq.id=fr.session_question_id
        JOIN class_sessions cs ON cs.id=fr.session_id
        JOIN batch_semesters bs ON bs.id=cs.batch_semester_id
        JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
        JOIN batches b ON b.id=bs.batch_id JOIN subjects su ON su.id=cs.subject_id
        JOIN users stu ON stu.id=fr.student_id JOIN users fac ON fac.id=fr.faculty_id
        GROUP BY fr.student_id,fr.session_id,fr.faculty_id,stu.name,fac.name,cs.title,su.name,
          b.name,bs.batch_id,yss.semester_id,cs.scheduled_start
        HAVING count(*) FILTER (
          WHERE sq.question_type='rating' AND fr.response_text ~ '^[1-5](\\.0+)?$'
        )>0
    """,
        ("student", "mentor", "session", "batch", "rating", "feedback", "date"),
        note="One row per student submission. Filtered by scheduled session date.",
    ),
    "support": Source(
        "Support reports",
        """
        SELECT r.id,u.name AS raised_by,r.category::text AS category,r.description,r.status::text AS status,
          r.created_at AS date,r.resolved_at,r.platform,
          coalesce(m.severity,'Unclassified') AS severity,a.display_name AS owner,m.sla_due,
          coalesce(m.version,0) AS version,m.owner_id,
          ARRAY(SELECT sb.batch_id FROM student_batches sb WHERE sb.student_id=r.user_id) AS batch_ids,
          NULL::uuid AS batch_id,NULL::uuid AS mentor_id,NULL::uuid AS semester_id
        FROM support_reports r LEFT JOIN users u ON u.id=r.user_id
        LEFT JOIN mis.support_metadata m ON m.report_id=r.id LEFT JOIN mis.accounts a ON a.id=m.owner_id
    """,
        ("raised_by", "category", "status", "severity", "owner", "date", "sla_due"),
        "multi",
        "Imported support reports have no priority or SLA policy. SLA starts when a report is triaged here; it is not backdated.",
    ),
    "concerns": Source(
        "Student and parent concerns",
        """
        SELECT c.id,c.title,c.category,c.status,c.content,coalesce(u.name,'Unlinked') AS student,c.created_at AS date,
          ARRAY(SELECT sb.batch_id FROM student_batches sb WHERE sb.student_id=c.student_id) AS batch_ids,
          NULL::uuid AS batch_id,NULL::uuid AS mentor_id,NULL::uuid AS semester_id
        FROM concerns c LEFT JOIN users u ON u.id=c.student_id
    """,
        ("title", "student", "category", "status", "date"),
        "multi",
        "Concerns are separate from support reports and do not have resolution SLA timestamps.",
    ),
    "announcements": Source(
        "Student communications",
        """
        SELECT a.uuid AS id,a.title,a.body,a.author_role,coalesce(b.name,'Program / cohort') AS batch,
          a.publish_at AS date,a.is_pinned,a.batch_id,a.specialization_id,a.graduation_year_id,
          NULL::uuid AS mentor_id,NULL::uuid AS semester_id
        FROM announcements a LEFT JOIN batches b ON b.id=a.batch_id
    """,
        ("title", "batch", "author_role", "date", "is_pinned"),
        "announcement",
        "Published announcement records. Delivery, acknowledgement and parent-contact coverage are not inferred from publication.",
    ),
    "parents": Source(
        "Parent communications",
        """
        SELECT id,title,content,category,publish_at AS date,is_published,
          NULL::uuid AS batch_id,NULL::uuid AS mentor_id,NULL::uuid AS semester_id
        FROM parent_announcements WHERE deleted_at IS NULL
    """,
        ("title", "category", "date", "is_published"),
        "institution",
        "Institution-wide parent publications; batch, semester and mentor filters do not apply.",
    ),
    "calendar": Source(
        "Academic calendar",
        """
        SELECT ac.id,ac.title,ac.type AS category,ac.start_date AS date,ac.duration_days,ac.is_break,ac.description,
          gy.start_year::text || '–' || gy.end_year::text AS cohort,ac.graduation_year_id,ac.semester_id,
          NULL::uuid AS batch_id,NULL::uuid AS mentor_id
        FROM academic_calendar ac JOIN graduation_years gy ON gy.id=ac.graduation_year_id
    """,
        ("title", "category", "cohort", "date", "duration_days", "is_break"),
        "calendar",
        "Cohort-level calendar entries. Class timetables and examinations appear in separate tabs.",
    ),
    "holidays": Source(
        "Holiday calendar",
        """
        SELECT id,name AS title,type::text AS category,start_date AS date,end_date,academic_year,description,
          NULL::uuid AS batch_id,NULL::uuid AS mentor_id,NULL::uuid AS semester_id FROM holidays
    """,
        ("title", "category", "date", "end_date", "academic_year"),
        "institution",
    ),
    "events": Source(
        "Industry and impact events",
        """
        SELECT e.id,e.title,e.category,e.start_date AS date,e.end_date,e.application_deadline,e.venue,
          e.description,e.is_team_event,
          (SELECT count(*) FROM impact_event_participants p WHERE p.event_id=e.id) AS participants,
          ARRAY(SELECT bs.batch_id FROM impact_event_batches eb JOIN batch_semesters bs ON bs.id=eb.batch_semester_id WHERE eb.event_id=e.id) AS batch_ids,
          NULL::uuid AS batch_id,NULL::uuid AS mentor_id,NULL::uuid AS semester_id
        FROM impact_events e WHERE e.archived_at IS NULL
    """,
        ("title", "category", "date", "application_deadline", "participants"),
        "multi",
        "Impact events are available, but they are not a substitute for an OJT project/milestone source.",
    ),
    "data_quality": Source(
        "Data quality findings",
        """
        SELECT 'timing:' || cs.id AS id,'Missing actual start' AS title,'Class delivery' AS category,
          'High' AS severity,'Open' AS status,cs.scheduled_start AS date,b.name AS batch,
          cs.title AS detail,bs.batch_id,cs.faculty_id AS mentor_id,yss.semester_id
        FROM class_sessions cs JOIN batch_semesters bs ON bs.id=cs.batch_semester_id
        JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id JOIN batches b ON b.id=bs.batch_id
        WHERE cs.status='completed' AND NOT EXISTS (SELECT 1 FROM live_sessions ls WHERE ls.class_session_id=cs.id AND ls.actual_start IS NOT NULL)
        UNION ALL
        SELECT 'result:' || r.id,'Unmatched examination result','Examinations','Medium','Open',e.date::timestamp,
          b.name,e.title,bs.batch_id,e.faculty,yss.semester_id
        FROM examination_results r JOIN examinations e ON e.id=r.examination_id
        JOIN batch_semesters bs ON bs.id=e.batch_semester_id JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
        JOIN batches b ON b.id=bs.batch_id WHERE r.student_id IS NULL OR r.match_status<>'matched'
    """,
        ("title", "category", "batch", "severity", "date"),
        note="Computed checks for missing completion timestamps and unmatched examination results. No audited denominator exists for an institutional error-rate KPI.",
    ),
}

for key, kind, title in [
    ("actions", "action", "Action register"),
    ("tasks", "task", "Operational tasks"),
    ("compliance", "compliance", "University compliance register"),
    ("projects", "project", "OJT projects"),
    ("incidents", "incident", "Technology incidents"),
    ("interventions", "intervention", "Student interventions"),
    ("corrections", "correction", "Correction register"),
]:
    SOURCES[key] = Source(
        title,
        f"""
        SELECT w.id,w.kind,w.title,w.description,w.status,w.severity,a.display_name AS owner,
          w.owner_id,w.due_date AS date,w.due_date,w.root_cause,w.evidence,w.source_module,w.source_id,
          w.version,w.created_at,w.updated_at,w.closed_at,w.completed_at,w.function_name,w.category,w.escalation_level,b.name AS batch,w.batch_id,
          NULL::uuid AS mentor_id,NULL::uuid AS semester_id
        FROM mis.work_items w JOIN mis.accounts a ON a.id=w.owner_id LEFT JOIN batches b ON b.id=w.batch_id
        WHERE w.kind='{kind}'
    """,
        ("title", "status", "severity", "owner", "date", "batch"),
        "work",
        "Persisted MIS register. No historical records for this workflow were supplied in the LMS dump. Date filter uses due date; unassigned items appear only in institution-wide scope.",
    )

# Risk remains a query projection; flags do not alter student records or outcomes.

SOURCES["students"] = replace(
    SOURCES["students"],
    sql=risk_projection(SOURCES["students"].sql, SOURCES["attendance"].sql),
    note="Single attendance-based risk rule: below 40% is High Risk, 40% or above is No Risk, and missing attendance is No attendance evidence. Other metrics use the selected period.",
)
