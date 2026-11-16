BEGIN;

CREATE TABLE IF NOT EXISTS mis.ai_query_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id uuid REFERENCES mis.accounts(id) ON DELETE SET NULL,
    question text NOT NULL,
    generated_sql text,
    model text NOT NULL,
    row_count integer,
    succeeded boolean NOT NULL DEFAULT false,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

CREATE OR REPLACE VIEW mis.ai_students AS
SELECT sb.id AS enrollment_id, u.id AS student_id, u.name AS student_name,
       sb.status AS enrollment_status, b.id AS batch_id, b.name AS batch_name,
       bt.name AS batch_type, s.name AS program, gy.start_year AS cohort_start_year,
       gy.end_year AS cohort_end_year, sem.number AS semester_number,
       sem.name AS semester_name, sb.joined_at
FROM student_batches sb
JOIN users u ON u.id=sb.student_id
JOIN batches b ON b.id=sb.batch_id
LEFT JOIN batch_types bt ON bt.id=b.batch_type_id
LEFT JOIN year_specializations ys ON ys.id=b.year_specialization_id
LEFT JOIN specializations s ON s.id=ys.specialization_id
LEFT JOIN graduation_years gy ON gy.id=ys.graduation_year_id
LEFT JOIN LATERAL (
  SELECT se.number,se.name
  FROM batch_semesters bs
  JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
  JOIN semesters se ON se.id=yss.semester_id
  WHERE bs.batch_id=b.id
  ORDER BY (bs.status='active') DESC, bs.start_date DESC NULLS LAST
  LIMIT 1
) sem ON true;

CREATE OR REPLACE VIEW mis.ai_attendance AS
SELECT ar.id AS attendance_id, ar.student_id, u.name AS student_name,
       ar.status AS attendance_status, ar.marked_at, ar.is_guest,
       cs.id AS session_id, cs.title AS session_title, cs.scheduled_start,
       cs.scheduled_end, cs.status AS session_status, su.id AS subject_id,
       su.name AS subject_name, cs.faculty_id AS mentor_id, mentor.name AS mentor_name,
       b.id AS batch_id, b.name AS batch_name, bt.name AS batch_type,
       sp.name AS program, gy.start_year AS cohort_start_year,
       gy.end_year AS cohort_end_year, sem.number AS semester_number
FROM attendance_records ar
JOIN users u ON u.id=ar.student_id
JOIN class_sessions cs ON cs.id=ar.session_id
LEFT JOIN subjects su ON su.id=cs.subject_id
LEFT JOIN users mentor ON mentor.id=cs.faculty_id
LEFT JOIN batch_semesters bs ON bs.id=cs.batch_semester_id
LEFT JOIN batches b ON b.id=coalesce(bs.batch_id,ar.home_batch_id)
LEFT JOIN batch_types bt ON bt.id=b.batch_type_id
LEFT JOIN year_specializations ys ON ys.id=b.year_specialization_id
LEFT JOIN specializations sp ON sp.id=ys.specialization_id
LEFT JOIN graduation_years gy ON gy.id=ys.graduation_year_id
LEFT JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
LEFT JOIN semesters sem ON sem.id=yss.semester_id;

CREATE OR REPLACE VIEW mis.ai_sessions AS
SELECT cs.id AS session_id, cs.title AS session_title, su.id AS subject_id,
       su.name AS subject_name, cs.faculty_id AS mentor_id, mentor.name AS mentor_name,
       cs.scheduled_start, cs.scheduled_end, ls.actual_start, ls.actual_end,
       cs.status AS session_status, cs.counts_for_attendance,
       CASE WHEN ls.actual_start IS NULL THEN NULL
            ELSE round(extract(epoch FROM (ls.actual_start-cs.scheduled_start))/60.0,1) END AS minutes_late,
       CASE WHEN ls.actual_start IS NULL THEN 'No telemetry'
            WHEN ls.actual_start<=cs.scheduled_start+interval '10 minutes' THEN 'On time'
            ELSE 'Delayed' END AS delivery_timing,
       b.id AS batch_id, b.name AS batch_name, bt.name AS batch_type,
       sp.name AS program, gy.start_year AS cohort_start_year,
       gy.end_year AS cohort_end_year, sem.number AS semester_number
FROM class_sessions cs
LEFT JOIN subjects su ON su.id=cs.subject_id
LEFT JOIN users mentor ON mentor.id=cs.faculty_id
LEFT JOIN LATERAL (
  SELECT min(actual_start) AS actual_start,max(actual_end) AS actual_end
  FROM live_sessions l WHERE l.class_session_id=cs.id
) ls ON true
LEFT JOIN batch_semesters bs ON bs.id=cs.batch_semester_id
LEFT JOIN batches b ON b.id=bs.batch_id
LEFT JOIN batch_types bt ON bt.id=b.batch_type_id
LEFT JOIN year_specializations ys ON ys.id=b.year_specialization_id
LEFT JOIN specializations sp ON sp.id=ys.specialization_id
LEFT JOIN graduation_years gy ON gy.id=ys.graduation_year_id
LEFT JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
LEFT JOIN semesters sem ON sem.id=yss.semester_id;

CREATE OR REPLACE VIEW mis.ai_feedback AS
SELECT sfr.id AS response_id, sfr.submitted_at, sfr.session_id,
       sfr.student_id, student.name AS student_name,
       sfr.faculty_id AS mentor_id, mentor.name AS mentor_name,
       sq.question_text, sq.question_type, sfr.response_text,
       CASE WHEN trim(sfr.response_text) ~ '^[1-5](\.0+)?$'
            THEN trim(sfr.response_text)::numeric ELSE NULL END AS numeric_rating,
       cs.scheduled_start, su.name AS subject_name, b.id AS batch_id,
       b.name AS batch_name, bt.name AS batch_type, sp.name AS program,
       gy.start_year AS cohort_start_year, gy.end_year AS cohort_end_year,
       sem.number AS semester_number
FROM session_feedback_responses sfr
LEFT JOIN users student ON student.id=sfr.student_id
LEFT JOIN users mentor ON mentor.id=sfr.faculty_id
LEFT JOIN session_questions sq ON sq.id=sfr.session_question_id
LEFT JOIN class_sessions cs ON cs.id=sfr.session_id
LEFT JOIN subjects su ON su.id=cs.subject_id
LEFT JOIN batch_semesters bs ON bs.id=cs.batch_semester_id
LEFT JOIN batches b ON b.id=bs.batch_id
LEFT JOIN batch_types bt ON bt.id=b.batch_type_id
LEFT JOIN year_specializations ys ON ys.id=b.year_specialization_id
LEFT JOIN specializations sp ON sp.id=ys.specialization_id
LEFT JOIN graduation_years gy ON gy.id=ys.graduation_year_id
LEFT JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
LEFT JOIN semesters sem ON sem.id=yss.semester_id;

CREATE OR REPLACE VIEW mis.ai_assignments AS
SELECT a.id AS assignment_id, a.title AS assignment_title, a.type AS assignment_type,
       a.status AS assignment_status, a.approval_status, a.due_at, a.max_score,
       su.name AS subject_name, b.id AS batch_id, b.name AS batch_name,
       bt.name AS batch_type, sem.number AS semester_number,
       sb.student_id, student.name AS student_name, sb.status AS enrollment_status,
       sub.id AS submission_id, sub.submitted_at, sub.graded_at, sub.marks,
       CASE WHEN sub.id IS NULL THEN 'Missing' WHEN sub.graded_at IS NULL THEN 'Submitted'
            ELSE 'Graded' END AS completion_status
FROM assignments a
JOIN batches b ON b.id=a.batch_id
LEFT JOIN batch_types bt ON bt.id=b.batch_type_id
LEFT JOIN subjects su ON su.id=a.subject_id
LEFT JOIN batch_semesters bs ON bs.id=a.batch_semester_id
LEFT JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
LEFT JOIN semesters sem ON sem.id=yss.semester_id
JOIN student_batches sb ON sb.batch_id=b.id
JOIN users student ON student.id=sb.student_id
LEFT JOIN assignment_submissions sub ON sub.assignment_id=a.id AND sub.student_id=sb.student_id;

CREATE OR REPLACE VIEW mis.ai_examination_results AS
SELECT er.id AS result_id, e.id AS examination_id, e.title AS examination_title,
       e.date AS examination_date, e.type AS examination_type,
       su.name AS subject_name, er.student_id, coalesce(u.name,er.student_name) AS student_name,
       er.marks_obtained, er.total_marks, er.percentage, er.tier, er.match_status,
       b.id AS batch_id, b.name AS batch_name, bt.name AS batch_type,
       sem.number AS semester_number
FROM examination_results er
JOIN examinations e ON e.id=er.examination_id
LEFT JOIN users u ON u.id=er.student_id
LEFT JOIN subjects su ON su.id=e.subject_id
LEFT JOIN batch_semesters bs ON bs.id=e.batch_semester_id
LEFT JOIN batches b ON b.id=bs.batch_id
LEFT JOIN batch_types bt ON bt.id=b.batch_type_id
LEFT JOIN year_specialization_semesters yss ON yss.id=bs.year_specialization_semester_id
LEFT JOIN semesters sem ON sem.id=yss.semester_id;

CREATE OR REPLACE VIEW mis.ai_internship_students AS
SELECT s.* FROM mis.ai_students s WHERE lower(coalesce(s.batch_type,'')) LIKE '%intern%';

CREATE OR REPLACE VIEW mis.ai_batch_managers AS
SELECT bm.id AS assignment_id, bm.assigned_at, bm.manager_id,
       manager.name AS manager_name, b.id AS batch_id, b.name AS batch_name,
       bt.name AS batch_type, sp.name AS program,
       gy.start_year AS cohort_start_year, gy.end_year AS cohort_end_year
FROM batch_managers bm
JOIN users manager ON manager.id=bm.manager_id
JOIN batches b ON b.id=bm.batch_id
LEFT JOIN batch_types bt ON bt.id=b.batch_type_id
LEFT JOIN year_specializations ys ON ys.id=b.year_specialization_id
LEFT JOIN specializations sp ON sp.id=ys.specialization_id
LEFT JOIN graduation_years gy ON gy.id=ys.graduation_year_id;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='polaris_api') THEN
    GRANT SELECT ON mis.ai_students,mis.ai_attendance,mis.ai_sessions,mis.ai_feedback,
      mis.ai_assignments,mis.ai_examination_results,mis.ai_internship_students,
      mis.ai_batch_managers TO polaris_api;
    GRANT SELECT,INSERT ON mis.ai_query_audit TO polaris_api;
  END IF;
END $$;

COMMIT;
