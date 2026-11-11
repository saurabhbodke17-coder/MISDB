import json
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from .auth import current_user, editor
from .config import settings
from .db import connection, query

router = APIRouter(prefix="/work-items", tags=["Workflows"])
Status = Literal[
    "Open", "In progress", "Blocked", "Done – awaiting verification", "Verified & closed", "Reopened"
]
Kind = Literal["action", "task", "compliance", "project", "incident", "intervention", "correction"]


def require_production_source():
    if settings().source_database_url:
        raise HTTPException(
            409,
            "Production does not provide workflow records. Local snapshot fallback is disabled.",
        )


class WorkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Kind = "action"
    title: str = Field(min_length=3, max_length=250)
    description: str = Field(default="", max_length=10000)
    owner_id: UUID
    batch_id: UUID | None = None
    due_date: date
    severity: Literal["Low", "Medium", "High", "Critical"] = "Medium"
    root_cause: str = Field(default="", max_length=2000)
    function_name: str = Field(default="Unassigned", max_length=100)
    category: str = Field(default="Unclassified", max_length=100)
    source_module: str = Field(default="actions", max_length=50)
    source_id: str | None = Field(default=None, max_length=200)


class WorkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: int = Field(ge=1)
    status: Status
    owner_id: UUID
    due_date: date
    severity: Literal["Low", "Medium", "High", "Critical"]
    root_cause: str = Field(default="", max_length=2000)
    evidence: str = Field(default="", max_length=4000)
    note: str = Field(default="", max_length=4000)
    escalation_level: int = Field(default=0, ge=0, le=3)


def serializable(row):
    return json.loads(json.dumps(row, default=str))


def audit(conn, user, kind, entity_id, event, before=None, after=None, note=""):
    conn.execute(
        """INSERT INTO mis.audit_events(actor_id,entity_type,entity_id,event,before_data,after_data,note)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (
            user["id"],
            kind,
            str(entity_id),
            event,
            Jsonb(serializable(before)),
            Jsonb(serializable(after)),
            note,
        ),
    )


def validate_transition(old, new, evidence, role):
    if new in {"Done – awaiting verification", "Verified & closed"} and not evidence.strip():
        raise HTTPException(422, "Resolution evidence is required before completion or verification")
    if new == "Verified & closed" and role != "admin":
        raise HTTPException(403, "Only administrators can edit verified closure")
    if new == "Verified & closed" and old != new:
        if role != "admin":
            raise HTTPException(403, "Only administrators can verify closure")
        if old != "Done – awaiting verification":
            raise HTTPException(409, "Submit the action for verification first")
    if old == "Verified & closed" and new not in {"Verified & closed", "Reopened"}:
        raise HTTPException(409, "Reopen the closed item before changing its status")


@router.get("/owners")
def owners(user=Depends(current_user)):
    require_production_source()
    return query(
        "SELECT id,display_name,role FROM mis.accounts WHERE active AND role IN ('admin','operator') ORDER BY display_name"
    )


@router.post("", status_code=201)
def create(body: WorkCreate, user=Depends(editor)):
    require_production_source()
    values = body.model_dump()
    with connection() as conn:
        owner = conn.execute(
            "SELECT id FROM mis.accounts WHERE id=%s AND active AND role IN ('admin','operator')",
            (body.owner_id,),
        ).fetchone()
        if not owner:
            raise HTTPException(422, "Select an active owner")
        values["created_by"] = user["id"]
        row = conn.execute(
            """INSERT INTO mis.work_items(kind,title,description,owner_id,batch_id,due_date,severity,root_cause,source_module,source_id,created_by,function_name,category)
            VALUES (%(kind)s,%(title)s,%(description)s,%(owner_id)s,%(batch_id)s,%(due_date)s,%(severity)s,%(root_cause)s,%(source_module)s,%(source_id)s,%(created_by)s,%(function_name)s,%(category)s) RETURNING *""",
            values,
        ).fetchone()
        audit(conn, user, "work", row["id"], "created", after=row)
        return row


@router.get("/{item_id}")
def detail(item_id: UUID, user=Depends(current_user)):
    require_production_source()
    with connection() as conn:
        row = conn.execute(
            "SELECT w.*, a.display_name AS owner FROM mis.work_items w JOIN mis.accounts a ON a.id=w.owner_id WHERE w.id=%s",
            (item_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Work item not found")
        events = conn.execute(
            """SELECT e.event,e.note,e.created_at,a.display_name AS actor,e.after_data
                               FROM mis.audit_events e JOIN mis.accounts a ON a.id=e.actor_id
                               WHERE entity_type='work' AND entity_id=%s ORDER BY e.id DESC""",
            (str(item_id),),
        ).fetchall()
        return {"record": row, "history": events}


@router.patch("/{item_id}")
def update(item_id: UUID, body: WorkUpdate, user=Depends(editor)):
    require_production_source()
    with connection() as conn:
        before = conn.execute("SELECT * FROM mis.work_items WHERE id=%s FOR UPDATE", (item_id,)).fetchone()
        if not before:
            raise HTTPException(404, "Work item not found")
        if before["version"] != body.version:
            raise HTTPException(409, "This item changed. Reload before saving your edits.")
        validate_transition(before["status"], body.status, body.evidence, user["role"])
        if not conn.execute(
            "SELECT id FROM mis.accounts WHERE id=%s AND active AND role IN ('admin','operator')",
            (body.owner_id,),
        ).fetchone():
            raise HTTPException(422, "Select an active owner")
        data = body.model_dump() | {"id": item_id}
        row = conn.execute(
            """UPDATE mis.work_items SET status=%(status)s,owner_id=%(owner_id)s,due_date=%(due_date)s,
            severity=%(severity)s,root_cause=%(root_cause)s,evidence=%(evidence)s,escalation_level=%(escalation_level)s,version=version+1,updated_at=now(),
            completed_at=CASE WHEN %(status)s IN ('Done – awaiting verification','Verified & closed') THEN coalesce(completed_at,now()) ELSE NULL END,
            closed_at=CASE WHEN %(status)s='Verified & closed' THEN coalesce(closed_at,now()) ELSE NULL END
            WHERE id=%(id)s RETURNING *""",
            data,
        ).fetchone()
        audit(conn, user, "work", item_id, "updated", before, row, body.note)
        return row
