"use client";
import {useEffect,useState} from 'react';
import {api,errorText} from '@/lib/api';
import type {LearningSet,LearningItem,SourcePDF,PageRange,PageTarget,PageLocations} from '@/lib/learning';
import {PdfPreview} from './pdf-preview';

type Metadata={source_pdf:SourcePDF;explicit_page_labels:boolean;numeric_labels:Record<string,number[]>};
type Plan={base_fingerprint:string;plan_fingerprint:string;pending:number;has_changes:boolean;report:Extract<PageLocations,{available:true}>};
export function DirectoryPageMapping({row,node}:{row:LearningSet;node:LearningItem}) {
  const stale=!!(row.page_locations?.available&&row.page_locations.stale);
  const [file,setFile]=useState<File|null>(null),[meta,setMeta]=useState<Metadata|null>(null);
  const [ranges,setRanges]=useState<PageRange[]>((row.page_mapping?.ranges||[]).map(rule=>({...rule,verified:!stale&&rule.verified}))),[targets,setTargets]=useState<PageTarget[]>((row.page_mapping?.entry_targets||[]).map(target=>({...target,verified:!stale&&target.verified})));
  const [plan,setPlan]=useState<Plan|null>(null),[requestKey,setRequestKey]=useState(''),[confirmed,setConfirmed]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[saved,setSaved]=useState<{id:string;version:number}|null>(null);
  const [view,setView]=useState<{page:number;label:string}|null>(null);
  const [rangeDraft,setRangeDraft]=useState({printed_start:'',printed_end:'',pdf_start:'',pdf_end:'',verified:false});
  const base=`/learning/${row.id}`;
  const source=meta?.source_pdf||row.directory_reference?.source_pdf||null;
  const report=plan?.report||(row.page_locations?.available?row.page_locations:null);
  const entryId=node.source_entry_id;
  const target=targets.find(item=>item.entry_id===entryId);
  const location=report?.locations.find(item=>item.entry_id===entryId);
  const candidates=node.directory?.printed_page!==null&&node.directory?.printed_page!==undefined?meta?.numeric_labels[String(node.directory.printed_page)]||[]:[];
  function reset(){setPlan(null);setSaved(null);setConfirmed(false);setRequestKey('');}
  useEffect(()=>{setView(null);},[node.id]);
  useEffect(()=>{if(stale){setRanges(values=>values.map(rule=>({...rule,verified:false})));setTargets(values=>values.map(target=>({...target,verified:false})));reset();}},[stale]);
  async function choose(file:File){
    setBusy(true);setError('');setView(null);setFile(null);setMeta(null);reset();
    try{
      const body=new FormData();body.append('file',file);
      const value=await api<Metadata>(`${base}/pdf-page-metadata`,{method:'POST',body});
      const bound=row.directory_reference?.source_pdf;
      if(bound&&(bound.sha256!==value.source_pdf.sha256||bound.total_pages!==value.source_pdf.total_pages))throw new Error('该PDF与当前版本绑定的文件不同，请选择原文件');
      setMeta(value);setFile(file);
    }catch(reason){setError(errorText(reason));}finally{setBusy(false);}
  }
  function updateTarget(page:string,verified=false){
    if(!entryId)return;
    setTargets(previous=>[...previous.filter(item=>item.entry_id!==entryId),...(page?[{entry_id:entryId,pdf_page:Number(page),verified}]:[])]);reset();
  }
  function addRange(){
    const values=[rangeDraft.printed_start,rangeDraft.printed_end,rangeDraft.pdf_start,rangeDraft.pdf_end];
    if(values.some(value=>!value||!Number.isInteger(Number(value))||Number(value)<1)){setError('请填写区间的四个起止页码');return;}
    setRanges(previous=>[...previous,{printed_start:Number(values[0]),printed_end:Number(values[1]),pdf_start:Number(values[2]),pdf_end:Number(values[3]),verified:rangeDraft.verified}]);
    setRangeDraft({printed_start:'',printed_end:'',pdf_start:'',pdf_end:'',verified:false});setError('');reset();
  }
  async function preview(){
    if(!source)return;
    setBusy(true);setError('');setSaved(null);setConfirmed(false);const key=crypto.randomUUID();setRequestKey(key);
    try{
      const value=await api<Plan>(`${base}/page-mapping/preview`,{method:'POST',body:JSON.stringify({source_pdf:source,ranges,entry_targets:targets,request_key:key})});
      setPlan(value);
    }catch(reason){setPlan(null);setError(errorText(reason));}finally{setBusy(false);}
  }
  async function save(){
    if(!plan||!source||!confirmed)return;
    setBusy(true);setError('');
    try{setSaved(await api<LearningSet>(`${base}/page-mapping`,{method:'POST',body:JSON.stringify({source_pdf:source,ranges,entry_targets:targets,request_key:requestKey,confirmed:true,base_fingerprint:plan.base_fingerprint,plan_fingerprint:plan.plan_fingerprint})}));}
    catch(reason){setError(errorText(reason));}finally{setBusy(false);}
  }
  function open(page:number,label:string){
    if(!file||!source||!Number.isInteger(page)||page<1||page>source.total_pages){setError('请先选择匹配的原PDF，并核对页码范围');return;}
    setError('');setView({page,label});
  }
  return <details className="directory-page-mapping">
    <summary>PDF页码定位 · {report?`已核对 ${report.mapped} / ${report.entries} 项`:'尚未校准'}</summary>
    <p className="muted">书内印刷页码与PDF页码分开记录。只定位明确核对的单条位置或连续区间，区间外不推算。</p>
    <label>选择原PDF，核对页数和页码标签<input aria-label="页码校准原PDF" type="file" accept=".pdf,application/pdf" disabled={busy} onChange={event=>{const next=event.target.files?.[0];if(next)void choose(next);event.target.value='';}}/></label>
    <p className="muted">文件不入库，不提取正文，不调用模型。只有点击预览页时，才在浏览器中显示所选页面。</p>
    {source&&<p>{source.total_pages}个PDF页面 · {file?'原文件已选择':'选择本机原文件后可预览页面'}</p>}
    {meta&&!meta.explicit_page_labels&&<p className="source-warning">PDF未提供页码标签，不会按固定偏移猜测正文位置。</p>}
    {report?.stale&&<p className="source-warning">{report.reason}；旧映射不会用于跳转。</p>}
    <div className="learning-toolbar">
      {node.directory?.toc_pdf_page&&<button className="button" disabled={!file||busy} onClick={()=>open(node.directory!.toc_pdf_page!,'目录来源页')}>查看目录PDF第{node.directory.toc_pdf_page}页</button>}
      <button className="button" disabled={!file||busy||!location?.verified} onClick={()=>open(location!.body_pdf_page!,(plan?'按预览规则定位，尚未保存':'当前版本已核对的正文位置'))}>{plan?'按预览规则定位':'定位当前版本正文'}</button>
    </div>
    {entryId&&<section className="page-target-editor" aria-label="当前目录条目定位">
      <h4>{node.title}</h4><p className="muted">书内页码：{node.directory?.printed_page??'未识别'}；{plan?'预览规则':'当前版本'}：{location?.verified?`已核对PDF第${location.body_pdf_page}页`:'正文位置尚未核对'}。</p>
      {!!candidates.length&&<p className="muted">PDF页码标签候选：{candidates.map(page=><button key={page} className="text-button" disabled={busy} onClick={()=>updateTarget(String(page))}>PDF第{page}页</button>)}。标签只作候选，不自动确认。</p>}
      {node.directory?.target_pdf_page&&!target&&<p className="muted">旧记录含PDF第{node.directory.target_pdf_page}页位置，尚未按当前文件核对。<button className="text-button" disabled={busy} onClick={()=>updateTarget(String(node.directory!.target_pdf_page))}>填为待核对候选</button></p>}
      <label>当前条目对应的PDF页码<input aria-label="当前条目PDF定位页" type="number" min={1} max={source?.total_pages} value={target?.pdf_page??''} disabled={busy} onChange={event=>updateTarget(event.target.value)}/></label>
      <div className="learning-toolbar"><button className="text-button" disabled={!file||busy||!target?.pdf_page} onClick={()=>open(target!.pdf_page,'候选页面，尚未确认目录对应关系')}>先预览候选页</button>
        <label className="copy-option"><input aria-label="确认单条PDF定位" type="checkbox" disabled={busy||!source||!target} checked={!!target?.verified} onChange={event=>updateTarget(String(target!.pdf_page),event.target.checked)}/>我已核对该条目与PDF位置一致</label>
      </div>
    </section>}
    {targets.length>0&&<details><summary>已设置单条定位（{targets.length}）</summary>{targets.map(item=><div className="page-range-row" key={item.entry_id}><span>{row.items?.find(node=>node.source_entry_id===item.entry_id)?.title||`已不在目录中的条目 ${item.entry_id}`} → PDF第{item.pdf_page}页 · {item.verified?'已核对':'待核对'}</span><button className="text-button" disabled={busy} onClick={()=>{setTargets(values=>values.filter(value=>value.entry_id!==item.entry_id));reset();}}>移除定位</button></div>)}</details>}
    <details><summary>连续页码区间（{ranges.length}）</summary>
      <p className="muted">只有起止位置和中间连续性都已核对时才使用区间。缺页、插页或重新编号时请拆段，或使用单条定位。</p>
      {ranges.map((rule,index)=><div className="page-range-row" key={index}><span>书内{rule.printed_start}–{rule.printed_end}页 → PDF {rule.pdf_start}–{rule.pdf_end}页</span><label className="copy-option"><input aria-label={`确认区间${index+1}`} type="checkbox" checked={rule.verified} disabled={busy} onChange={event=>{setRanges(values=>values.map((item,i)=>i===index?{...item,verified:event.target.checked}:item));reset();}}/>已核对连续</label><button className="text-button" disabled={busy} onClick={()=>{setRanges(values=>values.filter((_,i)=>i!==index));reset();}}>移除</button></div>)}
      <div className="page-range-inputs">{([['printed_start','书内起页'],['printed_end','书内止页'],['pdf_start','PDF起页'],['pdf_end','PDF止页']] as const).map(([key,label])=><label key={key}>{label}<input type="number" aria-label={label} min={1} value={rangeDraft[key]} disabled={busy} onChange={event=>setRangeDraft(value=>({...value,[key]:event.target.value}))}/></label>)}</div>
      <label className="copy-option"><input type="checkbox" checked={rangeDraft.verified} disabled={busy} onChange={event=>setRangeDraft(value=>({...value,verified:event.target.checked}))}/>已核对区间起止位置和中间页连续性</label>
      <button className="text-button" disabled={busy||!source} onClick={addRange}>添加这个区间</button>
    </details>
    <button className="button" disabled={busy||!source} onClick={preview}>预览页码校准结果</button>
    {busy&&<p className="muted" role="status">正在核对页码设置…</p>}
    {error&&<p className="document-error" role="alert">{error}</p>}
    {plan&&<section aria-label="页码校准结果">
      <p>已核对{plan.report.mapped}项，未定位{plan.report.unmapped}项；未定位条目继续保留。节点内容与层级不变。</p>
      {plan.pending>0&&<p className="source-warning">还有{plan.pending}项单条定位或区间未确认，暂不能保存。</p>}
      {!plan.has_changes?<p className="muted">设置没有变化。</p>:saved?<p role="status">已生成第{saved.version}版。<a href={`?tab=mindmap&item=${saved.id}`}>打开新版本</a>；原版保留。</p>:<>
        <label className="copy-option"><input aria-label="确认PDF校准方案" type="checkbox" checked={confirmed} disabled={busy||plan.pending>0} onChange={event=>setConfirmed(event.target.checked)}/>确认PDF对应当前目录，按以上已核对位置保存新版</label>
        <button className="button primary" disabled={busy||!confirmed||plan.pending>0} onClick={save}>保存校准新版</button>
      </>}
    </section>}
    {view&&file&&<section className="directory-local-pdf" aria-label="原PDF本地预览"><div className="learning-toolbar"><span>{view.label} · PDF第{view.page}页</span><button className="text-button" onClick={()=>setView(null)}>收起预览</button></div><PdfPreview key={file.name+view.page} file={file} page={view.page} filename={file.name}/></section>}
  </details>;
}
