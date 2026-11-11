"""Keep the original chart/tab inventory explicit and version controlled."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
original = json.loads((root / "docs/prototype-chart-inventory.json").read_text())
sections = {
    k: {"tabs": [{"id": x[0], "label": x[1]} for x in v], "charts": []}
    for k, v in original["tabs"].items()
}
sections["command"] = {"tabs": [], "charts": []}
sections["trends"] = {
    "tabs": [{"id": "overview", "label": "Trends & Performance"}],
    "charts": [],
}


def add(view, tab, title, kind, provider=None, reason=None, source=None):
    charts = sections[view]["charts"]
    charts.append(
        {
            "id": f"{view}-{len(charts) + 1}",
            "tab": tab,
            "title": title,
            "type": kind,
            "provider": provider,
            "reason": reason,
            "source": source,
        }
    )


def a(v, t, title, kind, p=None, r=None, s=None):
    add(v, t, title, kind, p, r, s)


# Overview: every original chart, including the daily/weekly attendance toggle.
for title, p in [
    ("Attendance", "attendance.weekly"),
    ("On-time class delivery", "delivery.weekly"),
    ("Assessment completion", "assessment.completion"),
    ("Student academic performance", "assessment.score"),
    ("SLA compliance", "support.sla"),
    ("Open vs resolved issues", "support.open_resolved"),
    ("Overdue operational tasks", "tasks.overdue_trend"),
]:
    a("command", "overview", title, "line", p)
a("exceptions", "list", "By area", "hbar", "quality.area", s="data_quality")
a(
    "exceptions",
    "list",
    "Exceptions by severity",
    "stacked",
    "quality.severity",
    s="data_quality",
)
a("exceptions", "students", "Flags by rule", "hbar", "risk.rules", s="students")
for title, kind, p in [
    ("Current vs previous period", "line", "trends.series"),
    ("Ranking by batch", "hbar", "trends.batch"),
    ("Ranking by mentor", "hbar", "trends.mentor"),
    ("By subject", "hbar", "trends.subject"),
    ("Heatmap · batch × week", "heatmap", "trends.heatmap"),
]:
    a("trends", "overview", title, kind, p)
a("attendance", "daily", "Daily attendance", "line", "attendance.daily", s="attendance")
a(
    "attendance",
    "daily",
    "Daily absence count",
    "bar",
    "attendance.absences",
    s="attendance",
)
a(
    "attendance",
    "weekly",
    "Weekly attendance",
    "line",
    "attendance.weekly",
    s="attendance",
)
a(
    "attendance",
    "weekly",
    "Weekly heatmap · batch × week",
    "heatmap",
    "attendance.heatmap",
    s="attendance",
)
a(
    "attendance",
    "matrix",
    "Student attendance matrix",
    "heatmap",
    "attendance.student_matrix",
    s="students",
)
for tab, title, kind, p in [
    ("daily", "Scheduled vs delivered, by day", "bar", "delivery.daily"),
    ("daily", "Daily SLA compliance", "line", "delivery.daily_sla"),
    ("timetable", "Weekly timetable adherence", "heatmap", "delivery.heatmap"),
    ("timetable", "SLA by time slot", "hbar", "delivery.slot"),
    ("timetable", "SLA by weekday", "hbar", "delivery.weekday"),
    ("batch", "Batch-wise SLA ranking", "hbar", "delivery.batch"),
    ("mentor", "Mentor-wise SLA ranking", "hbar", "delivery.mentor"),
    ("subject", "Subject × week SLA", "heatmap", "delivery.subject_heatmap"),
]:
    a("sla", tab, title, kind, p, s="sessions")
for tab, title, kind, p in [
    ("overview", "Score distribution", "bar", "assessment.histogram"),
    ("overview", "Semester performance trend", "line", "assessment.semester"),
    ("overview", "Attendance vs performance", "scatter", "assessment.scatter"),
    ("overview", "Batch comparison · average score", "hbar", "assessment.batch_score"),
    ("overview", "Batch comparison · pass rate", "hbar", "assessment.batch_pass"),
    (
        "subjects",
        "Subject-wise performance heatmap",
        "heatmap",
        "assessment.subject_heatmap",
    ),
    ("risk", "Student attendance trends", "spark", "attendance.student_trends"),
]:
    a(
        "academic",
        tab,
        title,
        kind,
        p,
        s="students" if "scatter" in p or "trends" in p else "results",
    )
for tab, title, kind, p in [
    ("trend", "Weekly on-time delivery", "line", "delivery.weekly"),
    (
        "trend",
        "Weekly classes: delivered vs breaches",
        "bar",
        "delivery.weekly_outcomes",
    ),
    ("workload", "Workload by mentor and batch", "bar", "delivery.workload"),
    ("feedback", "Feedback distribution · all mentors in view", "bar", "feedback.all"),
    ("feedback", "Feedback distribution · selected mentor", "bar", "feedback.selected"),
]:
    a("mentors", tab, title, kind, p, s="feedback" if tab == "feedback" else "sessions")
missing_process = "The supplied dump has no operational process definitions, ordered stages, dependencies or historical milestone plans. New tasks alone do not establish a process bottleneck or critical path."
for tab, title, kind, p in [
    ("planned", "Planned vs completed milestones, by process", "bar", None),
    ("trend", "On-time task completion trend", "line", "tasks.on_time"),
    ("trend", "Tasks due vs completed on time, per week", "bar", "tasks.due_completed"),
    ("overdue", "Overdue tasks by function", "bar", "tasks.overdue_function"),
    ("overdue", "Overdue tasks by owner", "hbar", "tasks.overdue_owner"),
    ("aging", "Delay aging buckets", "bar", "tasks.aging"),
    ("aging", "Escalation levels", "hbar", "tasks.escalation"),
    ("funnel", "Process bottleneck funnel", "funnel", None),
    ("funnel", "Where work is stuck", "hbar", None),
    ("gantt", "Milestone timeline", "gantt", "tasks.gantt"),
]:
    a(
        "operations",
        tab,
        title,
        kind,
        p,
        missing_process if p is None else None,
        "tasks",
    )
a(
    "dq",
    "pareto",
    "Pareto of error categories",
    "pareto",
    "quality.pareto",
    s="data_quality",
)
a(
    "dq",
    "pareto",
    "Repeat errors by category and source",
    "hbar",
    r="No repeated-audit history or recurrence identifiers were supplied. Current findings cannot establish repeat errors.",
)
for tab, title, kind in [
    ("trend", "Weekly error rate", "line"),
    ("trend", "Weekly first-time-right", "line"),
    ("source", "Error rate by source system", "hbar"),
]:
    a(
        "dq",
        tab,
        title,
        kind,
        r="No audit samples, records-checked denominators or first-pass acceptance history exist in the dump. An error count is not an error rate.",
    )
for tab, title, kind, reason in [
    (
        "overview",
        "Service availability trend",
        "line",
        "No timestamped service uptime or monitoring samples.",
    ),
    (
        "overview",
        "System availability sparklines",
        "spark",
        "No per-system availability samples.",
    ),
    (
        "integrations",
        "Integration success rate by week",
        "line",
        "No integration transaction outcomes or valid-transaction denominator.",
    ),
    (
        "integrations",
        "Success rate in period",
        "hbar",
        "No integration transaction outcomes or valid-transaction denominator.",
    ),
    (
        "releases",
        "Release status distribution",
        "stacked",
        "No releases or software defect lifecycle records.",
    ),
    (
        "drill",
        "System · daily availability",
        "line",
        "No per-system daily uptime telemetry.",
    ),
]:
    a("tech", tab, title, kind, r=reason)
for tab in ["student", "parent"]:
    a(
        "experience",
        tab,
        "Communication volume by channel",
        "bar",
        "communications." + tab,
        s="announcements" if tab == "student" else "parents",
    )
    a(
        "experience",
        tab,
        "Weekly volume and acknowledgement",
        "line",
        "communications.weekly_" + tab,
        s="announcements" if tab == "student" else "parents",
    )
a("experience", "sat", "Satisfaction trend", "line", "feedback.trend", s="feedback")
a(
    "experience",
    "sat",
    "Common feedback themes",
    "hbar",
    r="The dump contains question-level responses, not validated feedback-theme classifications. Free-text themes are not fabricated.",
)
for v, t in [("experience", "resolution"), ("tickets", "analytics")]:
    a(v, t, "Complaints by category", "hbar", "support.category", s="support")
    a(
        v,
        t,
        "Created vs resolved, weekly",
        "line",
        "support.created_resolved",
        s="support",
    )
for title, kind, p in [
    ("Open tickets by category", "hbar", "support.open_category"),
    ("Aging buckets", "bar", "support.aging"),
    ("Open tickets by batch", "hbar", "support.batch"),
    ("Open tickets by owner", "hbar", "support.owner"),
]:
    a("tickets", "analytics", title, kind, p, s="support")
a(
    "calendar",
    "conflicts",
    "Scheduling conflict matrix",
    "heatmap",
    "calendar.conflicts",
    s="sessions",
)
for title, kind in [
    ("Disruption trend", "bar"),
    ("Impact by batch", "hbar"),
    ("Reasons", "hbar"),
]:
    a(
        "calendar",
        "disruptions",
        title,
        kind,
        r="No disruption/cancellation reason records or approved-versus-unplanned cancellation flags. Past scheduled sessions are not automatically classified as missed.",
    )
a(
    "assess",
    "lifecycle",
    "Assessments by lifecycle stage",
    "funnel",
    r="Assignment approval and grading are present, but examination paper preparation, review, platform readiness, marks verification and result-publication stages are absent. The assignment register remains available.",
)
a(
    "assess",
    "lifecycle",
    "Evaluation progress",
    "hbar",
    "assessment.evaluation",
    s="assignments",
)
a(
    "assess",
    "matrix",
    "Semester-wise progress matrix",
    "heatmap",
    "assessment.progress_heatmap",
    s="assignments",
)
a(
    "assess",
    "timeline",
    "Cumulative assessments conducted vs published",
    "line",
    r="Examination dates exist, but actual conducted and result-publication timestamps are absent. Grading time is not publication time.",
)
a(
    "compliance",
    "funnel",
    "Submission-to-approval funnel",
    "funnel",
    r="No historical university submission, acknowledgement or approval milestones were supplied. New MIS compliance items track follow-up, not a fabricated university lifecycle.",
)
a(
    "compliance",
    "funnel",
    "Completion by category",
    "hbar",
    "compliance.category",
    s="compliance",
)
for tab, title, kind, reason, p in [
    (
        "overview",
        "Project allocation funnel (students)",
        "funnel",
        "No OJT student registrations, allocations or milestone acceptance records.",
        None,
    ),
    ("overview", "Project status distribution", "stacked", None, "projects.status"),
    ("overview", "Batch-wise completion", "hbar", None, "projects.batch"),
    (
        "overview",
        "Demo readiness",
        "stacked",
        "No project demo-readiness checklist or review evidence.",
        None,
    ),
    (
        "reviews",
        "Mentor review compliance",
        "hbar",
        "No OJT review schedule and completed review evidence.",
        None,
    ),
    (
        "reviews",
        "Viva and evaluation completion",
        "bar",
        "No OJT viva schedules or evaluation records.",
        None,
    ),
    (
        "outcomes",
        "Internship and industry-engagement outcomes",
        "hbar",
        "Impact events are not internship outcomes; no internship outcome records were supplied.",
        None,
    ),
    (
        "outcomes",
        "Outcomes by project type",
        "bar",
        "No OJT project-type outcome classifications were supplied.",
        None,
    ),
]:
    a("ojt", tab, title, kind, p, reason, "projects" if p else None)
a("actions", "roots", "Repeat root causes", "hbar", "actions.roots", s="actions")
a(
    "actions",
    "roots",
    "Root cause by function",
    "heatmap",
    "actions.root_heatmap",
    s="actions",
)
# Tables with visual rates are retained as charts plus the underlying register.
a(
    "actions",
    "closure",
    "Closure rate by owner",
    "hbar",
    "actions.closure_owner",
    s="actions",
)
a(
    "actions",
    "closure",
    "Closure rate by function",
    "hbar",
    "actions.closure_function",
    s="actions",
)
# Exact original tabs with backing record projections; unavailable tables are explicitly described.
source_map = {
    "exceptions": {"list": "data_quality", "students": "students"},
    "attendance": {
        "daily": "attendance",
        "weekly": "attendance",
        "matrix": "students",
        "interv": "interventions",
    },
    "sla": {
        "daily": "sessions",
        "timetable": "sessions",
        "batch": "sessions",
        "mentor": "mentors",
        "subject": "sessions",
        "log": "sessions",
    },
    "academic": {
        "overview": "students",
        "subjects": "results",
        "risk": "students",
        "backlog": "assignments",
    },
    "mentors": {
        "score": "mentors",
        "trend": "sessions",
        "workload": "sessions",
        "feedback": "mentor_feedback",
        "exceptions": "data_quality",
    },
    "operations": {
        k: "tasks"
        for k in [
            "planned",
            "trend",
            "overdue",
            "aging",
            "funnel",
            "blocked",
            "deps",
            "gantt",
            "register",
        ]
    },
    "dq": {
        "pareto": "data_quality",
        "trend": "data_quality",
        "source": "data_quality",
        "log": "corrections",
    },
    "experience": {
        "student": "announcements",
        "parent": "parents",
        "sat": "feedback",
        "resolution": "concerns",
    },
    "tickets": {k: "support" for k in ["queue", "breach", "analytics", "feedback"]},
    "calendar": {
        "calendar": "calendar",
        "conflicts": "sessions",
        "disruptions": "sessions",
        "makeup": "actions",
        "risk": "calendar",
    },
    "assess": {
        "lifecycle": "assignments",
        "matrix": "assignments",
        "overdue": "assignments",
        "timeline": "examinations",
        "improve": "corrections",
    },
    "compliance": {
        k: "compliance" for k in ["tracker", "calendar", "breach", "funnel"]
    },
    "ojt": {
        k: "projects"
        for k in ["overview", "projects", "delayed", "students", "reviews", "outcomes"]
    },
    "actions": {k: "actions" for k, _ in original["tabs"]["actions"]},
    "tech": {"incidents": "incidents"},
    "trends": {"overview": "attendance"},
}
for view, section in sections.items():
    for tab in section["tabs"]:
        tab["source"] = source_map.get(view, {}).get(tab["id"])
        if not tab["source"]:
            tab["missing"] = (
                "This view requires source records not supplied in the LMS dump."
                if tab["id"] != "rules"
                else None
            )
payload = {"version": 1, "sections": sections}
for path in ["backend/app/chart_manifest.json", "frontend/src/chartManifest.json"]:
    (root / path).write_text(json.dumps(payload, indent=2) + "\n")
lines = [
    "# Original chart integration map",
    "",
    "Every original chart family is retained in its corresponding module/tab. A null provider means the source is absent; no fabricated values are returned.",
    "",
    "| Section | Tab | Chart | Type | Source provider |",
    "|---|---|---|---|---|",
]
for view, s in sections.items():
    for c in s["charts"]:
        lines.append(
            f"| {view} | {c['tab']} | {c['title']} | {c['type']} | {c['provider'] or 'Missing source — explicit panel'} |"
        )
(root / "docs/chart-parity.md").write_text("\n".join(lines) + "\n")
print(
    sum(len(x["charts"]) for x in sections.values()),
    "chart panels; original tab structure synchronized",
)
