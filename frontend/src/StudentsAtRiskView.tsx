import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  TriangleAlert,
  ShieldCheck,
  Users,
  Search,
  SlidersHorizontal,
  Download,
  ChevronLeft,
  ChevronRight,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  BriefcaseBusiness,
  UserX,
} from 'lucide-react';
import { api, queryString } from './api';
import type { Filters, Row } from './api';
import { Card, Badge, Loading, ErrorState, Empty } from './components';

export interface StudentRiskRecord {
  id: string;
  student_id: string;
  student_name: string;
  email: string;
  year: string;
  batch: string;
  semester: string;
  enrollment_status: string;
  lms_active: boolean;
  is_active_intern: boolean;
  is_dropped_intern: boolean;
  total_classes: number;
  present_classes: number;
  attendance_percentage: number | null;
  risk_status: 'At risk' | 'No risk' | 'Active Intern';
}

interface RiskApiResponse {
  threshold: number;
  summary: {
    total_students: number;
    active_interns_count: number;
    active_interns_pct: number;
    evaluated_students: number;
    at_risk_count: number;
    at_risk_pct: number;
    no_risk_count: number;
    no_risk_pct: number;
    dropped_interns_count: number;
    average_attendance: number;
  };
  students: StudentRiskRecord[];
}

export function StudentsAtRiskView({
  filters,
  onOpen,
  setToast,
}: {
  filters: Filters;
  onOpen: (source: string, row: Row) => void;
  setToast: (msg: string) => void;
}) {
  const [threshold, setThreshold] = useState<number>(50);
  const [riskFilter, setRiskFilter] = useState<'all' | 'at_risk' | 'no_risk' | 'active_intern' | 'dropped_intern'>('all');
  const [search, setSearch] = useState<string>('');
  const [sortKey, setSortKey] = useState<keyof StudentRiskRecord>('attendance_percentage');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [page, setPage] = useState<number>(1);
  const pageSize = 20;

  const { data, isPending, error, refetch, isFetching } = useQuery({
    queryKey: ['attendance-risk-students', filters, threshold],
    queryFn: () =>
      api<RiskApiResponse>(
        `/attendance/risk-students?${queryString({ ...filters, threshold })}`
      ),
  });

  // Calculate dynamic risk status and counts for instantaneous threshold adjustments
  const evaluatedStudents = useMemo(() => {
    if (!data?.students) return [];
    return data.students.map(s => {
      if (s.is_active_intern) {
        return {
          ...s,
          risk_status: 'Active Intern' as const,
        };
      }
      const att = s.attendance_percentage ?? 0;
      const isRisk = att < threshold;
      return {
        ...s,
        risk_status: (isRisk ? 'At risk' : 'No risk') as 'At risk' | 'No risk',
      };
    });
  }, [data?.students, threshold]);

  const dynamicSummary = useMemo(() => {
    const total = evaluatedStudents.length;
    if (!total) {
      return (
        data?.summary ?? {
          total_students: 0,
          active_interns_count: 0,
          active_interns_pct: 0,
          evaluated_students: 0,
          at_risk_count: 0,
          at_risk_pct: 0,
          no_risk_count: 0,
          no_risk_pct: 0,
          dropped_interns_count: 0,
          average_attendance: 0,
        }
      );
    }
    let activeInterns = 0;
    let droppedInterns = 0;
    let atRisk = 0;
    let noRisk = 0;
    let totalAtt = 0;
    let validCount = 0;

    for (const s of evaluatedStudents) {
      if (s.is_active_intern) {
        activeInterns++;
      } else {
        if (s.risk_status === 'At risk') atRisk++;
        else noRisk++;
        if (s.attendance_percentage != null) {
          totalAtt += s.attendance_percentage;
          validCount++;
        }
      }
      if (s.is_dropped_intern && !s.is_active_intern) {
        droppedInterns++;
      }
    }

    const evaluated = total - activeInterns;
    return {
      total_students: total,
      active_interns_count: activeInterns,
      active_interns_pct: Math.round((activeInterns / total) * 1000) / 10,
      evaluated_students: evaluated,
      at_risk_count: atRisk,
      at_risk_pct: evaluated ? Math.round((atRisk / evaluated) * 1000) / 10 : 0,
      no_risk_count: noRisk,
      no_risk_pct: evaluated ? Math.round((noRisk / evaluated) * 1000) / 10 : 0,
      dropped_interns_count: droppedInterns,
      average_attendance: validCount ? Math.round((totalAtt / validCount) * 10) / 10 : 0,
    };
  }, [evaluatedStudents, data?.summary]);

  // Filtered and sorted students for display in the table
  const filteredStudents = useMemo(() => {
    let result = evaluatedStudents;

    if (riskFilter === 'at_risk') {
      result = result.filter(s => s.risk_status === 'At risk');
    } else if (riskFilter === 'no_risk') {
      result = result.filter(s => s.risk_status === 'No risk');
    } else if (riskFilter === 'active_intern') {
      result = result.filter(s => s.is_active_intern);
    } else if (riskFilter === 'dropped_intern') {
      result = result.filter(s => s.is_dropped_intern && !s.is_active_intern);
    }

    if (search.trim()) {
      const q = search.trim().toLowerCase();
      result = result.filter(
        s =>
          s.student_name.toLowerCase().includes(q) ||
          s.email.toLowerCase().includes(q) ||
          s.batch.toLowerCase().includes(q) ||
          s.year.toLowerCase().includes(q) ||
          s.semester.toLowerCase().includes(q) ||
          s.enrollment_status.toLowerCase().includes(q) ||
          s.risk_status.toLowerCase().includes(q)
      );
    }

    return [...result].sort((a, b) => {
      let av = a[sortKey];
      let bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === 'string') {
        const cmp = String(av).localeCompare(String(bv));
        return sortDir === 'asc' ? cmp : -cmp;
      }
      if (typeof av === 'boolean') {
        const boolCmp = (av ? 1 : 0) - (bv ? 1 : 0);
        return sortDir === 'asc' ? boolCmp : -boolCmp;
      }
      const numCmp = Number(av) - Number(bv);
      return sortDir === 'asc' ? numCmp : -numCmp;
    });
  }, [evaluatedStudents, riskFilter, search, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(filteredStudents.length / pageSize));
  const pagedStudents = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filteredStudents.slice(start, start + pageSize);
  }, [filteredStudents, page, pageSize]);

  function handleSort(key: keyof StudentRiskRecord) {
    if (sortKey === key) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(key === 'attendance_percentage' ? 'asc' : 'asc');
    }
    setPage(1);
  }

  function downloadCsv() {
    if (!evaluatedStudents.length) return;
    const headers = [
      'Student Name',
      'Email',
      'Year / Cohort',
      'Batch',
      'Semester',
      'Enrollment Status',
      'Active Intern',
      'Dropped Intern',
      'Total Classes',
      'Present Classes',
      'Attendance Percentage',
      'Threshold Applied (%)',
      'Risk Status',
    ];
    const escapeCsv = (v: unknown) => {
      let s = String(v ?? '');
      if (/^[\s]*[=+\-@]/.test(s)) s = "'" + s;
      return '"' + s.replaceAll('"', '""') + '"';
    };

    const csvRows = [
      headers.join(','),
      ...filteredStudents.map(s =>
        [
          escapeCsv(s.student_name),
          escapeCsv(s.email),
          escapeCsv(s.year),
          escapeCsv(s.batch),
          escapeCsv(s.semester),
          escapeCsv(s.enrollment_status),
          escapeCsv(s.is_active_intern ? 'Yes' : 'No'),
          escapeCsv(s.is_dropped_intern ? 'Yes' : 'No'),
          escapeCsv(s.total_classes),
          escapeCsv(s.present_classes),
          escapeCsv(s.attendance_percentage != null ? `${s.attendance_percentage}%` : '—'),
          escapeCsv(`${threshold}%`),
          escapeCsv(s.risk_status),
        ].join(',')
      ),
    ];

    const blob = new Blob([csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `polaris_all_students_risk_threshold_${threshold}pct.csv`;
    a.click();
    URL.revokeObjectURL(url);
    setToast(`Downloaded ${filteredStudents.length} student records.`);
  }

  return (
    <div className="risk-section">
      {/* Dynamic Threshold Control Card */}
      <Card
        title="Students at Risk (Based on Attendance)"
        subtitle={`Evaluation of all ${dynamicSummary.total_students} registered students. Active interns (${dynamicSummary.active_interns_count}) are excluded from attendance risk.`}
      >
        <div className="threshold-toolbar">
          <div className="threshold-main-control">
            <div className="threshold-label-group">
              <span className="threshold-title">
                <SlidersHorizontal size={15} /> Attendance Risk Threshold
              </span>
              <span className="threshold-description">
                Non-intern students with attendance below <strong>{threshold}%</strong> are classified as <strong>At risk</strong> (including dropped students). Students at or above <strong>{threshold}%</strong> are <strong>No risk</strong>.
              </span>
            </div>
            <div className="threshold-interactive">
              <input
                type="range"
                className="threshold-slider"
                min={1}
                max={99}
                step={1}
                value={threshold}
                onChange={e => {
                  setThreshold(Number(e.target.value));
                  setPage(1);
                }}
                aria-label="Attendance threshold slider"
              />
              <div className="threshold-number-wrapper">
                <input
                  type="number"
                  className="threshold-number-input"
                  min={1}
                  max={99}
                  value={threshold}
                  onChange={e => {
                    const val = Math.max(1, Math.min(99, Number(e.target.value) || 50));
                    setThreshold(val);
                    setPage(1);
                  }}
                  aria-label="Attendance threshold input"
                />
                <span className="threshold-pct-symbol">%</span>
              </div>
            </div>
          </div>

          <div className="threshold-presets">
            <span className="preset-label">Quick Presets:</span>
            {[
              { val: 50, label: '50% (Default)' },
              { val: 60, label: '60%' },
              { val: 75, label: '75%' },
              { val: 85, label: '85%' },
            ].map(p => (
              <button
                key={p.val}
                type="button"
                className={`preset-btn ${threshold === p.val ? 'active' : ''}`}
                onClick={() => {
                  setThreshold(p.val);
                  setPage(1);
                }}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Dynamic Attendance Breakdown */}
        <div className="risk-breakdown-grid">
          <div className="risk-metric-card total">
            <div className="metric-header">
              <span className="metric-label">
                <Users size={16} /> Total Students
              </span>
              <span className="metric-badge-neutral">All Records</span>
            </div>
            <div className="metric-body">
              <strong className="metric-number">{dynamicSummary.total_students.toLocaleString('en-IN')}</strong>
              <span className="metric-sub">{dynamicSummary.evaluated_students} evaluated</span>
            </div>
            <p className="metric-rule">All active, dropped, inactive &amp; test students</p>
          </div>

          <div className="risk-metric-card at-risk">
            <div className="metric-header">
              <span className="metric-label">
                <TriangleAlert size={16} /> At Risk
              </span>
              <Badge value="At risk" />
            </div>
            <div className="metric-body">
              <strong className="metric-number">{dynamicSummary.at_risk_count.toLocaleString('en-IN')}</strong>
              <span className="metric-sub">{dynamicSummary.at_risk_pct}% of evaluated</span>
            </div>
            <p className="metric-rule">Attendance &lt; {threshold}% (includes dropped)</p>
          </div>

          <div className="risk-metric-card no-risk">
            <div className="metric-header">
              <span className="metric-label">
                <ShieldCheck size={16} /> No Risk
              </span>
              <Badge value="No risk" />
            </div>
            <div className="metric-body">
              <strong className="metric-number">{dynamicSummary.no_risk_count.toLocaleString('en-IN')}</strong>
              <span className="metric-sub">{dynamicSummary.no_risk_pct}% of evaluated</span>
            </div>
            <p className="metric-rule">Attendance &ge; {threshold}% in selected period</p>
          </div>

          <div className="risk-metric-card active-intern">
            <div className="metric-header">
              <span className="metric-label">
                <BriefcaseBusiness size={16} /> Active Interns
              </span>
              <Badge value="Active Intern" />
            </div>
            <div className="metric-body">
              <strong className="metric-number">{dynamicSummary.active_interns_count.toLocaleString('en-IN')}</strong>
              <span className="metric-sub">{dynamicSummary.active_interns_pct}% of all</span>
            </div>
            <p className="metric-rule">Excluded from attendance risk assessment</p>
          </div>

          <div className="risk-metric-card dropped-intern">
            <div className="metric-header">
              <span className="metric-label">
                <UserX size={16} /> Dropped Interns
              </span>
              <Badge value="Dropped" />
            </div>
            <div className="metric-body">
              <strong className="metric-number">{dynamicSummary.dropped_interns_count.toLocaleString('en-IN')}</strong>
              <span className="metric-sub">Past internship tenure</span>
            </div>
            <p className="metric-rule">Enrolled in past internship batches</p>
          </div>
        </div>

        {/* Visual Stacked Proportional Bar */}
        <div className="risk-proportion-container">
          <div className="risk-proportion-bar">
            <div
              className="risk-bar-fill at-risk"
              style={{ width: `${(dynamicSummary.at_risk_count / (dynamicSummary.total_students || 1)) * 100}%` }}
              title={`At risk: ${dynamicSummary.at_risk_count}`}
            >
              {dynamicSummary.at_risk_count > 40 && <span>At risk ({dynamicSummary.at_risk_count})</span>}
            </div>
            <div
              className="risk-bar-fill no-risk"
              style={{ width: `${(dynamicSummary.no_risk_count / (dynamicSummary.total_students || 1)) * 100}%` }}
              title={`No risk: ${dynamicSummary.no_risk_count}`}
            >
              {dynamicSummary.no_risk_count > 40 && <span>No risk ({dynamicSummary.no_risk_count})</span>}
            </div>
            <div
              className="risk-bar-fill active-intern"
              style={{ width: `${(dynamicSummary.active_interns_count / (dynamicSummary.total_students || 1)) * 100}%` }}
              title={`Active Interns: ${dynamicSummary.active_interns_count}`}
            >
              {dynamicSummary.active_interns_count > 30 && <span>Active Interns ({dynamicSummary.active_interns_count})</span>}
            </div>
          </div>
          <div className="risk-proportion-legend">
            <span>
              <i className="legend-dot red" /> At risk ({dynamicSummary.at_risk_count})
            </span>
            <span>
              <i className="legend-dot green" /> No risk ({dynamicSummary.no_risk_count})
            </span>
            <span>
              <i className="legend-dot blue" /> Active Interns ({dynamicSummary.active_interns_count}) · Excluded from risk
            </span>
          </div>
        </div>
      </Card>

      {/* Student Records Table Card */}
      <Card
        title="Student Records &amp; Attendance Risk"
        subtitle={`All ${dynamicSummary.total_students} student records. Active interns shown separately; dropped students evaluated by attendance.`}
      >
        <div className="records-toolbar">
          <div className="risk-filter-tabs">
            <button
              type="button"
              className={`filter-tab ${riskFilter === 'all' ? 'active' : ''}`}
              onClick={() => {
                setRiskFilter('all');
                setPage(1);
              }}
            >
              All students ({dynamicSummary.total_students})
            </button>
            <button
              type="button"
              className={`filter-tab at-risk ${riskFilter === 'at_risk' ? 'active' : ''}`}
              onClick={() => {
                setRiskFilter('at_risk');
                setPage(1);
              }}
            >
              At risk ({dynamicSummary.at_risk_count})
            </button>
            <button
              type="button"
              className={`filter-tab no-risk ${riskFilter === 'no_risk' ? 'active' : ''}`}
              onClick={() => {
                setRiskFilter('no_risk');
                setPage(1);
              }}
            >
              No risk ({dynamicSummary.no_risk_count})
            </button>
            <button
              type="button"
              className={`filter-tab active-intern ${riskFilter === 'active_intern' ? 'active' : ''}`}
              onClick={() => {
                setRiskFilter('active_intern');
                setPage(1);
              }}
            >
              Active Interns ({dynamicSummary.active_interns_count})
            </button>
            <button
              type="button"
              className={`filter-tab dropped-intern ${riskFilter === 'dropped_intern' ? 'active' : ''}`}
              onClick={() => {
                setRiskFilter('dropped_intern');
                setPage(1);
              }}
            >
              Dropped interns ({dynamicSummary.dropped_interns_count})
            </button>
          </div>

          <div className="records-search-export">
            <div className="table-search-box">
              <Search size={14} />
              <input
                type="text"
                placeholder="Search name, email, batch, year, status…"
                value={search}
                onChange={e => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                aria-label="Filter student records"
              />
              {search && (
                <button
                  type="button"
                  className="clear-search"
                  onClick={() => setSearch('')}
                  aria-label="Clear search"
                >
                  ×
                </button>
              )}
            </div>

            <button
              type="button"
              className="button small"
              onClick={downloadCsv}
              disabled={!filteredStudents.length}
            >
              <Download size={14} /> Download CSV
            </button>
          </div>
        </div>

        {isPending ? (
          <Loading />
        ) : error ? (
          <ErrorState error={error} retry={() => void refetch()} />
        ) : !filteredStudents.length ? (
          <Empty
            title="No students match the criteria"
            message={`No students found for filter "${riskFilter}" with search query "${search}".`}
          />
        ) : (
          <>
            <div className={`table-scroll ${isFetching ? 'is-fetching' : ''}`}>
              <table>
                <thead>
                  <tr>
                    <th>
                      <button
                        className="sort-btn"
                        onClick={() => handleSort('student_name')}
                        type="button"
                      >
                        Student Name{' '}
                        {sortKey === 'student_name' ? (
                          sortDir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : (
                          <ArrowUpDown size={12} />
                        )}
                      </button>
                    </th>
                    <th>
                      <button className="sort-btn" onClick={() => handleSort('year')} type="button">
                        Year / Cohort{' '}
                        {sortKey === 'year' ? (
                          sortDir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : (
                          <ArrowUpDown size={12} />
                        )}
                      </button>
                    </th>
                    <th>
                      <button className="sort-btn" onClick={() => handleSort('batch')} type="button">
                        Batch{' '}
                        {sortKey === 'batch' ? (
                          sortDir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : (
                          <ArrowUpDown size={12} />
                        )}
                      </button>
                    </th>
                    <th>
                      <button
                        className="sort-btn"
                        onClick={() => handleSort('semester')}
                        type="button"
                      >
                        Semester{' '}
                        {sortKey === 'semester' ? (
                          sortDir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : (
                          <ArrowUpDown size={12} />
                        )}
                      </button>
                    </th>
                    <th>
                      <button
                        className="sort-btn"
                        onClick={() => handleSort('enrollment_status')}
                        type="button"
                      >
                        Status{' '}
                        {sortKey === 'enrollment_status' ? (
                          sortDir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : (
                          <ArrowUpDown size={12} />
                        )}
                      </button>
                    </th>
                    <th>
                      <button
                        className="sort-btn"
                        onClick={() => handleSort('is_active_intern')}
                        type="button"
                      >
                        Active Interns{' '}
                        {sortKey === 'is_active_intern' ? (
                          sortDir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : (
                          <ArrowUpDown size={12} />
                        )}
                      </button>
                    </th>
                    <th>Classes</th>
                    <th>
                      <button
                        className="sort-btn"
                        onClick={() => handleSort('attendance_percentage')}
                        type="button"
                      >
                        Attendance %{' '}
                        {sortKey === 'attendance_percentage' ? (
                          sortDir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : (
                          <ArrowUpDown size={12} />
                        )}
                      </button>
                    </th>
                    <th>
                      <button
                        className="sort-btn"
                        onClick={() => handleSort('risk_status')}
                        type="button"
                      >
                        Risk Status{' '}
                        {sortKey === 'risk_status' ? (
                          sortDir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : (
                          <ArrowUpDown size={12} />
                        )}
                      </button>
                    </th>
                    <th>
                      <span className="sr-only">Details</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {pagedStudents.map(s => {
                    const att = s.attendance_percentage;
                    const isAtRisk = s.risk_status === 'At risk';
                    const isNoRisk = s.risk_status === 'No risk';
                    return (
                      <tr key={s.student_id}>
                        <td>
                          <button
                            type="button"
                            className="text-link"
                            onClick={() =>
                              onOpen('students', {
                                id: s.student_id,
                                student: s.student_name,
                                email: s.email,
                                batch: s.batch,
                                attendance: att,
                                risk: s.risk_status,
                              } as Row)
                            }
                          >
                            <strong>{s.student_name}</strong>
                          </button>
                          <small className="student-email">{s.email}</small>
                        </td>
                        <td>{s.year || '—'}</td>
                        <td>{s.batch || '—'}</td>
                        <td>{s.semester || '—'}</td>
                        <td>
                          <Badge value={s.enrollment_status === 'active' && !s.lms_active ? 'Deactivated' : s.enrollment_status} />
                        </td>
                        <td>
                          {s.is_active_intern ? (
                            <Badge value="Active Intern" />
                          ) : s.is_dropped_intern ? (
                            <Badge value="Dropped Intern" />
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td className="numeric">
                          {s.present_classes} / {s.total_classes}
                        </td>
                        <td>
                          <div className="attendance-cell">
                            <span className="numeric font-medium">
                              {att != null ? `${att.toFixed(1)}%` : '—'}
                            </span>
                            <div className="mini-progress-track">
                              <div
                                className={`mini-progress-fill ${isAtRisk ? 'at-risk' : isNoRisk ? 'no-risk' : 'active-intern'}`}
                                style={{ width: `${Math.min(100, att ?? 0)}%` }}
                              />
                            </div>
                          </div>
                        </td>
                        <td>
                          <Badge value={s.risk_status} />
                        </td>
                        <td>
                          <button
                            type="button"
                            className="icon-button"
                            aria-label="Open student record"
                            onClick={() =>
                              onOpen('students', {
                                id: s.student_id,
                                student: s.student_name,
                                email: s.email,
                                batch: s.batch,
                                attendance: att,
                                risk: s.risk_status,
                              } as Row)
                            }
                          >
                            <ChevronRight size={16} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="pagination">
              <span>
                Page {page} of {totalPages} ({filteredStudents.length.toLocaleString('en-IN')}{' '}
                students)
              </span>
              <div>
                <button
                  type="button"
                  className="button small"
                  disabled={page === 1}
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  aria-label="Previous page"
                >
                  <ChevronLeft size={15} />
                </button>
                <button
                  type="button"
                  className="button small"
                  disabled={page >= totalPages}
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  aria-label="Next page"
                >
                  <ChevronRight size={15} />
                </button>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
