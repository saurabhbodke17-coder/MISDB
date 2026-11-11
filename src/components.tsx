import type { ReactNode } from 'react';
import { ArrowDownRight, ArrowUpRight, CircleHelp, Inbox, LoaderCircle, TriangleAlert } from 'lucide-react';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { Kpi } from './api';

export function Card({title, subtitle, action, children, className=''}: {title: string; subtitle?: string; action?: ReactNode; children: ReactNode; className?: string}) {
  return <section className={`card ${className}`}><div className="card-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>{children}</section>;
}
export function Empty({title='No records in this view', message='Try a different date range or filter. No synthetic records are displayed.'}: {title?: string; message?: string}) {
  return <div className="empty"><Inbox size={30}/><h3>{title}</h3><p>{message}</p></div>;
}
export function Loading() { return <div className="loading" role="status"><LoaderCircle className="spin" size={22}/> Loading database records…</div>; }
export function ErrorState({error, retry}: {error: Error | null; retry?: () => void}) { return <div className="error" role="alert"><TriangleAlert size={18}/><span>{error?.message || 'Unable to load records.'}</span>{retry && <button onClick={retry}>Try again</button>}</div>; }
export function Badge({value}: {value: unknown}) {
  const text = String(value ?? 'Unknown');
  const lower = text.toLowerCase();
  const tone = /critical|absent|blocked|missing|reopened|high risk|follow-up|overdue/.test(lower) ? 'bad' : /present|completed|verified|resolved|approved|matched|no risk/.test(lower) ? 'good' : /pending|progress|medium|scheduled|acknowledged|awaiting/.test(lower) ? 'warn' : 'neutral';
  return <span className={`badge ${tone}`}>{text}</span>;
}
export function KpiCard({kpi, onClick}: {kpi: Kpi; onClick: () => void}) {
  const good = kpi.target == null || (kpi.value != null && kpi.value >= kpi.target);
  return <button className="kpi" onClick={onClick}>
    <span className="kpi-label">{kpi.label}<span title={kpi.definition} aria-label={kpi.definition}><CircleHelp size={14}/></span></span>
    <span className="kpi-number">{kpi.value == null ? '—' : kpi.unit==='%'?kpi.value.toFixed(1):kpi.value.toLocaleString('en-IN')}{kpi.value != null && <small>{kpi.unit}</small>}</span>
    <span className={`kpi-change ${kpi.delta == null ? '' : kpi.delta >= 0 ? 'positive' : 'negative'}`}>{kpi.delta == null ? 'No comparable prior-period data' : <>{kpi.delta>=0?<ArrowUpRight size={15}/>:<ArrowDownRight size={15}/>} {Math.abs(kpi.delta).toFixed(1)} pp vs previous period</>}</span>
    <span className="kpi-footer"><i className={kpi.value == null ? 'gray-dot' : good ? 'green-dot' : 'amber-dot'}/>{kpi.value == null ? 'Insufficient source data' : kpi.evidence ?? (kpi.target==null?'Recorded count':`Target ${kpi.target}%`)}<span>View details →</span></span>
  </button>;
}
const colors=['#2457d6','#13a0a0','#e0932a','#8656c9','#d14c86','#5f7089'];
export function TrendChart({data,field='attendance',target, onDate}: {data: object[]; field?: string; target?: number; onDate?: (date:string)=>void}) {
  if (!data.length) return <Empty/>;
  return <div className="chart" role="img" aria-label={`${field} over time`}><ResponsiveContainer width="100%" height="100%"><AreaChart data={data} margin={{top:16,right:22,left:-22,bottom:8}} onClick={state=>{const value=state?.activeLabel; if (value && onDate) onDate(String(value));}}>
    <defs><linearGradient id={`fill-${field}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2457d6" stopOpacity={0.2}/><stop offset="100%" stopColor="#2457d6" stopOpacity={0}/></linearGradient></defs>
    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--line)"/>
    <XAxis dataKey="date" tickFormatter={d=>new Date(`${String(d).slice(0,10)}T00:00:00`).toLocaleDateString('en-IN',{day:'numeric',month:'short'})} tickLine={false} axisLine={false} minTickGap={28} tick={{fontSize:11,fill:'var(--muted)'}}/>
    <YAxis tickLine={false} axisLine={false} domain={field==='attendance'?[0,100]:[0,'auto']} tick={{fontSize:11,fill:'var(--muted)'}}/>
    <Tooltip contentStyle={{border:'1px solid var(--line)',borderRadius:8,background:'var(--surface)',color:'var(--ink)'}}/>
    {target != null && <ReferenceLine y={target} stroke="#168a5a" strokeDasharray="5 4" label={{value:`Target ${target}%`,fill:'#168a5a',fontSize:10,position:'insideTopRight'}}/>}
    <Area type="linear" dataKey={field} stroke="#2457d6" fill={`url(#fill-${field})`} strokeWidth={2.5} dot={{r:3,fill:'#2457d6'}} activeDot={{r:5}} connectNulls={false}/>
  </AreaChart></ResponsiveContainer></div>;
}
export function Distribution({data, horizontal=false}: {data: {name:string;value:number}[]; horizontal?:boolean}) {
  if (!data.length) return <Empty/>;
  return <div className="chart" role="img" aria-label="Record distribution"><ResponsiveContainer width="100%" height="100%"><BarChart data={data} layout={horizontal?'vertical':'horizontal'} margin={{top:15,right:20,bottom:5,left:horizontal?35:-20}}>
    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--line)"/>
    <XAxis dataKey={horizontal?undefined:'name'} type={horizontal?'number':'category'} tick={{fontSize:11,fill:'var(--muted)'}} tickLine={false} axisLine={false}/>
    <YAxis dataKey={horizontal?'name':undefined} type={horizontal?'category':'number'} tick={{fontSize:11,fill:'var(--muted)'}} tickLine={false} axisLine={false}/>
    <Tooltip contentStyle={{background:'var(--surface)',color:'var(--ink)',border:'1px solid var(--line)',borderRadius:8}}/>
    <Bar dataKey="value" radius={horizontal?[0,4,4,0]:[4,4,0,0]} maxBarSize={44}>{data.map((r,i)=><Cell key={r.name} fill={colors[i%colors.length]}/>)}</Bar>
  </BarChart></ResponsiveContainer></div>;
}
