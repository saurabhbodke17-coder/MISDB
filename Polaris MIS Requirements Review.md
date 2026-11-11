# Polaris MIS — prototype requirements review

Reviewed on 28 October 2026. Source: `Polaris MIS Command Center.html`.

This document records requirements inferred from the supplied prototype, not separately confirmed client specifications. Review covered the HTML, CSS, data generators, view renderers, metric calculations, and interaction handlers. Rendered visual inspection was unavailable because browser policy blocked the local file URL. No prototype code was changed and no React/FastAPI implementation has started.

## Product intent

An institutional management and accountability application for Polaris School of Technology, Bengaluru, covering an integrated B.Tech CS program with Applied AI, Product Management, and Cloud & Big Data specializations.

The central workflow is: monitor institutional health → identify an exception → inspect supporting records → assign an owner and deadline → record corrective work and evidence → verify closure or reopen. The application combines analytics with operational record updates.

## Layout and interaction baseline

- Navy navigation rail, collapsible on desktop and a menu on smaller screens; light analytic workspace with automatic dark-mode CSS support.
- IBM Plex Sans typography, IBM Plex Mono numeric/detail styling, blue primary accent, and green/amber/red status indicators.
- Two-row header: institutional identity, search, refresh timestamp, notifications, settings, and demo role selector; shared academic filters below.
- Filters: academic year (currently disabled at 2026–27 odd term), semester, date window, specialization/program, batch, and mentor. Date presets: 7, 14, 28, 56 days, term to date, or custom.
- Dependent batch options, active filter chips, reset filters, view tabs, and segmented controls.
- KPI cards with definitions, targets, comparison deltas, and drill-through links; chart cards and detailed registers.
- Right-side entity drawers with navigation history, related-record links, and editable forms. Modals handle definitions, new records, and CSV copying.
- Searchable, filterable, sortable, paginated tables, generally 12 rows per page. CSV includes filtered/sorted results across pages; prototype exports via a copyable text modal.
- Global search covers students, mentors, batches, tickets, and sessions. Notifications link to exceptions or calendar references and support read tracking.
- Responsive grids, mobile navigation at 900px, additional layout changes at 1100px, reduced-motion CSS, labels and some ARIA attributes. Accessibility and visual parity still require browser verification.

## Module inventory

| Module | Screens, plots, and responsibilities |
| --- | --- |
| Institutional Command Center | KPI summary; attendance and delivery trends; assessment completion and average scores; issue SLA; open/resolved issues; overdue tasks; batch health; critical exceptions; upcoming seven-day milestones. |
| Trends & Performance | KPI selection; time comparisons; batch and mentor rankings; heatmaps; chart point/cell selection to filter underlying records. |
| Exception & Risk Center | Exception register, student risk, rule explanations, severity and area breakdowns; conversion of exceptions into assigned actions. |
| Student Attendance | Daily attendance and absences, weekly trends and batch/week heatmap, student matrix, intervention tracker. |
| Class Delivery & Mentor SLA | Daily delivery, timetable adherence, batch/mentor/subject SLA, class exception log; scheduled versus delivered, slot/weekday analysis, recovery tracking. |
| Student Academic Performance | Score distributions, semester trends, attendance/performance scatter, batch and subject comparisons, student risk, assessment backlog. |
| Mentor Performance | Balanced scorecard, weekly trend, workload, feedback distributions, exception log; includes delivery, evaluation and follow-up rather than marks alone. |
| Assessments & Examinations | Lifecycle, readiness checklist, semester progress matrix, overdue evaluation, publication timeline, improvement examinations and marks corrections. |
| Academic Calendar & Scheduling | Master calendar; timetable, exams, holidays, events, OJT reviews and university deadlines; conflict matrix, disruptions, make-up tracker and deadline risk. |
| Operations & Process Timelines | Planned/completed milestones, on-time trend, overdue tasks by function/owner, delay aging, bottleneck funnel, blocked processes, dependencies/critical path, Gantt and task register. |
| Data Accuracy & Rework | Error-category Pareto, repeat errors, error and first-time-right trends, source comparisons, correction log and verification. |
| University Compliance | Tracker, calendar, deadline breaches, submission funnel, category completion; owners, evidence references, readiness and approval stages. |
| OJT & Industry Projects | Allocation funnel, project status and completion, delayed milestones, student progress, mentor reviews, vivas, demo readiness and industry outcomes. |
| Student & Parent Experience | Student/parent communications, channel volume, acknowledgement, coverage, satisfaction and themes, issue-resolution analytics. |
| Student Issues & Support | Ticket queue, SLA breaches, analytics, resolved-ticket feedback; category/batch/owner breakdowns, aging and response/resolution times. |
| Technology & Platform Health | System availability, incident log, integration reliability, failed/pending sync jobs, releases, bugs and system drill-down. |
| Action & Audit Center | All/my/overdue/critical actions, due today/week, verification queue, reopened actions, repeat root causes and closure by owner/function. |

Chart implementations are custom SVG/HTML helpers: lines, bars, horizontal bars, stacked bars, sparklines, scatter, Pareto, heatmaps, funnels, and Gantt timelines. Their encodings, labels, targets, legends, tooltips and drill-through behavior are part of the preservation baseline; library choice can change later.

## Main editable workflows

1. **Actions:** create manually, from an exception, or from an entity drawer; assign owner, due date, severity, function and root cause; record corrective work, notes and evidence. States: Open, In progress, Blocked, Done – awaiting verification, Verified & closed, Reopened. Escalation raises severity to Critical. The dedicated Done handler requires an evidence reference.
2. **Student intervention:** record contact status, parent contact, next follow-up, outcome and dated notes. Includes student contacted, parent informed, meeting scheduled, improving, resolved and escalated states.
3. **Support tickets:** create against a student, choose category/severity/source, reassign, update status and notes, escalate, resolve and reopen. SLA defaults: Critical 24h, High 48h, Medium 72h, Low 120h.
4. **Class recovery:** schedule a make-up/recovery date and mark recovered. The prototype chooses the recovery date synthetically; production needs a real scheduling decision and conflict handling.
5. **Operational tasks:** update status, progress, escalation, blocker and next step. Completion sets progress to 100% and records a completion date.
6. **Compliance:** update readiness, discrepancies and evidence reference; advance Drafting → Internal review → Submitted → Acknowledged → Approved; raise escalation.
7. **Data corrections:** update correction/verification/reopened states and associated dates.
8. **Assessments:** toggle readiness checklist items. Lifecycle stages displayed: Scheduled, Paper preparation, Paper review, Platform ready, Evaluation, Marks entry, Marks verification, Result published.
9. **Technology:** resolve incidents and update derived duration/status.
10. **Settings:** edit metric targets and risk thresholds; recompute affected analytics. Track notification reads.

Display of a domain does not imply full CRUD support. For example, project analytics and communication histories do not by themselves define project authoring or actual message delivery requirements.

## Metric semantics to preserve and reconcile

| Metric | Prototype definition |
| --- | --- |
| Attendance | Present plus late when configured, divided by present + late + absent student-session records. Excludes excused, unrecorded and not-enrolled records. |
| On-time delivery | Sessions starting within tolerance / eligible scheduled sessions. Missed sessions and unplanned cancellations remain in the denominator. Approved cancellations and reschedules are excluded when configured. |
| Missed-class rate | Missed sessions + unplanned cancellations / eligible scheduled sessions. |
| Assessment completion | Student assessments submitted by deadline / student assessments due. Late and missing submissions do not count as completed. |
| Average score | Mean percentage across evaluated student assessments due in the period; exclude unevaluated work. |
| Issue SLA compliance | Tickets resolved within SLA / tickets resolved in the selected period. |
| On-time task completion | Tasks completed by deadline / tasks falling due in the period; institution-wide, not batch-filtered. |
| Data error rate | Incorrect records detected / records checked. |
| First-time-right | Records accepted without correction / records reviewed. |
| Integration success | Successful / valid transactions; excludes validation-rejected records. |
| Parent contact coverage | Required parent contacts completed / contacts due. |

Default targets: attendance 85%, on-time class delivery 95%, assessment completion 92%, issue SLA 90%, task completion 90%. Late tolerance: 5 minutes. Pass mark: 40%. Missing denominators generally produce an unavailable value rather than zero.

Default student-risk triggers: attendance below 75%; at least 3 consecutive unexcused absences; attendance decline of at least 15 percentage points; at least 4 failed assessments; at least 3 missing/absent assessments. High risk means at least two reasons or attendance below 65%; otherwise a triggered rule is Medium. Count a student once even when multiple rules apply. These are illustrative operational follow-up rules, not confirmed client policy.

Intended date semantics: flows use the selected period; snapshots use its end; comparison uses the immediately preceding equal-length period. Some implementation paths instead use fixed demo-relative windows or term-wide student risk, so date behavior must be reconciled rather than mechanically copied. Global filters also do not apply uniformly to every domain; institution-wide measures need clear scope labels.

## Data and production gaps

- One standalone HTML file contains styles, generated records, calculations, views and event handlers. There is no database connection or API data layer.
- Seeded synthetic data is anchored to 15 October 2026; completed historical data ends on 14 October, term begins 10 August, and scheduling horizon extends through 30 November. These dates and synthetic person/entity identifiers must not become production assumptions.
- Browser-local persistence uses `polaris-mis-demo-v1` for patches, new actions, interventions, read flags and settings. This is not shared or server-backed storage.
- Newly created tickets are added in memory without being saved as new-ticket records by the persistence mechanism. Assessment checklist mutation calls use `asm`, but the mutation registry has no `asm` entry: a code-level issue to fix in the real implementation.
- Demo role choices are Head of Institution, Head of Academics, Head of Operations, Batch Manager, Support Lead and Mentor. They supply identity/context such as My actions; they are not a demonstrated authentication or authorization system.
- Action transition validation is inconsistent: the dedicated Done flow checks evidence, while generic status saving permits transitions without the same check. Production must enforce consistent backend rules, verification permissions and audit timestamps.
- Notes, evidence references and displayed audit information are not a complete immutable audit mechanism. Real evidence storage and external system integrations are not established by the prototype.
- Loading, backend errors, permissions, concurrent edits, actual data refresh and production-scale pagination need explicit implementation.

## Plan once the PostgreSQL dump is supplied

1. Inspect dump format, schema, keys, constraints, relationships, enums, timestamps, data volumes and available history in an isolated development database.
2. Build a mapping from each module, KPI, plot, drawer and write workflow to actual tables/columns. Classify each as directly available, derivable, or missing.
3. Identify needed entities: academic years/terms, programs, batches, courses, students/enrollments, staff/mentors/assignments, timetable/sessions/attendance, assessments/submissions/marks, interventions, tickets/SLA/events, processes/tasks/dependencies, data audits/corrections, systems/incidents/integrations, communications/surveys, compliance, OJT projects/milestones/reviews, and actions/evidence/audit history. This is a conceptual inventory, not a proposed replacement schema.
4. Confirm unresolved policies using the actual schema and client context: permissions, academic calendar/timezone boundaries, historic enrollment, cancellation treatment, risk windows, SLA clock rules, verification authority and missing source domains.
5. Build React components preserving the navigation, visual design, plot semantics, shared filters, drill-downs and workflows. Build FastAPI queries and mutations with database-backed aggregation, validation, transactions, authorization and audit history.
6. Keep derived metric definitions consistent between KPI cards, charts, drill-down tables and exports. Show genuine unavailable/empty states where source data is absent; do not silently retain dummy values.
7. Validate representative database totals and edge cases, filter/time-window behavior, persistence across reloads, state transitions, access controls and visual parity. Treat this HTML as the design/behavior reference, with known demo defects corrected.

No database tables, endpoint contracts, authentication provider or infrastructure choices are finalized before inspecting the dump.

## Source navigation

Approximate original HTML line anchors: design tokens 43; synthetic data 1517; roles 1810; actions 3431; configuration/filter context 3640; risk 3920; metric definitions 4038; exception rules 4393; chart helpers 4854; tables 5232; local persistence 5342; module views 5497–11264; drawers 11265–12052; navigation/header 12053; event/mutation handlers 12342; boot 13253.
