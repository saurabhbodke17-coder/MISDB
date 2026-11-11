import { useQuery } from '@tanstack/react-query';
import { CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts';
import { api, display, queryString } from './api';
import type { Filters, Row } from './api';
import { Badge, Card, Empty, ErrorState, Loading } from './components';

type HeatCell={batch_id:string;batch:string;week:string;eligible:number;attendance:number|null};
export function AttendanceHeatmap({filters,onSelect}:{filters:Filters;onSelect:(batch:string,date:string)=>void}) {
  const result=useQuery({queryKey:['heatmap',filters],queryFn:()=>api<HeatCell[]>(`/plots/attendance-heatmap?${queryString(filters)}`)});
  const weeks=[...new Set(result.data?.map(r=>r.week))].sort();const batches=[...new Map(result.data?.map(r=>[r.batch_id,r.batch])).entries()];
  return <Card title="Weekly attendance heatmap" subtitle="Batch × week · select a cell to drill into attendance records">
    {result.isPending?<Loading/>:result.error?<ErrorState error={result.error}/>:!result.data?.length?<Empty/>:<div className="heatmap-wrap"><table className="heatmap"><thead><tr><th>Batch</th>{weeks.map(w=><th key={w}>{display(w)}</th>)}</tr></thead><tbody>{batches.map(([id,name])=><tr key={id}><td>{name}</td>{weeks.map(w=>{const cell=result.data.find(r=>r.batch_id===id&&r.week===w);return <td key={w}><button disabled={cell?.attendance==null} style={{background:cell?.attendance==null?'var(--surface2)':cell.attendance>=85?'#168a5a':cell.attendance>=65?'#b8740a':'#cc3b35',color:cell?.attendance==null?'var(--muted)':'white'}} onClick={()=>onSelect(id,w)} title={`${name} · ${display(w)} · ${cell?.eligible??0} eligible records`}>{cell?.attendance==null?'—':`${cell.attendance}%`}</button></td>;})}</tr>)}</tbody></table></div>}
  </Card>;
}
export function StudentScatter({filters,onOpen}:{filters:Filters;onOpen:(row:Row)=>void}) {
  const result=useQuery({queryKey:['scatter',filters],queryFn:()=>api<(Row&{attendance:number;average_score:number;student:string})[]>(`/plots/student-scatter?${queryString(filters)}`)});
  return <Card title="Attendance vs academic performance" subtitle="Students with attendance and graded assignment evidence · maximum 500 points">
    {result.isPending?<Loading/>:result.error?<ErrorState error={result.error}/>:!result.data?.length?<Empty title="Not enough overlapping evidence" message="This plot requires both attendance and graded assignment records for the same student in the selected period."/>:<div className="chart"><ResponsiveContainer width="100%" height="100%"><ScatterChart margin={{top:15,right:20,bottom:20,left:5}}><CartesianGrid stroke="var(--line)" strokeDasharray="3 3"/><XAxis type="number" dataKey="attendance" name="Attendance" unit="%" domain={[0,100]} tick={{fontSize:10,fill:'var(--muted)'}} label={{value:'Attendance %',position:'insideBottom',offset:-10,fontSize:10,fill:'var(--muted)'}}/><YAxis type="number" dataKey="average_score" name="Assignment score" unit="%" domain={[0,100]} tick={{fontSize:10,fill:'var(--muted)'}}/><ZAxis range={[70,70]}/><Tooltip cursor={{strokeDasharray:'3 3'}} contentStyle={{background:'var(--surface)',border:'1px solid var(--line)'}}/><ReferenceLine x={75} stroke="#b8740a" strokeDasharray="4 4"/><ReferenceLine y={40} stroke="#cc3b35" strokeDasharray="4 4"/><Scatter name="Students" data={result.data} fill="#2457d6" onClick={point=>{if(point?.payload)onOpen(point.payload as Row);}}/></ScatterChart></ResponsiveContainer></div>}
  </Card>;
}
export function TaskTimeline({filters,onOpen}:{filters:Filters;onOpen:(row:Row)=>void}) {
  const result=useQuery({queryKey:['timeline',filters],queryFn:()=>api<Row[]>(`/plots/task-timeline?${queryString(filters)}`)});
  const allDates=result.data?.flatMap(r=>[Date.parse(String(r.created_at)),Date.parse(String(r.due_date))])||[];
  const min=Math.min(...allDates);const max=Math.max(...allDates,min+86400000);const span=max-min;
  return <Card title="Task timeline" subtitle="Creation to due date · persisted operational tasks, maximum 100">
    {result.isPending?<Loading/>:result.error?<ErrorState error={result.error}/>:!result.data?.length?<Empty title="No tasks in this period" message="Create an operational task with an owner and due date to begin tracking."/>:<div className="gantt"><div className="gantt-scale"><span>{display(new Date(min).toISOString())}</span><span>{display(new Date(max).toISOString())}</span></div>{result.data.map(r=>{const start=Math.min(Date.parse(String(r.created_at)),Date.parse(String(r.due_date)));const end=Math.max(Date.parse(String(r.created_at)),Date.parse(String(r.due_date)));return <button className="gantt-row" key={r.id} onClick={()=>onOpen(r)}><span>{String(r.title)}<small>{String(r.owner)}</small></span><div className="gantt-track"><i style={{left:`${(start-min)/span*100}%`,width:`${Math.max(1,(end-start)/span*100)}%`,background:r.status==='Verified & closed'?'var(--green)':'var(--accent)'}}/></div><Badge value={r.status}/></button>;})}</div>}
  </Card>;
}
