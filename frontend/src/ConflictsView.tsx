import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  Users,
  GraduationCap,
  Building2,
  Calendar,
  Clock,
  Search,
  Download,
  CheckCircle2,
  ExternalLink,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { api, queryString } from './api';
import type { Filters, Row } from './api';
import { Card, Loading, ErrorState } from './components';

export interface ConflictSession {
  id: string;
  title: string;
  faculty?: string;
  room?: string;
  batches?: string;
  start: string;
  end: string;
}

export interface ConflictRecord {
  id: string;
  conflict_type: 'batch' | 'faculty' | 'room';
  target_name: string;
  target_subtext: string;
  batch_name?: string;
  semester_name?: string;
  faculty_name?: string;
  room_number?: string;
  overlap_start: string;
  overlap_end: string;
  overlap_minutes: number;
  conflict_reason: string;
  session_1: ConflictSession;
  session_2: ConflictSession;
}

export interface ConflictsApiResponse {
  summary: {
    total: number;
    batch_conflicts: number;
    faculty_conflicts: number;
    room_conflicts: number;
    affected_batches: number;
    affected_faculties: number;
    affected_rooms: number;
  };
  batch_conflicts: ConflictRecord[];
  faculty_conflicts: ConflictRecord[];
  room_conflicts: ConflictRecord[];
}

function parseIstDate(isoStr: string): Date {
  return new Date(isoStr.endsWith('Z') || isoStr.includes('+') ? isoStr : `${isoStr}Z`);
}

function formatIstDate(isoStr: string): string {
  if (!isoStr) return '—';
  const d = parseIstDate(isoStr);
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata',
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(d);
}

function formatIstTime(isoStr: string): string {
  if (!isoStr) return '—';
  const d = parseIstDate(isoStr);
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).format(d);
}

function getDateKey(isoStr: string): string {
  if (!isoStr) return 'Unknown Date';
  const d = parseIstDate(isoStr);
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(d);
}

interface ConflictsViewProps {
  filters: Filters;
  onOpen?: (source: string, row: Row) => void;
  setToast?: (msg: string) => void;
}

export function ConflictsView({ filters, onOpen, setToast }: ConflictsViewProps) {
  const [activeTab, setActiveTab] = useState<'all' | 'batch' | 'faculty' | 'room'>('all');
  const [search, setSearch] = useState('');
  const [severityFilter, setSeverityFilter] = useState<'all' | 'high' | 'medium' | 'minor'>('all');
  const [includeAllDates, setIncludeAllDates] = useState(false);
  const [collapsedDates, setCollapsedDates] = useState<Record<string, boolean>>({});

  const conflictsQuery = useQuery({
    queryKey: ['conflicts', filters, includeAllDates],
    queryFn: () => {
      const q = queryString({
        ...filters,
        include_all: includeAllDates ? 'true' : undefined,
      });
      return api<ConflictsApiResponse>(`/calendar/conflicts${q ? `?${q}` : ''}`);
    },
  });

  const allRecords = useMemo(() => {
    if (!conflictsQuery.data) return [];
    const b = conflictsQuery.data.batch_conflicts || [];
    const f = conflictsQuery.data.faculty_conflicts || [];
    const r = conflictsQuery.data.room_conflicts || [];
    return [...b, ...f, ...r].sort((x, y) => {
      const dx = new Date(x.overlap_start).getTime();
      const dy = new Date(y.overlap_start).getTime();
      return dy - dx;
    });
  }, [conflictsQuery.data]);

  const filteredRecords = useMemo(() => {
    let list = allRecords;

    if (activeTab === 'batch') {
      list = list.filter((r) => r.conflict_type === 'batch');
    } else if (activeTab === 'faculty') {
      list = list.filter((r) => r.conflict_type === 'faculty');
    } else if (activeTab === 'room') {
      list = list.filter((r) => r.conflict_type === 'room');
    }

    if (severityFilter === 'high') {
      list = list.filter((r) => r.overlap_minutes >= 60);
    } else if (severityFilter === 'medium') {
      list = list.filter((r) => r.overlap_minutes >= 30 && r.overlap_minutes < 60);
    } else if (severityFilter === 'minor') {
      list = list.filter((r) => r.overlap_minutes < 30);
    }

    if (search.trim()) {
      const s = search.toLowerCase();
      list = list.filter((r) => {
        return (
          r.target_name.toLowerCase().includes(s) ||
          r.conflict_reason.toLowerCase().includes(s) ||
          r.session_1.title.toLowerCase().includes(s) ||
          r.session_2.title.toLowerCase().includes(s) ||
          (r.session_1.faculty || '').toLowerCase().includes(s) ||
          (r.session_2.faculty || '').toLowerCase().includes(s) ||
          (r.session_1.room || '').toLowerCase().includes(s) ||
          (r.session_2.room || '').toLowerCase().includes(s) ||
          (r.session_1.batches || '').toLowerCase().includes(s) ||
          (r.session_2.batches || '').toLowerCase().includes(s)
        );
      });
    }

    return list;
  }, [allRecords, activeTab, severityFilter, search]);

  const groupedByDate = useMemo(() => {
    const groups: { dateKey: string; displayDate: string; records: ConflictRecord[] }[] = [];
    const map = new Map<string, ConflictRecord[]>();

    for (const r of filteredRecords) {
      const key = getDateKey(r.overlap_start);
      if (!map.has(key)) {
        map.set(key, []);
      }
      map.get(key)!.push(r);
    }

    for (const [key, records] of map.entries()) {
      groups.push({
        dateKey: key,
        displayDate: formatIstDate(records[0].overlap_start),
        records,
      });
    }

    return groups;
  }, [filteredRecords]);

  const toggleDateCollapse = (dateKey: string) => {
    setCollapsedDates((prev) => ({
      ...prev,
      [dateKey]: !prev[dateKey],
    }));
  };

  const handleExportCsv = () => {
    if (!filteredRecords.length) {
      if (setToast) setToast('No records to export');
      return;
    }
    const headers = [
      'Conflict Type',
      'Target Entity',
      'Date (IST)',
      'Overlap Start (IST)',
      'Overlap End (IST)',
      'Overlap Duration (Mins)',
      'Conflict Details',
      'Session 1 Title',
      'Session 1 Faculty',
      'Session 1 Room',
      'Session 1 Batches',
      'Session 2 Title',
      'Session 2 Faculty',
      'Session 2 Room',
      'Session 2 Batches',
    ];

    const rows = filteredRecords.map((r) => [
      r.conflict_type.toUpperCase(),
      `"${r.target_name.replace(/"/g, '""')}"`,
      `"${formatIstDate(r.overlap_start)}"`,
      `"${formatIstTime(r.overlap_start)}"`,
      `"${formatIstTime(r.overlap_end)}"`,
      r.overlap_minutes,
      `"${r.conflict_reason.replace(/"/g, '""')}"`,
      `"${r.session_1.title.replace(/"/g, '""')}"`,
      `"${(r.session_1.faculty || '').replace(/"/g, '""')}"`,
      `"${(r.session_1.room || '').replace(/"/g, '""')}"`,
      `"${(r.session_1.batches || '').replace(/"/g, '""')}"`,
      `"${r.session_2.title.replace(/"/g, '""')}"`,
      `"${(r.session_2.faculty || '').replace(/"/g, '""')}"`,
      `"${(r.session_2.room || '').replace(/"/g, '""')}"`,
      `"${(r.session_2.batches || '').replace(/"/g, '""')}"`,
    ]);

    const csvContent = [headers.join(','), ...rows.map((row) => row.join(','))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', `polaris_scheduling_conflicts_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    if (setToast) setToast('Exported scheduling conflicts to CSV.');
  };

  const summary = conflictsQuery.data?.summary || {
    total: 0,
    batch_conflicts: 0,
    faculty_conflicts: 0,
    room_conflicts: 0,
    affected_batches: 0,
    affected_faculties: 0,
    affected_rooms: 0,
  };

  return (
    <div className="conflicts-view" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Top Header Card */}
      <div
        className="conflicts-header-card"
        style={{
          background: 'var(--surface)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '18px 22px',
          display: 'flex',
          flexDirection: 'column',
          gap: '16px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <h2 style={{ fontSize: '18px', fontWeight: 600, margin: 0, color: 'var(--ink)' }}>
                Scheduling Conflict Metrics
              </h2>
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  padding: '3px 8px',
                  borderRadius: '12px',
                  background: summary.total > 0 ? '#40191a' : '#123a2d',
                  color: summary.total > 0 ? '#f06a63' : '#3dc088',
                  border: `1px solid ${summary.total > 0 ? '#73302d' : '#195040'}`,
                }}
              >
                {summary.total} {summary.total === 1 ? 'Conflict' : 'Conflicts'} Detected
              </span>
            </div>
            <p style={{ margin: '4px 0 0', fontSize: '12px', color: 'var(--muted)' }}>
              Accurate detection of batch timetable overlaps, mentor double-bookings, and classroom collisions in Indian Standard Time (IST).
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <label
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: '11px',
                color: 'var(--secondary)',
                cursor: 'pointer',
                background: 'var(--surface2)',
                padding: '6px 10px',
                borderRadius: '5px',
                border: '1px solid var(--line)',
              }}
            >
              <input
                type="checkbox"
                checked={includeAllDates}
                onChange={(e) => setIncludeAllDates(e.target.checked)}
                style={{ cursor: 'pointer' }}
              />
              <span>View all dates (ignore date picker)</span>
            </label>

            <button
              type="button"
              className="button"
              onClick={handleExportCsv}
              disabled={filteredRecords.length === 0}
              style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '11px', padding: '6px 12px' }}
            >
              <Download size={13} />
              <span>Export CSV</span>
            </button>
          </div>
        </div>

        {/* 4 Summary KPI Cards */}
        <div
          className="conflicts-kpi-grid"
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '12px',
          }}
        >
          {/* Card 1: Total */}
          <div
            onClick={() => setActiveTab('all')}
            style={{
              cursor: 'pointer',
              background: activeTab === 'all' ? 'var(--surface2)' : 'var(--bg)',
              border: `1px solid ${activeTab === 'all' ? 'var(--accent)' : 'var(--line)'}`,
              borderRadius: '6px',
              padding: '12px 14px',
              transition: 'all 0.15s ease',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--muted)' }}>TOTAL CONFLICTS</span>
              <AlertTriangle size={15} style={{ color: summary.total > 0 ? '#f06a63' : '#3dc088' }} />
            </div>
            <div style={{ fontSize: '24px', fontWeight: 700, margin: '6px 0 2px', color: 'var(--ink)' }}>
              {summary.total}
            </div>
            <div style={{ fontSize: '10px', color: 'var(--secondary)' }}>
              Across {summary.affected_batches} batches · {summary.affected_faculties} mentors · {summary.affected_rooms} rooms
            </div>
          </div>

          {/* Card 2: Batch Conflicts */}
          <div
            onClick={() => setActiveTab('batch')}
            style={{
              cursor: 'pointer',
              background: activeTab === 'batch' ? 'var(--surface2)' : 'var(--bg)',
              border: `1px solid ${activeTab === 'batch' ? '#6b94ff' : 'var(--line)'}`,
              borderRadius: '6px',
              padding: '12px 14px',
              transition: 'all 0.15s ease',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '11px', fontWeight: 600, color: '#6b94ff' }}>BATCH OVERLAPS</span>
              <Users size={15} style={{ color: '#6b94ff' }} />
            </div>
            <div style={{ fontSize: '24px', fontWeight: 700, margin: '6px 0 2px', color: 'var(--ink)' }}>
              {summary.batch_conflicts}
            </div>
            <div style={{ fontSize: '10px', color: 'var(--secondary)' }}>
              {summary.affected_batches} student sections double-booked
            </div>
          </div>

          {/* Card 3: Faculty Conflicts */}
          <div
            onClick={() => setActiveTab('faculty')}
            style={{
              cursor: 'pointer',
              background: activeTab === 'faculty' ? 'var(--surface2)' : 'var(--bg)',
              border: `1px solid ${activeTab === 'faculty' ? '#e5a53b' : 'var(--line)'}`,
              borderRadius: '6px',
              padding: '12px 14px',
              transition: 'all 0.15s ease',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '11px', fontWeight: 600, color: '#e5a53b' }}>FACULTY CONFLICTS</span>
              <GraduationCap size={15} style={{ color: '#e5a53b' }} />
            </div>
            <div style={{ fontSize: '24px', fontWeight: 700, margin: '6px 0 2px', color: 'var(--ink)' }}>
              {summary.faculty_conflicts}
            </div>
            <div style={{ fontSize: '10px', color: 'var(--secondary)' }}>
              {summary.affected_faculties} mentors assigned to 2+ classes simultaneously
            </div>
          </div>

          {/* Card 4: Room Conflicts */}
          <div
            onClick={() => setActiveTab('room')}
            style={{
              cursor: 'pointer',
              background: activeTab === 'room' ? 'var(--surface2)' : 'var(--bg)',
              border: `1px solid ${activeTab === 'room' ? '#ec4899' : 'var(--line)'}`,
              borderRadius: '6px',
              padding: '12px 14px',
              transition: 'all 0.15s ease',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '11px', fontWeight: 600, color: '#ec4899' }}>ROOM COLLISIONS</span>
              <Building2 size={15} style={{ color: '#ec4899' }} />
            </div>
            <div style={{ fontSize: '24px', fontWeight: 700, margin: '6px 0 2px', color: 'var(--ink)' }}>
              {summary.room_conflicts}
            </div>
            <div style={{ fontSize: '10px', color: 'var(--secondary)' }}>
              {summary.affected_rooms} physical classrooms double-allocated
            </div>
          </div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div
        className="conflicts-controls-bar"
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '12px',
          background: 'var(--surface)',
          padding: '10px 16px',
          borderRadius: '6px',
          border: '1px solid var(--line)',
        }}
      >
        {/* Section Segmented Tabs */}
        <div style={{ display: 'flex', gap: '6px' }}>
          <button
            type="button"
            className={`button ${activeTab === 'all' ? 'primary' : ''}`}
            onClick={() => setActiveTab('all')}
            style={{ fontSize: '11px', padding: '5px 12px' }}
          >
            All Conflicts ({summary.total})
          </button>
          <button
            type="button"
            className={`button ${activeTab === 'batch' ? 'primary' : ''}`}
            onClick={() => setActiveTab('batch')}
            style={{ fontSize: '11px', padding: '5px 12px' }}
          >
            Batch Conflicts ({summary.batch_conflicts})
          </button>
          <button
            type="button"
            className={`button ${activeTab === 'faculty' ? 'primary' : ''}`}
            onClick={() => setActiveTab('faculty')}
            style={{ fontSize: '11px', padding: '5px 12px' }}
          >
            Faculty Conflicts ({summary.faculty_conflicts})
          </button>
          <button
            type="button"
            className={`button ${activeTab === 'room' ? 'primary' : ''}`}
            onClick={() => setActiveTab('room')}
            style={{ fontSize: '11px', padding: '5px 12px' }}
          >
            Room Collisions ({summary.room_conflicts})
          </button>
        </div>

        {/* Search & Severity Filter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div className="table-search-box">
            <Search size={13} />
            <input
              type="text"
              placeholder="Search batch, mentor, room, subject…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ width: '240px', fontSize: '11px' }}
            />
          </div>

          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: 'var(--muted)' }}>
            <span>Severity:</span>
            <select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value as any)}
              style={{ fontSize: '11px', padding: '4px 8px' }}
            >
              <option value="all">All Durations</option>
              <option value="high">Critical (≥ 60 mins)</option>
              <option value="medium">Moderate (30–59 mins)</option>
              <option value="minor">Minor (&lt; 30 mins)</option>
            </select>
          </label>
        </div>
      </div>

      {/* Main Content Area */}
      {conflictsQuery.isPending && (
        <Card title="Loading Conflict Records">
          <Loading />
        </Card>
      )}

      {conflictsQuery.isError && (
        <ErrorState error={conflictsQuery.error} retry={() => void conflictsQuery.refetch()} />
      )}

      {!conflictsQuery.isPending && !conflictsQuery.isError && filteredRecords.length === 0 && (
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--line)',
            borderRadius: '8px',
            padding: '40px 20px',
            textAlign: 'center',
          }}
        >
          <CheckCircle2 size={40} style={{ color: '#3dc088', margin: '0 auto 12px' }} />
          <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--ink)', margin: '0 0 6px' }}>
            No Scheduling Conflicts Found
          </h3>
          <p style={{ fontSize: '12px', color: 'var(--muted)', maxWidth: '480px', margin: '0 auto' }}>
            {search || severityFilter !== 'all' || activeTab !== 'all'
              ? 'No conflicts match your active search filters. Try clearing search or changing the filter options.'
              : 'There are no overlapping batch sessions, mentor double-bookings, or classroom collisions in the selected time period.'}
          </p>
        </div>
      )}

      {!conflictsQuery.isPending && !conflictsQuery.isError && filteredRecords.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {groupedByDate.map((group) => {
            const isCollapsed = Boolean(collapsedDates[group.dateKey]);
            return (
              <div
                key={group.dateKey}
                style={{
                  background: 'var(--surface)',
                  border: '1px solid var(--line)',
                  borderRadius: '8px',
                  overflow: 'hidden',
                }}
              >
                {/* Date Group Header */}
                <div
                  onClick={() => toggleDateCollapse(group.dateKey)}
                  style={{
                    background: 'var(--surface2)',
                    padding: '10px 16px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    cursor: 'pointer',
                    userSelect: 'none',
                    borderBottom: isCollapsed ? 'none' : '1px solid var(--line)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Calendar size={14} style={{ color: 'var(--accent)' }} />
                    <strong style={{ fontSize: '13px', color: 'var(--ink)' }}>{group.displayDate}</strong>
                    <span
                      style={{
                        fontSize: '10px',
                        background: 'var(--line)',
                        color: 'var(--secondary)',
                        padding: '2px 7px',
                        borderRadius: '10px',
                        fontWeight: 600,
                      }}
                    >
                      {group.records.length} {group.records.length === 1 ? 'Conflict' : 'Conflicts'}
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--muted)', fontSize: '11px' }}>
                    <span>{isCollapsed ? 'Show details' : 'Hide details'}</span>
                    {isCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                  </div>
                </div>

                {/* Conflict Cards within this Date */}
                {!isCollapsed && (
                  <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                    {group.records.map((conflict) => {
                      const isBatch = conflict.conflict_type === 'batch';
                      const isFaculty = conflict.conflict_type === 'faculty';

                      const typeColor = isBatch ? '#6b94ff' : isFaculty ? '#e5a53b' : '#ec4899';
                      const typeLabel = isBatch ? 'BATCH CONFLICT' : isFaculty ? 'FACULTY CONFLICT' : 'ROOM COLLISION';
                      const TypeIcon = isBatch ? Users : isFaculty ? GraduationCap : Building2;

                      const severityBadge =
                        conflict.overlap_minutes >= 60 ? (
                          <span
                            style={{
                              fontSize: '10px',
                              fontWeight: 700,
                              background: '#40191a',
                              color: '#f06a63',
                              border: '1px solid #73302d',
                              padding: '2px 8px',
                              borderRadius: '4px',
                            }}
                          >
                            ⚠️ {conflict.overlap_minutes} MIN OVERLAP (CRITICAL)
                          </span>
                        ) : conflict.overlap_minutes >= 30 ? (
                          <span
                            style={{
                              fontSize: '10px',
                              fontWeight: 700,
                              background: '#3b2d10',
                              color: '#e5a53b',
                              border: '1px solid #6b531e',
                              padding: '2px 8px',
                              borderRadius: '4px',
                            }}
                          >
                            ⚡ {conflict.overlap_minutes} MIN OVERLAP (MODERATE)
                          </span>
                        ) : (
                          <span
                            style={{
                              fontSize: '10px',
                              fontWeight: 600,
                              background: 'var(--surface2)',
                              color: 'var(--secondary)',
                              border: '1px solid var(--line)',
                              padding: '2px 8px',
                              borderRadius: '4px',
                            }}
                          >
                            ⏱️ {conflict.overlap_minutes} MIN OVERLAP
                          </span>
                        );

                      return (
                        <div
                          key={conflict.id}
                          style={{
                            background: 'var(--bg)',
                            border: '1px solid var(--line)',
                            borderRadius: '6px',
                            padding: '14px 16px',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '12px',
                          }}
                        >
                          {/* Card Top Meta */}
                          <div
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              alignItems: 'center',
                              flexWrap: 'wrap',
                              gap: '8px',
                            }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <span
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '5px',
                                  fontSize: '10px',
                                  fontWeight: 700,
                                  color: typeColor,
                                  background: `${typeColor}18`,
                                  border: `1px solid ${typeColor}40`,
                                  padding: '3px 8px',
                                  borderRadius: '4px',
                                  textTransform: 'uppercase',
                                }}
                              >
                                <TypeIcon size={12} />
                                {typeLabel}
                              </span>

                              <strong style={{ fontSize: '13px', color: 'var(--ink)' }}>
                                {conflict.target_name}
                              </strong>
                              {conflict.target_subtext && (
                                <span style={{ fontSize: '11px', color: 'var(--muted)' }}>
                                  ({conflict.target_subtext})
                                </span>
                              )}
                            </div>

                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <span style={{ fontSize: '11px', color: 'var(--secondary)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                                <Clock size={12} />
                                {formatIstTime(conflict.overlap_start)} – {formatIstTime(conflict.overlap_end)} IST
                              </span>
                              {severityBadge}
                            </div>
                          </div>

                          {/* Specific Conflict Explanation ("mention whats the conflict") */}
                          <div
                            style={{
                              background: 'var(--surface2)',
                              borderLeft: `3px solid ${typeColor}`,
                              padding: '8px 12px',
                              borderRadius: '0 4px 4px 0',
                              fontSize: '11.5px',
                              lineHeight: '1.45',
                              color: 'var(--ink)',
                            }}
                          >
                            <span style={{ fontWeight: 600, color: typeColor, marginRight: '6px' }}>
                              Conflict Reason:
                            </span>
                            {conflict.conflict_reason}
                          </div>

                          {/* Two Colliding Sessions Comparison Block */}
                          <div
                            style={{
                              display: 'grid',
                              gridTemplateColumns: '1fr auto 1fr',
                              gap: '12px',
                              alignItems: 'center',
                              background: 'var(--surface)',
                              border: '1px solid var(--line)',
                              borderRadius: '6px',
                              padding: '10px 14px',
                            }}
                          >
                            {/* Session 1 */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <span style={{ fontSize: '9px', fontWeight: 700, color: 'var(--muted)', letterSpacing: '0.5px' }}>
                                  SESSION 1
                                </span>
                              </div>
                              <strong style={{ fontSize: '12px', color: 'var(--ink)' }}>
                                {conflict.session_1.title}
                              </strong>
                              <div style={{ fontSize: '10.5px', color: 'var(--secondary)', display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '2px' }}>
                                <span>⏰ {formatIstTime(conflict.session_1.start)} – {formatIstTime(conflict.session_1.end)} IST</span>
                                {conflict.session_1.faculty && <span>👤 Mentor: {conflict.session_1.faculty}</span>}
                                {conflict.session_1.room && <span>📍 Room: {conflict.session_1.room}</span>}
                                {conflict.session_1.batches && <span>👥 Batches: {conflict.session_1.batches}</span>}
                              </div>
                            </div>

                            {/* Middle Overlap Indicator */}
                            <div
                              style={{
                                display: 'flex',
                                flexDirection: 'column',
                                alignItems: 'center',
                                padding: '0 6px',
                                color: 'var(--muted)',
                              }}
                            >
                              <div
                                style={{
                                  fontSize: '10px',
                                  fontWeight: 700,
                                  color: '#f06a63',
                                  background: '#40191a',
                                  padding: '2px 6px',
                                  borderRadius: '4px',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                {conflict.overlap_minutes}m overlap
                              </div>
                              <span style={{ fontSize: '9px', marginTop: '2px' }}>collides with</span>
                            </div>

                            {/* Session 2 */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <span style={{ fontSize: '9px', fontWeight: 700, color: 'var(--muted)', letterSpacing: '0.5px' }}>
                                  SESSION 2
                                </span>
                              </div>
                              <strong style={{ fontSize: '12px', color: 'var(--ink)' }}>
                                {conflict.session_2.title}
                              </strong>
                              <div style={{ fontSize: '10.5px', color: 'var(--secondary)', display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '2px' }}>
                                <span>⏰ {formatIstTime(conflict.session_2.start)} – {formatIstTime(conflict.session_2.end)} IST</span>
                                {conflict.session_2.faculty && <span>👤 Mentor: {conflict.session_2.faculty}</span>}
                                {conflict.session_2.room && <span>📍 Room: {conflict.session_2.room}</span>}
                                {conflict.session_2.batches && <span>👥 Batches: {conflict.session_2.batches}</span>}
                              </div>
                            </div>
                          </div>

                          {/* Footer action to inspect records if callback provided */}
                          {onOpen && (
                            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', paddingTop: '4px' }}>
                              <button
                                type="button"
                                className="button"
                                onClick={() => onOpen('sessions', { id: conflict.session_1.id, title: conflict.session_1.title } as Row)}
                                style={{ fontSize: '10px', padding: '3px 8px', display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                              >
                                <ExternalLink size={11} />
                                Inspect Session 1
                              </button>
                              <button
                                type="button"
                                className="button"
                                onClick={() => onOpen('sessions', { id: conflict.session_2.id, title: conflict.session_2.title } as Row)}
                                style={{ fontSize: '10px', padding: '3px 8px', display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                              >
                                <ExternalLink size={11} />
                                Inspect Session 2
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
