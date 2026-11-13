"""Explicit, read-only projections of the additional production systems.

No views are created in PostgreSQL. Identity filters use exact normalized email
matches; unlinked records remain visible only when no LMS identity filter is set.
"""

PROJECTIONS = {
    "internship_placements": {
        "title": "Internship company and role records",
        "sql": """SELECT i.id::text AS id,i."Name" AS student,i."Company" AS company,
          i."Role" AS role,i."Batch"::text AS cohort,i."Joining" AS joining,
          i."Stipend" AS stipend,i."Tenure - Months" AS tenure_months,i.created_at AS date,
          lower(trim(i." MSU Email Address")) AS student_email,ARRAY[]::text[] AS mentor_emails
          FROM "LMS".student_internships i""",
        "columns": ("student", "company", "role", "cohort", "joining", "stipend", "tenure_months", "date"),
        "note": "Production internship records; dates filter the recorded creation date, not the free-text joining date. Multiple placements for one student remain separate. LMS filters require an exact email match. Mentor filtering is unavailable for this source.",
    },
    "ojt_allocations": {
        "title": "OJT student project allocations",
        "sql": """SELECT a.id,s.full_name AS student,p.title AS project,c.name AS cohort,
          s.batch,a.status::text AS status,m.full_name AS mentor,a.created_at AS date,
          a.milestone_industry_alignment,a.milestone_problem_statement,
          a.milestone_end_users_defined,a.milestone_feature_list,
          a.milestone_tech_stack_selection,a.milestone_proposal_approved,
          lower(trim(s.email)) AS student_email,
          ARRAY[lower(trim(m.email)),lower(trim(m2.email))] AS mentor_emails
          FROM ojt_system.ojt_allocations a
          JOIN ojt_system.ojt_students s ON s.id=a.student_id
          JOIN ojt_system.ojt_projects p ON p.id=a.project_id
          JOIN ojt_system.ojt_cohorts c ON c.id=a.cohort_id
          LEFT JOIN ojt_system.ojt_mentors m ON m.id=a.primary_mentor_id
          LEFT JOIN ojt_system.ojt_mentors m2 ON m2.id=a.secondary_mentor_id
          WHERE NOT coalesce(a.is_deleted,false) AND NOT coalesce(s.is_deleted,false)
            AND NOT coalesce(p.is_deleted,false) AND NOT coalesce(c.is_deleted,false)""",
        "columns": ("student", "project", "cohort", "batch", "status", "mentor", "date"),
        "note": "One row per production OJT allocation. Dates use allocation creation; milestones are current flags, not historical completion dates. LMS filters use exact email matches; OJT batch labels are retained from their source.",
    },
    "ojt_evaluations": {
        "title": "OJT evaluations",
        "sql": """SELECT e.id,s.full_name AS student,c.name AS cohort,s.batch,
          CASE WHEN e.evaluated_at IS NOT NULL AND e.final_marks_obtained IS NOT NULL
            THEN 'Evaluated' ELSE 'Pending evaluation' END AS status,
          e.final_marks_obtained AS marks,cfg.max_marks_snapshot AS maximum_marks,
          round(100.0*e.final_marks_obtained/nullif(cfg.max_marks_snapshot,0),1) AS percentage,
          e.attendance_status::text AS attendance,e.evaluated_at,
          coalesce(cfg.start_date,e.created_at) AS date,lower(trim(s.email)) AS student_email,
          ARRAY[]::text[] AS mentor_emails
          FROM ojt_system.ojt_evaluations e
          JOIN ojt_system.ojt_students s ON s.id=e.student_id
          JOIN ojt_system.ojt_cohort_evaluation_configs cfg ON cfg.id=e.cohort_evaluation_config_id
          JOIN ojt_system.ojt_cohorts c ON c.id=cfg.cohort_id
          WHERE NOT coalesce(s.is_deleted,false) AND NOT coalesce(c.is_deleted,false)""",
        "columns": (
            "student",
            "cohort",
            "batch",
            "status",
            "marks",
            "maximum_marks",
            "percentage",
            "attendance",
            "date",
        ),
        "note": "Production evaluation rows, scoped by scheduled evaluation start (creation date if absent). Completion requires an evaluation timestamp and final marks. Missing evaluation rows are not assumed failures. Mentor filtering is unavailable for this source.",
    },
}
