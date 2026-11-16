"""Single transparent student-risk rule calculated from recorded attendance."""


def risk_projection(student_sql, attendance_sql):
    student_sql = student_sql.replace(" END AS risk", " END AS attendance_signal")
    return f"""WITH base AS ({student_sql}), flags AS (
      SELECT base.*,array_remove(ARRAY[
        CASE WHEN attendance<%(risk_attendance)s THEN 'Low attendance' END
      ],NULL) AS risk_reasons FROM base
    ) SELECT flags.*,CASE
       WHEN attendance IS NULL THEN 'No attendance evidence'
       WHEN attendance<%(risk_attendance)s THEN 'High Risk'
       ELSE 'No Risk' END AS risk FROM flags"""
