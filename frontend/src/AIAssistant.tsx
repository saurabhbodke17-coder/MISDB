import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Bot, Download, Send, Sparkles, Trash2 } from 'lucide-react';
import { api, display, humanize } from './api';
import type { Filters, User } from './api';
import { Dialog } from './Dialogs';
import { Empty, ErrorState, Loading } from './components';

type Status={configured:boolean;model:string|null;suggestions:string[];reason?:string};
type Answer={title:string;explanation:string;columns:string[];rows:Record<string,unknown>[];row_count:number;truncated:boolean;retried_empty_result?:boolean;empty_message?:string;sql?:string};
type Exchange={question:string;answer:Answer};

function csvCell(value:unknown){
  let text=value==null?'':String(value);
  if (/^[=+\-@]/.test(text)) text=`'${text}`;
  return `"${text.replaceAll('"','""')}"`;
}
function downloadCsv(answer:Answer){
  const body=[answer.columns.map(csvCell).join(','),...answer.rows.map(row=>answer.columns.map(c=>csvCell(row[c])).join(','))].join('\r\n');
  const url=URL.createObjectURL(new Blob(['\ufeff',body],{type:'text/csv;charset=utf-8'}));
  const anchor=document.createElement('a');anchor.href=url;anchor.download=`${answer.title.replace(/[^a-z0-9]+/gi,'-').toLowerCase()||'polaris-ai-result'}.csv`;anchor.click();URL.revokeObjectURL(url);
}

export function AIAssistant({filters,user,onClose}:{filters:Filters;user:User;onClose:()=>void}){
  const [question,setQuestion]=useState('');const [history,setHistory]=useState<Exchange[]>([]);
  const status=useQuery({queryKey:['ai-status'],queryFn:()=>api<Status>('/ai/status')});
  const ask=useMutation({mutationFn:(text:string)=>api<Answer>('/ai/ask',{method:'POST',body:JSON.stringify({question:text,filters,history:history.slice(-6).map(x=>x.question)})}),onSuccess:(answer,text)=>{setHistory(items=>[...items,{question:text,answer}]);setQuestion('');}});
  function submit(text=question){const clean=text.trim();if(clean&&!ask.isPending)ask.mutate(clean);}
  return <Dialog title="Ask Polaris AI" drawer className="ai-drawer" onClose={onClose}>
    <div className="ai-intro"><span className="ai-orb"><Sparkles size={19}/></span><div><strong>Ask the production database in plain language</strong><p>Answers come from approved read-only reporting views and are returned as verifiable tables.</p></div></div>
    {status.isPending?<Loading/>:status.error?<ErrorState error={status.error}/>:!status.data?.configured?<div className="ai-setup"><Bot size={28}/><strong>Polaris AI unavailable</strong><p>{status.data?.reason||<>Add <code>GEMINI_API_KEY</code> to <code>backend/.env</code>, then restart the backend.</>}</p></div>:<>
      {!history.length&&<div className="ai-suggestions"><span>Try a question</span>{status.data.suggestions.map(item=><button key={item} onClick={()=>submit(item)}>{item}</button>)}</div>}
      <div className="ai-thread" aria-live="polite">{history.map((item,index)=><div className="ai-exchange" key={`${index}-${item.question}`}>
        <div className="ai-question"><span>{user.display_name.split(' ')[0]}</span><p>{item.question}</p></div>
        <article className="ai-answer"><div className="ai-answer-head"><div><span>POLARIS AI</span><h3>{item.answer.title}</h3></div>{item.answer.rows.length>0&&<button className="button small" onClick={()=>downloadCsv(item.answer)}><Download size={13}/> CSV</button>}</div><p>{item.answer.explanation}</p>
          {item.answer.rows.length?<div className="ai-table"><table><thead><tr>{item.answer.columns.map(c=><th key={c}>{humanize(c)}</th>)}</tr></thead><tbody>{item.answer.rows.map((row,r)=><tr key={r}>{item.answer.columns.map(c=><td key={c}>{display(row[c])}</td>)}</tr>)}</tbody></table></div>:<Empty title="No matching database evidence" message={item.answer.empty_message||"Polaris AI could not find database records matching this question and the selected filters."}/>}
          <div className="ai-result-meta"><span>{item.answer.row_count} row{item.answer.row_count===1?'':'s'}{item.answer.truncated?' · first 200 shown':''}</span>{item.answer.sql&&<details><summary>Verified SQL</summary><pre>{item.answer.sql}</pre></details>}</div>
        </article>
      </div>)}{ask.isPending&&<div className="ai-thinking"><span/><span/><span/> Generating, reviewing and validating the query…</div>}</div>
      {ask.error&&<ErrorState error={ask.error}/>}
      <form className="ai-composer" onSubmit={e=>{e.preventDefault();submit();}}><textarea aria-label="Ask a database question" value={question} onChange={e=>setQuestion(e.target.value)} maxLength={1000} rows={3} placeholder="Ask about attendance, students, sessions, feedback, assignments, exams, internships or batch managers…"/><div><span>{status.data.model}</span>{history.length>0&&<button type="button" className="icon-button" onClick={()=>setHistory([])} aria-label="Clear conversation"><Trash2 size={15}/></button>}<button className="button primary" disabled={!question.trim()||ask.isPending}><Send size={14}/> Ask</button></div></form>
    </>}
  </Dialog>;
}
