export type Row = Record<string, unknown> & { id: string };
export type User = { id: string; username: string; display_name: string; role: 'admin' | 'operator' | 'viewer' };
export type Filters = { from_date: string; to_date: string; batch_id: string; specialization_id: string; semester_id: string; graduation_year_id: string; mentor_id: string };
export type Option = { id: string; name: string; specialization_id?: string; graduation_year_id?: string; semester_ids?: string[] };
export type MetricSettings = { attendance_target: number; delivery_target: number; completion_target: number; late_tolerance: number; risk_attendance: number; pass_mark: number; sla_target: number; task_target: number; late_counts_present: boolean };
export type Options = { batches: Option[]; programs: Option[]; semesters: Option[]; years: Option[]; mentors: Option[]; settings: MetricSettings; data_range: { first_date: string; last_date: string } };
export type Register = { title: string; columns: string[]; rows: Row[]; total: number; page: number; page_size: number; note: string; scope: string };
export type Kpi = { key: string; label: string; value: number | null; unit: string; delta: number | null; target: number | null; definition: string; module: string; denominator?: number; evidence?: string; spark?: (number|null)[] };

export function abbreviateWords(value: unknown) {
  const text=String(value??'').trim();
  const words=text.match(/[\p{L}\p{N}]+/gu)??[];
  const significant=words.filter(word=>!new Set(['and','of','the','on','for','to','in','with']).has(word.toLowerCase()));
  return words.length>1?(significant.length?significant:words).map(word=>word[0]).join('').toUpperCase():text;
}
export type Dashboard = { kpis: Kpi[]; trends: { date: string; attendance: number | null; sessions: number; absent: number }[]; batches: { id: string; name: string; sessions: number; students: number; attendance: number | null }[]; scores: {name: string; value: number}[]; coverage: string; delivery: { scheduled: number; completed: number; actual_recorded: number } };
export type Summary = { groups: {name: string; value: number}[]; daily: {date: string; value: number}[]; total: number; group_by: string | null };

export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }
export async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${url}`, { ...init, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'PolarisMIS', ...init?.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === 'string' ? body.detail : Array.isArray(body.detail) ? body.detail.map((d: {msg: string}) => d.msg).join('; ') : 'Request failed. Please try again.';
    if (response.status === 401 && url !== '/auth/login') window.dispatchEvent(new Event('polaris-session-expired'));
    throw new ApiError(response.status, detail);
  }
  return response.status === 204 ? undefined as T : response.json();
}
export const queryString = (values: object) => new URLSearchParams(Object.entries(values).filter(([,v]) => v !== '' && v != null).map(([k,v]) => [k,String(v)])).toString();
export function istToday(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now);
  const part = (type: string) => parts.find(p => p.type === type)?.value ?? '';
  return `${part('year')}-${part('month')}-${part('day')}`;
}
export function istRange(days: number, now: Date = new Date()): { from_date: string; to_date: string } {
  const to_date = istToday(now);
  if (days <= 1) return { from_date: to_date, to_date };
  const start = new Date(`${to_date}T00:00:00Z`);
  start.setUTCDate(start.getUTCDate() - days + 1);
  return { from_date: start.toISOString().slice(0, 10), to_date };
}
export function initialFilters(): Filters {
  return { ...istRange(28), batch_id: '', specialization_id: '', semester_id: '', graduation_year_id: '', mentor_id: '' };
}
export const humanize = (s: string) => s.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
export function display(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') return JSON.stringify(value);
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}/.test(value)) {
    const d = new Date(value.length === 10 ? `${value}T00:00:00` : value);
    if (!Number.isNaN(d.getTime())) return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
  }
  return String(value);
}
