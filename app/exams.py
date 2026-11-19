import re
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from .analytics import Filters, filters
from .auth import current_user
from .db import read_connection

router = APIRouter(prefix="/academic", tags=["Academic Performance"])

NUM_REGEX = r"^[0-9]+(\.[0-9]+)?$"


def build_exams_filter(
    conn,
    from_date: date | None = None,
    to_date: date | None = None,
    batch_id: UUID | None = None,
    semester_id: UUID | None = None,
    graduation_year_id: UUID | None = None,
    exam_type: str | None = None,
    subject: str | None = None,
    tier: str | None = None,
    search: str | None = None,
):
    where = [
        "marks_scored ~ %(num_pat)s",
        "maximum_marks ~ %(num_pat)s",
        "maximum_marks::numeric > 0",
    ]
    params: dict[str, Any] = {"num_pat": NUM_REGEX, "p1": "1"}

    if from_date:
        where.append("exam_date >= %(from_date)s")
        params["from_date"] = from_date
    if to_date:
        where.append("exam_date <= %(to_date)s")
        params["to_date"] = to_date

    if semester_id:
        sem = conn.execute(
            "SELECT number FROM semesters WHERE id = %(sid)s", {"sid": semester_id}
        ).fetchone()
        if sem:
            num = sem["number"]
            where.append("semester ILIKE %(sem_pat)s")
            params["sem_pat"] = f"%{num}%"
        else:
            return "1=0", {}

    if graduation_year_id:
        gy = conn.execute(
            "SELECT start_year FROM graduation_years WHERE id = %(gyid)s",
            {"gyid": graduation_year_id},
        ).fetchone()
        if gy:
            yr = gy["start_year"]
            where.append("batch LIKE %(gy_pat)s")
            params["gy_pat"] = f"{yr}%"
        else:
            return "1=0", {}

    if batch_id:
        b_info = conn.execute(
            """
            SELECT b.name, gy.start_year
            FROM batches b
            JOIN year_specializations ys ON ys.id=b.year_specialization_id
            JOIN graduation_years gy ON gy.id=ys.graduation_year_id
            WHERE b.id = %(bid)s
            """,
            {"bid": batch_id},
        ).fetchone()
        if b_info:
            yr = b_info["start_year"]
            b_name = b_info["name"].lower()
            sec = "A" if "section a" in b_name else ("B" if "section b" in b_name else ("C" if "section c" in b_name else None))
            if sec:
                where.append("batch = %(batch_name)s")
                params["batch_name"] = f"{yr} {sec}"
            else:
                return "1=0", {}
        else:
            return "1=0", {}

    if exam_type and exam_type.lower() != "all":
        where.append("exam_type ILIKE %(etype)s")
        params["etype"] = f"%{exam_type}%"

    if subject and subject.lower() != "all":
        where.append("subject_name ILIKE %(subj)s")
        params["subj"] = f"%{subject}%"

    if search and search.strip():
        where.append("(student_name ILIKE %(search)s OR email ILIKE %(search)s OR subject_name ILIKE %(search)s)")
        params["search"] = f"%{search.strip()}%"

    if tier and tier.lower() != "all":
        t = tier.lower()
        if "distinction" in t or "75" in t:
            where.append("(marks_scored::numeric / maximum_marks::numeric) >= 0.75")
        elif "first" in t or "60" in t:
            where.append("(marks_scored::numeric / maximum_marks::numeric) >= 0.60 AND (marks_scored::numeric / maximum_marks::numeric) < 0.75")
        elif "pass" in t or "40" in t:
            where.append("(marks_scored::numeric / maximum_marks::numeric) >= 0.40 AND (marks_scored::numeric / maximum_marks::numeric) < 0.60")
        elif "risk" in t or "fail" in t:
            where.append("(marks_scored::numeric / maximum_marks::numeric) < 0.40")

    return " AND ".join(where), params


def serialize_val(val):
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, (date,)):
        return str(val)
    if isinstance(val, UUID):
        return str(val)
    return val


def fetch_subject_cards(
    conn,
    where_clause: str,
    params: dict[str, Any],
    sem_filter: str | None = None,
    batch_filter: str | None = None,
    clean_subject: str | None = None,
    clean_search: str | None = None,
) -> list[dict[str, Any]]:
    # 1. Attempt reading from internal_data.cwa via run_readonly_query
    cwa_rows = []
    where_cwa = ["maximum_marks > 0"]
    if sem_filter:
        where_cwa.append(f"semester ILIKE '%%{sem_filter}%%'")
    if batch_filter:
        clean_batch_esc = batch_filter.replace("'", "''")
        where_cwa.append(f"batch ILIKE '%%{clean_batch_esc}%%'")
    if clean_subject:
        clean_subj_esc = clean_subject.replace("'", "''")
        where_cwa.append(f"subject_name ILIKE '%%{clean_subj_esc}%%'")
    where_cwa_str = " AND ".join(where_cwa)

    cwa_sql = f"""
        SELECT 
            semester,
            subject_name,
            string_agg(DISTINCT batch, ', ') as batches,
            count(DISTINCT email) as student_count,
            round(avg(CASE WHEN exam_type = 'Internal Evaluation' THEN marks_scored * 100.0 / NULLIF(maximum_marks, 0) END), 1) as eval_avg,
            round(avg(CASE WHEN exam_type = 'Mid-Sem' THEN marks_scored * 100.0 / NULLIF(maximum_marks, 0) END), 1) as midsem_avg,
            round(avg(CASE WHEN exam_type = 'End-Sem' THEN marks_scored * 100.0 / NULLIF(maximum_marks, 0) END), 1) as endsem_avg
        FROM internal_data.cwa
        WHERE {where_cwa_str}
        GROUP BY semester, subject_name
        ORDER BY semester, subject_name
    """
    try:
        res = conn.execute("SELECT public.run_readonly_query(%s)", (cwa_sql,)).fetchall()
        cwa_rows = res[0]["run_readonly_query"] if res and res[0] and res[0]["run_readonly_query"] else []
    except Exception:
        cwa_rows = []

    # 2. Viva Voce metrics from internal_data.exams_latest
    exams_sql = f"""
        SELECT 
            subject_name,
            semester,
            round(avg(CASE WHEN exam_type = 'Viva' THEN (marks_scored::numeric / maximum_marks::numeric) * 100 END), 1) as viva_avg,
            round(avg(CASE WHEN exam_type IN ('Evaluations', 'Evaluation') THEN (marks_scored::numeric / maximum_marks::numeric) * 100 END), 1) as raw_eval_avg,
            count(CASE WHEN exam_type = 'Viva' THEN 1 END) as viva_count
        FROM internal_data.exams_latest
        WHERE {where_clause}
        GROUP BY subject_name, semester
    """
    try:
        exams_rows = conn.execute(exams_sql, params).fetchall()
        exams_map = {(r["semester"], r["subject_name"]): r for r in exams_rows}
    except Exception:
        exams_map = {}

    cards = []
    seen_keys = set()

    for c in cwa_rows:
        sem = c.get("semester") or ""
        sn = c.get("subject_name") or ""
        key = (sem, sn)
        seen_keys.add(key)

        ex = exams_map.get(key) or {}
        viva = ex.get("viva_avg")

        e_avg = float(c["eval_avg"]) if c.get("eval_avg") is not None else None
        m_avg = float(c["midsem_avg"]) if c.get("midsem_avg") is not None else None
        end_avg = float(c["endsem_avg"]) if c.get("endsem_avg") is not None else None
        v_avg = float(viva) if viva is not None else None

        # Determine composite overall score & formula
        if m_avg is not None and end_avg is not None and e_avg is not None:
            overall = round((e_avg * 0.25) + (m_avg * 0.25) + (end_avg * 0.50), 1)
            formula = "(0.25 × Eval) + (0.25 × Mid-Sem) + (0.50 × End-Sem)"
        elif end_avg is not None and e_avg is not None:
            overall = round((e_avg * 0.35) + (end_avg * 0.65), 1)
            formula = "(0.35 × Eval) + (0.65 × End-Sem)"
        else:
            avail = [x for x in [e_avg, m_avg, end_avg, v_avg] if x is not None]
            overall = round(sum(avail) / len(avail), 1) if avail else 0.0
            formula = "Simple Average of Available Assessments"

        tier = "Distinction" if overall >= 75 else "First Class" if overall >= 60 else "Pass" if overall >= 40 else "At Risk"

        red_flags = []
        if v_avg is not None and v_avg < 30.0:
            red_flags.append(f"Severe Oral Defense Lag: Viva average is {v_avg}% (lagging behind {end_avg or m_avg}% written exam score)")
        elif v_avg is not None and v_avg < 40.0:
            red_flags.append(f"Oral Defense Gap: Viva average is {v_avg}%")
        if m_avg is not None and end_avg is not None and (end_avg - m_avg) > 20.0:
            red_flags.append(f"Mid-Sem Volatility: Students scored {m_avg}% in Mid-Sem before rebounding to {end_avg}% in End-Sem")
        if v_avg is None:
            red_flags.append("Viva Voce not scheduled for this semester")
        if m_avg is None:
            red_flags.append("Mid-Sem not scheduled for this subject")

        cards.append({
            "id": f"{sem}-{sn}",
            "subject_name": sn,
            "semester": sem,
            "batches": c.get("batches") or "",
            "student_count": c.get("student_count") or 0,
            "eval_avg": e_avg,
            "viva_avg": v_avg,
            "midsem_avg": m_avg,
            "endsem_avg": end_avg,
            "overall_avg": overall,
            "tier": tier,
            "formula": formula,
            "red_flags": red_flags,
        })

    # If cwa_rows were not found, fallback to exams_latest subjects
    if not cwa_rows:
        for (sem, sn), ex in exams_map.items():
            if len(sn.strip()) < 3 or (ex.get("raw_eval_avg") is None and ex.get("viva_avg") is None):
                continue
            v_avg = float(ex["viva_avg"]) if ex.get("viva_avg") is not None else None
            e_avg = float(ex["raw_eval_avg"]) if ex.get("raw_eval_avg") is not None else None
            avail = [x for x in [e_avg, v_avg] if x is not None]
            overall = round(sum(avail) / len(avail), 1) if avail else 0.0
            tier = "Distinction" if overall >= 75 else "First Class" if overall >= 60 else "Pass" if overall >= 40 else "At Risk"

            red_flags = []
            if v_avg is not None and v_avg < 35.0:
                red_flags.append(f"Oral Defense Lag: Viva average is {v_avg}%")
            red_flags.append("End-Sem data pending or not scheduled")

            cards.append({
                "id": f"{sem}-{sn}",
                "subject_name": sn,
                "semester": sem,
                "batches": "Cohort Enrolled",
                "student_count": ex.get("viva_count") or 0,
                "eval_avg": e_avg,
                "viva_avg": v_avg,
                "midsem_avg": None,
                "endsem_avg": None,
                "overall_avg": overall,
                "tier": tier,
                "formula": "Internal Evaluations & Viva Average",
                "red_flags": red_flags,
            })

    # Secondary text search filtering if provided
    if clean_search:
        s_lower = clean_search.lower()
        cards = [
            c for c in cards
            if s_lower in c["subject_name"].lower()
            or s_lower in c["semester"].lower()
            or s_lower in c["batches"].lower()
        ]

    return cards


@router.get("/performance")
def academic_performance(
    f: Filters = Depends(filters),
    exam_type: str | None = Query(default=None),
    subject: str | None = Query(default=None),
    tier: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=5, le=100),
    sort_by: str = Query(default="date_desc", pattern="^(date_desc|date_asc|score_desc|score_asc|name_asc)$"),
    user=Depends(current_user),
):
    # Ensure parameter types when invoked directly in tests
    clean_exam_type = exam_type if isinstance(exam_type, str) else None
    clean_subject = subject if isinstance(subject, str) else None
    clean_tier = tier if isinstance(tier, str) else None
    clean_search = search if isinstance(search, str) else None
    clean_page = page if isinstance(page, int) else 1
    clean_page_size = page_size if isinstance(page_size, int) else 25
    clean_sort_by = sort_by if isinstance(sort_by, str) else "date_desc"

    with read_connection("internal_data.exams_latest") as conn:
        where_clause, params = build_exams_filter(
            conn,
            from_date=f.from_date,
            to_date=f.to_date,
            batch_id=f.batch_id,
            semester_id=f.semester_id,
            graduation_year_id=f.graduation_year_id,
            exam_type=clean_exam_type,
            subject=clean_subject,
            tier=clean_tier,
            search=clean_search,
        )

        # 1. KPIs
        kpi_row = conn.execute(
            f"""
            SELECT
                COUNT(*) as total_submissions,
                COUNT(DISTINCT email) as unique_students,
                COUNT(DISTINCT subject_name) as unique_subjects,
                ROUND(AVG((marks_scored::numeric / maximum_marks::numeric) * 100), 1) as avg_score_pct,
                ROUND(COUNT(CASE WHEN attendance = %(p1)s THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 1) as attendance_rate,
                ROUND(COUNT(CASE WHEN (marks_scored::numeric / maximum_marks::numeric) >= 0.40 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 1) as pass_rate,
                ROUND(COUNT(CASE WHEN (marks_scored::numeric / maximum_marks::numeric) >= 0.75 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 1) as distinction_rate
            FROM internal_data.exams_latest
            WHERE {where_clause}
            """,
            params,
        ).fetchone()

        kpis = {k: serialize_val(v) for k, v in (dict(kpi_row) if kpi_row else {}).items()}
        if not kpis.get("total_submissions"):
            kpis = {
                "total_submissions": 0,
                "unique_students": 0,
                "unique_subjects": 0,
                "avg_score_pct": 0.0,
                "attendance_rate": 0.0,
                "pass_rate": 0.0,
                "distinction_rate": 0.0,
            }

        # 2. Grade distribution
        grade_params = dict(params)
        grade_params.update({
            "t1": "Distinction (>=75%)",
            "t2": "First Class (60-74%)",
            "t3": "Pass (40-59%)",
            "t4": "At Risk (<40%)",
        })
        grade_rows = conn.execute(
            f"""
            SELECT
                CASE
                    WHEN pct >= 75 THEN %(t1)s
                    WHEN pct >= 60 THEN %(t2)s
                    WHEN pct >= 40 THEN %(t3)s
                    ELSE %(t4)s
                END as name,
                COUNT(*) as count,
                ROUND(COUNT(*) * 100.0 / NULLIF(SUM(COUNT(*)) OVER (), 0), 1) as percentage
            FROM (
                SELECT (marks_scored::numeric / maximum_marks::numeric) * 100 as pct
                FROM internal_data.exams_latest
                WHERE {where_clause}
            ) s
            GROUP BY 1
            ORDER BY MIN(pct) DESC
            """,
            grade_params,
        ).fetchall()
        grade_distribution = [{k: serialize_val(v) for k, v in dict(r).items()} for r in grade_rows]

        # 3. Subject-wise performance
        subj_rows = conn.execute(
            f"""
            SELECT
                subject_name as name,
                COUNT(*) as count,
                COUNT(DISTINCT email) as students,
                ROUND(AVG((marks_scored::numeric / maximum_marks::numeric) * 100), 1) as avg_score,
                ROUND(COUNT(CASE WHEN attendance = %(p1)s THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 1) as attendance_rate,
                ROUND(COUNT(CASE WHEN (marks_scored::numeric / maximum_marks::numeric) >= 0.40 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 1) as pass_rate
            FROM internal_data.exams_latest
            WHERE {where_clause}
            GROUP BY 1
            ORDER BY avg_score DESC
            """,
            params,
        ).fetchall()
        subject_performance = [{k: serialize_val(v) for k, v in dict(r).items()} for r in subj_rows]

        # 4. Assessment types breakdown
        type_rows = conn.execute(
            f"""
            SELECT
                exam_type as name,
                COUNT(*) as count,
                ROUND(AVG((marks_scored::numeric / maximum_marks::numeric) * 100), 1) as avg_score,
                ROUND(COUNT(CASE WHEN attendance = %(p1)s THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 1) as attendance_rate
            FROM internal_data.exams_latest
            WHERE {where_clause}
            GROUP BY 1
            ORDER BY count DESC
            """,
            params,
        ).fetchall()
        assessment_types = [{k: serialize_val(v) for k, v in dict(r).items()} for r in type_rows]

        # 5. Batch comparison
        batch_rows = conn.execute(
            f"""
            SELECT
                batch as name,
                COUNT(*) as count,
                COUNT(DISTINCT email) as students,
                ROUND(AVG((marks_scored::numeric / maximum_marks::numeric) * 100), 1) as avg_score,
                ROUND(COUNT(CASE WHEN attendance = %(p1)s THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 1) as attendance_rate
            FROM internal_data.exams_latest
            WHERE {where_clause}
            GROUP BY 1
            ORDER BY name ASC
            """,
            params,
        ).fetchall()
        batch_comparison = [{k: serialize_val(v) for k, v in dict(r).items()} for r in batch_rows]

        # 6. Viva skills (where exam_type = Viva)
        viva_params = dict(params)
        viva_params["viva_str"] = "%Viva%"
        viva_row = conn.execute(
            f"""
            SELECT
                ROUND(AVG(CASE WHEN question_one_progress_tracking ~ %(num_pat)s THEN question_one_progress_tracking::numeric END), 2) as progress_tracking,
                ROUND(AVG(CASE WHEN question_two_technical_understanding ~ %(num_pat)s THEN question_two_technical_understanding::numeric END), 2) as technical_understanding,
                ROUND(AVG(CASE WHEN question_three_problem_solving_data_structures ~ %(num_pat)s THEN question_three_problem_solving_data_structures::numeric END), 2) as problem_solving,
                ROUND(AVG(CASE WHEN communication ~ %(num_pat)s THEN communication::numeric END), 2) as communication,
                COUNT(*) as viva_count
            FROM internal_data.exams_latest
            WHERE {where_clause} AND exam_type ILIKE %(viva_str)s
            """,
            viva_params,
        ).fetchone()
        viva_skills = {k: serialize_val(v) for k, v in (dict(viva_row) if viva_row else {}).items()}

        # 7. Student Records Paginated Table
        sort_sql = {
            "date_desc": "exam_date DESC, student_name ASC",
            "date_asc": "exam_date ASC, student_name ASC",
            "score_desc": "(marks_scored::numeric / maximum_marks::numeric) DESC, student_name ASC",
            "score_asc": "(marks_scored::numeric / maximum_marks::numeric) ASC, student_name ASC",
            "name_asc": "student_name ASC, exam_date DESC",
        }.get(clean_sort_by, "exam_date DESC, student_name ASC")

        limit = clean_page_size
        offset = (clean_page - 1) * clean_page_size
        list_params = dict(params)
        list_params.update({"lim": limit, "off": offset})

        records_rows = conn.execute(
            f"""
            SELECT
                id,
                batch,
                semester,
                student_name,
                email,
                exam_date,
                exam_type,
                exam_count,
                attendance,
                subject_name,
                maximum_marks,
                marks_scored,
                ROUND((marks_scored::numeric / maximum_marks::numeric) * 100, 1) as score_pct,
                CASE
                    WHEN (marks_scored::numeric / maximum_marks::numeric) >= 0.75 THEN 'Distinction'
                    WHEN (marks_scored::numeric / maximum_marks::numeric) >= 0.60 THEN 'First Class'
                    WHEN (marks_scored::numeric / maximum_marks::numeric) >= 0.40 THEN 'Pass'
                    ELSE 'At Risk'
                END as tier,
                feedback_summary,
                question_one_progress_tracking,
                question_two_technical_understanding,
                question_three_problem_solving_data_structures,
                communication
            FROM internal_data.exams_latest
            WHERE {where_clause}
            ORDER BY {sort_sql}
            LIMIT %(lim)s OFFSET %(off)s
            """,
            list_params,
        ).fetchall()
        records = [{k: serialize_val(v) for k, v in dict(r).items()} for r in records_rows]

        # 8. Available options for in-page filters
        avail_types = conn.execute(
            f"SELECT DISTINCT exam_type FROM internal_data.exams_latest WHERE {where_clause} ORDER BY 1",
            params,
        ).fetchall()
        avail_subjs = conn.execute(
            f"SELECT DISTINCT subject_name FROM internal_data.exams_latest WHERE {where_clause} ORDER BY 1",
            params,
        ).fetchall()

        # 9. Unified Subject Cards with Viva, Weekly Eval, Mid-Sem, End-Sem & Red Flags
        sem_filter = None
        if f.semester_id:
            try:
                sem_row = conn.execute("SELECT number FROM semesters WHERE id = %(sid)s", {"sid": f.semester_id}).fetchone()
                if sem_row and sem_row[0]:
                    sem_filter = f"SEM {sem_row[0]}"
            except Exception:
                pass

        batch_filter = None
        if f.batch_id:
            try:
                b_row = conn.execute("SELECT name FROM batches WHERE id = %(bid)s", {"bid": f.batch_id}).fetchone()
                if b_row and b_row[0]:
                    batch_filter = b_row[0]
            except Exception:
                pass

        subject_cards = fetch_subject_cards(
            conn,
            where_clause,
            params,
            sem_filter=sem_filter,
            batch_filter=batch_filter,
            clean_subject=clean_subject,
            clean_search=clean_search,
        )

        return {
            "kpis": kpis,
            "subject_cards": subject_cards,
            "charts": {
                "grade_distribution": grade_distribution,
                "subject_performance": subject_performance,
                "assessment_types": assessment_types,
                "batch_comparison": batch_comparison,
                "viva_skills": viva_skills,
            },
            "records": records,
            "pagination": {
                "total": kpis.get("total_submissions", 0),
                "page": clean_page,
                "page_size": clean_page_size,
                "total_pages": max(1, (kpis.get("total_submissions", 0) + clean_page_size - 1) // clean_page_size),
            },
            "filter_options": {
                "exam_types": [r["exam_type"] for r in avail_types if r["exam_type"]],
                "subjects": [r["subject_name"] for r in avail_subjs if r["subject_name"]],
            },
        }
