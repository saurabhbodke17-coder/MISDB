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


def clean_subject_title(name: str) -> str:
    s = name.strip()
    s = re.sub(r'(?i)\badvance\b(?=\s+[a-z])', 'Advanced', s)
    s = re.sub(r'(?i)programing', 'Programming', s)
    s = re.sub(r'(?i)dev[elo]*pment', 'Development', s)
    s = re.sub(r'(?i)with\s+programming', 'Using Programming', s)
    s = re.sub(r'\s*-\s*', ' - ', s)
    s = re.sub(r'\s+', ' ', s)
    return s


def canonical_subject_key(name: str) -> str:
    s = clean_subject_title(name)
    s = re.sub(r'\([^)]*\)', '', s)
    s = re.sub(r'(?i)[-\s]*sem(ester)?\s*[0-9]+', '', s)
    s = re.sub(r'[^a-z0-9]', '', s.lower())
    s = re.sub(r'systems$', 'system', s)
    s = re.sub(r'basics$', 'basic', s)
    return s


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

    # If subject is specified, do not constrain by global attendance from_date/to_date
    if from_date and not subject:
        where.append("exam_date >= %(from_date)s")
        params["from_date"] = from_date
    if to_date and not subject:
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
        et_lower = exam_type.lower()
        if any(k in et_lower for k in ["internal", "eval", "weekly"]):
            where.append("exam_type IN ('Internal Evaluation', 'Evaluations', 'Evaluation')")
        elif "viva" in et_lower:
            where.append("exam_type ILIKE %(etype_viva)s")
            params["etype_viva"] = "%Viva%"
        elif "mid" in et_lower:
            where.append("(exam_type ILIKE %(etype_mid1)s OR exam_type ILIKE %(etype_mid2)s)")
            params["etype_mid1"] = "%Mid-Sem%"
            params["etype_mid2"] = "%Mid Sem%"
        elif "end" in et_lower:
            where.append("(exam_type ILIKE %(etype_end1)s OR exam_type ILIKE %(etype_end2)s)")
            params["etype_end1"] = "%End-Sem%"
            params["etype_end2"] = "%End Sem%"
        else:
            where.append("exam_type ILIKE %(etype)s")
            params["etype"] = f"%{exam_type}%"

    if subject and subject.lower() != "all":
        target_ckey = canonical_subject_key(subject)
        matching_raws = []
        try:
            raw_rows = conn.execute("SELECT DISTINCT subject_name FROM internal_data.exams_latest WHERE length(trim(subject_name)) > 2").fetchall()
            matching_raws = [r["subject_name"] for r in raw_rows if canonical_subject_key(r["subject_name"]) == target_ckey or r["subject_name"].lower() == subject.lower() or subject.lower() in r["subject_name"].lower()]
        except Exception:
            pass
        if matching_raws:
            where.append("subject_name = ANY(%(subj_list)s)")
            params["subj_list"] = matching_raws
        else:
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
    cohort_filter: str | None = None,
    batch_filter: str | None = None,
    clean_subject: str | None = None,
    clean_search: str | None = None,
) -> list[dict[str, Any]]:
    # 1. Reading from internal_data.cwa via run_readonly_query
    cwa_rows = []
    where_cwa = ["maximum_marks > 0"]
    if sem_filter:
        where_cwa.append(f"semester ILIKE '%%{sem_filter}%%'")
    if cohort_filter:
        clean_coh_esc = cohort_filter.replace("'", "''")
        where_cwa.append(f"batch LIKE '%%{clean_coh_esc}%%'")
    if batch_filter:
        clean_batch_esc = batch_filter.replace("'", "''")
        where_cwa.append(f"batch ILIKE '%%{clean_batch_esc}%%'")
    if clean_subject:
        clean_subj_esc = clean_subject.replace("'", "''")
        where_cwa.append(f"subject_name ILIKE '%%{clean_subj_esc}%%'")
    if clean_search:
        clean_search_esc = clean_search.replace("'", "''")
        where_cwa.append(f"(subject_name ILIKE '%%{clean_search_esc}%%' OR batch ILIKE '%%{clean_search_esc}%%')")
    where_cwa_str = " AND ".join(where_cwa)

    cwa_sql = f"""
        SELECT 
            COALESCE(NULLIF(substring(batch from '^[0-9]{{4}}'), ''), 'General') as cohort,
            semester,
            subject_name,
            string_agg(DISTINCT batch, ', ' ORDER BY batch) as batches,
            count(DISTINCT email) as student_count,
            round(avg(CASE WHEN exam_type = 'Internal Evaluation' THEN marks_scored * 100.0 / NULLIF(maximum_marks, 0) END), 1) as eval_avg,
            round(avg(CASE WHEN exam_type = 'Mid-Sem' THEN marks_scored * 100.0 / NULLIF(maximum_marks, 0) END), 1) as midsem_avg,
            round(avg(CASE WHEN exam_type = 'End-Sem' THEN marks_scored * 100.0 / NULLIF(maximum_marks, 0) END), 1) as endsem_avg
        FROM internal_data.cwa
        WHERE {where_cwa_str}
        GROUP BY 1, semester, subject_name
        ORDER BY semester, cohort, subject_name
    """
    try:
        res = conn.execute("SELECT public.run_readonly_query(%s)", (cwa_sql,)).fetchall()
        cwa_rows = res[0]["run_readonly_query"] if res and res[0] and res[0]["run_readonly_query"] else []
    except Exception:
        cwa_rows = []

    # 2. Metrics from internal_data.exams_latest
    exams_where = ["maximum_marks::numeric > 0", "length(trim(subject_name)) > 2"]
    exams_params: dict[str, Any] = {}
    if sem_filter:
        exams_where.append("semester ILIKE %(sem_f)s")
        exams_params["sem_f"] = f"%{sem_filter}%"
    if cohort_filter:
        exams_where.append("batch LIKE %(coh_f)s")
        exams_params["coh_f"] = f"{cohort_filter}%"
    if batch_filter:
        exams_where.append("batch ILIKE %(bat_f)s")
        exams_params["bat_f"] = f"%{batch_filter}%"
    if clean_subject:
        exams_where.append("subject_name ILIKE %(sub_f)s")
        exams_params["sub_f"] = f"%{clean_subject}%"
    if clean_search:
        exams_where.append("(subject_name ILIKE %(sea_f)s OR batch ILIKE %(sea_f)s)")
        exams_params["sea_f"] = f"%{clean_search}%"
    exams_where_str = " AND ".join(exams_where)

    exams_sql = f"""
        SELECT 
            COALESCE(NULLIF(substring(batch from '^[0-9]{{4}}'), ''), 'General') as cohort,
            subject_name,
            semester,
            string_agg(DISTINCT batch, ', ' ORDER BY batch) as batches,
            count(DISTINCT email) as student_count,
            round(avg(CASE WHEN exam_type = 'Viva' THEN (marks_scored::numeric / maximum_marks::numeric) * 100 END), 1) as viva_avg,
            round(avg(CASE WHEN exam_type IN ('Evaluations', 'Evaluation') THEN (marks_scored::numeric / maximum_marks::numeric) * 100 END), 1) as raw_eval_avg,
            round(avg(CASE WHEN exam_type = 'Mid-Sem' THEN (marks_scored::numeric / maximum_marks::numeric) * 100 END), 1) as raw_midsem_avg
        FROM internal_data.exams_latest
        WHERE {exams_where_str}
        GROUP BY 1, subject_name, semester
    """
    try:
        exams_rows = conn.execute(exams_sql, exams_params).fetchall()
    except Exception:
        exams_rows = []

    combined: dict[tuple[str, str, str], dict[str, Any]] = {}

    for c in cwa_rows:
        cohort = c.get("cohort") or "General"
        sem = c.get("semester") or ""
        sn = clean_subject_title(c.get("subject_name") or "")
        ckey = canonical_subject_key(sn)
        key = (cohort, sem, ckey)

        combined[key] = {
            "cohort": cohort,
            "semester": sem,
            "subject_name": sn,
            "batches": set(b.strip() for b in (c.get("batches") or "").split(",") if b.strip()),
            "student_count": c.get("student_count") or 0,
            "eval_avg": float(c["eval_avg"]) if c.get("eval_avg") is not None else None,
            "midsem_avg": float(c["midsem_avg"]) if c.get("midsem_avg") is not None else None,
            "endsem_avg": float(c["endsem_avg"]) if c.get("endsem_avg") is not None else None,
            "viva_avg": None,
        }

    for r in exams_rows:
        cohort = r.get("cohort") or "General"
        sem = r.get("semester") or ""
        sn = clean_subject_title(r.get("subject_name") or "")
        ckey = canonical_subject_key(sn)
        key = (cohort, sem, ckey)

        ex_batches = set(b.strip() for b in (r.get("batches") or "").split(",") if b.strip())
        viva = float(r["viva_avg"]) if r.get("viva_avg") is not None else None
        raw_eval = float(r["raw_eval_avg"]) if r.get("raw_eval_avg") is not None else None
        raw_midsem = float(r["raw_midsem_avg"]) if r.get("raw_midsem_avg") is not None else None
        st_count = r.get("student_count") or 0

        if key in combined:
            entry = combined[key]
            entry["batches"].update(ex_batches)
            if st_count > entry["student_count"]:
                entry["student_count"] = st_count
            if viva is not None:
                entry["viva_avg"] = viva
            if entry["eval_avg"] is None and raw_eval is not None:
                entry["eval_avg"] = raw_eval
            if entry["midsem_avg"] is None and raw_midsem is not None:
                entry["midsem_avg"] = raw_midsem
            if len(sn) > len(entry["subject_name"]):
                entry["subject_name"] = sn
        else:
            combined[key] = {
                "cohort": cohort,
                "semester": sem,
                "subject_name": sn,
                "batches": ex_batches,
                "student_count": st_count,
                "eval_avg": raw_eval,
                "midsem_avg": raw_midsem,
                "endsem_avg": None,
                "viva_avg": viva,
            }

    cards = []
    for (cohort, sem, ckey), entry in combined.items():
        cards.append({
            "id": f"{cohort}-{sem}-{ckey}",
            "cohort": cohort,
            "subject_name": entry["subject_name"],
            "semester": sem,
            "batches": ", ".join(sorted(entry["batches"])),
            "student_count": entry["student_count"],
            "eval_avg": entry["eval_avg"],
            "viva_avg": entry["viva_avg"],
            "midsem_avg": entry["midsem_avg"],
            "endsem_avg": entry["endsem_avg"],
            "overall_avg": 0.0,
            "tier": "Pass",
            "formula": "",
            "red_flags": [],
        })

    cards.sort(key=lambda x: (x["semester"], x["cohort"], x["subject_name"]))

    if clean_search:
        s_lower = clean_search.lower()
        cards = [
            c for c in cards
            if s_lower in c["subject_name"].lower()
            or s_lower in c["semester"].lower()
            or s_lower in c["batches"].lower()
            or s_lower in c.get("cohort", "").lower()
        ]

    return cards


def fetch_student_records(
    conn,
    subject: str | None = None,
    cohort: str | None = None,
    sem_filter: str | None = None,
    batch_filter: str | None = None,
    exam_type: str | None = None,
    exam_count: str | None = None,
    tier: str | None = None,
    search: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "date_desc",
) -> tuple[list[dict[str, Any]], int]:
    where_u = ["u.maximum_marks::numeric > 0", "length(trim(u.subject_name)) > 2"]

    # 1. Subject filter with smart canonical resolution
    if subject and subject.lower() != "all":
        target_ckey = canonical_subject_key(subject)
        matching_raws = []
        try:
            raw_res = conn.execute("SELECT public.run_readonly_query(%s)", ("SELECT DISTINCT subject_name FROM internal_data.cwa UNION SELECT DISTINCT subject_name FROM internal_data.exams_latest",)).fetchall()
            all_raws = [r["subject_name"] for r in (raw_res[0]["run_readonly_query"] if raw_res else []) if r.get("subject_name") and len(r["subject_name"].strip()) > 2]
            matching_raws = [r for r in all_raws if canonical_subject_key(r) == target_ckey or r.lower() == subject.lower() or subject.lower() in r.lower()]
        except Exception:
            pass
        if matching_raws:
            clean_raws = [r.replace("'", "''") for r in matching_raws]
            in_clause = ", ".join(f"'{x}'" for x in clean_raws)
            where_u.append(f"u.subject_name IN ({in_clause})")
        else:
            subj_esc = subject.replace("'", "''")
            where_u.append(f"u.subject_name ILIKE '%%{subj_esc}%%'")

    # 2. Cohort filter
    if cohort and cohort.lower() != "all":
        coh_match = re.search(r'\d{4}', cohort)
        coh_val = coh_match.group(0) if coh_match else cohort.strip()
        coh_esc = coh_val.replace("'", "''")
        where_u.append(f"u.batch LIKE '{coh_esc}%%'")

    # 3. Semester filter
    if sem_filter:
        sem_esc = sem_filter.replace("'", "''")
        where_u.append(f"u.semester ILIKE '%%{sem_esc}%%'")

    # 4. Batch filter
    if batch_filter:
        bat_esc = batch_filter.replace("'", "''")
        where_u.append(f"u.batch ILIKE '%%{bat_esc}%%'")

    # 5. Exam type filter
    if exam_type and exam_type.lower() != "all":
        et_lower = exam_type.lower()
        if any(k in et_lower for k in ["internal", "eval", "weekly"]):
            where_u.append("u.exam_type IN ('Internal Evaluation', 'Evaluations', 'Evaluation')")
        elif "viva" in et_lower:
            where_u.append("u.exam_type ILIKE '%%viva%%'")
        elif "mid" in et_lower:
            where_u.append("(u.exam_type ILIKE '%%mid-sem%%' OR u.exam_type ILIKE '%%mid sem%%' OR u.exam_type ILIKE '%%midterm%%')")
        elif "end" in et_lower:
            where_u.append("(u.exam_type ILIKE '%%end-sem%%' OR u.exam_type ILIKE '%%end sem%%' OR u.exam_type ILIKE '%%endterm%%')")
        else:
            et_esc = exam_type.replace("'", "''")
            where_u.append(f"u.exam_type ILIKE '%%{et_esc}%%'")

    # 5b. Exam count / iteration filter (e.g. 'Eval 1', 'Eval 2', 'Viva 1', 'Viva 2')
    if exam_count and exam_count.lower() != "all":
        ec_clean = exam_count.strip()
        num_match = re.search(r'\d+', ec_clean)
        if num_match:
            num = num_match.group(0)
            if "viva" in ec_clean.lower() or (exam_type and "viva" in exam_type.lower()):
                where_u.append(f"(u.exam_count ILIKE '%%Viva {num}%%' OR u.exam_count ILIKE '%%Viva-{num}%%' OR u.exam_count ILIKE '%%Viva{num}%%')")
            else:
                where_u.append(f"(u.exam_count ILIKE '%%Eval {num}%%' OR u.exam_count ILIKE '%%Evaluation {num}%%' OR u.exam_count ILIKE '%%Evaluation-{num}%%' OR u.exam_count ILIKE '%%Eval{num}%%')")
        else:
            ec_esc = ec_clean.replace("'", "''")
            where_u.append(f"u.exam_count ILIKE '%%{ec_esc}%%'")

    # 6. Performance tier
    if tier and tier.lower() != "all":
        t = tier.lower()
        if "distinction" in t or "75" in t:
            where_u.append("(u.marks_scored::numeric / u.maximum_marks::numeric) >= 0.75")
        elif "first" in t or "60" in t:
            where_u.append("(u.marks_scored::numeric / u.maximum_marks::numeric) >= 0.60 AND (u.marks_scored::numeric / u.maximum_marks::numeric) < 0.75")
        elif "pass" in t or "40" in t:
            where_u.append("(u.marks_scored::numeric / u.maximum_marks::numeric) >= 0.40 AND (u.marks_scored::numeric / u.maximum_marks::numeric) < 0.60")
        elif "risk" in t or "fail" in t:
            where_u.append("(u.marks_scored::numeric / u.maximum_marks::numeric) < 0.40")

    # 7. Search filter
    if search and search.strip():
        s_esc = search.strip().replace("'", "''")
        s_conds = [
            f"u.student_name ILIKE '%%{s_esc}%%'",
            f"u.email ILIKE '%%{s_esc}%%'",
            f"u.subject_name ILIKE '%%{s_esc}%%'",
            f"u.batch ILIKE '%%{s_esc}%%'",
        ]
        if "advanced" in s_esc.lower():
            alt_s = re.sub(r'(?i)advanced', 'advance', s_esc)
            s_conds.append(f"u.subject_name ILIKE '%%{alt_s}%%'")
        elif "advance" in s_esc.lower():
            alt_s = re.sub(r'(?i)advance', 'advanced', s_esc)
            s_conds.append(f"u.subject_name ILIKE '%%{alt_s}%%'")
        where_u.append(f"({' OR '.join(s_conds)})")

    # 8. Date bounds
    # If a specific subject or cohort is queried, milestone assessments are bounded by that
    # subject's semester timeline; do not let global attendance date bounds prune historical student records.
    if from_date and not subject and not cohort:
        where_u.append(f"u.exam_date >= '{from_date}'")
    if to_date and not subject and not cohort:
        where_u.append(f"u.exam_date <= '{to_date}'")

    where_u_str = " AND ".join(where_u)

    # 9. Sort ordering
    sort_sql = {
        "date_desc": "u.exam_date DESC, u.student_name ASC",
        "date_asc": "u.exam_date ASC, u.student_name ASC",
        "score_desc": "(u.marks_scored::numeric / u.maximum_marks::numeric) DESC, u.student_name ASC",
        "score_asc": "(u.marks_scored::numeric / u.maximum_marks::numeric) ASC, u.student_name ASC",
        "name_asc": "u.student_name ASC, u.exam_date DESC",
    }.get(sort_by, "u.exam_date DESC, u.student_name ASC")

    limit = page_size
    offset = (page - 1) * page_size

    count_sql = f"""
    SELECT count(*) as total
    FROM (
        SELECT id::text, batch, semester, student_name, email, exam_date::text, exam_type, exam_count, attendance::text, subject_name, maximum_marks::text, marks_scored::text
        FROM internal_data.exams_latest
        WHERE maximum_marks::numeric > 0 AND length(trim(subject_name)) > 2
        UNION ALL
        SELECT id::text, batch, semester, student_name, email, exam_date::text, exam_type, exam_count, attendance::text, subject_name, maximum_marks::text, marks_scored::text
        FROM internal_data.cwa c
        WHERE maximum_marks > 0 AND length(trim(subject_name)) > 2
          AND NOT EXISTS (
              SELECT 1 FROM internal_data.exams_latest e
              WHERE e.email = c.email 
                AND e.exam_date::date = c.exam_date 
                AND (e.exam_type = c.exam_type OR (e.exam_type IN ('Evaluations', 'Evaluation') AND c.exam_type = 'Internal Evaluation'))
          )
    ) u
    WHERE {where_u_str}
    """

    rec_sql = f"""
    SELECT 
        u.id,
        u.batch,
        u.semester,
        u.student_name,
        u.email,
        u.exam_date::text as exam_date,
        u.exam_type,
        u.exam_count,
        u.attendance,
        u.subject_name,
        u.maximum_marks,
        u.marks_scored,
        ROUND((u.marks_scored::numeric / NULLIF(u.maximum_marks::numeric, 0)) * 100, 1) as score_pct,
        CASE
            WHEN (u.marks_scored::numeric / NULLIF(u.maximum_marks::numeric, 0)) >= 0.75 THEN 'Distinction'
            WHEN (u.marks_scored::numeric / NULLIF(u.maximum_marks::numeric, 0)) >= 0.60 THEN 'First Class'
            WHEN (u.marks_scored::numeric / NULLIF(u.maximum_marks::numeric, 0)) >= 0.40 THEN 'Pass'
            ELSE 'At Risk'
        END as tier,
        u.feedback_summary,
        u.question_one_progress_tracking,
        u.question_two_technical_understanding,
        u.question_three_problem_solving_data_structures,
        u.communication
    FROM (
        SELECT id::text, batch, semester, student_name, email, exam_date::text, exam_type, exam_count, attendance::text, subject_name, maximum_marks::text, marks_scored::text, feedback_summary, question_one_progress_tracking, question_two_technical_understanding, question_three_problem_solving_data_structures, communication
        FROM internal_data.exams_latest
        WHERE maximum_marks::numeric > 0 AND length(trim(subject_name)) > 2
        UNION ALL
        SELECT id::text, batch, semester, student_name, email, exam_date::text, exam_type, exam_count, attendance::text, subject_name, maximum_marks::text, marks_scored::text, NULL as feedback_summary, NULL as question_one_progress_tracking, NULL as question_two_technical_understanding, NULL as question_three_problem_solving_data_structures, NULL as communication
        FROM internal_data.cwa c
        WHERE maximum_marks > 0 AND length(trim(subject_name)) > 2
          AND NOT EXISTS (
              SELECT 1 FROM internal_data.exams_latest e
              WHERE e.email = c.email 
                AND e.exam_date::date = c.exam_date 
                AND (e.exam_type = c.exam_type OR (e.exam_type IN ('Evaluations', 'Evaluation') AND c.exam_type = 'Internal Evaluation'))
          )
    ) u
    WHERE {where_u_str}
    ORDER BY {sort_sql}
    LIMIT {limit} OFFSET {offset}
    """

    try:
        count_res = conn.execute("SELECT public.run_readonly_query(%s)", (count_sql,)).fetchall()
        total_records = count_res[0]["run_readonly_query"][0]["total"] if count_res and count_res[0].get("run_readonly_query") else 0
        
        rec_res = conn.execute("SELECT public.run_readonly_query(%s)", (rec_sql,)).fetchall()
        records_rows = rec_res[0]["run_readonly_query"] if rec_res and rec_res[0].get("run_readonly_query") else []
        for r in records_rows:
            r["subject_name"] = clean_subject_title(r.get("subject_name", ""))
            raw_et = (r.get("exam_type") or "").strip()
            if raw_et in ("Evaluations", "Evaluation", "Internal Evaluation"):
                r["exam_type"] = "Weekly Evaluation"
        return records_rows, total_records
    except Exception:
        return [], 0


@router.get("/performance")
def academic_performance(
    f: Filters = Depends(filters),
    cohort: str | None = Query(default=None),
    exam_type: str | None = Query(default=None),
    exam_count: str | None = Query(default=None),
    subject: str | None = Query(default=None),
    tier: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=5, le=100),
    sort_by: str = Query(default="date_desc", pattern="^(date_desc|date_asc|score_desc|score_asc|name_asc)$"),
    user=Depends(current_user),
):
    # Ensure parameter types when invoked directly in tests
    clean_cohort = cohort if isinstance(cohort, str) and cohort.lower() != "all" else None
    clean_exam_type = exam_type if isinstance(exam_type, str) else None
    clean_exam_count = exam_count if isinstance(exam_count, str) and exam_count.lower() != "all" else None
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

        # 7. Unified Subject Cards with Viva, Weekly Eval, Mid-Sem, End-Sem & Cohort grouping
        cohort_filter = clean_cohort
        if not cohort_filter and f.graduation_year_id:
            try:
                gy_row = conn.execute("SELECT start_year FROM graduation_years WHERE id = %(gyid)s", {"gyid": f.graduation_year_id}).fetchone()
                if gy_row and gy_row[0]:
                    cohort_filter = str(gy_row[0])
            except Exception:
                pass

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
            cohort_filter=None,
            batch_filter=batch_filter,
            clean_subject=None,
            clean_search=None,
        )

        # 8. Unified Student Records Paginated Table (from exams_latest + cwa)
        records, total_records = fetch_student_records(
            conn,
            subject=clean_subject,
            cohort=cohort_filter,
            sem_filter=sem_filter,
            batch_filter=batch_filter,
            exam_type=clean_exam_type,
            exam_count=clean_exam_count,
            tier=clean_tier,
            search=clean_search,
            from_date=f.from_date,
            to_date=f.to_date,
            page=clean_page,
            page_size=clean_page_size,
            sort_by=clean_sort_by,
        )

        avail_types = [
            "Weekly Evaluation",
            "Mid-Sem",
            "Viva",
            "End-Sem",
        ]
        avail_subjs = sorted(list(set(c["subject_name"] for c in subject_cards)))
        avail_cohorts = sorted(list(set(c["cohort"] for c in subject_cards if c.get("cohort") and c["cohort"] != "General")))

        # Compute dynamically available iterations for evals and vivas
        avail_eval_counts = []
        avail_viva_counts = []
        try:
            where_iter = ["length(trim(exam_count)) > 0"]
            params_iter: dict[str, Any] = {}
            if clean_subject:
                target_ckey = canonical_subject_key(clean_subject)
                raw_rows = conn.execute("SELECT DISTINCT subject_name FROM internal_data.exams_latest WHERE length(trim(subject_name)) > 2").fetchall()
                matching_subjs = [r["subject_name"] for r in raw_rows if canonical_subject_key(r["subject_name"]) == target_ckey or r["subject_name"].lower() == clean_subject.lower() or clean_subject.lower() in r["subject_name"].lower()]
                if matching_subjs:
                    where_iter.append("subject_name = ANY(%(s_list)s)")
                    params_iter["s_list"] = matching_subjs
            if cohort_filter:
                coh_match = re.search(r'\d{4}', cohort_filter)
                if coh_match:
                    where_iter.append("batch LIKE %(c_pat)s")
                    params_iter["c_pat"] = f"{coh_match.group(0)}%"

            iter_sql = f"SELECT DISTINCT exam_type, exam_count FROM internal_data.exams_latest WHERE {' AND '.join(where_iter)}"
            iter_rows = conn.execute(iter_sql, params_iter).fetchall()

            eval_nums = sorted(list(set(int(re.search(r'\d+', r['exam_count']).group(0)) for r in iter_rows if r['exam_type'] in ('Evaluations', 'Evaluation') and re.search(r'\d+', r['exam_count']))))
            viva_nums = sorted(list(set(int(re.search(r'\d+', r['exam_count']).group(0)) for r in iter_rows if 'viva' in r['exam_type'].lower() and re.search(r'\d+', r['exam_count']))))

            avail_eval_counts = [f"Eval {n}" for n in eval_nums] if eval_nums else ["Eval 1", "Eval 2", "Eval 3", "Eval 4", "Eval 5", "Eval 6"]
            avail_viva_counts = [f"Viva {n}" for n in viva_nums] if viva_nums else ["Viva 1", "Viva 2", "Viva 3"]
        except Exception:
            avail_eval_counts = ["Eval 1", "Eval 2", "Eval 3", "Eval 4", "Eval 5", "Eval 6"]
            avail_viva_counts = ["Viva 1", "Viva 2", "Viva 3"]

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
                "total": total_records,
                "page": clean_page,
                "page_size": clean_page_size,
                "total_pages": max(1, (total_records + clean_page_size - 1) // clean_page_size),
            },
            "filter_options": {
                "exam_types": avail_types,
                "subjects": avail_subjs,
                "cohorts": avail_cohorts,
                "eval_counts": avail_eval_counts,
                "viva_counts": avail_viva_counts,
            },
        }
