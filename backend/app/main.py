import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg import IntegrityError, OperationalError
from psycopg_pool import PoolTimeout
from pydantic import BaseModel, ConfigDict, Field

from . import ai, analytics, auth, calendar, chart_data, db, plots, records, support, workflows
from .auth import admin, current_user
from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("polaris")


@asynccontextmanager
async def lifespan(app):
    db.start_pool()
    yield
    if db.source_pool:
        db.source_pool.close()
    if db.pool:
        db.pool.close()


app = FastAPI(
    title="Polaris MIS API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings().environment != "production" else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings().environment != "production" else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT"],
    allow_headers=["Content-Type", "X-Requested-With"],
)


@app.middleware("http")
async def security(request: Request, call_next):
    request_id = str(uuid4())
    start = time.monotonic()
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.headers.get("x-requested-with") != "PolarisMIS":
            return JSONResponse({"detail": "Missing request verification header"}, status_code=403)
        if request.headers.get("origin") and request.headers["origin"] not in settings().allowed_origins:
            return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
    try:
        response = await call_next(request)
    except Exception:
        log.exception("Unhandled request error id=%s", request_id)
        response = JSONResponse(
            {"detail": "An unexpected error occurred", "request_id": request_id}, status_code=500
        )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "same-origin"
    log.info(
        "request=%s method=%s path=%s status=%s ms=%.1f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        (time.monotonic() - start) * 1000,
    )
    return response


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return JSONResponse(
        {"detail": "The record conflicts with existing data or references an unavailable record"},
        status_code=409,
    )


@app.exception_handler(OperationalError)
@app.exception_handler(PoolTimeout)
async def database_error(request, exc):
    return JSONResponse({"detail": "The database is temporarily unavailable"}, status_code=503)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/ready")
def ready():
    schema = db.one(
        "SELECT to_regclass('mis.accounts') AS accounts,to_regclass('mis.work_items') AS work_items"
    )
    if not schema["accounts"] or not schema["work_items"]:
        raise HTTPException(503, "Database migrations are required")
    return {"status": "ready"}


for router in [
    auth.router,
    analytics.router,
    records.router,
    workflows.router,
    support.router,
    plots.router,
    chart_data.router,
    calendar.router,
    ai.router,
]:
    app.include_router(router, prefix="/api")


class MetricSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attendance_target: float = Field(ge=0, le=100)
    delivery_target: float = Field(ge=0, le=100)
    completion_target: float = Field(ge=0, le=100)
    late_tolerance: int = Field(ge=0, le=60)
    risk_attendance: float = Field(ge=0, le=100)
    pass_mark: float = Field(ge=0, le=100)
    sla_target: float = Field(default=90, ge=0, le=100)
    task_target: float = Field(default=90, ge=0, le=100)
    late_counts_present: bool


@app.get("/api/settings")
def get_settings(user=Depends(current_user)):
    return analytics.metric_settings()


@app.put("/api/settings")
def set_settings(body: MetricSettings, user=Depends(admin)):
    from psycopg.types.json import Jsonb

    with db.connection() as conn:
        before = conn.execute("SELECT value FROM mis.settings WHERE key='metrics' FOR UPDATE").fetchone()[
            "value"
        ]
        conn.execute(
            "UPDATE mis.settings SET value=%s,updated_by=%s,updated_at=now() WHERE key='metrics'",
            (Jsonb(body.model_dump()), user["id"]),
        )
        workflows.audit(conn, user, "settings", "metrics", "updated", before, body.model_dump())
    return body


@app.get("/api/search")
def search(q: str = "", user=Depends(current_user)):
    if len(q.strip()) < 2:
        return []
    if len(q) > 200:
        raise HTTPException(422, "Search is too long")
    academic = db.query(
        """SELECT * FROM (
       SELECT sb.id::text AS id,u.name AS title,'students' AS source,'Student' AS type
       FROM users u JOIN student_batches sb ON sb.student_id=u.id WHERE u.name ILIKE %(q)s
       UNION ALL SELECT cs.id::text,coalesce(cs.title,su.name),'sessions','Class session'
       FROM class_sessions cs JOIN subjects su ON su.id=cs.subject_id WHERE coalesce(cs.title,su.name) ILIKE %(q)s
    ) hits ORDER BY title LIMIT 20""",
        {"q": f"%{q}%"},
    )
    return academic


@app.get("/api/notifications")
def notifications(user=Depends(current_user)):
    # Production provides no action/workflow source. Never fall back to local snapshot content.
    return []


@app.get("/api/coverage")
def coverage(user=Depends(current_user)):
    return {
        "source": settings().source_dump,
        "snapshot": settings().source_snapshot,
        "freshness": db.one("""SELECT
          (SELECT max(marked_at) FROM attendance_records) AS attendance_last_marked,
          (SELECT max(cs.scheduled_start) FROM attendance_records ar
            JOIN class_sessions cs ON cs.id=ar.session_id) AS latest_session_with_attendance,
          (SELECT max(scheduled_start) FROM class_sessions) AS latest_scheduled_session,
          (SELECT max(due_at) FROM assignments) AS latest_assignment_due"""),
        "available": [
            "attendance",
            "class scheduling",
            "assignments",
            "examination results",
            "session feedback",
            "announcements",
            "academic calendar",
            "impact events",
            "student concerns",
            "internship companies and roles",
            "OJT allocations and recorded milestones",
            "OJT evaluations",
        ],
        "missing": [
            "complete actual session timing coverage",
            "institutional uptime telemetry",
            "integration job history",
            "parent contact acknowledgements",
            "historic enrollment transitions",
            "OJT demo readiness and validated review-compliance denominators",
            "university submissions",
            "operational process histories",
            "support ticket owners, SLA deadlines and resolution timestamps",
            "secondary class-to-batch links",
        ],
        "workflows": "Production LMS and OJT sources are read-only. Institutional actions, interventions, operational tasks, compliance, corrections and incidents have no verified source mapping. OJT allocations and evaluations are available separately. Local fallback is disabled.",
    }
