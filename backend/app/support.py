from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .auth import current_user, editor
from .config import settings
from .db import connection, query
from .workflows import audit

router = APIRouter(prefix="/support", tags=["Support"])
SLA = {"Critical": 24, "High": 48, "Medium": 72, "Low": 120}


def require_production_source():
    if settings().source_database_url:
        raise HTTPException(
            409,
            "Production does not provide support workflow records. Local snapshot fallback is disabled.",
        )


class SupportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    user_id: UUID
    category: Literal["bug", "feedback", "other"]
    description: str = Field(min_length=5, max_length=10000)
    severity: Literal["Low", "Medium", "High", "Critical"] = "Medium"
    owner_id: UUID


class SupportUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: int = Field(ge=0)
    status: Literal["open", "acknowledged", "resolved"]
    severity: Literal["Low", "Medium", "High", "Critical"]
    owner_id: UUID
    note: str = Field(min_length=3, max_length=4000)


@router.get("/students")
def students(user=Depends(current_user)):
    return query(
        "SELECT DISTINCT u.id,u.name FROM users u JOIN student_batches sb ON sb.student_id=u.id WHERE u.is_active ORDER BY u.name"
    )


@router.post("", status_code=201)
def create(body: SupportCreate, user=Depends(editor)):
    require_production_source()
    with connection() as conn:
        if not conn.execute("SELECT id FROM users WHERE id=%s AND is_active", (body.user_id,)).fetchone():
            raise HTTPException(422, "Select an active LMS user")
        if not conn.execute(
            "SELECT id FROM mis.accounts WHERE id=%s AND active AND role IN ('admin','operator')",
            (body.owner_id,),
        ).fetchone():
            raise HTTPException(422, "Select an active MIS owner")
        row = conn.execute(
            "INSERT INTO support_reports(user_id,category,description) VALUES (%s,%s,%s) RETURNING *",
            (body.user_id, body.category, body.description),
        ).fetchone()
        conn.execute(
            """INSERT INTO mis.support_metadata(report_id,owner_id,severity,sla_due)
                        VALUES (%s,%s,%s,now()+make_interval(hours=>%s))""",
            (row["id"], body.owner_id, body.severity, SLA[body.severity]),
        )
        audit(
            conn,
            user,
            "support",
            row["id"],
            "created",
            after={"status": "open", "severity": body.severity, "owner_id": body.owner_id},
        )
        return {"id": row["id"]}


@router.patch("/{report_id}")
def update(report_id: UUID, body: SupportUpdate, user=Depends(editor)):
    require_production_source()
    with connection() as conn:
        row = conn.execute(
            "SELECT id,status,resolved_at FROM support_reports WHERE id=%s FOR UPDATE", (report_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Support report not found")
        meta = conn.execute("SELECT * FROM mis.support_metadata WHERE report_id=%s", (report_id,)).fetchone()
        if (meta["version"] if meta else 0) != body.version:
            raise HTTPException(409, "This report changed. Reload before saving.")
        if not conn.execute(
            "SELECT id FROM mis.accounts WHERE id=%s AND active AND role IN ('admin','operator')",
            (body.owner_id,),
        ).fetchone():
            raise HTTPException(422, "Select an active MIS owner")
        conn.execute(
            """UPDATE support_reports SET status=%s,resolved_at=CASE WHEN %s='resolved' THEN coalesce(resolved_at,now()) ELSE NULL END WHERE id=%s""",
            (body.status, body.status, report_id),
        )
        conn.execute(
            """INSERT INTO mis.support_metadata(report_id,owner_id,severity,sla_due)
            VALUES (%s,%s,%s,now()+make_interval(hours=>%s)) ON CONFLICT(report_id) DO UPDATE
            SET owner_id=excluded.owner_id,severity=excluded.severity,version=mis.support_metadata.version+1,updated_at=now()""",
            (report_id, body.owner_id, body.severity, SLA[body.severity]),
        )
        audit(
            conn,
            user,
            "support",
            report_id,
            "updated",
            before=row | (meta or {}),
            after=body.model_dump(),
            note=body.note,
        )
        return {"id": report_id, "status": body.status, "version": body.version + 1}


@router.get("/{report_id}/history")
def history(report_id: UUID, user=Depends(current_user)):
    require_production_source()
    return query(
        """SELECT e.event,e.note,e.created_at,a.display_name AS actor FROM mis.audit_events e
                   JOIN mis.accounts a ON a.id=e.actor_id WHERE e.entity_type='support' AND e.entity_id=%s ORDER BY e.id DESC""",
        (str(report_id),),
    )
