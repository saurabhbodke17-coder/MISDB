import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { 
  ChevronLeft, ChevronRight, 
  Clock, User, BookOpen, 
  Sparkles, Search, GraduationCap
} from 'lucide-react';
import { api, display, istToday, queryString } from './api';
import type { Filters, Row } from './api';
import { Card, Empty, ErrorState, Loading } from './components';

export type CalendarEvent = {
  id: string;
  title: string;
  start: string;
  end: string;
  source: string;
  category: string;
  batch?: string | null;
  semester?: string | null;
  subject?: string | null;
  mentor?: string | null;
  status?: string | null;
};

// Hardcoded exclusions per requirement
const EXCLUDED_EVENTS = [
  'claude campus ambassador program',
  'great indian ai internship challenge',
];

interface SemesterTheme {
  name: string;
  primary: string;
  bgTint: string;
  border: string;
  text: string;
  badgeBg: string;
}

const SEMESTER_THEMES: Record<string, SemesterTheme> = {
  'Semester 1': {
    name: 'Semester 1',
    primary: '#3b82f6',
    bgTint: 'rgba(59, 130, 246, 0.15)',
    border: 'rgba(59, 130, 246, 0.45)',
    text: '#93c5fd',
    badgeBg: '#1e40af',
  },
  'Semester 2': {
    name: 'Semester 2',
    primary: '#06b6d4',
    bgTint: 'rgba(6, 182, 212, 0.15)',
    border: 'rgba(6, 182, 212, 0.45)',
    text: '#67e8f9',
    badgeBg: '#155e75',
  },
  'Semester 3': {
    name: 'Semester 3',
    primary: '#10b981',
    bgTint: 'rgba(16, 185, 129, 0.15)',
    border: 'rgba(16, 185, 129, 0.45)',
    text: '#6ee7b7',
    badgeBg: '#065f46',
  },
  'Semester 4': {
    name: 'Semester 4',
    primary: '#f59e0b',
    bgTint: 'rgba(245, 158, 11, 0.15)',
    border: 'rgba(245, 158, 11, 0.45)',
    text: '#fcd34d',
    badgeBg: '#92400e',
  },
  'Semester 5': {
    name: 'Semester 5',
    primary: '#a855f7',
    bgTint: 'rgba(168, 85, 247, 0.15)',
    border: 'rgba(168, 85, 247, 0.45)',
    text: '#d8b4fe',
    badgeBg: '#6b21a8',
  },
  'Semester 6': {
    name: 'Semester 6',
    primary: '#ec4899',
    bgTint: 'rgba(236, 72, 153, 0.15)',
    border: 'rgba(236, 72, 153, 0.45)',
    text: '#f472b6',
    badgeBg: '#9d174d',
  },
  'Semester 7': {
    name: 'Semester 7',
    primary: '#f97316',
    bgTint: 'rgba(249, 115, 22, 0.15)',
    border: 'rgba(249, 115, 22, 0.45)',
    text: '#fdba74',
    badgeBg: '#9a3412',
  },
  'Semester 8': {
    name: 'Semester 8',
    primary: '#14b8a6',
    bgTint: 'rgba(20, 184, 166, 0.15)',
    border: 'rgba(20, 184, 166, 0.45)',
    text: '#5eead4',
    badgeBg: '#115e59',
  },
};

const DEFAULT_SEMESTER_THEME: SemesterTheme = {
  name: 'Institution-Wide',
  primary: '#64748b',
  bgTint: 'rgba(100, 116, 139, 0.15)',
  border: 'rgba(100, 116, 139, 0.45)',
  text: '#cbd5e1',
  badgeBg: '#334155',
};

function getSemesterTheme(sem: string): SemesterTheme {
  return SEMESTER_THEMES[sem] || DEFAULT_SEMESTER_THEME;
}

function resolveSemester(e: CalendarEvent): string {
  if (e.semester && e.semester.trim()) return e.semester.trim();
  const b = (e.batch || e.title || '').toLowerCase();
  if (b.includes('sem 1') || b.includes('semester 1') || b.includes('applied ai')) return 'Semester 1';
  if (b.includes('sem 2') || b.includes('semester 2')) return 'Semester 2';
  if (b.includes('sem 3') || b.includes('semester 3')) return 'Semester 3';
  if (b.includes('sem 4') || b.includes('semester 4')) return 'Semester 4';
  if (b.includes('sem 5') || b.includes('semester 5')) return 'Semester 5';
  if (b.includes('sem 6') || b.includes('semester 6')) return 'Semester 6';
  if (b.includes('sem 7') || b.includes('semester 7')) return 'Semester 7';
  if (b.includes('sem 8') || b.includes('semester 8')) return 'Semester 8';
  return 'Institution-Wide / General';
}

function resolveBatch(e: CalendarEvent): string {
  if (e.batch && e.batch.trim()) return e.batch.trim();
  return 'Main Section';
}

function getIstDate(isoStr: string): string {
  if (!isoStr) return '';
  if (!isoStr.includes('T')) return isoStr.slice(0, 10);
  const d = new Date(isoStr.endsWith('Z') || isoStr.includes('+') ? isoStr : `${isoStr}Z`);
  return d.toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' }); // YYYY-MM-DD
}

function getIstTime(isoStr: string): string {
  if (!isoStr || !isoStr.includes('T')) return '';
  const d = new Date(isoStr.endsWith('Z') || isoStr.includes('+') ? isoStr : `${isoStr}Z`);
  return d.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZone: 'Asia/Kolkata',
  });
}

function getIstMinutes(isoStr: string): number | null {
  if (!isoStr || !isoStr.includes('T')) return null;
  const d = new Date(isoStr.endsWith('Z') || isoStr.includes('+') ? isoStr : `${isoStr}Z`);
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Kolkata',
    hour: 'numeric',
    minute: 'numeric',
    hour12: false,
  });
  const parts = formatter.formatToParts(d);
  let hour = parseInt(parts.find(p => p.type === 'hour')?.value ?? '0', 10);
  if (hour === 24) hour = 0;
  const minute = parseInt(parts.find(p => p.type === 'minute')?.value ?? '0', 10);
  return hour * 60 + minute;
}

function getSubjectColor(subjectOrTitle: string, defaultPrimary: string): string {
  const s = (subjectOrTitle || '').toLowerCase();
  if (s.includes('math') || s.includes('m&m') || s.includes('ai/ml')) return '#8b5cf6'; // Purple
  if (s.includes('frontend') || s.includes('web') || s.includes('fsd')) return '#0ea5e9'; // Cyan
  if (s.includes('programming') || s.includes('dsa') || s.includes('python') || s.includes('go')) return '#10b981'; // Green
  if (s.includes('operating') || s.includes('system') || s.includes('security')) return '#ec4899'; // Pink/Rose
  if (s.includes('data science') || s.includes('vision') || s.includes('multimodal')) return '#6366f1'; // Indigo
  if (s.includes('eval') || s.includes('test') || s.includes('exam')) return '#f43f5e'; // Coral
  if (s.includes('open source') || s.includes('guest') || s.includes('workshop')) return '#f59e0b'; // Amber
  return defaultPrimary;
}

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

function inDay(e: CalendarEvent, d: string): boolean {
  const startDay = getIstDate(e.start);
  const endDay = getIstDate(e.end);
  return startDay <= d && endDay >= d;
}

export function CalendarBoard({ filters, onOpen }: { filters: Filters; onOpen: (s: string, r: Row) => void }) {
  const today = istToday();
  const [month, setMonth] = useState(() => new Date(`${today.slice(0, 7)}-01T00:00:00`));
  const [day, setDay] = useState(today);
  const [selectedSemester, setSelectedSemester] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');

  const first = iso(month);
  const last = iso(new Date(month.getFullYear(), month.getMonth() + 1, 0));

  const result = useQuery({
    queryKey: ['calendar', filters, first],
    queryFn: () =>
      api<{ events: CalendarEvent[]; truncated: boolean; note: string }>(
        `/calendar?${queryString({ ...filters, from_date: first, to_date: last })}`
      ),
  });

  // Filter out excluded events
  const allEvents = useMemo(() => {
    const raw = result.data?.events ?? [];
    return raw.filter(e => {
      const t = (e.title || '').toLowerCase();
      return !EXCLUDED_EVENTS.some(ex => t.includes(ex));
    });
  }, [result.data]);

  // Calendar month days calculation
  const offset = (month.getDay() + 6) % 7;
  const length = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const days = Array.from({ length: Math.ceil((offset + length) / 7) * 7 }, (_, i) => i - offset + 1);

  // Day events
  const dayEvents = useMemo(() => {
    return allEvents.filter(e => inDay(e, day));
  }, [allEvents, day]);

  // Specific event categories on the selected day
  const dayClasses = useMemo(() => {
    return dayEvents.filter(e => e.source === 'sessions');
  }, [dayEvents]);

  const dayExams = useMemo(() => {
    return dayEvents.filter(e => e.source === 'examinations');
  }, [dayEvents]);

  const dayHolidays = useMemo(() => {
    return dayEvents.filter(e => e.source === 'holidays');
  }, [dayEvents]);

  const dayAcademicEvents = useMemo(() => {
    return dayEvents.filter(e => e.source === 'calendar');
  }, [dayEvents]);

  const dayOtherEvents = useMemo(() => {
    return dayEvents.filter(e => !['sessions', 'examinations', 'holidays', 'calendar'].includes(e.source));
  }, [dayEvents]);

  // Filter classes by user search & semester filter
  const filteredClasses = useMemo(() => {
    return dayClasses.filter(c => {
      const sem = resolveSemester(c);
      if (selectedSemester !== 'all' && sem !== selectedSemester) return false;
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesSubject = (c.subject || c.title || '').toLowerCase().includes(q);
        const matchesMentor = (c.mentor || '').toLowerCase().includes(q);
        const matchesBatch = (c.batch || '').toLowerCase().includes(q);
        if (!matchesSubject && !matchesMentor && !matchesBatch) return false;
      }
      return true;
    });
  }, [dayClasses, selectedSemester, searchQuery]);

  // Group classes semester-wise and then batch-wise with natural sorting
  const semesterMap = useMemo(() => {
    const semOrder = (s: string) => {
      const match = s.match(/\d+/);
      return match ? parseInt(match[0], 10) : 999;
    };

    const sortedClasses = [...filteredClasses].sort((a, b) => {
      const semA = resolveSemester(a);
      const semB = resolveSemester(b);
      const diffSem = semOrder(semA) - semOrder(semB);
      if (diffSem !== 0) return diffSem;

      const batchA = resolveBatch(a);
      const batchB = resolveBatch(b);
      const diffBatch = batchA.localeCompare(batchB);
      if (diffBatch !== 0) return diffBatch;

      return (getIstMinutes(a.start) ?? 0) - (getIstMinutes(b.start) ?? 0);
    });

    const map = new Map<string, Map<string, CalendarEvent[]>>();
    for (const c of sortedClasses) {
      const sem = resolveSemester(c);
      const batch = resolveBatch(c);
      if (!map.has(sem)) map.set(sem, new Map());
      const batchMap = map.get(sem)!;
      if (!batchMap.has(batch)) batchMap.set(batch, []);
      batchMap.get(batch)!.push(c);
    }
    return map;
  }, [filteredClasses]);

  // Available semesters list for filters sorted naturally
  const availableSemesters = useMemo(() => {
    const semSet = new Set<string>();
    for (const c of dayClasses) {
      semSet.add(resolveSemester(c));
    }
    const semOrder = (s: string) => {
      const match = s.match(/\d+/);
      return match ? parseInt(match[0], 10) : 999;
    };
    return Array.from(semSet).sort((a, b) => semOrder(a) - semOrder(b));
  }, [dayClasses]);

  // Formatted date string for banner
  const dateHeading = useMemo(() => {
    if (!day) return '';
    const d = new Date(`${day.slice(0, 10)}T00:00:00`);
    return d.toLocaleDateString('en-IN', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    });
  }, [day]);

  return (
    <Card
      title="Academic Calendar & Schedule"
      subtitle="Timetable grid of semester-wise and batch-wise class schedules, timings, and institutional events."
      action={
        <div className="acad-nav-controls">
          <div className="calendar-nav">
            <button
              className="icon-button"
              aria-label="Previous month"
              onClick={() => setMonth(d => new Date(d.getFullYear(), d.getMonth() - 1, 1))}
            >
              <ChevronLeft size={16} />
            </button>
            <strong style={{ fontSize: 13, minWidth: 120, textAlign: 'center' }}>
              {month.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}
            </strong>
            <button
              className="icon-button"
              aria-label="Next month"
              onClick={() => setMonth(d => new Date(d.getFullYear(), d.getMonth() + 1, 1))}
            >
              <ChevronRight size={16} />
            </button>
            <button
              type="button"
              className="today-nav-button"
              onClick={() => {
                const now = istToday();
                setMonth(new Date(`${now.slice(0, 7)}-01T00:00:00`));
                setDay(now);
              }}
            >
              Today
            </button>
          </div>
        </div>
      }
    >
      {result.isPending ? (
        <Loading />
      ) : result.error ? (
        <ErrorState error={result.error} />
      ) : (
        <>
          {/* Month Calendar Grid */}
          <div className="calendar-grid">
            {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(w => (
              <div className="calendar-weekday" key={w}>
                {w}
              </div>
            ))}
            {days.map((n, i) => {
              if (n < 1 || n > length) return <div key={i} className="calendar-blank" />;
              const date = `${first.slice(0, 7)}-${String(n).padStart(2, '0')}`;
              const events = allEvents.filter(e => inDay(e, date));
              const classCount = events.filter(e => e.source === 'sessions').length;
              const hasHoliday = events.some(e => e.source === 'holidays');
              const hasExam = events.some(e => e.source === 'examinations');
              const hasEvent = events.some(e => e.source === 'calendar');

              return (
                <button
                  key={i}
                  className={`calendar-cell ${date === day ? 'selected' : ''} ${date === today ? 'is-today' : ''}`}
                  onClick={() => setDay(date)}
                  aria-label={`${display(date)}: ${events.length} events`}
                >
                  <strong className="day-number">
                    <span>{n}</span>
                    {date === today && <span className="today-badge">Today</span>}
                  </strong>

                  <div className="acad-cell-indicators">
                    {classCount > 0 && (
                      <span className="acad-cell-pill class" title={`${classCount} scheduled classes`}>
                        <span className="acad-dot blue" /> {classCount} {classCount === 1 ? 'class' : 'classes'}
                      </span>
                    )}
                    {hasHoliday && (
                      <span className="acad-cell-pill holiday" title="Holiday">
                        <span className="acad-dot green" /> Holiday
                      </span>
                    )}
                    {hasExam && (
                      <span className="acad-cell-pill exam" title="Examination">
                        <span className="acad-dot purple" /> Exam
                      </span>
                    )}
                    {hasEvent && (
                      <span className="acad-cell-pill event" title="Academic Event">
                        <span className="acad-dot orange" /> Event
                      </span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Date-Wise Schedule Section */}
          <div className="acad-schedule-panel">
            {/* Schedule Header & Filter Toolbar */}
            <div className="acad-schedule-header">
              <div className="acad-schedule-title-area">
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <h3 className="acad-schedule-date">{dateHeading}</h3>
                  {day === today && <span className="acad-badge-today">Today</span>}
                </div>
                <div className="acad-schedule-metrics">
                  <span className="acad-metric-item">
                    <BookOpen size={13} style={{ color: '#38bdf8' }} />
                    <strong>{dayClasses.length}</strong> classes scheduled
                  </span>
                  <span className="acad-metric-item">
                    <GraduationCap size={13} style={{ color: '#a78bfa' }} />
                    <strong>{availableSemesters.length}</strong> semesters active
                  </span>
                  {dayHolidays.length > 0 && (
                    <span className="acad-metric-item holiday">
                      <Sparkles size={13} style={{ color: '#34d399' }} />
                      <strong>{dayHolidays[0].title}</strong>
                    </span>
                  )}
                </div>
              </div>

              {/* Filter Chips & Search */}
              <div className="acad-toolbar-filters">
                <div className="acad-semester-chips">
                  <button
                    type="button"
                    className={`acad-sem-chip ${selectedSemester === 'all' ? 'active' : ''}`}
                    onClick={() => setSelectedSemester('all')}
                  >
                    All Semesters ({dayClasses.length})
                  </button>
                  {availableSemesters.map(sem => {
                    const theme = getSemesterTheme(sem);
                    const count = dayClasses.filter(c => resolveSemester(c) === sem).length;
                    return (
                      <button
                        key={sem}
                        type="button"
                        className={`acad-sem-chip ${selectedSemester === sem ? 'active' : ''}`}
                        onClick={() => setSelectedSemester(sem)}
                        style={
                          selectedSemester === sem
                            ? { background: theme.badgeBg, color: '#fff', borderColor: theme.primary }
                            : { borderColor: theme.border }
                        }
                      >
                        <span
                          style={{
                            display: 'inline-block',
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            background: theme.primary,
                            marginRight: 6,
                          }}
                        />
                        {sem} ({count})
                      </button>
                    );
                  })}
                </div>

                <div className="acad-search-box">
                  <Search size={13} style={{ color: 'var(--muted)' }} />
                  <input
                    type="text"
                    placeholder="Search subject, mentor, batch..."
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    className="acad-search-input"
                  />
                  {searchQuery && (
                    <button type="button" onClick={() => setSearchQuery('')} className="acad-clear-btn">
                      ×
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* Non-class Events Banner (Holidays, Examinations, Deadlines) */}
            {(dayHolidays.length > 0 || dayExams.length > 0 || dayAcademicEvents.length > 0 || dayOtherEvents.length > 0) && (
              <div className="acad-notices-bar">
                {dayHolidays.map(h => (
                  <div key={h.id} className="acad-notice-card holiday" onClick={() => onOpen(h.source, { id: h.id, title: h.title })}>
                    <span className="notice-badge">Holiday</span>
                    <strong>{h.title}</strong>
                    <span>{h.start.slice(0, 10) === h.end.slice(0, 10) ? 'Full day holiday' : `${display(h.start)} – ${display(h.end)}`}</span>
                  </div>
                ))}
                {dayExams.map(ex => (
                  <div key={ex.id} className="acad-notice-card exam" onClick={() => onOpen(ex.source, { id: ex.id, title: ex.title })}>
                    <span className="notice-badge">Examination</span>
                    <strong>{ex.title}</strong>
                    <span>{resolveSemester(ex)} · {resolveBatch(ex)}</span>
                  </div>
                ))}
                {dayAcademicEvents.map(ae => (
                  <div key={ae.id} className="acad-notice-card event" onClick={() => onOpen(ae.source, { id: ae.id, title: ae.title })}>
                    <span className="notice-badge">Academic Event</span>
                    <strong>{ae.title}</strong>
                    <span>{display(ae.start)}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Schedule Body */}
            {filteredClasses.length === 0 ? (
              <Empty
                title="No classes scheduled for this date"
                message={
                  searchQuery || selectedSemester !== 'all'
                    ? 'No scheduled classes match the selected filter.'
                    : 'No classes are scheduled on this date (weekend or non-instructional day).'
                }
              />
            ) : (
              /* ================= TIMETABLE GRID VIEW ================= */
              <div className="acad-timetable-wrapper">
                <div className="acad-timetable-scroll">
                  {Array.from(semesterMap.entries()).flatMap(([semesterName, batchMap]) => {
                    const theme = getSemesterTheme(semesterName);
                    return Array.from(batchMap.entries()).map(([batchName, items]) => {
                      // Sort items chronologically
                      const sorted = [...items].sort((a, b) => (getIstMinutes(a.start) ?? 0) - (getIstMinutes(b.start) ?? 0));

                      return (
                        <div key={`${semesterName}-${batchName}`} className="acad-timetable-col" style={{ borderColor: theme.border }}>
                          {/* Column Header */}
                          <div className="acad-tt-header" style={{ background: theme.bgTint, borderBottomColor: theme.border }}>
                            <span className="acad-tt-sem" style={{ background: theme.badgeBg, color: '#fff' }}>
                              {semesterName}
                            </span>
                            <strong className="acad-tt-batch">{batchName}</strong>
                            <span className="acad-tt-count">{sorted.length} {sorted.length === 1 ? 'class' : 'classes'}</span>
                          </div>

                          {/* Sessions in Column */}
                          <div className="acad-tt-body">
                            {sorted.map(s => {
                              const sTime = getIstTime(s.start);
                              const eTime = getIstTime(s.end);
                              const subjectColor = getSubjectColor(s.subject || s.title, theme.primary);

                              return (
                                <button
                                  key={s.id}
                                  type="button"
                                  className={`acad-tt-card status-${s.status || 'scheduled'}`}
                                  style={{ borderLeftColor: subjectColor }}
                                  onClick={() => onOpen(s.source, { id: s.id, title: s.title, batch: s.batch, subject: s.subject })}
                                >
                                  <div className="acad-tt-time">
                                    <Clock size={11} style={{ color: subjectColor }} />
                                    <span>{sTime} – {eTime}</span>
                                  </div>
                                  <div className="acad-tt-title">{s.subject || s.title}</div>
                                  {s.mentor && (
                                    <div className="acad-tt-mentor">
                                      <User size={11} />
                                      <span>{s.mentor}</span>
                                    </div>
                                  )}
                                  <div className="acad-tt-footer">
                                    <span className={`acad-status-tag status-${s.status || 'scheduled'}`}>
                                      {s.status || 'Scheduled'}
                                    </span>
                                  </div>
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      );
                    });
                  })}
                </div>
              </div>
            )}
          </div>

          {result.data?.truncated && (
            <p className="source-note" style={{ marginTop: 14 }}>
              This month contains more than 1,000 entries across sources. Narrow the academic filters if needed.
            </p>
          )}
        </>
      )}
    </Card>
  );
}
