# Original chart integration map

Every original chart family is retained in its corresponding module/tab. A null provider means the source is absent; no fabricated values are returned.

| Section | Tab | Chart | Type | Source provider |
|---|---|---|---|---|
| exceptions | list | By area | hbar | quality.area |
| exceptions | list | Exceptions by severity | stacked | quality.severity |
| exceptions | students | Flags by rule | hbar | risk.rules |
| attendance | daily | Daily attendance | line | attendance.daily |
| attendance | daily | Daily absence count | bar | attendance.absences |
| attendance | weekly | Weekly attendance | line | attendance.weekly |
| attendance | weekly | Weekly heatmap · batch × week | heatmap | attendance.heatmap |
| attendance | matrix | Student attendance matrix | heatmap | attendance.student_matrix |
| sla | daily | Scheduled vs delivered, by day | bar | delivery.daily |
| sla | daily | Daily SLA compliance | line | delivery.daily_sla |
| sla | timetable | Weekly timetable adherence | heatmap | delivery.heatmap |
| sla | timetable | SLA by time slot | hbar | delivery.slot |
| sla | timetable | SLA by weekday | hbar | delivery.weekday |
| sla | batch | Batch-wise SLA ranking | hbar | delivery.batch |
| sla | mentor | Mentor-wise SLA ranking | hbar | delivery.mentor |
| sla | subject | Subject × week SLA | heatmap | delivery.subject_heatmap |
| academic | overview | Score distribution | bar | assessment.histogram |
| academic | overview | Semester performance trend | line | assessment.semester |
| academic | overview | Attendance vs performance | scatter | assessment.scatter |
| academic | overview | Batch comparison · average score | hbar | assessment.batch_score |
| academic | overview | Batch comparison · pass rate | hbar | assessment.batch_pass |
| academic | subjects | Subject-wise performance heatmap | heatmap | assessment.subject_heatmap |
| academic | risk | Student attendance trends | spark | attendance.student_trends |
| mentors | trend | Weekly on-time delivery | line | delivery.weekly |
| mentors | trend | Weekly classes: delivered vs breaches | bar | delivery.weekly_outcomes |
| mentors | workload | Workload by mentor and batch | bar | delivery.workload |
| mentors | feedback | Feedback distribution · all mentors in view | bar | feedback.all |
| mentors | feedback | Feedback distribution · selected mentor | bar | feedback.selected |
| operations | planned | Planned vs completed milestones, by process | bar | Missing source — explicit panel |
| operations | trend | On-time task completion trend | line | tasks.on_time |
| operations | trend | Tasks due vs completed on time, per week | bar | tasks.due_completed |
| operations | overdue | Overdue tasks by function | bar | tasks.overdue_function |
| operations | overdue | Overdue tasks by owner | hbar | tasks.overdue_owner |
| operations | aging | Delay aging buckets | bar | tasks.aging |
| operations | aging | Escalation levels | hbar | tasks.escalation |
| operations | funnel | Process bottleneck funnel | funnel | Missing source — explicit panel |
| operations | funnel | Where work is stuck | hbar | Missing source — explicit panel |
| operations | gantt | Milestone timeline | gantt | tasks.gantt |
| dq | pareto | Pareto of error categories | pareto | quality.pareto |
| dq | pareto | Repeat errors by category and source | hbar | Missing source — explicit panel |
| dq | trend | Weekly error rate | line | Missing source — explicit panel |
| dq | trend | Weekly first-time-right | line | Missing source — explicit panel |
| dq | source | Error rate by source system | hbar | Missing source — explicit panel |
| tech | overview | Service availability trend | line | Missing source — explicit panel |
| tech | overview | System availability sparklines | spark | Missing source — explicit panel |
| tech | integrations | Integration success rate by week | line | Missing source — explicit panel |
| tech | integrations | Success rate in period | hbar | Missing source — explicit panel |
| tech | releases | Release status distribution | stacked | Missing source — explicit panel |
| tech | drill | System · daily availability | line | Missing source — explicit panel |
| experience | student | Communication volume by channel | bar | communications.student |
| experience | student | Weekly volume and acknowledgement | line | communications.weekly_student |
| experience | parent | Communication volume by channel | bar | communications.parent |
| experience | parent | Weekly volume and acknowledgement | line | communications.weekly_parent |
| experience | sat | Satisfaction trend | line | feedback.trend |
| experience | sat | Common feedback themes | hbar | Missing source — explicit panel |
| experience | resolution | Complaints by category | hbar | support.category |
| experience | resolution | Created vs resolved, weekly | line | support.created_resolved |
| tickets | analytics | Complaints by category | hbar | support.category |
| tickets | analytics | Created vs resolved, weekly | line | support.created_resolved |
| tickets | analytics | Open tickets by category | hbar | support.open_category |
| tickets | analytics | Aging buckets | bar | support.aging |
| tickets | analytics | Open tickets by batch | hbar | support.batch |
| tickets | analytics | Open tickets by owner | hbar | support.owner |
| calendar | conflicts | Scheduling conflict matrix | heatmap | calendar.conflicts |
| calendar | disruptions | Disruption trend | bar | Missing source — explicit panel |
| calendar | disruptions | Impact by batch | hbar | Missing source — explicit panel |
| calendar | disruptions | Reasons | hbar | Missing source — explicit panel |
| assess | lifecycle | Assessments by lifecycle stage | funnel | Missing source — explicit panel |
| assess | lifecycle | Evaluation progress | hbar | assessment.evaluation |
| assess | matrix | Semester-wise progress matrix | heatmap | assessment.progress_heatmap |
| assess | timeline | Cumulative assessments conducted vs published | line | Missing source — explicit panel |
| compliance | funnel | Submission-to-approval funnel | funnel | Missing source — explicit panel |
| compliance | funnel | Completion by category | hbar | compliance.category |
| ojt | overview | Project allocation funnel (students) | funnel | Missing source — explicit panel |
| ojt | overview | Project status distribution | stacked | projects.status |
| ojt | overview | Batch-wise completion | hbar | projects.batch |
| ojt | overview | Demo readiness | stacked | Missing source — explicit panel |
| ojt | reviews | Mentor review compliance | hbar | Missing source — explicit panel |
| ojt | reviews | Viva and evaluation completion | bar | Missing source — explicit panel |
| ojt | outcomes | Internship and industry-engagement outcomes | hbar | Missing source — explicit panel |
| ojt | outcomes | Outcomes by project type | bar | Missing source — explicit panel |
| actions | roots | Repeat root causes | hbar | actions.roots |
| actions | roots | Root cause by function | heatmap | actions.root_heatmap |
| actions | closure | Closure rate by owner | hbar | actions.closure_owner |
| actions | closure | Closure rate by function | hbar | actions.closure_function |
| command | overview | Attendance | line | attendance.weekly |
| command | overview | On-time class delivery | line | delivery.weekly |
| command | overview | Assessment completion | line | assessment.completion |
| command | overview | Student academic performance | line | assessment.score |
| command | overview | SLA compliance | line | support.sla |
| command | overview | Open vs resolved issues | line | support.open_resolved |
| command | overview | Overdue operational tasks | line | tasks.overdue_trend |
| trends | overview | Current vs previous period | line | trends.series |
| trends | overview | Ranking by batch | hbar | trends.batch |
| trends | overview | Ranking by mentor | hbar | trends.mentor |
| trends | overview | By subject | hbar | trends.subject |
| trends | overview | Heatmap · batch × week | heatmap | trends.heatmap |
