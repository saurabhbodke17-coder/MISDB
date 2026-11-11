import { useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ExternalLink, Save, X } from 'lucide-react';
import { api, display, humanize, queryString } from './api';
import type { Filters, MetricSettings, Option, Row, User } from './api';
import { Badge, Empty, ErrorState, Loading } from './components';
import { workSources } from './modules';

type Owner = { id:string; display_name:string; role:string };
const statuses=['Open','In progress','Blocked','Done – awaiting verification','Verified & closed','Reopened'];
export function Dialog({title,onClose,children,drawer=false,className=''}: {title:string;onClose:()=>void;children:ReactNode;drawer?:boolean;className?:string}) {
  const ref=useRef<HTMLDialogElement>(null);
  useEffect(()=>{ref.current?.showModal();return ()=>ref.current?.close();},[]);
  return <dialog ref={ref} className={`${drawer?'drawer':'modal'} ${className}`.trim()} onCancel={e=>{e.preventDefault();onClose();}} onClick={e=>{if(e.target===ref.current)onClose();}} aria-labelledby="dialog-title"><div className="dialog-head"><div><span className="eyebrow">POLARIS MIS</span><h2 id="dialog-title">{title}</h2></div><button className="icon-button" onClick={onClose} aria-label="Close dialog"><X size={20}/></button></div><div className="dialog-body">{children}</div></dialog>;
}
export function CreateWork({kind,source,sourceId,title='',batchId='',onClose,onSaved}: {kind:string;source:string;sourceId?:string;title?:string;batchId?:string;onClose:()=>void;onSaved:()=>void}) {
  const owners=useQuery({queryKey:['owners'],queryFn:()=>api<Owner[]>('/work-items/owners')});
  const mutation=useMutation({mutationFn:(body:object)=>api('/work-items',{method:'POST',body:JSON.stringify(body)}),onSuccess:onSaved});
  function submit(e:FormEvent<HTMLFormElement>) {e.preventDefault();const data=Object.fromEntries(new FormData(e.currentTarget));mutation.mutate({...data,kind,source_module:source,source_id:sourceId??null,batch_id:batchId||null});}
  return <Dialog title={`New ${kind}`} onClose={onClose}><p className="muted">Create a persistent record with an owner and a deadline. All changes are audited.</p><form onSubmit={submit} className="form-grid">
    <label className="full">Title<input name="title" required minLength={3} maxLength={250} defaultValue={title}/></label>
    <label>Owner<select name="owner_id" required><option value="">Select owner</option>{owners.data?.map(o=><option key={o.id} value={o.id}>{o.display_name}</option>)}</select></label>
    <label>Due date<input name="due_date" type="date" required defaultValue={new Date().toISOString().slice(0,10)}/></label>
    <label>Severity<select name="severity" defaultValue="Medium">{['Low','Medium','High','Critical'].map(s=><option key={s}>{s}</option>)}</select></label>
    <label>Function<input name="function_name" maxLength={100} placeholder="e.g. Academics" defaultValue="Unassigned"/></label><label>Category<input name="category" maxLength={100} defaultValue="Unclassified"/></label>
    <label>Root cause<input name="root_cause" maxLength={2000} placeholder="Describe the cause if known"/></label>
    <label className="full">Description / corrective action<textarea name="description" rows={4} maxLength={10000}/></label>
    {owners.error&&<ErrorState error={owners.error}/>} {mutation.error&&<ErrorState error={mutation.error}/>}
    <div className="form-actions full"><button type="button" className="button" onClick={onClose}>Cancel</button><button className="button primary" disabled={mutation.isPending||!owners.data?.length}>{mutation.isPending?'Creating…':'Create record'}</button></div>
  </form></Dialog>;
}
export function CreateTicket({onClose,onSaved}:{onClose:()=>void;onSaved:()=>void}) {
  const owners=useQuery({queryKey:['owners'],queryFn:()=>api<Owner[]>('/work-items/owners')});
  const students=useQuery({queryKey:['support-students'],queryFn:()=>api<Option[]>('/support/students')});
  const mutation=useMutation({mutationFn:(body:object)=>api('/support',{method:'POST',body:JSON.stringify(body)}),onSuccess:onSaved});
  return <Dialog title="New support report" onClose={onClose}><form className="form-grid" onSubmit={e=>{e.preventDefault();mutation.mutate(Object.fromEntries(new FormData(e.currentTarget)));}}>
    <label className="full">Student<select name="user_id" required><option value="">Select student</option>{students.data?.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
    <label>Category<select name="category">{['bug','feedback','other'].map(s=><option key={s}>{s}</option>)}</select></label>
    <label>Severity<select name="severity" defaultValue="Medium">{['Low','Medium','High','Critical'].map(s=><option key={s}>{s}</option>)}</select></label>
    <label className="full">Owner<select name="owner_id" required><option value="">Select owner</option>{owners.data?.map(o=><option key={o.id} value={o.id}>{o.display_name}</option>)}</select></label>
    <label className="full">Description<textarea name="description" required minLength={5} maxLength={10000} rows={4}/></label>
    <p className="source-note full">SLA begins at creation: Critical 24h · High 48h · Medium 72h · Low 120h.</p>
    {(owners.error||students.error)&&<ErrorState error={owners.error||students.error}/>} {mutation.error&&<ErrorState error={mutation.error}/>}
    <div className="form-actions full"><button type="button" className="button" onClick={onClose}>Cancel</button><button className="button primary" disabled={mutation.isPending||!owners.data||!students.data}>Create report</button></div>
  </form></Dialog>;
}
type History={event:string;note:string;created_at:string;actor:string}[];
export function DetailDrawer({source,row,filters,user,onClose,onCreate,onSaved}: {source:string;row:Row;filters:Filters;user:User;onClose:()=>void;onCreate:(title:string,id:string)=>void;onSaved:()=>void}) {
  const isWork=workSources.has(source);const client=useQueryClient();
  const detail=useQuery({queryKey:['detail',source,row.id,filters],queryFn:()=>api<{record:Row;history?:History}>(isWork?`/work-items/${row.id}`:`/records/${source}/${encodeURIComponent(row.id)}?${queryString(filters)}`)});
  const owners=useQuery({queryKey:['owners'],queryFn:()=>api<Owner[]>('/work-items/owners'),enabled:(isWork||source==='support')&&user.role!=='viewer'});
  const history=useQuery({queryKey:['support-history',row.id],queryFn:()=>api<History>(`/support/${row.id}/history`),enabled:source==='support'});
  const mutation=useMutation({mutationFn:(body:object)=>api(isWork?`/work-items/${row.id}`:`/support/${row.id}`,{method:'PATCH',body:JSON.stringify(body)}),onSuccess:()=>{void client.invalidateQueries();onSaved();}});
  const record=detail.data?.record;const events=detail.data?.history||history.data;
  function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();mutation.mutate({...Object.fromEntries(new FormData(e.currentTarget)),version:Number(record?.version??0)});}
  return <Dialog title={String(record?.title||record?.student||record?.mentor||row.title||'Record detail')} drawer onClose={onClose}>
    {detail.isPending?<Loading/>:detail.error?<ErrorState error={detail.error} retry={()=>void detail.refetch()}/>:record&&<>
      <div className="detail-top"><span className="mono small-text">{record.id}</span>{record.status!=null&&<Badge value={record.status}/>}</div>
      <dl className="detail-fields">{Object.entries(record).filter(([k])=>!['id','owner_id','version','student_id'].includes(k)).map(([k,v])=><div key={k}><dt>{humanize(k)}</dt><dd>{display(v)}</dd></div>)}</dl>
      {user.role!=='viewer'&&(isWork||source==='support')&&<form key={String(record.version)} className="form-grid edit-form" onSubmit={submit}>
        <h3 className="full">Update {isWork?'work item':'support report'}</h3>
        <label>Status<select name="status" defaultValue={String(record.status)}>{(isWork?statuses:['open','acknowledged','resolved']).map(s=><option key={s} disabled={s==='Verified & closed'&&user.role!=='admin'}>{s}</option>)}</select></label>
        <label>Severity<select name="severity" defaultValue={String(record.severity)==='Unclassified'?'Medium':String(record.severity)}>{['Low','Medium','High','Critical'].map(s=><option key={s}>{s}</option>)}</select></label>
        <label className={isWork?'':'full'}>Owner<select name="owner_id" defaultValue={String(record.owner_id||'')} required><option value="">Assign owner</option>{owners.data?.map(o=><option key={o.id} value={o.id}>{o.display_name}</option>)}</select></label>
        {isWork&&<><label>Due date<input type="date" name="due_date" defaultValue={String(record.due_date).slice(0,10)} required/></label><label>Escalation level<select name="escalation_level" defaultValue={String(record.escalation_level??0)}>{[0,1,2,3].map(n=><option key={n} value={n}>Level {n}</option>)}</select></label><label className="full">Root cause<input name="root_cause" defaultValue={String(record.root_cause||'')} maxLength={2000}/></label><label className="full">Resolution evidence reference<textarea name="evidence" rows={2} defaultValue={String(record.evidence||'')} maxLength={4000}/></label></>}
        <label className="full">Audit note<textarea name="note" rows={3} required={!isWork} minLength={isWork?0:3} maxLength={4000} placeholder="What changed and why?"/></label>
        {mutation.error&&<div className="full"><ErrorState error={mutation.error} retry={()=>void detail.refetch()}/></div>}
        <button className="button primary full" disabled={mutation.isPending||!owners.data}><Save size={15}/>{mutation.isPending?'Saving…':'Save changes'}</button>
      </form>}
      {user.role!=='viewer'&&!isWork&&<button className="button primary full-width" onClick={()=>onCreate(`Follow-up: ${String(record.title||record.student||record.mentor||source)}`,record.id)}><ExternalLink size={15}/> Create follow-up action</button>}
      {events&&<section className="audit"><h3>Audit history</h3>{events.length?events.map((e,i)=><div className="audit-event" key={`${e.created_at}-${i}`}><span className="audit-dot"/><div><strong>{e.actor}</strong> · {e.event}<p>{e.note||'Record change saved'}</p><small>{new Date(e.created_at).toLocaleString('en-IN')}</small></div></div>):<Empty title="No MIS changes yet" message="Future changes made here will appear in the audit history."/>}</section>}
    </>}
  </Dialog>;
}
export function SettingsDialog({user,onClose,onSaved}: {user:User;onClose:()=>void;onSaved:()=>void}) {
  const current=useQuery({queryKey:['settings'],queryFn:()=>api<MetricSettings>('/settings')});
  const [error,setError]=useState('');
  const mutation=useMutation({mutationFn:(body:object)=>api('/settings',{method:'PUT',body:JSON.stringify(body)}),onSuccess:onSaved});
  return <Dialog title="Settings & metric rules" onClose={onClose}>{current.isPending?<Loading/>:current.error?<ErrorState error={current.error}/>:current.data&&<form className="form-grid" onSubmit={e=>{e.preventDefault();setError('');const form=new FormData(e.currentTarget);const body=Object.fromEntries(Object.entries(current.data!).map(([k])=>[k,k==='late_counts_present'?form.get(k)==='true':Number(form.get(k))]));mutation.mutate(body);}}>
    <p className="source-note full">Targets are operational settings. Changes recalculate database-derived analytics and are recorded in the audit log.</p>
    {Object.entries(current.data).map(([k,v])=><label key={k}>{humanize(k)}{typeof v==='boolean'?<select name={k} defaultValue={String(v)} disabled={user.role!=='admin'}><option value="true">Count late as present</option><option value="false">Exclude late from present</option></select>:<input type="number" name={k} defaultValue={v} min={0} max={k==='late_tolerance'?60:100} step={k==='late_tolerance'?1:0.1} disabled={user.role!=='admin'} required/>}</label>)}
    {(mutation.error||error)&&<ErrorState error={mutation.error||new Error(error)}/>}
    {user.role==='admin'?<button className="button primary full" disabled={mutation.isPending}>Save metric rules</button>:<p className="muted full">Only administrators can change these settings.</p>}
  </form>}</Dialog>;
}
