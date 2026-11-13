import { useEffect, useRef, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Bar, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts';
import { ChevronLeft, ChevronRight, Database, Download, Info } from 'lucide-react';
import { abbreviateWords, api, display, humanize, queryString } from './api';
import type { Filters, Options } from './api';
import { Card, Empty, ErrorState, Loading } from './components';

type Point=Record<string,unknown>;
export type Chart={id:string;title:string;type:string;render_as?:string;provider:string|null;source:string|null;status:'available'|'empty'|'unavailable';rows:Point[];series:string[];unit:string;note:string;stacked?:boolean;target?:number|null;plot_limit?:number;page?:number;page_size?:number;total?:number;row_entities?:{id:string;name:string}[];heatmap_mode?:'percentage'|'absolute'|'unique';summary?:{avg_absent?:number;avg_present?:number;total_students?:number;days_count?:number}};
const palette=['#2457d6','#13a0a0','#e0932a','#8656c9','#d14c86','#5f7089','#6fa836'];
function number(value:unknown){return typeof value==='number'?value:typeof value==='string'&&value.trim()!==''&&Number.isFinite(Number(value))?Number(value):null;}
function chartColumnLabel(chart:Chart,column:string){
  if(chart.provider==='feedback.ranking')return {name:'Mentor',value:'Average feedback',feedback_count:'Rating responses'}[column]??humanize(column);
  if(chart.provider==='attendance.overall_daily'){
    if(column==='name'||column==='date')return 'Date';
    if(column==='value'||column==='absent_students')return 'Absent students';
    if(column==='present_students')return 'Present students';
    if(column==='total_students')return 'Total students';
  }
  return humanize(column);
}
function downloadData(chart:Chart){
  if(chart.id==='attendance-2'||chart.render_as==='class_absences'){
    const classRows=chart.rows.flatMap(r=>{
      const date=String(r.name);
      const classes=Array.isArray(r.classes)?(r.classes as Record<string,unknown>[]):[];
      if(!classes.length){
        return [{date,cohort:'—',semester:'—',batch:'—',subject:'—',title:'—',absent:Number(r.value||0),present:Number(r.present_count||0),total_students:Number(r.total_students||0),attendance_rate:'—'}];
      }
      return classes.map(c=>({
        date,
        cohort:String(c.cohort||'—'),
        semester:String(c.semester||'—'),
        batch:String(c.batch||'—'),
        subject:String(c.subject||'—'),
        title:String(c.title||'—'),
        absent:Number(c.absent||0),
        present:Number(c.present||0),
        total_students:Number(c.total||0),
        attendance_rate:c.rate!=null?`${c.rate}%`:'—'
      }));
    });
    const cols=['date','cohort','semester','batch','subject','title','absent','present','total_students','attendance_rate'];
    const cell=(v:unknown)=>{let value=String(v??'');if(/^[\s]*[=+\-@]/.test(value))value="'"+value;return '"'+value.replaceAll('"','""')+'"';};
    const body=[cols.map(c=>cell(humanize(c))).join(','),...classRows.map(r=>cols.map(c=>cell(r[c as keyof typeof r])).join(','))].join('\n');
    const url=URL.createObjectURL(new Blob([body],{type:'text/csv'}));
    const a=document.createElement('a');a.href=url;a.download=`${chart.id}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    return;
  }
  const cols=[...new Set(chart.rows.flatMap(r=>Object.keys(r)))];const cell=(v:unknown)=>{let value=String(v??'');if(/^[\s]*[=+\-@]/.test(value))value="'"+value;return '"'+value.replaceAll('"','""')+'"';};const body=[cols.map(c=>cell(chartColumnLabel(chart,c))).join(','),...chart.rows.map(r=>cols.map(c=>cell(r[c])).join(','))].join('\n');const url=URL.createObjectURL(new Blob([body],{type:'text/csv'}));const a=document.createElement('a');a.href=url;a.download=`${chart.id}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

type ClassRecord={id:string;session_id:string;title:string;subject:string;subject_id:string;batch:string;batch_id:string;semester:string;semester_number:number;semester_id:string;cohort:string;graduation_year_id:string;absent:number;present:number;total:number;rate:number;color?:string};
const CLASS_PALETTE=['#2563eb','#10b981','#f59e0b','#8b5cf6','#ec4899','#06b6d4','#ea580c','#6366f1','#14b8a6','#e11d48','#84cc16','#a855f7','#0284c7','#d97706','#4338ca','#059669'];
function stringHash(str:string):number{let hash=0;for(let i=0;i<str.length;i++){hash=(hash<<5)-hash+str.charCodeAt(i);hash|=0;}return Math.abs(hash);}
function assignClassColors(classes:ClassRecord[]):(ClassRecord&{color:string})[]{
  return classes.map((c,i)=>{
    const baseIndex=stringHash(c.subject||'')%CLASS_PALETTE.length;
    const colorIndex=(baseIndex+i*3)%CLASS_PALETTE.length;
    return {...c,color:CLASS_PALETTE[colorIndex]};
  });
}

function ClassAbsenceChart({chart,onSelect,globalFilters}:{chart:Chart;onSelect:(row:Point)=>void;globalFilters?:Filters}){
  const [cohort,setCohort]=useState<string>(globalFilters?.graduation_year_id||'');
  const [semester,setSemester]=useState<string>(globalFilters?.semester_id||'');
  const [batch,setBatch]=useState<string>(globalFilters?.batch_id||'');
  const [subject,setSubject]=useState<string>('');

  useEffect(()=>{
    if(globalFilters?.graduation_year_id)setCohort(globalFilters.graduation_year_id);
    if(globalFilters?.semester_id)setSemester(globalFilters.semester_id);
    if(globalFilters?.batch_id)setBatch(globalFilters.batch_id);
  },[globalFilters?.graduation_year_id,globalFilters?.semester_id,globalFilters?.batch_id]);

  const svgWrapRef=useRef<HTMLDivElement>(null);
  const [hoveredPoint,setHoveredPoint]=useState<{date:string;totalAbsent:number;totalStudents:number;totalPresent:number;classes:(ClassRecord&{color:string})[];hoveredClassId?:string;mouseX:number;mouseY:number}|null>(null);

  const allRawClasses:ClassRecord[]=chart.rows.flatMap(r=>Array.isArray(r.classes)?(r.classes as ClassRecord[]):[]);
  const cohortOptions=[...new Set(allRawClasses.map(c=>c.cohort).filter(Boolean))].sort();
  const semesterOptions=[...new Set(allRawClasses.filter(c=>!cohort||c.cohort===cohort||c.graduation_year_id===cohort).map(c=>c.semester).filter(Boolean))].sort((a,b)=>(parseInt(a.replace(/\D/g,''),10)||0)-(parseInt(b.replace(/\D/g,''),10)||0));
  const batchOptions=[...new Set(allRawClasses.filter(c=>(!cohort||c.cohort===cohort||c.graduation_year_id===cohort)&&(!semester||c.semester===semester||String(c.semester_number)===semester||c.semester_id===semester)).map(c=>c.batch).filter(Boolean))].sort();
  const subjectOptions=[...new Set(allRawClasses.filter(c=>(!cohort||c.cohort===cohort||c.graduation_year_id===cohort)&&(!semester||c.semester===semester||String(c.semester_number)===semester||c.semester_id===semester)&&(!batch||c.batch===batch||c.batch_id===batch)).map(c=>c.subject).filter(Boolean))].sort();

  const hasActiveFilters=Boolean((cohort&&cohort!==globalFilters?.graduation_year_id)||(semester&&semester!==globalFilters?.semester_id)||(batch&&batch!==globalFilters?.batch_id)||subject);

  const filteredDates=chart.rows.map(row=>{
    const rawClasses=Array.isArray(row.classes)?(row.classes as ClassRecord[]):[];
    const matching=rawClasses.filter(c=>{
      if(cohort&&c.cohort!==cohort&&c.graduation_year_id!==cohort)return false;
      if(semester&&c.semester!==semester&&String(c.semester_number)!==semester&&c.semester_id!==semester)return false;
      if(batch&&c.batch!==batch&&c.batch_id!==batch)return false;
      if(subject&&c.subject!==subject&&c.subject_id!==subject)return false;
      return true;
    });
    const coloredClasses=assignClassColors(matching);
    const totalAbsent=coloredClasses.reduce((sum,c)=>sum+(c.absent||0),0);
    const totalStudents=coloredClasses.reduce((sum,c)=>sum+(c.total||0),0);
    const totalPresent=coloredClasses.reduce((sum,c)=>sum+(c.present||0),0);
    return {date:String(row.name),classes:coloredClasses,totalAbsent,totalStudents,totalPresent};
  });

  const maxAbsent=Math.max(5,...filteredDates.map(d=>d.totalAbsent));
  const scaleMax=maxAbsent<=10?10:maxAbsent<=25?25:maxAbsent<=50?50:maxAbsent<=100?100:maxAbsent<=200?200:maxAbsent<=500?500:Math.ceil(maxAbsent/250)*250;
  const width=1160;const height=310;const margin={left:48,right:20,top:20,bottom:28};
  const W=width-margin.left-margin.right;const H=height-margin.top-margin.bottom;const baselineY=margin.top+H;
  const N=filteredDates.length;const stepX=N>0?W/N:W;const barWidth=Math.max(5,Math.min(26,stepX-4));
  const yTicks=[0,Math.round(scaleMax/3),Math.round((scaleMax*2)/3),scaleMax];
  const dateStep=Math.max(1,Math.ceil(N/14));

  return (
    <div className="class-absence-wrap">
      <div className="class-absence-filters">
        <label>
          <span>Batch year</span>
          <select aria-label="Batch year filter" value={cohort} onChange={e=>{setCohort(e.target.value);setBatch('');setSubject('');}}>
            <option value="">All batch years</option>
            {cohortOptions.map(c=><option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label>
          <span>Semester</span>
          <select aria-label="Semester filter" value={semester} onChange={e=>{setSemester(e.target.value);setBatch('');setSubject('');}}>
            <option value="">All semesters</option>
            {semesterOptions.map(s=><option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>
          <span>Batch</span>
          <select aria-label="Batch filter" value={batch} onChange={e=>{setBatch(e.target.value);setSubject('');}}>
            <option value="">All batches</option>
            {batchOptions.map(b=><option key={b} value={b}>{b}</option>)}
          </select>
        </label>
        <label>
          <span>Subject</span>
          <select aria-label="Subject filter" value={subject} onChange={e=>setSubject(e.target.value)}>
            <option value="">All subjects</option>
            {subjectOptions.map(s=><option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        {hasActiveFilters&&(
          <button type="button" className="reset-local-filter" onClick={()=>{setCohort(globalFilters?.graduation_year_id||'');setSemester(globalFilters?.semester_id||'');setBatch(globalFilters?.batch_id||'');setSubject('');}}>
            Reset class filters
          </button>
        )}
      </div>
      <div className="class-absence-svg-wrap" ref={svgWrapRef}>
        <svg className="class-absence-svg" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" onMouseLeave={()=>setHoveredPoint(null)}>
          {yTicks.map(tickVal=>{
            const y=baselineY-(tickVal/scaleMax)*H;
            return (
              <g key={tickVal}>
                <line x1={margin.left} y1={y} x2={width-margin.right} y2={y} stroke="var(--line)" strokeDasharray="3 3"/>
                <text x={margin.left-6} y={y+3} textAnchor="end" fontSize="9" fill="var(--muted)">{tickVal.toLocaleString('en-IN')}</text>
              </g>
            );
          })}
          {filteredDates.map((d,i)=>{
            const centerX=margin.left+i*stepX+stepX/2;
            const barX=centerX-barWidth/2;
            let curY=baselineY;
            const activeClasses=d.classes.filter(c=>c.absent>0);
            const segments=activeClasses.map((cls,idx)=>{
              const segH=Math.max(3,(cls.absent/scaleMax)*H);
              curY-=segH;
              return {...cls,segX:barX,segY:curY,segW:barWidth,segH,isTop:idx===activeClasses.length-1};
            });
            const showDateLabel=i%dateStep===0||i===N-1;
            const formattedDate=typeof d.date==='string'&&/^\d{4}-\d{2}-\d{2}/.test(d.date)?new Date(`${d.date.slice(0,10)}T00:00:00`).toLocaleDateString('en-IN',{month:'short',day:'numeric'}):d.date;
            return (
              <g key={d.date}>
                {showDateLabel&&<text x={centerX} y={height-6} textAnchor="middle" fontSize="9" fill="var(--muted)">{formattedDate}</text>}
                <rect x={centerX-stepX/2} y={margin.top} width={stepX} height={H} fill="transparent" style={{cursor:'pointer'}}
                  onMouseEnter={e=>{
                    const rect=svgWrapRef.current?.getBoundingClientRect();
                    setHoveredPoint({date:d.date,totalAbsent:d.totalAbsent,totalStudents:d.totalStudents,totalPresent:d.totalPresent,classes:d.classes,mouseX:rect?e.clientX-rect.left:0,mouseY:rect?e.clientY-rect.top:0});
                  }}
                  onMouseMove={e=>{
                    const rect=svgWrapRef.current?.getBoundingClientRect();
                    setHoveredPoint(prev=>prev?{...prev,mouseX:rect?e.clientX-rect.left:0,mouseY:rect?e.clientY-rect.top:0}:null);
                  }}
                  onClick={()=>onSelect({name:d.date,date:d.date,value:d.totalAbsent})}
                />
                {d.totalAbsent===0&&d.totalStudents>0&&<rect x={barX} y={baselineY-2} width={barWidth} height={2} fill="#10b981" rx={1}/>}
                {segments.map(seg=>{
                  const isHoveredClass=hoveredPoint?.hoveredClassId===seg.id;
                  return (
                    <rect key={seg.id} x={seg.segX} y={seg.segY} width={seg.segW} height={seg.segH} fill={seg.color} rx={seg.isTop?2:0}
                      stroke={isHoveredClass?'#ffffff':'rgba(0,0,0,0.2)'} strokeWidth={isHoveredClass?1.5:0.5}
                      style={{cursor:'pointer',opacity:hoveredPoint&&hoveredPoint.date!==d.date?0.35:(hoveredPoint?.hoveredClassId&&!isHoveredClass?0.65:1),filter:isHoveredClass?'brightness(1.2)':'none',transition:'opacity 0.12s, filter 0.12s'}}
                      onMouseEnter={e=>{
                        const rect=svgWrapRef.current?.getBoundingClientRect();
                        setHoveredPoint({date:d.date,totalAbsent:d.totalAbsent,totalStudents:d.totalStudents,totalPresent:d.totalPresent,classes:d.classes,hoveredClassId:seg.id,mouseX:rect?e.clientX-rect.left:0,mouseY:rect?e.clientY-rect.top:0});
                      }}
                      onClick={e=>{e.stopPropagation();onSelect({...seg,id:seg.id,date:d.date,source:'sessions'});}}
                    />
                  );
                })}
              </g>
            );
          })}
        </svg>
        {hoveredPoint&&(()=>{
          const wrapWidth=svgWrapRef.current?.clientWidth||700;
          const tooltipWidth=295;
          const isRightSide=(hoveredPoint.mouseX||0)>wrapWidth*0.52;
          const tooltipLeft=isRightSide?Math.max(8,(hoveredPoint.mouseX||0)-tooltipWidth-14):Math.min(Math.max(8,(hoveredPoint.mouseX||0)+14),wrapWidth-tooltipWidth-8);
          const hoveredClass=hoveredPoint.hoveredClassId?hoveredPoint.classes.find(c=>c.id===hoveredPoint.hoveredClassId):null;
          const sortedClasses=hoveredClass?[hoveredClass,...hoveredPoint.classes.filter(c=>c.id!==hoveredClass.id)]:hoveredPoint.classes;
          return (
            <div className="class-absence-tooltip" style={{left:tooltipLeft,top:6}}>
              <div className="class-absence-tooltip-head">
                <div className="tooltip-date-row">
                  <strong>{display(hoveredPoint.date)}</strong>
                  <span className="tooltip-badge">{hoveredPoint.classes.length} {hoveredPoint.classes.length===1?'class':'classes'}</span>
                </div>
                <div className="tooltip-summary-stat">
                  <span>Total: <b>{hoveredPoint.totalAbsent} of {hoveredPoint.totalStudents}</b> absent</span>
                  {hoveredPoint.totalStudents>0&&<span className="tooltip-rate">({((hoveredPoint.totalPresent/hoveredPoint.totalStudents)*100).toFixed(1)}% present)</span>}
                </div>
              </div>
              <div className="class-absence-tooltip-list">
                {sortedClasses.map((cls,idx)=>{
                  const isHovered=hoveredPoint.hoveredClassId===cls.id;
                  return (
                    <div key={cls.id||idx} className={`class-absence-item ${isHovered?'highlighted':''}`}>
                      <div className="class-absence-item-title">
                        <span className="class-absence-item-dot" style={{background:cls.color}}/>
                        <strong className="class-name">{cls.title||cls.subject}</strong>
                        {isHovered&&<span className="hovered-chip">Hovered</span>}
                      </div>
                      <div className="class-absence-item-meta">
                        <span>{cls.subject}</span> · <span>{cls.batch}</span> · <span>{cls.semester}</span>{cls.cohort?` · ${cls.cohort}`:''}
                      </div>
                      <div className="class-absence-item-stat">
                        <span className="stat-absent">{cls.absent} of {cls.total} students absent</span>
                        <span className="stat-present">({cls.present} present · {cls.rate}%)</span>
                      </div>
                    </div>
                  );
                })}
              </div>
              {hoveredPoint.classes.length>3&&(
                <div className="tooltip-scroll-hint">
                  Showing {hoveredPoint.classes.length} classes · scroll to view more
                </div>
              )}
            </div>
          );
        })()}
      </div>
    </div>
  );
}

function Heatmap({chart,onSelect}:{chart:Chart;onSelect:(row:Point)=>void}){
  const rows=chart.row_entities?.map(row=>[row.id,row.name] as [string,string])??[...new Map(chart.rows.map(r=>[String(r.row_id??r.row),String(r.row)])).entries()];const cols=[...new Set(chart.rows.map(r=>String(r.column)))].sort((a,b)=>a.localeCompare(b));
  const max=Math.max(1,...chart.rows.map(r=>number(r.value)??0));
  return <div className="heatmap-wrap"><table className="heatmap"><thead><tr><th>{chart.id==='attendance-5'?'Student':'Group'}</th>{cols.map(c=><th key={c}>{display(c)}</th>)}</tr></thead><tbody>{rows.map(([rowId,rowLabel])=><tr key={rowId}><td className="heatmap-row-label" title={rowLabel}>{rowLabel}</td>{cols.map(c=>{const point=chart.rows.find(p=>String(p.row_id??p.row)===rowId&&String(p.column)===c);const value=number(point?.value);const strength=number(point?.total_strength);const sessions=Array.isArray(point?.sessions)?point.sessions as Point[]:[];const uniqueLabel=chart.heatmap_mode==='unique'&&value!=null&&strength!=null?`${Math.round(value)}/${Math.round(strength)}`:null;const title=chart.heatmap_mode==='absolute'&&sessions.length?sessions.map(s=>`${String(s.subject)} — ${String(s.attended)}/${String(s.eligible)} attended`).join('\n'):`${rowLabel} · ${display(c)} · ${value==null?'No evidence':uniqueLabel?`${uniqueLabel} unique attenders`:value+chart.unit}`;const scaleValue=chart.heatmap_mode==='unique'&&strength?value!/strength:max?value!/max:0;const color=value==null?'var(--surface2)':chart.unit==='%'?(value>=85?'#168a5a':value>=65?'#b8740a':'#cc3b35'):`rgba(36,87,214,${.2+.8*scaleValue})`;return <td key={c}><button className={chart.heatmap_mode==='absolute'?'session-cell':undefined} title={title} style={{background:color,color:value==null?'var(--muted)':'white'}} disabled={!point||value==null} onClick={()=>point&&onSelect(point)}>{chart.heatmap_mode==='absolute'&&sessions.length?sessions.map((s,index)=><span key={`${String(s.session_id)}-${index}`}>{abbreviateWords(s.subject)}: {String(s.attended)}</span>):value==null?'—':uniqueLabel??`${Math.round(value*10)/10}${chart.unit??''}`}</button></td>;})}</tr>)}</tbody></table></div>;
}
function Timeline({chart,onSelect}:{chart:Chart;onSelect:(row:Point)=>void}){
  const dates=chart.rows.flatMap(r=>[Date.parse(String(r.created_at)),Date.parse(String(r.due_date))]);const start=Math.min(...dates);const end=Math.max(...dates,start+86400000);
  return <div className="gantt"><div className="gantt-scale"><span>{display(new Date(start).toISOString())}</span><span>{display(new Date(end).toISOString())}</span></div>{chart.rows.map((r,i)=><button className="gantt-row" key={String(r.id??i)} onClick={()=>onSelect(r)}><span>{String(r.title)}<small>{String(r.owner)}</small></span><div className="gantt-track"><i style={{left:`${(Math.min(Date.parse(String(r.created_at)),Date.parse(String(r.due_date)))-start)/(end-start)*100}%`,width:`${Math.max(1,Math.abs(Date.parse(String(r.due_date))-Date.parse(String(r.created_at)))/(end-start)*100)}%`,background:palette[i%palette.length]}}/></div><span className="small-text">{String(r.status)}</span></button>)}</div>;
}
function Plot({chart,onSelect,filters}:{chart:Chart;onSelect:(row:Point)=>void;filters?:Filters}){
  const type=chart.render_as||chart.type;
  if(type==='class_absences'||chart.id==='attendance-2')return <ClassAbsenceChart chart={chart} onSelect={onSelect} globalFilters={filters}/>;
  if(type==='heatmap')return <Heatmap chart={chart} onSelect={onSelect}/>;
  if(type==='spark'&&chart.rows.some(r=>r.row!=null)){
    const students=[...new Set(chart.rows.map(r=>String(r.row)))];
    return <div className="spark-rows">{students.map(student=>{const points=chart.rows.filter(r=>r.row===student);let pen=false;const path=points.map((p,i)=>{const value=number(p.value);if(value==null){pen=false;return '';}const x=points.length===1?60:i/(points.length-1)*120;const command=pen?'L':'M';pen=true;return `${command}${x},${28-value/100*24}`;}).join(' ');return <button key={student} onClick={()=>onSelect({name:student})}><span>{student}</span><svg viewBox="0 0 120 32" aria-label={`${student} recorded attendance trend`}><path d={path} fill="none" stroke="var(--accent)" strokeWidth="2"/></svg><b>{display(points.at(-1)?.value)}%</b></button>;})}</div>;
  }
  if(type==='gantt')return <Timeline chart={chart} onSelect={onSelect}/>;
  if(type==='funnel'){
    const max=Math.max(1,...chart.rows.map(r=>number(r.value)??0));return <div className="funnel">{chart.rows.map((r,i)=><button key={i} onClick={()=>onSelect(r)}><span>{String(r.name)}</span><i style={{width:`${Math.max(4,(number(r.value)??0)/max*100)}%`,background:palette[i%palette.length]}}>{String(r.value)}</i></button>)}</div>;
  }
  if(type==='stacked'){
    const total=chart.rows.reduce((sum,r)=>sum+(number(r.value)??0),0);return <div className="stacked-chart"><div className="stacked-track">{chart.rows.map((r,i)=><button key={i} title={`${r.name}: ${r.value}`} style={{width:`${total?(number(r.value)??0)/total*100:0}%`,background:palette[i%palette.length]}} onClick={()=>onSelect(r)}>{String(r.value)}</button>)}</div><div className="chart-legend">{chart.rows.map((r,i)=><button key={i} onClick={()=>onSelect(r)}><i style={{background:palette[i%palette.length]}}/>{String(r.name)} <b>{String(r.value)}</b></button>)}</div></div>;
  }
  if(type==='scatter')return <div className="chart"><ResponsiveContainer width="100%" height="100%"><ScatterChart margin={{top:15,right:25,bottom:20,left:0}}><CartesianGrid stroke="var(--line)" strokeDasharray="3 3"/><XAxis dataKey="x" name="Attendance" type="number" domain={[0,100]} unit="%" tick={{fontSize:10,fill:'var(--muted)'}}/><YAxis dataKey="y" name="Average score" type="number" domain={[0,100]} unit="%" tick={{fontSize:10,fill:'var(--muted)'}}/><Tooltip contentStyle={{background:'var(--surface)',border:'1px solid var(--line)'}}/><Scatter data={chart.rows} fill={palette[0]} onClick={p=>{if(p?.payload)onSelect(p.payload as Point);}}/></ScatterChart></ResponsiveContainer></div>;
  const horizontal=type==='hbar';const lines=type==='line'||type==='spark';
  return <div className={`chart ${horizontal&&chart.rows.length>6?'tall-chart':''}`}><ResponsiveContainer width="100%" height="100%"><ComposedChart data={chart.rows} layout={horizontal?'vertical':'horizontal'} margin={{top:15,right:type==='pareto'?20:25,bottom:10,left:horizontal?65:-15}} onClick={state=>{if(state?.activeLabel!=null){const point=chart.rows.find(r=>String(r.name)===String(state.activeLabel));if(point)onSelect(point);}}}>
    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--line)"/>
    <XAxis dataKey={horizontal?undefined:'name'} type={horizontal?'number':'category'} domain={horizontal&&chart.unit==='/5'?[0,5]:undefined} tickFormatter={v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}/.test(v)?new Date(`${v.slice(0,10)}T00:00:00`).toLocaleDateString('en-IN',{month:'short',day:'numeric'}):String(v).length>22?String(v).slice(0,20)+'…':String(v)} tickLine={false} axisLine={false} tick={{fontSize:10,fill:'var(--muted)'}} minTickGap={20}/>
    <YAxis dataKey={horizontal?'name':undefined} type={horizontal?'category':'number'} width={horizontal?(chart.id==='trends-4'?60:105):50} domain={!horizontal&&chart.unit==='%'?[0,100]:undefined} tick={{fontSize:10,fill:'var(--muted)'}} tickFormatter={v=>chart.id==='trends-4'?abbreviateWords(v):horizontal&&String(v).length>22?String(v).slice(0,20)+'…':String(v)} tickLine={false} axisLine={false}/>
    {type==='pareto'&&<YAxis yAxisId="cumulative" orientation="right" domain={[0,100]} tick={{fontSize:10,fill:'var(--muted)'}} unit="%"/>}
    {chart.target!=null&&!horizontal&&<ReferenceLine y={chart.target} stroke="#168a5a" strokeDasharray="5 4" label={{value:`Target ${chart.target}${chart.unit}`,fontSize:10,fill:'#168a5a',position:'insideTopRight'}}/>}
    <Tooltip 
      contentStyle={{background:'var(--surface)',border:'1px solid var(--line)',borderRadius:7,color:'var(--ink)'}} 
      labelFormatter={v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}/.test(v)?new Date(`${v.slice(0,10)}T00:00:00`).toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'}):display(v)}
      formatter={(val: unknown, name: unknown, item: any) => {
        if(chart.provider==='attendance.overall_daily'){
          const tot = item?.payload?.total_students;
          return [`${Number(val).toLocaleString('en-IN')} students${tot ? ` (out of ${Number(tot).toLocaleString('en-IN')})` : ''}`, 'Absent students'];
        }
        return [display(val)+(chart.unit?chart.unit:''), chartColumnLabel(chart, String(name))];
      }}
    />
    {chart.series.map((series,i)=>lines||series==='cumulative'?<Line key={series} dataKey={series} name={series==='value'?chart.title:series} yAxisId={series==='cumulative'?'cumulative':0} type="linear" stroke={palette[i%palette.length]} strokeWidth={2} strokeDasharray={series==='Previous period'?'5 4':undefined} dot={{r:3}} connectNulls={false}/>:<Bar key={series} dataKey={series} name={series==='value'?chart.title:series} stackId={chart.stacked?'workload':undefined} fill={chart.provider==='attendance.overall_daily'?'#e0564c':palette[i%palette.length]} radius={horizontal?[0,3,3,0]:[3,3,0,0]} maxBarSize={42}>{chart.series.length===1&&chart.provider!=='attendance.overall_daily'&&chart.rows.map((_,j)=><Cell key={j} fill={palette[j%palette.length]}/>)}</Bar>)}
  </ComposedChart></ResponsiveContainer></div>;
}
function ChartCard({chart,onSelect,onPage,heatmapMode,onHeatmapMode,filters}:{chart:Chart;onSelect:(row:Point)=>void;onPage?:(page:number)=>void;heatmapMode?:string;onHeatmapMode?:(mode:string)=>void;filters?:Filters}){
  const [dataOpen,setDataOpen]=useState(false);const columns=[...new Set(chart.rows.flatMap(r=>Object.keys(r)))];
  const isClassAbsence=chart.id==='attendance-2'||chart.render_as==='class_absences';
  const isDailyAttendance=chart.id==='attendance-1';
  const isOverallDaily=chart.id==='attendance-overall'||chart.provider==='attendance.overall_daily';
  const isWide=['heatmap','gantt'].includes(chart.render_as||chart.type)||isClassAbsence||isDailyAttendance||isOverallDaily;
  const cardClasses=[
    isWide?'wide-chart':'',
    isClassAbsence?'class-absence-card':''
  ].filter(Boolean).join(' ');
  return <Card title={chart.title} subtitle={chart.status==='unavailable'?'Source data required':chart.status==='empty'?'Connected · no matching records':'Database-derived · selected filters'} className={cardClasses} action={<div className="chart-card-actions">{onHeatmapMode&&<label className="heatmap-mode"><span>View</span><select aria-label="Attendance heatmap view" value={heatmapMode} onChange={e=>onHeatmapMode(e.target.value)}><option value="percentage">Percentage</option><option value="absolute">Absolute by session</option><option value="unique">Unique attenders</option></select></label>}<span className={`chart-source ${chart.status}`} title={chart.provider||chart.note}>{chart.status==='unavailable'?<Info size={13}/>:<Database size={13}/>}</span></div>}>
    {chart.summary && (
      <div className="compact-metrics" style={{margin:'0 0 16px 0'}}>
        <div><span>Average daily absent students</span><strong>{chart.summary.avg_absent?.toLocaleString('en-IN') ?? '—'}</strong></div>
        <div><span>Average daily present students</span><strong>{chart.summary.avg_present?.toLocaleString('en-IN') ?? '—'}</strong></div>
        <div><span>Total active student base</span><strong>{chart.summary.total_students?.toLocaleString('en-IN') ?? '—'}</strong></div>
      </div>
    )}
    {chart.status==='unavailable'?<Empty title="Source unavailable for this chart" message={chart.note}/>:!chart.rows.length?<Empty title="No matching source records" message={chart.note||'This chart is connected to the database. No records match the selected filters in the connected production source.'}/>:<Plot chart={{...chart,rows:chart.plot_limit?chart.rows.slice(0,chart.plot_limit):chart.rows}} onSelect={onSelect} filters={filters}/>}
    {chart.note&&chart.status!=='unavailable'&&chart.rows.length>0&&<p className="source-note">{chart.note}</p>}
    {chart.page&&chart.page_size&&chart.total!=null&&<div className="pagination"><span>Students {(chart.page-1)*chart.page_size+1}–{Math.min(chart.page*chart.page_size,chart.total)} of {chart.total} · Page {chart.page} of {Math.max(1,Math.ceil(chart.total/chart.page_size))}</span><div><button className="button small" disabled={chart.page===1} onClick={()=>onPage?.(chart.page!-1)} aria-label="Previous student matrix page"><ChevronLeft size={15}/></button><button className="button small" disabled={chart.page*chart.page_size>=chart.total} onClick={()=>onPage?.(chart.page!+1)} aria-label="Next student matrix page"><ChevronRight size={15}/></button></div></div>}
    {chart.rows.length>0&&<><div className="plot-tools"><button className="text-link" onClick={()=>setDataOpen(v=>!v)}>{chart.plot_limit?(dataOpen?'Hide all':'View all'):`${dataOpen?'Hide':'View'} chart data`}</button><button className="text-link" onClick={()=>downloadData(chart)}><Download size={12}/> CSV</button></div>{dataOpen&&<div className="table-scroll"><table><thead><tr>{columns.map(c=><th key={c}>{chartColumnLabel(chart,c)}</th>)}</tr></thead><tbody>{chart.rows.map((r,i)=><tr key={i}>{columns.map(c=><td key={c}>{display(r[c])}{c==='value'&&r[c]!=null?chart.unit:''}</td>)}</tr>)}</tbody></table></div>}</>}
  </Card>;
}
export function ChartPanels({view,tab,filters,metric='feedback',granularity='weekly',breakdown='institution',onSelect}:{view:string;tab:string;filters:Filters;metric?:string;granularity?:string;breakdown?:string;onSelect?:(chart:Chart,point:Point)=>void}){
  const isMatrix=view==='attendance'&&tab==='matrix';
  const [matrixPage,setMatrixPage]=useState(1);const [studentStatus,setStudentStatus]=useState('active');const [matrixSemester,setMatrixSemester]=useState(filters.semester_id);const [matrixBatch,setMatrixBatch]=useState(filters.batch_id);const [attendanceHeatmapMode,setAttendanceHeatmapMode]=useState('percentage');
  useEffect(()=>{setMatrixPage(1);setStudentStatus('active');setMatrixSemester(filters.semester_id);setMatrixBatch(filters.batch_id);},[view,tab,filters.semester_id,filters.batch_id,filters.specialization_id,filters.graduation_year_id]);
  const options=useQuery({queryKey:['options'],queryFn:()=>api<Options>('/filters'),enabled:isMatrix});
  const matrixBatches=options.data?.batches.filter(b=>(!filters.specialization_id||b.specialization_id===filters.specialization_id)&&(!filters.graduation_year_id||b.graduation_year_id===filters.graduation_year_id)&&(!matrixSemester||b.semester_ids?.includes(matrixSemester)));
  const chartFilters=isMatrix?{...filters,semester_id:matrixSemester,batch_id:matrixBatch}:filters;
  const result=useQuery({queryKey:['original-charts',view,tab,chartFilters,metric,granularity,breakdown,matrixPage,studentStatus,attendanceHeatmapMode],queryFn:()=>api<{charts:Chart[]}>(`/charts/${view}/${tab}?${queryString({...chartFilters,metric,granularity,breakdown,matrix_page:matrixPage,student_status:studentStatus,attendance_heatmap_mode:attendanceHeatmapMode})}`),placeholderData:keepPreviousData});
  const controls=isMatrix&&<div className="matrix-filters"><label>Enrollment status<select value={studentStatus} onChange={e=>{setStudentStatus(e.target.value);setMatrixPage(1);}}><option value="active">Active students</option><option value="dropped">Dropped students</option><option value="all">Active and dropped</option></select></label><label>Semester<select value={matrixSemester} onChange={e=>{setMatrixSemester(e.target.value);setMatrixBatch('');setMatrixPage(1);}}><option value="">All semesters</option>{options.data?.semesters.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Batch<select value={matrixBatch} onChange={e=>{setMatrixBatch(e.target.value);setMatrixPage(1);}}><option value="">All batches</option>{matrixBatches?.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></label></div>;
  if(result.isPending)return <>{controls}<Loading/></>;if(result.error)return <>{controls}<ErrorState error={result.error} retry={()=>void result.refetch()}/></>;
  const rawCharts=result.data?.charts||[];
  const orderedCharts=[...rawCharts].sort((a,b)=>{
    if(view==='attendance'&&tab==='daily'){
      if(a.id==='attendance-2')return -1;
      if(b.id==='attendance-2')return 1;
    }
    return 0;
  });
  return <>{controls}<div className={`original-charts ${result.isFetching && !result.isPending ? 'is-fetching' : ''}`}>{orderedCharts.map(c=><ChartCard key={c.id} chart={c} onSelect={point=>onSelect?.(c,point)} onPage={c.id==='attendance-5'?setMatrixPage:undefined} heatmapMode={c.id==='trends-5'&&metric==='att'?attendanceHeatmapMode:undefined} onHeatmapMode={c.id==='trends-5'&&metric==='att'?setAttendanceHeatmapMode:undefined} filters={chartFilters}/>)}</div></>;
}
