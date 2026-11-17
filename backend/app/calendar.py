from fastapi import APIRouter, Depends, HTTPException, Query

from .analytics import Filters, filters, params
from .auth import current_user
from .db import query
from .records import source_query

router = APIRouter(prefix="/calendar", tags=["Scheduling"])


EXCLUDED_EVENT_TITLES = (
    "Claude Campus Ambassador Program",
    "Great Indian AI Internship Challenge",
)


def clean_title(title: str | None, subject: str | None = None) -> str:
    """Clean repeating merged session titles and normalize subject names."""
    if subject and subject.strip():
        parts = [p.strip() for p in subject.split("+") if p.strip()]
        if parts:
            return " / ".join(list(dict.fromkeys(parts)))
        return subject.strip()
    if not title:
        return "Untitled Session"
    parts = [p.strip() for p in title.split("+") if p.strip()]
    if parts:
        return " / ".join(list(dict.fromkeys(parts)))
    return title.strip()


@router.get("")
def events(f: Filters = Depends(filters), user=Depends(current_user)):
    sources = [
        ("calendar", "Academic event", "date + (duration_days-1)*interval '1 day'"),
        ("sessions", "Class", "scheduled_end"),
        ("examinations", "Examination", "date"),
        ("holidays", "Holiday", "end_date"),
        ("events", "Industry event", "end_date"),
        ("actions", "Action deadline", "date"),
        ("tasks", "Task deadline", "date"),
        ("compliance", "Compliance deadline", "date"),
    ]
    result = []
    truncated = False
    for name, category, end_expression in sources:
        try:
            _, sql, p = source_query(name, f, apply_dates=False)
        except HTTPException as exc:
            if exc.status_code == 409:
                continue
            raise

        if name == "sessions":
            extra_cols = "x.batch, x.mentor, x.subject, sm.name AS semester, x.status"
        elif name == "examinations":
            extra_cols = "x.batch, NULL::text AS mentor, x.subject, sm.name AS semester, x.status"
        else:
            extra_cols = "NULL::text AS batch, NULL::text AS mentor, NULL::text AS subject, sm.name AS semester, NULL::text AS status"

        rows = query(
            f"""SELECT x.id::text, x.title, x.date AS start, coalesce({end_expression}, x.date) AS end,
                       {extra_cols}
                FROM ({sql}) x
                LEFT JOIN semesters sm ON sm.id = x.semester_id
                WHERE x.date < %(to_date)s::date + 1
                  AND coalesce({end_expression}, x.date) >= %(from_date)s::date
                  AND NOT (
                    coalesce(x.title, '') ILIKE '%%Claude Campus Ambassador Program%%'
                    OR coalesce(x.title, '') ILIKE '%%Great Indian AI Internship Challenge%%'
                  )
                ORDER BY x.date, x.id
                LIMIT 1001""",
            p,
        )
        if len(rows) > 1000:
            truncated = True
        for row in rows[:1000]:
            result.append(row | {"source": name, "category": category})
    return {
        "events": result,
        "truncated": truncated,
        "note": "Calendar entries combine actual schedules, academic events, holidays and MIS deadlines. Source-specific scope applies; holidays are institution-wide.",
    }


@router.get("/conflicts")
def conflicts(
    f: Filters = Depends(filters),
    conflict_type: str = Query("all", pattern="^(all|batch|faculty|room)$"),
    include_all: bool = Query(False),
    user=Depends(current_user),
):
    p = params(f)
    date_filter_sql = (
        ""
        if include_all
        else "AND greatest(e1.scheduled_start, e2.scheduled_start) < %(to_date)s::date + 1 AND least(e1.scheduled_end, e2.scheduled_end) >= %(from_date)s::date"
    )

    batch_conflicts = []
    faculty_conflicts = []
    room_conflicts = []

    # 1. Batch Conflicts: Same batch/section scheduled for multiple overlapping classes
    if conflict_type in {"all", "batch"}:
        sql_batch = f"""
        WITH scoped_batches AS (
            SELECT b.id, b.name, sem.name AS semester_name
            FROM batches b
            JOIN year_specializations ys ON ys.id = b.year_specialization_id
            JOIN year_specialization_semesters yss ON yss.year_specialization_id = ys.id
            JOIN semesters sem ON sem.id = yss.semester_id
            WHERE (%(graduation_year_id)s::uuid IS NULL OR ys.graduation_year_id = %(graduation_year_id)s)
              AND (%(specialization_id)s::uuid IS NULL OR ys.specialization_id = %(specialization_id)s)
              AND (%(semester_id)s::uuid IS NULL OR sem.id = %(semester_id)s)
              AND (%(batch_id)s::uuid IS NULL OR b.id = %(batch_id)s)
        ),
        session_events AS (
            SELECT 
                coalesce(cs.class_session_id, cs.id) AS session_key,
                b.id AS batch_id,
                b.name AS batch_name,
                sem.name AS semester_name,
                min(cs.scheduled_start) AS scheduled_start,
                max(cs.scheduled_end) AS scheduled_end,
                string_agg(DISTINCT coalesce(su.name, cs.title), ' / ') AS titles,
                string_agg(DISTINCT su.name, ', ') AS subjects,
                string_agg(DISTINCT u.name, ', ') AS faculties,
                string_agg(DISTINCT r.room_number, ', ') AS rooms
            FROM class_sessions cs
            JOIN batch_semesters bs ON bs.id = cs.batch_semester_id
            JOIN batches b ON b.id = bs.batch_id
            JOIN year_specialization_semesters yss ON yss.id = bs.year_specialization_semester_id
            JOIN semesters sem ON sem.id = yss.semester_id
            LEFT JOIN users u ON u.id = cs.faculty_id
            LEFT JOIN subjects su ON su.id = cs.subject_id
            LEFT JOIN rooms r ON r.id = cs.room_id
            WHERE cs.status != 'cancelled'
              AND b.id IN (SELECT id FROM scoped_batches)
              AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id = %(mentor_id)s)
              AND NOT (
                coalesce(cs.title, '') ILIKE '%%Claude Campus Ambassador Program%%'
                OR coalesce(cs.title, '') ILIKE '%%Great Indian AI Internship Challenge%%'
              )
            GROUP BY coalesce(cs.class_session_id, cs.id), b.id, b.name, sem.name
        )
        SELECT 
            e1.batch_id::text,
            e1.batch_name,
            e1.semester_name,
            e1.session_key::text AS session_key1,
            e2.session_key::text AS session_key2,
            e1.titles AS title1, e2.titles AS title2,
            e1.subjects AS subject1, e2.subjects AS subject2,
            e1.faculties AS faculty1, e2.faculties AS faculty2,
            e1.rooms AS rooms1, e2.rooms AS rooms2,
            e1.scheduled_start AS start1, e1.scheduled_end AS end1,
            e2.scheduled_start AS start2, e2.scheduled_end AS end2,
            greatest(e1.scheduled_start, e2.scheduled_start) AS overlap_start,
            least(e1.scheduled_end, e2.scheduled_end) AS overlap_end,
            round(extract(epoch from (least(e1.scheduled_end, e2.scheduled_end) - greatest(e1.scheduled_start, e2.scheduled_start))) / 60) AS overlap_minutes
        FROM session_events e1
        JOIN session_events e2 ON e1.batch_id = e2.batch_id AND e1.session_key < e2.session_key
        WHERE e1.scheduled_start < e2.scheduled_end AND e1.scheduled_end > e2.scheduled_start
          {date_filter_sql}
        ORDER BY overlap_start DESC
        LIMIT 500;
        """
        for r in query(sql_batch, p):
            clean_t1 = clean_title(r["title1"], r.get("subject1"))
            clean_t2 = clean_title(r["title2"], r.get("subject2"))
            overlap_min = int(r["overlap_minutes"] or 0)
            fac1 = r["faculty1"] or "Unassigned"
            fac2 = r["faculty2"] or "Unassigned"
            rm1 = r["rooms1"] or "Unassigned"
            rm2 = r["rooms2"] or "Unassigned"
            desc = (
                f"{r['batch_name']} ({r['semester_name']}) has 2 overlapping scheduled classes: "
                f"'{clean_t1}' (Mentor: {fac1}, Venue: {rm1}) and "
                f"'{clean_t2}' (Mentor: {fac2}, Venue: {rm2}), overlapping by {overlap_min} mins."
            )
            batch_conflicts.append(
                {
                    "id": f"batch-{r['batch_id']}-{r['session_key1']}-{r['session_key2']}",
                    "conflict_type": "batch",
                    "target_name": r["batch_name"],
                    "target_subtext": r["semester_name"],
                    "batch_id": r["batch_id"],
                    "batch_name": r["batch_name"],
                    "semester_name": r["semester_name"],
                    "overlap_start": r["overlap_start"],
                    "overlap_end": r["overlap_end"],
                    "overlap_minutes": overlap_min,
                    "conflict_reason": desc,
                    "session_1": {
                        "id": r["session_key1"],
                        "title": clean_t1,
                        "faculty": fac1,
                        "room": rm1,
                        "start": r["start1"],
                        "end": r["end1"],
                    },
                    "session_2": {
                        "id": r["session_key2"],
                        "title": clean_t2,
                        "faculty": fac2,
                        "room": rm2,
                        "start": r["start2"],
                        "end": r["end2"],
                    },
                }
            )

    # 2. Faculty Conflicts: Same mentor scheduled for multiple overlapping classes
    if conflict_type in {"all", "faculty"}:
        sql_faculty = f"""
        WITH scoped_batches AS (
            SELECT b.id
            FROM batches b
            JOIN year_specializations ys ON ys.id = b.year_specialization_id
            JOIN year_specialization_semesters yss ON yss.year_specialization_id = ys.id
            JOIN semesters sem ON sem.id = yss.semester_id
            WHERE (%(graduation_year_id)s::uuid IS NULL OR ys.graduation_year_id = %(graduation_year_id)s)
              AND (%(specialization_id)s::uuid IS NULL OR ys.specialization_id = %(specialization_id)s)
              AND (%(semester_id)s::uuid IS NULL OR sem.id = %(semester_id)s)
              AND (%(batch_id)s::uuid IS NULL OR b.id = %(batch_id)s)
        ),
        session_events AS (
            SELECT 
                coalesce(cs.class_session_id, cs.id) AS session_key,
                cs.faculty_id,
                u.name AS faculty_name,
                min(cs.scheduled_start) AS scheduled_start,
                max(cs.scheduled_end) AS scheduled_end,
                string_agg(DISTINCT coalesce(su.name, cs.title), ' / ') AS titles,
                string_agg(DISTINCT su.name, ', ') AS subjects,
                string_agg(DISTINCT b.name, ', ') AS batches,
                string_agg(DISTINCT r.room_number, ', ') AS rooms
            FROM class_sessions cs
            JOIN users u ON u.id = cs.faculty_id
            LEFT JOIN subjects su ON su.id = cs.subject_id
            LEFT JOIN batch_semesters bs ON bs.id = cs.batch_semester_id
            LEFT JOIN batches b ON b.id = bs.batch_id
            LEFT JOIN rooms r ON r.id = cs.room_id
            WHERE cs.status != 'cancelled'
              AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id = %(mentor_id)s)
              AND (b.id IS NULL OR b.id IN (SELECT id FROM scoped_batches))
              AND NOT (
                coalesce(cs.title, '') ILIKE '%%Claude Campus Ambassador Program%%'
                OR coalesce(cs.title, '') ILIKE '%%Great Indian AI Internship Challenge%%'
              )
            GROUP BY coalesce(cs.class_session_id, cs.id), cs.faculty_id, u.name
        )
        SELECT 
            e1.faculty_id::text,
            e1.faculty_name,
            e1.session_key::text AS session_key1,
            e2.session_key::text AS session_key2,
            e1.titles AS title1, e2.titles AS title2,
            e1.subjects AS subject1, e2.subjects AS subject2,
            e1.batches AS batches1, e2.batches AS batches2,
            e1.rooms AS rooms1, e2.rooms AS rooms2,
            e1.scheduled_start AS start1, e1.scheduled_end AS end1,
            e2.scheduled_start AS start2, e2.scheduled_end AS end2,
            greatest(e1.scheduled_start, e2.scheduled_start) AS overlap_start,
            least(e1.scheduled_end, e2.scheduled_end) AS overlap_end,
            round(extract(epoch from (least(e1.scheduled_end, e2.scheduled_end) - greatest(e1.scheduled_start, e2.scheduled_start))) / 60) AS overlap_minutes
        FROM session_events e1
        JOIN session_events e2 ON e1.faculty_id = e2.faculty_id AND e1.session_key < e2.session_key
        WHERE e1.scheduled_start < e2.scheduled_end AND e1.scheduled_end > e2.scheduled_start
          {date_filter_sql}
        ORDER BY overlap_start DESC
        LIMIT 500;
        """
        for r in query(sql_faculty, p):
            clean_t1 = clean_title(r["title1"], r.get("subject1"))
            clean_t2 = clean_title(r["title2"], r.get("subject2"))
            overlap_min = int(r["overlap_minutes"] or 0)
            bt1 = r["batches1"] or "Unassigned"
            bt2 = r["batches2"] or "Unassigned"
            rm1 = r["rooms1"] or "Unassigned"
            rm2 = r["rooms2"] or "Unassigned"
            desc = (
                f"{r['faculty_name']} is double-booked across 2 simultaneous classes: "
                f"'{clean_t1}' [{bt1}] in {rm1} and "
                f"'{clean_t2}' [{bt2}] in {rm2}, overlapping by {overlap_min} mins."
            )
            faculty_conflicts.append(
                {
                    "id": f"faculty-{r['faculty_id']}-{r['session_key1']}-{r['session_key2']}",
                    "conflict_type": "faculty",
                    "target_name": r["faculty_name"],
                    "target_subtext": "Mentor Double-Booking",
                    "faculty_id": r["faculty_id"],
                    "faculty_name": r["faculty_name"],
                    "overlap_start": r["overlap_start"],
                    "overlap_end": r["overlap_end"],
                    "overlap_minutes": overlap_min,
                    "conflict_reason": desc,
                    "session_1": {
                        "id": r["session_key1"],
                        "title": clean_t1,
                        "batches": bt1,
                        "room": rm1,
                        "start": r["start1"],
                        "end": r["end1"],
                    },
                    "session_2": {
                        "id": r["session_key2"],
                        "title": clean_t2,
                        "batches": bt2,
                        "room": rm2,
                        "start": r["start2"],
                        "end": r["end2"],
                    },
                }
            )

    # 3. Room Conflicts: Physical classroom allocated to multiple distinct classes simultaneously
    if conflict_type in {"all", "room"}:
        sql_room = f"""
        WITH scoped_batches AS (
            SELECT b.id
            FROM batches b
            JOIN year_specializations ys ON ys.id = b.year_specialization_id
            JOIN year_specialization_semesters yss ON yss.year_specialization_id = ys.id
            JOIN semesters sem ON sem.id = yss.semester_id
            WHERE (%(graduation_year_id)s::uuid IS NULL OR ys.graduation_year_id = %(graduation_year_id)s)
              AND (%(specialization_id)s::uuid IS NULL OR ys.specialization_id = %(specialization_id)s)
              AND (%(semester_id)s::uuid IS NULL OR sem.id = %(semester_id)s)
              AND (%(batch_id)s::uuid IS NULL OR b.id = %(batch_id)s)
        ),
        session_events AS (
            SELECT 
                coalesce(cs.class_session_id, cs.id) AS session_key,
                cs.room_id,
                r.room_number,
                min(cs.scheduled_start) AS scheduled_start,
                max(cs.scheduled_end) AS scheduled_end,
                string_agg(DISTINCT coalesce(su.name, cs.title), ' / ') AS titles,
                string_agg(DISTINCT su.name, ', ') AS subjects,
                string_agg(DISTINCT u.name, ', ') AS faculties,
                string_agg(DISTINCT b.name, ', ') AS batches
            FROM class_sessions cs
            JOIN rooms r ON r.id = cs.room_id
            LEFT JOIN users u ON u.id = cs.faculty_id
            LEFT JOIN subjects su ON su.id = cs.subject_id
            LEFT JOIN batch_semesters bs ON bs.id = cs.batch_semester_id
            LEFT JOIN batches b ON b.id = bs.batch_id
            WHERE cs.status != 'cancelled'
              AND r.room_number !~* 'online'
              AND (%(mentor_id)s::uuid IS NULL OR cs.faculty_id = %(mentor_id)s)
              AND (b.id IS NULL OR b.id IN (SELECT id FROM scoped_batches))
              AND NOT (
                coalesce(cs.title, '') ILIKE '%%Claude Campus Ambassador Program%%'
                OR coalesce(cs.title, '') ILIKE '%%Great Indian AI Internship Challenge%%'
              )
            GROUP BY coalesce(cs.class_session_id, cs.id), cs.room_id, r.room_number
        )
        SELECT 
            e1.room_id::text,
            e1.room_number,
            e1.session_key::text AS session_key1,
            e2.session_key::text AS session_key2,
            e1.titles AS title1, e2.titles AS title2,
            e1.subjects AS subject1, e2.subjects AS subject2,
            e1.faculties AS faculty1, e2.faculties AS faculty2,
            e1.batches AS batches1, e2.batches AS batches2,
            e1.scheduled_start AS start1, e1.scheduled_end AS end1,
            e2.scheduled_start AS start2, e2.scheduled_end AS end2,
            greatest(e1.scheduled_start, e2.scheduled_start) AS overlap_start,
            least(e1.scheduled_end, e2.scheduled_end) AS overlap_end,
            round(extract(epoch from (least(e1.scheduled_end, e2.scheduled_end) - greatest(e1.scheduled_start, e2.scheduled_start))) / 60) AS overlap_minutes
        FROM session_events e1
        JOIN session_events e2 ON e1.room_id = e2.room_id AND e1.session_key < e2.session_key
        WHERE e1.scheduled_start < e2.scheduled_end AND e1.scheduled_end > e2.scheduled_start
          {date_filter_sql}
        ORDER BY overlap_start DESC
        LIMIT 500;
        """
        for r in query(sql_room, p):
            clean_t1 = clean_title(r["title1"], r.get("subject1"))
            clean_t2 = clean_title(r["title2"], r.get("subject2"))
            overlap_min = int(r["overlap_minutes"] or 0)
            fac1 = r["faculty1"] or "Unassigned"
            fac2 = r["faculty2"] or "Unassigned"
            bt1 = r["batches1"] or "Unassigned"
            bt2 = r["batches2"] or "Unassigned"
            desc = (
                f"Classroom {r['room_number']} is double-booked for 2 simultaneous classes: "
                f"'{clean_t1}' by {fac1} [{bt1}] and "
                f"'{clean_t2}' by {fac2} [{bt2}], overlapping by {overlap_min} mins."
            )
            room_conflicts.append(
                {
                    "id": f"room-{r['room_id']}-{r['session_key1']}-{r['session_key2']}",
                    "conflict_type": "room",
                    "target_name": f"Room {r['room_number']}",
                    "target_subtext": "Classroom Collision",
                    "room_id": r["room_id"],
                    "room_number": r["room_number"],
                    "overlap_start": r["overlap_start"],
                    "overlap_end": r["overlap_end"],
                    "overlap_minutes": overlap_min,
                    "conflict_reason": desc,
                    "session_1": {
                        "id": r["session_key1"],
                        "title": clean_t1,
                        "faculty": fac1,
                        "batches": bt1,
                        "start": r["start1"],
                        "end": r["end1"],
                    },
                    "session_2": {
                        "id": r["session_key2"],
                        "title": clean_t2,
                        "faculty": fac2,
                        "batches": bt2,
                        "start": r["start2"],
                        "end": r["end2"],
                    },
                }
            )

    return {
        "summary": {
            "total": len(batch_conflicts) + len(faculty_conflicts) + len(room_conflicts),
            "batch_conflicts": len(batch_conflicts),
            "faculty_conflicts": len(faculty_conflicts),
            "room_conflicts": len(room_conflicts),
            "affected_batches": len({c["batch_name"] for c in batch_conflicts if c.get("batch_name")}),
            "affected_faculties": len({c["faculty_name"] for c in faculty_conflicts if c.get("faculty_name")}),
            "affected_rooms": len({c["room_number"] for c in room_conflicts if c.get("room_number")}),
        },
        "batch_conflicts": batch_conflicts,
        "faculty_conflicts": faculty_conflicts,
        "room_conflicts": room_conflicts,
    }

