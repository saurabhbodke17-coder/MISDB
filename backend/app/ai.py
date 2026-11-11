import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import db
from .auth import current_user
from .config import settings

router = APIRouter(prefix="/ai", tags=["Database AI"])
log = logging.getLogger("polaris.ai")

ALLOWED_VIEWS = {
    "mis.ai_students",
    "mis.ai_attendance",
    "mis.ai_sessions",
    "mis.ai_feedback",
    "mis.ai_assignments",
    "mis.ai_examination_results",
    "mis.ai_internship_students",
    "mis.ai_batch_managers",
}

SCHEMA = """
mis.ai_students(enrollment_id, student_id, student_name, enrollment_status, batch_id,
 batch_name, batch_type, program, cohort_start_year, cohort_end_year, semester_number,
 semester_name, joined_at)
mis.ai_attendance(attendance_id, student_id, student_name, attendance_status, marked_at,
 is_guest, session_id, session_title, scheduled_start, scheduled_end, session_status,
 subject_id, subject_name, mentor_id, mentor_name, batch_id, batch_name, batch_type,
 program, cohort_start_year, cohort_end_year, semester_number)
mis.ai_sessions(session_id, session_title, subject_id, subject_name, mentor_id, mentor_name,
 scheduled_start, scheduled_end, actual_start, actual_end, session_status,
 counts_for_attendance, minutes_late, delivery_timing, batch_id, batch_name, batch_type,
 program, cohort_start_year, cohort_end_year, semester_number)
mis.ai_feedback(response_id, submitted_at, session_id, student_id, student_name, mentor_id,
 mentor_name, question_text, question_type, response_text, numeric_rating, scheduled_start,
 subject_name, batch_id, batch_name, batch_type, program, cohort_start_year,
 cohort_end_year, semester_number)
mis.ai_assignments(assignment_id, assignment_title, assignment_type, assignment_status,
 approval_status, due_at, max_score, subject_name, batch_id, batch_name, batch_type,
 semester_number, student_id, student_name, enrollment_status, submission_id,
 submitted_at, graded_at, marks, completion_status)
mis.ai_examination_results(result_id, examination_id, examination_title, examination_date,
 examination_type, subject_name, student_id, student_name, marks_obtained, total_marks,
 percentage, tier, match_status, batch_id, batch_name, batch_type, semester_number)
mis.ai_internship_students(same columns as mis.ai_students; internship memberships only)
mis.ai_batch_managers(assignment_id, assigned_at, manager_id, manager_name, batch_id,
 batch_name, batch_type, program, cohort_start_year, cohort_end_year)
""".strip()

SUGGESTIONS = [
    "Show attendance below 40% by student and batch",
    "Rank mentors by average numeric feedback rating and response count",
    "Show sessions delayed beyond the 10-minute grace period this month",
    "Show missing assignment submissions by semester and batch",
]


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=2, max_length=1000)
    filters: dict[str, str] = Field(default_factory=dict)
    history: list[str] = Field(default_factory=list, max_length=6)


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "sql": {"type": "string"},
        "explanation": {"type": "string"},
    },
    "required": ["title", "sql", "explanation"],
}


def _gemini(prompt: str) -> dict:
    cfg = settings()
    if not cfg.gemini_api_key:
        raise HTTPException(503, "Gemini is not configured. Add GEMINI_API_KEY to backend/.env and restart the API.")
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": PLAN_SCHEMA,
        },
    }).encode()
    # Prefer the high-throughput Flash-Lite family for this structured SQL task.
    # Keep the chain configurable so quota/capacity changes do not require a deploy.
    models = list(dict.fromkeys([cfg.gemini_model, *cfg.gemini_fallback_models]))
    last_error = None
    for model_name in models:
        model = urllib.parse.quote(model_name, safe="-._")
        for attempt in range(1):
            request = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                data=body,
                headers={"Content-Type": "application/json", "x-goog-api-key": cfg.gemini_api_key},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=35) as response:
                    payload = json.load(response)
                text = payload["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)
            except urllib.error.HTTPError as exc:
                last_error = exc
                detail = exc.read(1000).decode(errors="replace")
                log.warning("Gemini model=%s HTTP %s: %s", model_name, exc.code, detail)
                if exc.code not in {404, 429, 500, 502, 503, 504}:
                    raise HTTPException(502, "The AI model could not process this question") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                log.warning("Gemini model=%s transport error: %s", model_name, exc)
            except (KeyError, IndexError, json.JSONDecodeError) as exc:
                log.warning("Gemini model=%s response error: %s", model_name, exc)
                raise HTTPException(502, "The AI model returned an unusable response") from exc
    raise HTTPException(503, "Gemini is temporarily at capacity. Please retry shortly.") from last_error


def validate_sql(sql: str) -> str:
    sql = sql.strip().removesuffix(";").strip()
    if not sql or len(sql) > 12000:
        raise ValueError("The generated query is empty or too long")
    # Remove literals before inspecting syntax keywords and relation names.
    inspected = re.sub(r"'(?:''|[^'])*'", "''", sql)
    if ";" in inspected or "--" in inspected or "/*" in inspected:
        raise ValueError("Multiple statements and SQL comments are not allowed")
    if not re.match(r"^(select|with)\b", inspected, re.I):
        raise ValueError("Only SELECT queries are allowed")
    forbidden = r"\b(insert|update|delete|merge|alter|drop|create|truncate|copy|call|do|grant|revoke|set|reset|show|vacuum|analyze|refresh|listen|notify|lock)\b"
    if re.search(forbidden, inspected, re.I):
        raise ValueError("The query contains a prohibited operation")
    if re.search(r"\b(pg_sleep|pg_read_file|pg_ls_dir|lo_import|dblink|query_to_xml)\s*\(", inspected, re.I):
        raise ValueError("The query contains a prohibited function")
    if re.search(r"\bselect\s+\*", inspected, re.I):
        raise ValueError("SELECT * is not allowed; explicit result columns are required")

    ctes = {m.lower() for m in re.findall(r"(?:\bwith|,)\s*([a-z_][a-z0-9_]*)\s+as\s*\(", inspected, re.I)}
    relations = re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_.]*)", inspected, re.I)
    if not relations:
        raise ValueError("The query must read from an approved reporting view")
    for relation in relations:
        normalized = relation.lower()
        if normalized not in ALLOWED_VIEWS and normalized not in ctes:
            raise ValueError(f"Unapproved data source: {relation}")
    return sql


def _json_value(value):
    if isinstance(value, (datetime, date, UUID, Decimal)):
        return str(value)
    return value


def _execute_read_query(sql: str):
    """Validate the plan with EXPLAIN, then execute it inside a read-only transaction."""
    with db.connection() as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(settings().ai_query_timeout_ms),),
        )
        conn.execute("EXPLAIN (FORMAT JSON) " + sql)
        rows = conn.execute(
            f"SELECT * FROM ({sql}) AS ai_result LIMIT {settings().ai_max_rows + 1}"
        ).fetchall()
    truncated = len(rows) > settings().ai_max_rows
    return rows[: settings().ai_max_rows], truncated


def _audit(user, question, sql, succeeded, row_count=None, error=None):
    try:
        with db.connection() as conn:
            conn.execute(
                """INSERT INTO mis.ai_query_audit
                   (account_id,question,generated_sql,model,row_count,succeeded,error_message,completed_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,now())""",
                (user["id"], question, sql, settings().gemini_model, row_count, succeeded, error),
            )
    except Exception:
        log.exception("Unable to persist AI query audit")


@router.get("/status")
def ai_status(user=Depends(current_user)):
    if settings().source_database_url:
        return {
            "configured": False,
            "model": None,
            "reason": "Polaris AI is disabled because production does not provide the required read-only reporting views. Local snapshot fallback is disabled.",
            "suggestions": [],
        }
    return {
        "configured": bool(settings().gemini_api_key),
        "model": settings().gemini_model if settings().gemini_api_key else None,
        "suggestions": SUGGESTIONS,
    }


@router.post("/ask")
def ask(body: AskRequest, user=Depends(current_user)):
    if settings().source_database_url:
        raise HTTPException(
            409,
            "Polaris AI requires production-native reporting views. Local snapshot fallback is disabled.",
        )
    filter_context = {k: v for k, v in body.filters.items() if v}
    history = "\n".join(f"- {item[:300]}" for item in body.history)
    base_rules = f"""You generate one PostgreSQL read-only analytics query for Polaris MIS.
Use ONLY the reporting views and columns below. Never invent a table or column.
Return explicit result columns (never SELECT *), human-readable aliases, and no more than 200 rows.
Use Asia/Kolkata calendar dates. Attendance percentage is Present records / all Present+Absent records.
Numeric mentor feedback is numeric_rating and is averaged as sum/count of non-null ratings.
On-time delivery uses delivery_timing, which already applies the 10-minute grace rule.
Treat active/current students as enrollment_status='active'. Missing evidence is not zero.
When page filters are supplied, apply them unless the question explicitly overrides them.
Do not expose UUIDs unless needed to disambiguate the displayed result.

REPORTING SCHEMA:\n{SCHEMA}
CURRENT PAGE FILTERS: {json.dumps(filter_context)}
RECENT QUESTIONS:\n{history or '(none)'}
USER QUESTION: {body.question}
"""
    first = _gemini(base_rules + "\nCreate the best query and a short plain-language explanation.")
    review_prompt = f"""Act as a strict PostgreSQL query reviewer. Correct the proposed query if needed.
It must answer the user precisely, use only the listed schema, avoid double-counting, handle nulls,
honor filters, remain read-only, and return at most 200 rows. Return the corrected final plan.

SCHEMA:\n{SCHEMA}
QUESTION: {body.question}
FILTERS: {json.dumps(filter_context)}
PROPOSED PLAN: {json.dumps(first)}
"""
    reviewed = _gemini(review_prompt)
    try:
        sql = validate_sql(reviewed["sql"])
    except (ValueError, KeyError) as exc:
        _audit(user, body.question, reviewed.get("sql", ""), False, error=str(exc))
        raise HTTPException(422, f"The generated query did not pass safety validation: {exc}") from exc

    try:
        rows, truncated = _execute_read_query(sql)
        retried_empty_result = False

        # A syntactically valid query can still be too narrow for the available evidence.
        # Give the model one evidence-aware recovery attempt before returning an empty answer.
        if not rows:
            retry_prompt = f"""The query below executed successfully but returned zero rows.
Create one alternative PostgreSQL query that makes the best accurate attempt to answer the question.
Preserve every explicit constraint in the user's question and every supplied page filter.
Do not fabricate data, relax an explicit semester/batch/date constraint, or turn missing evidence into zero.
Remove only unnecessary assumptions introduced by the previous plan, such as an unrequested threshold,
status restriction, date restriction, or inner join. Prefer LEFT JOIN/conditional aggregation where valid.
For phrases such as "most consistent students", use a defensible ranking from available evidence—for
attendance, rank recorded Present / (Present + Absent), then use attendance record count as a tie-breaker.
Return explicit columns, include the evidence count, and limit the result to at most 200 rows.

SCHEMA:\n{SCHEMA}
QUESTION: {body.question}
FILTERS: {json.dumps(filter_context)}
ZERO-ROW PLAN: {json.dumps(reviewed)}
ZERO-ROW SQL: {sql}
"""
            try:
                alternative = _gemini(retry_prompt)
                alternative_sql = validate_sql(alternative["sql"])
                alternative_rows, alternative_truncated = _execute_read_query(alternative_sql)
                retried_empty_result = True
                reviewed = alternative
                sql = alternative_sql
                rows = alternative_rows
                truncated = alternative_truncated
            except Exception as retry_exc:
                # The original query was safe and valid. A failed recovery attempt must not
                # turn a legitimate no-data answer into an API error.
                retried_empty_result = True
                log.warning("AI empty-result recovery failed: %s", retry_exc)

        columns = list(rows[0].keys()) if rows else []
        serial = [{k: _json_value(v) for k, v in row.items()} for row in rows]
        _audit(user, body.question, sql, True, len(rows))
        result = {
            "title": reviewed["title"][:160],
            "explanation": reviewed["explanation"][:1000],
            "columns": columns,
            "rows": serial,
            "row_count": len(rows),
            "truncated": truncated,
            "retried_empty_result": retried_empty_result,
        }
        if not rows:
            result["empty_message"] = (
                "Polaris AI tried the original query and an alternative interpretation, but could not "
                "find matching database evidence for this question and the selected filters. Try a wider "
                "date range, remove a filter, or ask for the available records in that semester first."
            )
        if user["role"] == "admin":
            result["sql"] = sql
        return result
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("AI query execution failed: %s", exc)
        _audit(user, body.question, sql, False, error=str(exc)[:500])
        raise HTTPException(422, "The generated query could not be executed safely") from exc
