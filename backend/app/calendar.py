from fastapi import APIRouter, Depends, HTTPException

from .analytics import Filters, filters
from .auth import current_user
from .db import query
from .records import source_query

router = APIRouter(prefix="/calendar", tags=["Scheduling"])


EXCLUDED_EVENT_TITLES = (
    "Claude Campus Ambassador Program",
    "Great Indian AI Internship Challenge",
)


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
