from fastapi import APIRouter, Depends, HTTPException

from .analytics import Filters, filters
from .auth import current_user
from .db import query
from .records import source_query

router = APIRouter(prefix="/calendar", tags=["Scheduling"])


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
        rows = query(
            f"SELECT id::text,title,date AS start,coalesce({end_expression},date) AS end FROM ({sql}) x WHERE date<%(to_date)s::date+1 AND coalesce({end_expression},date)>=%(from_date)s::date ORDER BY date,id LIMIT 1001",
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
