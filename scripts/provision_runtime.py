"""Provision a limited API database role using the schema owner's DSN.

Set OWNER_DATABASE_URL and API_DATABASE_PASSWORD; run after restore and MIS migrations.
The role name is fixed to polaris_api. Does not grant permissions to public/anonymous clients.
"""

import os

import psycopg
from psycopg import sql

PUBLIC_TABLES = [
    "users",
    "student_batches",
    "class_sessions",
    "live_sessions",
    "attendance_records",
    "assignments",
    "assignment_submissions",
    "examinations",
    "examination_results",
    "batches",
    "batch_types",
    "batch_semesters",
    "year_specializations",
    "year_specialization_semesters",
    "specializations",
    "semesters",
    "graduation_years",
    "subjects",
    "faculty_subjects",
    "curriculum",
    "class_session_batches",
    "session_feedback_responses",
    "session_questions",
    "support_reports",
    "concerns",
    "announcements",
    "parent_announcements",
    "academic_calendar",
    "holidays",
    "impact_events",
    "impact_event_batches",
    "impact_event_participants",
]


def provision(owner_url, password):
    if len(password) < 24:
        raise ValueError("API database password must have at least 24 characters")
    with psycopg.connect(owner_url) as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname='polaris_api'"
        ).fetchone():
            conn.execute(
                sql.SQL(
                    "CREATE ROLE polaris_api LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
                ).format(sql.Literal(password))
            )
        else:
            conn.execute(
                sql.SQL("ALTER ROLE polaris_api PASSWORD {}").format(
                    sql.Literal(password)
                )
            )
        conn.execute("GRANT USAGE ON SCHEMA public,mis TO polaris_api")
        for table in PUBLIC_TABLES:
            conn.execute(
                sql.SQL("GRANT SELECT ON public.{} TO polaris_api").format(
                    sql.Identifier(table)
                )
            )
        conn.execute(
            "GRANT INSERT (user_id,category,description), UPDATE (status,resolved_at) ON public.support_reports TO polaris_api"
        )
        conn.execute("GRANT SELECT ON mis.accounts TO polaris_api")
        conn.execute(
            "GRANT SELECT,INSERT,UPDATE ON mis.sessions,mis.work_items,mis.support_metadata TO polaris_api"
        )
        conn.execute("GRANT SELECT,INSERT,DELETE ON mis.login_attempts TO polaris_api")
        conn.execute("GRANT SELECT,INSERT ON mis.audit_events TO polaris_api")
        conn.execute(
            "GRANT USAGE,SELECT ON SEQUENCE mis.audit_events_id_seq TO polaris_api"
        )
        conn.execute("GRANT SELECT,UPDATE ON mis.settings TO polaris_api")
        conn.execute("ALTER ROLE polaris_api SET statement_timeout='15s'")
    print(
        "Limited API role provisioned (no DDL, no audit UPDATE/DELETE, no credential-table access)."
    )


if __name__ == "__main__":
    provision(os.environ["OWNER_DATABASE_URL"], os.environ["API_DATABASE_PASSWORD"])
