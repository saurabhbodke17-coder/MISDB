import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { api, display, queryString } from './api';
import type { Filters, Row } from './api';
import { Badge, Card, Empty, ErrorState, Loading } from './components';

type Event={id:string;title:string;start:string;end:string;source:string;category:string};
const iso=(d:Date)=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
export function CalendarBoard({filters,onOpen}:{filters:Filters;onOpen:(s:string,r:Row)=>void}){
  const [month,setMonth]=useState(()=>new Date(`${filters.to_date.slice(0,7)}-01T00:00:00`));const [day,setDay]=useState(filters.to_date);
  const first=iso(month);const last=iso(new Date(month.getFullYear(),month.getMonth()+1,0));
  const result=useQuery({queryKey:['calendar',filters,first],queryFn:()=>api<{events:Event[];truncated:boolean;note:string}>(`/calendar?${queryString({...filters,from_date:first,to_date:last})}`)});
  const offset=(month.getDay()+6)%7;const length=new Date(month.getFullYear(),month.getMonth()+1,0).getDate();const days=Array.from({length:Math.ceil((offset+length)/7)*7},(_,i)=>i-offset+1);
  function inDay(e:Event,d:string){return e.start.slice(0,10)<=d&&e.end.slice(0,10)>=d;}
  return <Card title="Master academic calendar" subtitle="Month navigation is independent of the dashboard date range; academic scope is retained." action={<div className="calendar-nav"><button className="icon-button" aria-label="Previous month" onClick={()=>setMonth(d=>new Date(d.getFullYear(),d.getMonth()-1,1))}><ChevronLeft size={16}/></button><strong>{month.toLocaleDateString('en-IN',{month:'long',year:'numeric'})}</strong><button className="icon-button" aria-label="Next month" onClick={()=>setMonth(d=>new Date(d.getFullYear(),d.getMonth()+1,1))}><ChevronRight size={16}/></button></div>}>
    {result.isPending?<Loading/>:result.error?<ErrorState error={result.error}/>:<><div className="calendar-grid">{['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map(w=><div className="calendar-weekday" key={w}>{w}</div>)}{days.map((n,i)=>{if(n<1||n>length)return <div key={i} className="calendar-blank"/>;const date=`${first.slice(0,7)}-${String(n).padStart(2,'0')}`;const events=result.data?.events.filter(e=>inDay(e,date))??[];return <button key={i} className={`calendar-cell ${date===day?'selected':''}`} onClick={()=>setDay(date)} aria-label={`${display(date)}: ${events.length} events`}><strong>{n}</strong>{events.slice(0,3).map((e,j)=><span key={e.source+e.id} className={`calendar-event category-${e.source}`}>{e.title||e.category}{j===2&&events.length>3?` +${events.length-3}`:''}</span>)}</button>;})}</div><div className="calendar-detail"><h3>{display(day)}</h3>{result.data?.events.filter(e=>inDay(e,day)).length?<div className="priority-list">{result.data.events.filter(e=>inDay(e,day)).map(e=><button key={e.source+e.id} onClick={()=>onOpen(e.source,{id:e.id,title:e.title})}><Badge value={e.category}/><strong>{e.title}</strong><span>{display(e.start)} – {display(e.end)}</span></button>)}</div>:<Empty title="No scheduled records for this day" message="No calendar entries were supplied for this date."/>}</div>{result.data?.truncated&&<p className="source-note">This month contains more than 1,000 entries in a source. Narrow the academic filters.</p>}</>}
  </Card>;
}
