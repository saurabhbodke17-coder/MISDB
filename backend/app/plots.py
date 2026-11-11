from fastapi import APIRouter, Depends

from .analytics import BATCH_SCOPE, SESSION_SCOPE, Filters, filters, metric_settings, params
from .auth import current_user
from .db import query
from .records import source_query

router = APIRouter(prefix="/plots", tags=["Plots"])


@router.get("/attendance-heatmap")
def attendance_heatmap(f: Filters = Depends(filters), user=Depends(current_user)):
    p = params(f) | metric_settings()
    return query(
        f"""WITH scoped_batches AS ({BATCH_SCOPE}),scoped_sessions AS ({SESSION_SCOPE})
      SELECT b.id AS batch_id,b.name AS batch,date_trunc('week',s.scheduled_start)::date AS week,
      count(*) FILTER(WHERE ar.status IN ('present','late','absent')) AS eligible,
      round(100.0*count(*) FILTER(WHERE ar.status='present' OR (%(late_counts_present)s AND ar.status='late'))/
       nullif(count(*) FILTER(WHERE ar.status IN ('present','late','absent')),0),1) AS attendance
      FROM scoped_sessions s JOIN attendance_records ar ON ar.session_id=s.id
      JOIN batches b ON b.id=coalesce(ar.home_batch_id,s.batch_id)
      WHERE s.counts_for_attendance AND b.id IN (SELECT id FROM scoped_batches)
      GROUP BY b.id,b.name,week ORDER BY b.name,week""",
        p,
    )


@router.get("/student-scatter")
def student_scatter(f: Filters = Depends(filters), user=Depends(current_user)):
    _, sql, p = source_query("students", f)
    return query(
        f"""SELECT id,student,batch,attendance,average_score FROM ({sql}) students
      WHERE attendance IS NOT NULL AND average_score IS NOT NULL ORDER BY student LIMIT 500""",
        p,
    )


@router.get("/task-timeline")
def task_timeline(f: Filters = Depends(filters), user=Depends(current_user)):
    _, sql, p = source_query("tasks", f)
    return query(
        f"SELECT id,title,owner,status,created_at,due_date,severity FROM ({sql}) tasks ORDER BY due_date LIMIT 100",
        p,
    )
