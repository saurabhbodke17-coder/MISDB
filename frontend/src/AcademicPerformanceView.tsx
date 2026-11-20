import { useState, useMemo, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Award,
  Users,
  CheckCircle2,
  Search,
  Download,
  Calendar,
  ChevronLeft,
  ChevronRight,
  BarChart3,
  FileText,
  X,
  ArrowRight,
  HelpCircle,
} from 'lucide-react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
  CartesianGrid,
  ReferenceLine,
} from 'recharts';
import { api, queryString } from './api';
import type { Filters, Row } from './api';
import { Card, Loading, ErrorState, Badge } from './components';

export interface SubjectCard {
  id: string;
  subject_name: string;
  semester: string;
  batches: string;
  student_count: number;
  eval_avg: number | null;
  viva_avg: number | null;
  midsem_avg: number | null;
  endsem_avg: number | null;
  overall_avg: number;
  tier: 'Distinction' | 'First Class' | 'Pass' | 'At Risk';
  formula: string;
  red_flags: string[];
}

export interface AcademicPerformanceApiResponse {
  kpis: {
    total_submissions: number;
    unique_students: number;
    unique_subjects: number;
    avg_score_pct: number;
    attendance_rate: number;
    pass_rate: number;
    distinction_rate: number;
  };
  subject_cards?: SubjectCard[];
  charts: {
    grade_distribution: { name: string; count: number; percentage: number }[];
    subject_performance: {
      name: string;
      count: number;
      students: number;
      avg_score: number;
      attendance_rate: number;
      pass_rate: number;
    }[];
    assessment_types: { name: string; count: number; avg_score: number; attendance_rate: number }[];
    batch_comparison: { name: string; count: number; students: number; avg_score: number; attendance_rate: number }[];
    viva_skills: {
      progress_tracking?: number;
      technical_understanding?: number;
      problem_solving?: number;
      communication?: number;
      viva_count?: number;
    };
  };
  records: Array<{
    id: string;
    batch: string;
    semester: string;
    student_name: string;
    email: string;
    exam_date: string;
    exam_type: string;
    exam_count: string;
    attendance: string;
    subject_name: string;
    maximum_marks: string;
    marks_scored: string;
    score_pct: number;
    tier: 'Distinction' | 'First Class' | 'Pass' | 'At Risk';
    feedback_summary?: string;
    question_one_progress_tracking?: string;
    question_two_technical_understanding?: string;
    question_three_problem_solving_data_structures?: string;
    communication?: string;
  }>;
  pagination: {
    total: number;
    page: number;
    page_size: number;
    total_pages: number;
  };
  filter_options: {
    exam_types: string[];
    subjects: string[];
  };
}

interface AcademicPerformanceViewProps {
  filters: Filters;
  activeTab?: string;
  onOpen?: (source: string, row: Row) => void;
  setToast?: (msg: string) => void;
}

export function AcademicPerformanceView({ filters, activeTab = 'overview', setToast }: AcademicPerformanceViewProps) {
  // Local state for internal tab switching
  const [localTab, setLocalTab] = useState<string | null>(null);
  const effectiveTab = localTab || activeTab;

  useEffect(() => {
    setLocalTab(null);
  }, [activeTab]);

  // Subject cards state on Overview tab
  const [cardSemester, setCardSemester] = useState<string>('all');
  const [cardSearch, setCardSearch] = useState<string>('');
  const [cardSort, setCardSort] = useState<string>('name_asc');

  // Local state for table search, sub-filters, pagination, and feedback modal
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedExamType, setSelectedExamType] = useState('all');
  const [selectedSubject, setSelectedSubject] = useState('all');
  const [selectedTier, setSelectedTier] = useState('all');
  const [sortBy, setSortBy] = useState('date_desc');
  const [page, setPage] = useState(1);
  const [selectedRecord, setSelectedRecord] = useState<AcademicPerformanceApiResponse['records'][0] | null>(null);

  // Construct query parameters combining global appliedFilters + local secondary filters
  const queryParams = useMemo(() => {
    const q: Record<string, string> = {
      ...filters,
      page: String(page),
      page_size: '25',
      sort_by: sortBy,
    };
    if (selectedExamType !== 'all') q.exam_type = selectedExamType;
    if (selectedSubject !== 'all') q.subject = selectedSubject;
    if (selectedTier !== 'all') q.tier = selectedTier;
    if (searchTerm.trim()) q.search = searchTerm.trim();
    return q;
  }, [filters, page, sortBy, selectedExamType, selectedSubject, selectedTier, searchTerm]);

  const { data, isLoading, isError, error, refetch } = useQuery<AcademicPerformanceApiResponse>({
    queryKey: ['academic-performance', queryParams],
    queryFn: () => {
      const q = queryString(queryParams);
      return api<AcademicPerformanceApiResponse>(`/academic/performance${q ? `?${q}` : ''}`);
    },
    staleTime: 30000,
  });

  const kpis = data?.kpis;
  const charts = data?.charts;
  const records = data?.records || [];
  const pagination = data?.pagination;
  const subjectCards = data?.subject_cards || [];

  const availableSemesters = useMemo(() => {
    const sems = new Set<string>();
    subjectCards.forEach((c) => {
      if (c.semester) sems.add(c.semester);
    });
    return Array.from(sems).sort();
  }, [subjectCards]);

  const filteredCards = useMemo(() => {
    let list = [...subjectCards];
    if (cardSemester !== 'all') {
      list = list.filter((c) => c.semester.toUpperCase() === cardSemester.toUpperCase());
    }
    if (cardSearch.trim()) {
      const term = cardSearch.toLowerCase().trim();
      list = list.filter(
        (c) =>
          c.subject_name.toLowerCase().includes(term) ||
          c.semester.toLowerCase().includes(term) ||
          c.batches.toLowerCase().includes(term)
      );
    }
    list.sort((a, b) => {
      if (cardSort === 'endsem_desc') return (b.endsem_avg || 0) - (a.endsem_avg || 0);
      if (cardSort === 'midsem_desc') return (b.midsem_avg || 0) - (a.midsem_avg || 0);
      if (cardSort === 'eval_desc') return (b.eval_avg || 0) - (a.eval_avg || 0);
      if (cardSort === 'viva_desc') return (b.viva_avg ?? -1) - (a.viva_avg ?? -1);
      if (cardSort === 'students_desc') return b.student_count - a.student_count;
      if (cardSort === 'name_asc') return a.subject_name.localeCompare(b.subject_name);
      return 0;
    });
    return list;
  }, [subjectCards, cardSemester, cardSearch, cardSort]);

  const getSemesterStyle = (sem: string) => {
    if (sem.includes('1')) return { bg: 'rgba(14, 165, 233, 0.12)', color: '#0284c7', border: 'rgba(14, 165, 233, 0.3)' };
    if (sem.includes('2')) return { bg: 'rgba(99, 102, 241, 0.12)', color: '#6366f1', border: 'rgba(99, 102, 241, 0.3)' };
    if (sem.includes('3')) return { bg: 'rgba(168, 85, 247, 0.12)', color: '#a855f7', border: 'rgba(168, 85, 247, 0.3)' };
    if (sem.includes('4')) return { bg: 'rgba(236, 72, 153, 0.12)', color: '#ec4899', border: 'rgba(236, 72, 153, 0.3)' };
    return { bg: 'var(--surface2)', color: 'var(--ink)', border: 'var(--line)' };
  };

  // CSV Export
  const handleExportCSV = () => {
    if (!records.length) {
      if (setToast) setToast('No records to export');
      return;
    }
    const headers = [
      'Student Name',
      'Email',
      'Batch',
      'Semester',
      'Subject',
      'Assessment Type',
      'Assessment Count',
      'Exam Date',
      'Attendance',
      'Marks Scored',
      'Max Marks',
      'Score %',
      'Performance Tier',
      'Feedback Summary',
    ];

    const rows = records.map((r) => [
      `"${(r.student_name || '').replace(/"/g, '""')}"`,
      `"${(r.email || '').replace(/"/g, '""')}"`,
      `"${r.batch || ''}"`,
      `"${r.semester || ''}"`,
      `"${(r.subject_name || '').replace(/"/g, '""')}"`,
      `"${r.exam_type || ''}"`,
      `"${r.exam_count || ''}"`,
      `"${r.exam_date || ''}"`,
      `"${r.attendance === '1' ? 'Present' : r.attendance === '0' ? 'Absent' : 'Excused'}"`,
      `"${r.marks_scored || ''}"`,
      `"${r.maximum_marks || ''}"`,
      `"${r.score_pct || 0}%"`,
      `"${r.tier || ''}"`,
      `"${(r.feedback_summary || '').replace(/"/g, '""').replace(/\n/g, ' ')}"`,
    ]);

    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map((e) => e.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `academic_performance_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    if (setToast) setToast('Academic performance data exported to CSV');
  };

  if (isLoading) {
    return <Loading />;
  }

  if (isError) {
    return (
      <ErrorState
        error={error}
        retry={() => refetch()}
      />
    );
  }

  // Active filter count and labels
  const activeFilterTags: string[] = [];
  if (filters.from_date || filters.to_date) {
    activeFilterTags.push(`${filters.from_date || 'Start'} to ${filters.to_date || 'End'}`);
  }
  if (filters.graduation_year_id) activeFilterTags.push('Filtered by Cohort');
  if (filters.semester_id) activeFilterTags.push('Filtered by Semester');
  if (filters.batch_id) activeFilterTags.push('Filtered by Batch');

  return (
    <div className="academic-performance-view" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* 1. Header Banner */}
      <Card title="Student Academic Performance (Beta)">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
              <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 600, color: 'var(--ink)' }}>
                Student Academic Performance
              </h2>
              <span
                style={{
                  background: 'rgba(36, 87, 214, 0.12)',
                  color: 'var(--accent)',
                  border: '1px solid rgba(36, 87, 214, 0.3)',
                  padding: '2px 7px',
                  borderRadius: '12px',
                  fontSize: '10px',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px',
                }}
              >
                Beta
              </span>
            </div>
            <p style={{ margin: 0, fontSize: '12px', color: 'var(--secondary)' }}>
              Live evaluation records, oral vivas, and examinations across cohorts and subjects.
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <button
              onClick={handleExportCSV}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                background: 'var(--surface)',
                border: '1px solid var(--line)',
                color: 'var(--ink)',
                borderRadius: '6px',
                padding: '6px 12px',
                fontSize: '12px',
                fontWeight: 500,
                cursor: 'pointer',
              }}
              title="Download CSV"
            >
              <Download size={14} />
              Export CSV
            </button>
          </div>
        </div>

        {/* Filter tags pill row */}
        {activeFilterTags.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '12px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '11px', color: 'var(--muted)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
              <Calendar size={12} /> Active Global Filters:
            </span>
            {activeFilterTags.map((tag, idx) => (
              <span
                key={idx}
                style={{
                  fontSize: '11px',
                  background: 'var(--surface2)',
                  color: 'var(--ink)',
                  border: '1px solid var(--line)',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  fontWeight: 500,
                }}
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </Card>

      {/* 2. Top Summary KPI Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '12px',
        }}
      >
        <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: '8px', padding: '14px 16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
            <span style={{ fontSize: '12px', color: 'var(--secondary)' }}>Evaluated Submissions</span>
            <FileText size={16} color="var(--accent)" />
          </div>
          <div style={{ fontSize: '22px', fontWeight: 700, color: 'var(--ink)' }}>
            {(kpis?.total_submissions || 0).toLocaleString()}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '4px' }}>
            Across {kpis?.unique_subjects || 0} subjects
          </div>
        </div>

        <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: '8px', padding: '14px 16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
            <span style={{ fontSize: '12px', color: 'var(--secondary)' }}>Average Score %</span>
            <BarChart3 size={16} color="#3b82f6" />
          </div>
          <div style={{ fontSize: '22px', fontWeight: 700, color: (kpis?.avg_score_pct || 0) >= 50 ? '#10b981' : '#f59e0b' }}>
            {kpis?.avg_score_pct || 0}%
          </div>
          <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '4px' }}>
            Cohort mean percentage
          </div>
        </div>

        <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: '8px', padding: '14px 16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
            <span style={{ fontSize: '12px', color: 'var(--secondary)' }}>Pass Rate (≥40%)</span>
            <CheckCircle2 size={16} color="#10b981" />
          </div>
          <div style={{ fontSize: '22px', fontWeight: 700, color: '#10b981' }}>
            {kpis?.pass_rate || 0}%
          </div>
          <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '4px' }}>
            Minimum passing grade
          </div>
        </div>

        <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: '8px', padding: '14px 16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
            <span style={{ fontSize: '12px', color: 'var(--secondary)' }}>Distinction (≥75%)</span>
            <Award size={16} color="#8b5cf6" />
          </div>
          <div style={{ fontSize: '22px', fontWeight: 700, color: '#8b5cf6' }}>
            {kpis?.distinction_rate || 0}%
          </div>
          <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '4px' }}>
            Top percentile achievers
          </div>
        </div>

        <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: '8px', padding: '14px 16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
            <span style={{ fontSize: '12px', color: 'var(--secondary)' }}>Assessed Students</span>
            <Users size={16} color="#06b6d4" />
          </div>
          <div style={{ fontSize: '22px', fontWeight: 700, color: 'var(--ink)' }}>
            {(kpis?.unique_students || 0).toLocaleString()}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '4px' }}>
            Distinct student records
          </div>
        </div>

        <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: '8px', padding: '14px 16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
            <span style={{ fontSize: '12px', color: 'var(--secondary)' }}>Exam Attendance</span>
            <Calendar size={16} color="#ec4899" />
          </div>
          <div style={{ fontSize: '22px', fontWeight: 700, color: (kpis?.attendance_rate || 0) >= 75 ? '#10b981' : '#f59e0b' }}>
            {kpis?.attendance_rate || 0}%
          </div>
          <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '4px' }}>
            Present on scheduled date
          </div>
        </div>
      </div>

      {/* 3. Main Views depending on activeTab / effectiveTab */}
      {effectiveTab === 'overview' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* A. Subject Academic Scorecards Section */}
          <Card title="Subject Academic Performance">
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
                <p style={{ margin: 0, fontSize: '13px', color: 'var(--secondary)' }}>
                  Average percentage marks across <strong>Mid-Sem</strong>, <strong>Weekly Eval</strong>, <strong>Viva Voce</strong>, and <strong>End-Sem</strong> examinations.
                </p>
                <div style={{ fontSize: '11px', color: 'var(--muted)', background: 'var(--surface2)', padding: '4px 10px', borderRadius: '4px', fontWeight: 500 }}>
                  Showing {filteredCards.length} of {subjectCards.length} Subjects
                </div>
              </div>

              {/* Filter Controls Row */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', alignItems: 'center', justifyContent: 'space-between' }}>
                {/* Semester Pills */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                  <button
                    onClick={() => setCardSemester('all')}
                    style={{
                      padding: '5px 12px',
                      borderRadius: '16px',
                      fontSize: '12px',
                      fontWeight: 600,
                      cursor: 'pointer',
                      border: '1px solid',
                      background: cardSemester === 'all' ? 'var(--accent)' : 'var(--surface)',
                      color: cardSemester === 'all' ? '#ffffff' : 'var(--ink)',
                      borderColor: cardSemester === 'all' ? 'var(--accent)' : 'var(--line)',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    All ({subjectCards.length})
                  </button>
                  {availableSemesters.map((sem) => {
                    const count = subjectCards.filter((c) => c.semester === sem).length;
                    const isSel = cardSemester === sem;
                    return (
                      <button
                        key={sem}
                        onClick={() => setCardSemester(sem)}
                        style={{
                          padding: '5px 12px',
                          borderRadius: '16px',
                          fontSize: '12px',
                          fontWeight: 600,
                          cursor: 'pointer',
                          border: '1px solid',
                          background: isSel ? 'var(--accent)' : 'var(--surface)',
                          color: isSel ? '#ffffff' : 'var(--ink)',
                          borderColor: isSel ? 'var(--accent)' : 'var(--line)',
                          transition: 'all 0.15s ease',
                        }}
                      >
                        {sem} ({count})
                      </button>
                    );
                  })}
                </div>

                {/* Search & Sort Controls */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                  <div style={{ position: 'relative', width: '220px' }}>
                    <Search size={13} style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', color: 'var(--muted)' }} />
                    <input
                      type="text"
                      placeholder="Search subject..."
                      value={cardSearch}
                      onChange={(e) => setCardSearch(e.target.value)}
                      style={{
                        width: '100%',
                        padding: '6px 8px 6px 26px',
                        fontSize: '12px',
                        background: 'var(--surface)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--ink)',
                        boxSizing: 'border-box',
                      }}
                    />
                  </div>

                  <select
                    value={cardSort}
                    onChange={(e) => setCardSort(e.target.value)}
                    style={{
                      padding: '6px 10px',
                      fontSize: '12px',
                      background: 'var(--surface)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--ink)',
                    }}
                  >
                    <option value="name_asc">Subject Name (A-Z)</option>
                    <option value="endsem_desc">End-Sem (High to Low)</option>
                    <option value="midsem_desc">Mid-Sem (High to Low)</option>
                    <option value="eval_desc">Weekly Eval (High to Low)</option>
                    <option value="viva_desc">Viva Voce (High to Low)</option>
                    <option value="students_desc">Student Count (Highest First)</option>
                  </select>
                </div>
              </div>

              {/* Subject Cards Grid */}
              {filteredCards.length === 0 ? (
                <div style={{ padding: '36px', textAlign: 'center', color: 'var(--muted)', background: 'var(--surface2)', borderRadius: '8px' }}>
                  No subject scorecards match the current filter criteria.
                </div>
              ) : (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))',
                    gap: '16px',
                    alignItems: 'stretch',
                  }}
                >
                  {filteredCards.map((card) => {
                    const semStyle = getSemesterStyle(card.semester);

                    return (
                      <div
                        key={card.id}
                        style={{
                          background: 'var(--surface)',
                          border: '1px solid var(--line)',
                          borderRadius: '10px',
                          padding: '16px',
                          display: 'flex',
                          flexDirection: 'column',
                          justifyContent: 'space-between',
                          gap: '14px',
                          height: '100%',
                          boxSizing: 'border-box',
                          transition: 'all 0.2s ease',
                        }}
                      >
                        {/* Top Header with Fixed Heights for Perfect Row Alignment */}
                        <div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px', marginBottom: '8px' }}>
                            <h3
                              style={{
                                margin: 0,
                                fontSize: '14px',
                                fontWeight: 700,
                                color: 'var(--ink)',
                                lineHeight: '1.35',
                                flex: 1,
                                minHeight: '38px',
                                display: '-webkit-box',
                                WebkitLineClamp: 2,
                                WebkitBoxOrient: 'vertical',
                                overflow: 'hidden',
                              }}
                              title={card.subject_name}
                            >
                              {card.subject_name}
                            </h3>
                            <span
                              style={{
                                background: semStyle.bg,
                                color: semStyle.color,
                                border: `1px solid ${semStyle.border}`,
                                fontSize: '10px',
                                fontWeight: 700,
                                padding: '2px 8px',
                                borderRadius: '10px',
                                letterSpacing: '0.3px',
                                flexShrink: 0,
                                marginTop: '1px',
                              }}
                            >
                              {card.semester}
                            </span>
                          </div>

                          <div
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: '6px',
                              fontSize: '11px',
                              color: 'var(--muted)',
                              height: '18px',
                              whiteSpace: 'nowrap',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                            }}
                          >
                            <Users size={12} style={{ flexShrink: 0 }} />
                            <span style={{ flexShrink: 0 }}>{card.student_count} Students Enrolled</span>
                            <span style={{ flexShrink: 0 }}>•</span>
                            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={card.batches}>
                              Batches: {card.batches || 'Pioneer'}
                            </span>
                          </div>
                        </div>

                        {/* 4 Parameters Grid: Unified Box Height, Baseline, and Bar Alignment */}
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }}>
                          {/* 1. Mid-Sem */}
                          <div
                            style={{
                              background: 'var(--surface2)',
                              borderRadius: '6px',
                              padding: '10px 8px',
                              display: 'flex',
                              flexDirection: 'column',
                              justifyContent: 'space-between',
                              height: '78px',
                              boxSizing: 'border-box',
                            }}
                          >
                            <div
                              style={{
                                fontSize: '10px',
                                color: 'var(--secondary)',
                                textTransform: 'uppercase',
                                fontWeight: 600,
                                letterSpacing: '0.2px',
                                height: '24px',
                                display: 'flex',
                                alignItems: 'flex-start',
                                lineHeight: '1.2',
                              }}
                            >
                              Mid-Sem
                            </div>
                            <div
                              style={{
                                fontSize: '16px',
                                fontWeight: 700,
                                lineHeight: '1',
                                color: card.midsem_avg !== null ? 'var(--ink)' : 'var(--muted)',
                              }}
                            >
                              {card.midsem_avg !== null ? `${card.midsem_avg}%` : '—'}
                            </div>
                            <div style={{ height: '4px', width: '100%', background: 'var(--line)', borderRadius: '2px', overflow: 'hidden', marginTop: '2px' }}>
                              <div style={{ height: '100%', width: `${Math.min(100, card.midsem_avg || 0)}%`, background: '#8b5cf6', borderRadius: '2px' }} />
                            </div>
                          </div>

                          {/* 2. Weekly Eval */}
                          <div
                            style={{
                              background: 'var(--surface2)',
                              borderRadius: '6px',
                              padding: '10px 8px',
                              display: 'flex',
                              flexDirection: 'column',
                              justifyContent: 'space-between',
                              height: '78px',
                              boxSizing: 'border-box',
                            }}
                          >
                            <div
                              style={{
                                fontSize: '10px',
                                color: 'var(--secondary)',
                                textTransform: 'uppercase',
                                fontWeight: 600,
                                letterSpacing: '0.2px',
                                height: '24px',
                                display: 'flex',
                                alignItems: 'flex-start',
                                lineHeight: '1.2',
                              }}
                            >
                              Weekly Eval
                            </div>
                            <div
                              style={{
                                fontSize: '16px',
                                fontWeight: 700,
                                lineHeight: '1',
                                color: card.eval_avg !== null ? 'var(--ink)' : 'var(--muted)',
                              }}
                            >
                              {card.eval_avg !== null ? `${card.eval_avg}%` : '—'}
                            </div>
                            <div style={{ height: '4px', width: '100%', background: 'var(--line)', borderRadius: '2px', overflow: 'hidden', marginTop: '2px' }}>
                              <div style={{ height: '100%', width: `${Math.min(100, card.eval_avg || 0)}%`, background: '#3b82f6', borderRadius: '2px' }} />
                            </div>
                          </div>

                          {/* 3. Viva Voce */}
                          <div
                            style={{
                              background: 'var(--surface2)',
                              borderRadius: '6px',
                              padding: '10px 8px',
                              display: 'flex',
                              flexDirection: 'column',
                              justifyContent: 'space-between',
                              height: '78px',
                              boxSizing: 'border-box',
                            }}
                          >
                            <div
                              style={{
                                fontSize: '10px',
                                color: 'var(--secondary)',
                                textTransform: 'uppercase',
                                fontWeight: 600,
                                letterSpacing: '0.2px',
                                height: '24px',
                                display: 'flex',
                                alignItems: 'flex-start',
                                lineHeight: '1.2',
                              }}
                            >
                              Viva Voce
                            </div>
                            <div
                              style={{
                                fontSize: '16px',
                                fontWeight: 700,
                                lineHeight: '1',
                                color: card.viva_avg !== null ? 'var(--ink)' : 'var(--muted)',
                              }}
                            >
                              {card.viva_avg !== null ? `${card.viva_avg}%` : '—'}
                            </div>
                            <div style={{ height: '4px', width: '100%', background: 'var(--line)', borderRadius: '2px', overflow: 'hidden', marginTop: '2px' }}>
                              <div style={{ height: '100%', width: `${Math.min(100, card.viva_avg || 0)}%`, background: '#f59e0b', borderRadius: '2px' }} />
                            </div>
                          </div>

                          {/* 4. End-Sem */}
                          <div
                            style={{
                              background: 'var(--surface2)',
                              borderRadius: '6px',
                              padding: '10px 8px',
                              display: 'flex',
                              flexDirection: 'column',
                              justifyContent: 'space-between',
                              height: '78px',
                              boxSizing: 'border-box',
                            }}
                          >
                            <div
                              style={{
                                fontSize: '10px',
                                color: 'var(--secondary)',
                                textTransform: 'uppercase',
                                fontWeight: 600,
                                letterSpacing: '0.2px',
                                height: '24px',
                                display: 'flex',
                                alignItems: 'flex-start',
                                lineHeight: '1.2',
                              }}
                            >
                              End-Sem
                            </div>
                            <div
                              style={{
                                fontSize: '16px',
                                fontWeight: 700,
                                lineHeight: '1',
                                color: card.endsem_avg !== null ? 'var(--ink)' : 'var(--muted)',
                              }}
                            >
                              {card.endsem_avg !== null ? `${card.endsem_avg}%` : '—'}
                            </div>
                            <div style={{ height: '4px', width: '100%', background: 'var(--line)', borderRadius: '2px', overflow: 'hidden', marginTop: '2px' }}>
                              <div style={{ height: '100%', width: `${Math.min(100, card.endsem_avg || 0)}%`, background: '#10b981', borderRadius: '2px' }} />
                            </div>
                          </div>
                        </div>

                        {/* Card Action Link: Pinned to Bottom with marginTop: auto */}
                        <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: '10px', marginTop: 'auto', borderTop: '1px solid var(--line)' }}>
                          <button
                            onClick={() => {
                              setSelectedSubject(card.subject_name);
                              setLocalTab('records');
                            }}
                            style={{
                              background: 'transparent',
                              border: 'none',
                              color: 'var(--accent)',
                              fontSize: '11px',
                              fontWeight: 600,
                              cursor: 'pointer',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px',
                              padding: '2px 0',
                            }}
                          >
                            View Student Records <ArrowRight size={12} />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </Card>
        </div>
      )}

      {/* 4. Subject Analytics Tab */}
      {effectiveTab === 'subjects' && (
        <Card title="Subject-wise Academic Performance">
          <p style={{ margin: '0 0 16px 0', fontSize: '12px', color: 'var(--secondary)' }}>
            Average marks percentage, student count, and attendance across all evaluated curriculum subjects.
          </p>
          <div style={{ height: 380, width: '100%' }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={charts?.subject_performance || []}
                layout="vertical"
                margin={{ top: 5, right: 30, left: 160, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--line)" />
                <XAxis type="number" domain={[0, 100]} unit="%" tick={{ fontSize: 11, fill: 'var(--secondary)' }} />
                <YAxis
                  type="category"
                  dataKey="name"
                  tick={{ fontSize: 11, fill: 'var(--ink)' }}
                  width={150}
                  tickFormatter={(val) => (val.length > 24 ? `${val.slice(0, 22)}…` : val)}
                />
                <Tooltip
                  contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: '6px', fontSize: '12px' }}
                  formatter={(val, _name, item) => [
                    `${val}% | Pass Rate: ${item.payload.pass_rate}% | Attendance: ${item.payload.attendance_rate}%`,
                    item.payload.name,
                  ]}
                />
                <ReferenceLine x={40} stroke="#ef4444" strokeDasharray="3 3" />
                <Bar dataKey="avg_score" fill="#3b82f6" radius={[0, 4, 4, 0]}>
                  {(charts?.subject_performance || []).map((entry, index) => (
                    <Cell
                      key={`subj-${index}`}
                      fill={entry.avg_score >= 60 ? '#10b981' : entry.avg_score >= 40 ? '#3b82f6' : '#ef4444'}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {/* 5. Vivas & Batch Comparison Tab */}
      {effectiveTab === 'vivas' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: '16px' }}>
          {/* Viva Competencies Card */}
          <Card title="Viva Competency & Skill Breakdown">
            <p style={{ margin: '0 0 16px 0', fontSize: '12px', color: 'var(--secondary)' }}>
              Granular sub-skills evaluated during viva interviews (scored out of 5).
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', padding: '10px 0' }}>
              {[
                {
                  label: 'Technical Understanding',
                  val: charts?.viva_skills?.technical_understanding || 0,
                  desc: 'Core concept clarity, architecture, and syntax precision',
                },
                {
                  label: 'Problem Solving & DSA',
                  val: charts?.viva_skills?.problem_solving || 0,
                  desc: 'Algorithmic approach, data structure selection, edge-case analysis',
                },
                {
                  label: 'Verbal & Technical Communication',
                  val: charts?.viva_skills?.communication || 0,
                  desc: 'Clarity of explanation, technical terminology, confidence',
                },
                {
                  label: 'Progress Tracking & Consistency',
                  val: charts?.viva_skills?.progress_tracking || 0,
                  desc: 'Project milestones completed, regular submission pace',
                },
              ].map((skill, idx) => (
                <div key={idx} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--ink)' }}>{skill.label}</span>
                    <strong style={{ fontSize: '13px', color: 'var(--accent)' }}>{skill.val} / 5.0</strong>
                  </div>
                  <div style={{ width: '100%', height: '8px', background: 'var(--surface2)', borderRadius: '4px', overflow: 'hidden' }}>
                    <div
                      style={{
                        width: `${Math.min(100, (skill.val / 5) * 100)}%`,
                        height: '100%',
                        background: 'var(--accent)',
                        borderRadius: '4px',
                      }}
                    />
                  </div>
                  <span style={{ fontSize: '11px', color: 'var(--muted)' }}>{skill.desc}</span>
                </div>
              ))}
            </div>
            <div style={{ marginTop: '14px', fontSize: '11px', color: 'var(--muted)', background: 'var(--surface2)', padding: '8px 12px', borderRadius: '6px' }}>
              Based on {charts?.viva_skills?.viva_count || 0} evaluated oral viva examination records.
            </div>
          </Card>

          {/* Section & Batch Comparison */}
          <Card title="Batch & Section Comparison">
            <p style={{ margin: '0 0 16px 0', fontSize: '12px', color: 'var(--secondary)' }}>
              Benchmarking performance across cohort sections (2024 A, 2025 A, B, C).
            </p>
            <div style={{ height: 260, width: '100%' }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={charts?.batch_comparison || []} margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--line)" />
                  <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'var(--secondary)' }} />
                  <YAxis unit="%" domain={[0, 100]} tick={{ fontSize: 11, fill: 'var(--secondary)' }} />
                  <Tooltip
                    contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: '6px', fontSize: '12px' }}
                    formatter={(val, _name, item) => [
                      `${val}% (Students: ${item.payload.students}, Attendance: ${item.payload.attendance_rate}%)`,
                      'Average Score',
                    ]}
                  />
                  <ReferenceLine y={40} stroke="#ef4444" strokeDasharray="3 3" />
                  <Bar dataKey="avg_score" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.max(1, (charts?.batch_comparison || []).length)}, 1fr)`, gap: '8px', marginTop: '12px' }}>
              {(charts?.batch_comparison || []).map((b, idx) => (
                <div key={idx} style={{ background: 'var(--surface2)', borderRadius: '6px', padding: '8px 10px', textAlign: 'center' }}>
                  <div style={{ fontSize: '11px', color: 'var(--secondary)', marginBottom: '2px' }}>{b.name}</div>
                  <div style={{ fontSize: '14px', fontWeight: 700, color: '#8b5cf6' }}>{b.avg_score}%</div>
                  <div style={{ fontSize: '10px', color: 'var(--muted)' }}>{b.students} students</div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {/* 6. Student Assessment Records Tab */}
      {effectiveTab === 'records' && (
        <Card title="Student Assessment Records & Feedback">
          {localTab === 'records' && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: '14px',
                background: 'rgba(36, 87, 214, 0.08)',
                border: '1px solid rgba(36, 87, 214, 0.25)',
                borderRadius: '6px',
                padding: '8px 12px',
                flexWrap: 'wrap',
                gap: '8px',
              }}
            >
              <div style={{ fontSize: '12px', color: 'var(--ink)' }}>
                Viewing records filtered for subject: <strong>{selectedSubject === 'all' ? 'All Subjects' : selectedSubject}</strong>
              </div>
              <button
                onClick={() => {
                  setLocalTab(null);
                  setSelectedSubject('all');
                }}
                style={{
                  background: 'var(--surface)',
                  border: '1px solid var(--line)',
                  borderRadius: '4px',
                  padding: '4px 10px',
                  fontSize: '11px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  color: 'var(--accent)',
                }}
              >
                ← Return to Overview Scorecards
              </button>
            </div>
          )}
          {/* Interactive Filters Bar */}
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: '10px',
              alignItems: 'center',
              marginBottom: '16px',
              paddingBottom: '14px',
              borderBottom: '1px solid var(--line)',
            }}
          >
            {/* Search Input */}
            <div style={{ position: 'relative', flex: '1 1 200px' }}>
              <Search
                size={14}
                style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--muted)' }}
              />
              <input
                type="text"
                placeholder="Search student, email, or subject…"
                value={searchTerm}
                onChange={(e) => {
                  setSearchTerm(e.target.value);
                  setPage(1);
                }}
                style={{
                  width: '100%',
                  padding: '7px 10px 7px 30px',
                  background: 'var(--surface)',
                  border: '1px solid var(--line)',
                  borderRadius: '6px',
                  fontSize: '12px',
                  color: 'var(--ink)',
                  boxSizing: 'border-box',
                }}
              />
            </div>

            {/* Assessment Type Filter */}
            <select
              value={selectedExamType}
              onChange={(e) => {
                setSelectedExamType(e.target.value);
                setPage(1);
              }}
              style={{
                padding: '7px 10px',
                background: 'var(--surface)',
                border: '1px solid var(--line)',
                borderRadius: '6px',
                fontSize: '12px',
                color: 'var(--ink)',
              }}
            >
              <option value="all">All Assessment Types</option>
              {(data?.filter_options?.exam_types || []).map((t, idx) => (
                <option key={idx} value={t}>
                  {t}
                </option>
              ))}
            </select>

            {/* Subject Filter */}
            <select
              value={selectedSubject}
              onChange={(e) => {
                setSelectedSubject(e.target.value);
                setPage(1);
              }}
              style={{
                padding: '7px 10px',
                background: 'var(--surface)',
                border: '1px solid var(--line)',
                borderRadius: '6px',
                fontSize: '12px',
                color: 'var(--ink)',
                maxWidth: '180px',
              }}
            >
              <option value="all">All Subjects</option>
              {(data?.filter_options?.subjects || []).map((s, idx) => (
                <option key={idx} value={s}>
                  {s.length > 28 ? `${s.slice(0, 26)}…` : s}
                </option>
              ))}
            </select>

            {/* Performance Tier Filter */}
            <select
              value={selectedTier}
              onChange={(e) => {
                setSelectedTier(e.target.value);
                setPage(1);
              }}
              style={{
                padding: '7px 10px',
                background: 'var(--surface)',
                border: '1px solid var(--line)',
                borderRadius: '6px',
                fontSize: '12px',
                color: 'var(--ink)',
              }}
            >
              <option value="all">All Performance Tiers</option>
              <option value="distinction">Distinction (≥75%)</option>
              <option value="first">First Class (60–74%)</option>
              <option value="pass">Pass (40–59%)</option>
              <option value="risk">At-Risk (&lt;40%)</option>
            </select>

            {/* Sort Filter */}
            <select
              value={sortBy}
              onChange={(e) => {
                setSortBy(e.target.value);
                setPage(1);
              }}
              style={{
                padding: '7px 10px',
                background: 'var(--surface)',
                border: '1px solid var(--line)',
                borderRadius: '6px',
                fontSize: '12px',
                color: 'var(--ink)',
              }}
            >
              <option value="date_desc">Date: Newest First</option>
              <option value="date_asc">Date: Oldest First</option>
              <option value="score_desc">Score: High to Low</option>
              <option value="score_asc">Score: Low to High</option>
              <option value="name_asc">Student Name (A-Z)</option>
            </select>

            {(searchTerm || selectedExamType !== 'all' || selectedTier !== 'all') && (
              <button
                onClick={() => {
                  setSearchTerm('');
                  setSelectedExamType('all');
                  setSelectedTier('all');
                  setPage(1);
                }}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--accent)',
                  fontSize: '11px',
                  cursor: 'pointer',
                  padding: '4px 8px',
                  fontWeight: 500,
                }}
              >
                Reset filters
              </button>
            )}
          </div>

          {/* Records Table */}
          {records.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--muted)' }}>
              <HelpCircle size={32} style={{ margin: '0 auto 10px', opacity: 0.5 }} />
              <div style={{ fontSize: '14px', fontWeight: 500, color: 'var(--ink)' }}>No assessment records match filters</div>
              <div style={{ fontSize: '12px', marginTop: '4px' }}>Try broadening your search or resetting applied filters.</div>
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', textAlign: 'left' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--line)', color: 'var(--secondary)' }}>
                    <th style={{ padding: '8px 10px' }}>Student</th>
                    <th style={{ padding: '8px 10px' }}>Batch & Sem</th>
                    <th style={{ padding: '8px 10px' }}>Subject</th>
                    <th style={{ padding: '8px 10px' }}>Assessment</th>
                    <th style={{ padding: '8px 10px' }}>Date</th>
                    <th style={{ padding: '8px 10px' }}>Score</th>
                    <th style={{ padding: '8px 10px' }}>Tier</th>
                    <th style={{ padding: '8px 10px', textAlign: 'center' }}>Feedback</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((row) => (
                    <tr
                      key={row.id}
                      style={{
                        borderBottom: '1px solid var(--line)',
                        background: 'transparent',
                        transition: 'background 0.15s ease',
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--surface2)')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                    >
                      <td style={{ padding: '8px 10px' }}>
                        <div style={{ fontWeight: 600, color: 'var(--ink)' }}>{row.student_name}</div>
                        <div style={{ fontSize: '11px', color: 'var(--muted)' }}>{row.email}</div>
                      </td>
                      <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>
                        <div style={{ color: 'var(--ink)' }}>{row.batch}</div>
                        <div style={{ fontSize: '10px', color: 'var(--muted)' }}>{row.semester}</div>
                      </td>
                      <td style={{ padding: '8px 10px', maxWidth: '200px' }}>
                        <div style={{ color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={row.subject_name}>
                          {row.subject_name}
                        </div>
                      </td>
                      <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>
                        <span style={{ fontWeight: 500, color: 'var(--ink)' }}>{row.exam_type}</span>
                        {row.exam_count && row.exam_count !== row.exam_type && (
                          <div style={{ fontSize: '10px', color: 'var(--muted)' }}>{row.exam_count}</div>
                        )}
                      </td>
                      <td style={{ padding: '8px 10px', whiteSpace: 'nowrap', color: 'var(--secondary)' }}>
                        {row.exam_date}
                      </td>
                      <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>
                        <div style={{ fontWeight: 700, color: 'var(--ink)' }}>
                          {row.marks_scored} / {row.maximum_marks}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--muted)' }}>{row.score_pct}%</div>
                      </td>
                      <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>
                        <Badge value={row.tier} />
                      </td>
                      <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                        {row.feedback_summary && row.feedback_summary !== 'null' ? (
                          <button
                            onClick={() => setSelectedRecord(row)}
                            style={{
                              background: 'var(--surface2)',
                              border: '1px solid var(--line)',
                              color: 'var(--accent)',
                              borderRadius: '4px',
                              padding: '3px 8px',
                              fontSize: '11px',
                              fontWeight: 500,
                              cursor: 'pointer',
                            }}
                          >
                            View
                          </button>
                        ) : (
                          <span style={{ color: 'var(--muted)', fontSize: '11px' }}>—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* Pagination controls */}
              {pagination && pagination.total_pages > 1 && (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '12px 10px 0',
                    fontSize: '12px',
                    color: 'var(--secondary)',
                  }}
                >
                  <div>
                    Showing page {pagination.page} of {pagination.total_pages} ({(pagination.total || 0).toLocaleString()} total records)
                  </div>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <button
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page <= 1}
                      style={{
                        padding: '4px 8px',
                        background: 'var(--surface)',
                        border: '1px solid var(--line)',
                        borderRadius: '4px',
                        cursor: page <= 1 ? 'not-allowed' : 'pointer',
                        opacity: page <= 1 ? 0.5 : 1,
                      }}
                    >
                      <ChevronLeft size={14} />
                    </button>
                    <button
                      onClick={() => setPage((p) => Math.min(pagination.total_pages, p + 1))}
                      disabled={page >= pagination.total_pages}
                      style={{
                        padding: '4px 8px',
                        background: 'var(--surface)',
                        border: '1px solid var(--line)',
                        borderRadius: '4px',
                        cursor: page >= pagination.total_pages ? 'not-allowed' : 'pointer',
                        opacity: page >= pagination.total_pages ? 0.5 : 1,
                      }}
                    >
                      <ChevronRight size={14} />
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </Card>
      )}

      {/* 7. Feedback Dialog Modal */}
      {selectedRecord && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.5)',
            zIndex: 1000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
          }}
          onClick={() => setSelectedRecord(null)}
        >
          <div
            style={{
              background: 'var(--surface)',
              border: '1px solid var(--line)',
              borderRadius: '8px',
              padding: '24px',
              maxWidth: '540px',
              width: '100%',
              boxShadow: '0 12px 32px rgba(0,0,0,0.2)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '14px' }}>
              <div>
                <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 600, color: 'var(--ink)' }}>
                  Mentor Assessment Feedback
                </h3>
                <p style={{ margin: '3px 0 0', fontSize: '12px', color: 'var(--secondary)' }}>
                  {selectedRecord.student_name} · {selectedRecord.subject_name}
                </p>
              </div>
              <button
                onClick={() => setSelectedRecord(null)}
                style={{ background: 'none', border: 'none', color: 'var(--secondary)', cursor: 'pointer', padding: '4px' }}
              >
                <X size={16} />
              </button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '16px', fontSize: '12px' }}>
              <div style={{ background: 'var(--surface2)', padding: '8px 12px', borderRadius: '6px' }}>
                <span style={{ color: 'var(--muted)' }}>Score: </span>
                <strong style={{ color: 'var(--ink)' }}>
                  {selectedRecord.marks_scored} / {selectedRecord.maximum_marks} ({selectedRecord.score_pct}%)
                </strong>
              </div>
              <div style={{ background: 'var(--surface2)', padding: '8px 12px', borderRadius: '6px' }}>
                <span style={{ color: 'var(--muted)' }}>Tier: </span>
                <strong style={{ color: 'var(--accent)' }}>{selectedRecord.tier}</strong>
              </div>
            </div>

            <div style={{ fontSize: '12px', color: 'var(--secondary)', marginBottom: '8px', fontWeight: 600 }}>
              Feedback Notes:
            </div>
            <div
              style={{
                background: 'var(--surface2)',
                border: '1px solid var(--line)',
                borderRadius: '6px',
                padding: '12px',
                fontSize: '12px',
                lineHeight: 1.6,
                color: 'var(--ink)',
                whiteSpace: 'pre-wrap',
                maxHeight: '220px',
                overflowY: 'auto',
              }}
            >
              {selectedRecord.feedback_summary || 'No detailed feedback provided.'}
            </div>

            <div style={{ marginTop: '16px', textAlign: 'right' }}>
              <button
                onClick={() => setSelectedRecord(null)}
                style={{
                  padding: '6px 14px',
                  background: 'var(--accent)',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '6px',
                  fontSize: '12px',
                  fontWeight: 500,
                  cursor: 'pointer',
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
