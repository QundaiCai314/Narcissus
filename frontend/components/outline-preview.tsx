"use client";
import { useRef,useState } from "react";
import { api, errorText } from "@/lib/api";
import type {LearningSet,SourcePDF} from '@/lib/learning';
import {MindMap} from './mind-map';

type Entry = {id:string;parent_id:string|null;level:number;kind:string;number?:string|null;title:string;
  toc_pdf_page:number|null;printed_page:number|null;target_pdf_page:number|null;needs_review:boolean;reviewed?:boolean;user_corrected?:boolean;visually_checked?:boolean};
type Result = {status:string;method:string;total_pdf_pages:number;pages_read:number[];ocr_pages:number[];
  model_calls:number;embedding_calls:number;entries:Entry[];warnings:string[];
  unparsed_lines:{text:string;toc_pdf_page:number;reason:string}[];
  ignored_headers?:{text:string;toc_pdf_page:number}[];source_name?:string;title?:string;failed_pages?:{pdf_page:number}[];source_pdf?:SourcePDF};

export function OutlinePreview({notebookId,onBusy}:{notebookId:string;onBusy:(value:boolean)=>void}) {
  const [file,setFile]=useState<File|null>(null),[pages,setPages]=useState("");
  const [result,setResult]=useState<Result|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
  const [progress,setProgress]=useState("");
  const [mapRow,setMapRow]=useState<LearningSet|null>(null),[sourceName,setSourceName]=useState(''),[mapTitle,setMapTitle]=useState(''),[confirmed,setConfirmed]=useState(false),[savedId,setSavedId]=useState('');
  const saveKey=useRef('');
  const pending=result?.entries.filter(entry=>entry.needs_review&&!entry.reviewed).length||0;
  function acceptResult(next:Result,name:string){
    const byId=new Map(next.entries.map(entry=>[entry.id,entry]));
    const entries=next.entries.map(entry=>{let level=1,current=entry;const seen=new Set([entry.id]);while(current.parent_id&&level<12&&!seen.has(current.parent_id)){seen.add(current.parent_id);const parent=byId.get(current.parent_id);if(!parent)break;current=parent;level++;}return {...entry,level};});
    setResult({...next,entries});setSourceName(next.source_name||name);setMapTitle((next.title||next.source_name||name).replace(/\.[^.]+$/,'').replace(/ · 目录导图$/,'').slice(0,100));setMapRow(null);setSavedId('');setConfirmed(false);saveKey.current='';
  }
  async function importJson(file:File){
    setError('');
    try{
      if(file.size>3*1024*1024)throw new Error('目录JSON不能超过3MB');
      const value=JSON.parse(await file.text());
      if(!Array.isArray(value.entries)||!value.entries.length||value.entries.length>2000||!value.entries.every((e:Entry)=>e&&typeof e.id==='string'&&typeof e.title==='string'))throw new Error('请选择目录核对导出的JSON文件');
      if(['pages_read','ocr_pages','warnings','unparsed_lines','failed_pages','ignored_headers'].some(key=>value[key]!==undefined&&!Array.isArray(value[key])))throw new Error('目录JSON字段格式错误');
      if(['source_name','title'].some(key=>value[key]!==undefined&&typeof value[key]!=='string'))throw new Error('目录名称必须是文字');
      if(value.warnings?.some((item:unknown)=>typeof item!=='string')||value.unparsed_lines?.some((item:{text?:unknown})=>!item||typeof item.text!=='string'))throw new Error('目录核对记录格式错误');
      if(new Set(value.entries.map((e:Entry)=>e.id)).size!==value.entries.length)throw new Error('目录节点编号重复');
      acceptResult({...value,entries:value.entries.map((e:Entry)=>({...e,reviewed:e.reviewed||e.visually_checked||false})),pages_read:value.pages_read||[],ocr_pages:value.ocr_pages||[],warnings:value.warnings||[],unparsed_lines:value.unparsed_lines||[],model_calls:0,embedding_calls:0},file.name);
    }catch(reason){setError(errorText(reason));}
  }
  function edit(id:string,change:Partial<Entry>){
    setResult(previous=>previous?{...previous,entries:previous.entries.map(entry=>entry.id===id?{...entry,...change}:entry)}:previous);
    setMapRow(null);setSavedId('');setConfirmed(false);saveKey.current='';
  }
  function payload(){
    if(!result)throw new Error('请先识别或导入目录');
    if(!saveKey.current)saveKey.current=crypto.randomUUID();
    return {title:mapTitle,source_name:sourceName,entries:result.entries,pages_read:result.pages_read,source_pdf:result.source_pdf,unresolved_lines:result.unparsed_lines.length,failed_pages:(result.failed_pages||[]).map(page=>page.pdf_page),confirmed,request_key:saveKey.current};
  }
  async function buildMap(save=false){
    setBusy(true);onBusy(true);setError('');setProgress('');
    try{
      const body=JSON.stringify(payload());
      if(save){const row=await api<LearningSet>(`/notebooks/${notebookId}/outline-map`,{method:'POST',body});setMapRow(row);setSavedId(row.id);}
      else{
        const compiled=await api<{items:LearningSet['items'];outline:NonNullable<LearningSet['outline']>}>(`/notebooks/${notebookId}/outline-map/preview`,{method:'POST',body});
        setMapRow({id:'directory-preview',family_id:'directory-preview',version:1,kind:'mindmap',title:mapTitle,params:{origin:'outline',topic:mapTitle,audience:'',difficulty:'standard',count:compiled.items?.length||0},status:'complete',phase:'complete',attempts:0,error:null,warning:null,created_at:new Date().toISOString(),completed_at:null,model:null,count:compiled.items?.length||0,sources:[],...compiled});
      }
    }catch(reason){setError(errorText(reason));}finally{setBusy(false);onBusy(false);}
  }
  async function run() {
    if(!file)return;
    setBusy(true);onBusy(true);setError("");setResult(null);setMapRow(null);setProgress('正在检查PDF目录…');
    try {
      const body=new FormData();body.append('file',file);body.append('pages',pages);
      const job=await api<{job_id:string}>(`/notebooks/${notebookId}/outline-preview`,{method:'POST',body});
      const deadline=Date.now()+660000;
      while(Date.now()<deadline){
        const state=await api<{status:string;completed_pages:number;total_pages:number;result?:Result;error?:string}>(`/notebooks/${notebookId}/outline-preview/${job.job_id}`);
        if(state.status==='error')throw new Error(state.error||'目录识别失败');
        if(state.status==='done'&&state.result){acceptResult(state.result,file.name);return;}
        setProgress(state.total_pages?`本地识别目录 ${state.completed_pages} / ${state.total_pages} 页，扫描件可能需要几分钟…`:'正在检查PDF目录…');
        await new Promise(resolve=>setTimeout(resolve,2000));
      }
      throw new Error('目录识别超时，请缩小页码范围后重试');
    }catch(reason){setError(errorText(reason));}finally{setBusy(false);onBusy(false);}
  }
  function download(format:'json'|'md') {
    if(!result)return;
    const readable=['# 目录核对',`读取PDF页码：${result.pages_read.join(', ')||'仅书签'}；大模型调用0次。`,
      '待核对标记不代表已经确认；书内页码未换算成PDF正文位置。','',
      ...result.entries.map(entry=>`${'  '.repeat(Math.max(0,entry.level-1))}- ${entry.number||''} ${entry.title}${entry.printed_page!==null?`（书内${entry.printed_page}页）`:''}${entry.needs_review&&!entry.reviewed?' [待核对]':''}`),
      '',...result.unparsed_lines.map(line=>`- 未解析（PDF第${line.toc_pdf_page}页）：${line.text}`),...result.warnings.map(warning=>`- 提醒：${warning}`)].join('\n');
    const url=URL.createObjectURL(new Blob([format==='json'?JSON.stringify(result,null,2):readable],{type:format==='json'?'application/json;charset=utf-8':'text/markdown;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download=`narcissus-outline.${format}`;link.click();URL.revokeObjectURL(url);
  }
  return <div className="outline-preview">
    <p className="muted">只读取书签或指定目录页，在本地识别。不会导入全文、建立向量或调用模型。</p>
    <label>选择PDF<input aria-label="目录识别PDF" type="file" accept=".pdf" disabled={busy}
      onChange={event=>{setFile(event.target.files?.[0]||null);setResult(null);setError("");}}/></label>
    <label>目录所在的PDF页码<input aria-label="目录PDF页码" value={pages} disabled={busy} placeholder="例如12-20；留空只检查书签"
      onChange={event=>{setPages(event.target.value);setResult(null);}}/></label>
    <p className="muted">使用阅读器显示的PDF页码，每次最多12页。书内印刷页码可能不同。</p>
    <label>或导入已核对的目录JSON<input aria-label="导入已核对目录JSON" type="file" accept=".json,application/json" disabled={busy} onChange={event=>{const file=event.target.files?.[0];if(file)void importJson(file);event.target.value='';}}/></label>
    <button className="button primary" disabled={!file||busy} onClick={run}>{busy?'正在处理…':'识别目录'}</button>
    {busy&&!mapRow&&progress&&<p className="muted" role="status" aria-live="polite">{progress}</p>}
    {error&&<p className="document-error" role="alert">{error}</p>}
    {result&&<section className="outline-result" aria-label="目录识别结果">
      {result.status==='needs_pages'?<p role="status">未找到书签。共{result.total_pdf_pages}页，请填写目录页范围后识别；尚未读取正文。</p>:<>
        <h3>目录核对</h3><p className="muted">{result.entries.length}个条目 · {result.entries.filter(e=>e.kind==='chapter').length}章 · 读取{result.pages_read.length}页 · 大模型调用{result.model_calls}次</p>
        {!!pending&&<p className="source-warning" role="status">还有{pending}个条目待核对。请修改标题或书内页码，再逐项勾选确认。</p>}
        <div className="outline-map-settings">
          <label>导图名称<input aria-label="目录导图名称" maxLength={100} value={mapTitle} disabled={busy} onChange={event=>{setMapTitle(event.target.value);setMapRow(null);setConfirmed(false);setSavedId('');saveKey.current='';}}/></label>
          <label>目录来源名称<input aria-label="目录来源名称" maxLength={240} value={sourceName} disabled={busy} onChange={event=>{setSourceName(event.target.value);setMapRow(null);setConfirmed(false);setSavedId('');saveKey.current='';}}/></label>
          <button className="button" disabled={busy||!mapTitle.trim()} onClick={()=>buildMap()}>预览目录导图</button>
        </div>
        {mapRow&&<section aria-label="目录导图预览">
          <MindMap key={mapRow.id} row={mapRow} onCitation={()=>{}} onAsk={()=>{}}/>
          {!savedId?<><label className="copy-option"><input type="checkbox" checked={confirmed} disabled={busy||pending>0} onChange={event=>setConfirmed(event.target.checked)}/>已核对目录层级与标记条目，保存为独立目录导图</label>
            <button className="button primary" disabled={busy||!confirmed||pending>0} onClick={()=>buildMap(true)}>{busy?'正在保存…':'保存到本笔记本'}</button></>:<p role="status">目录导图已保存。<a href={`/notebooks/${notebookId}?tab=mindmap&item=${savedId}`}>在工作区打开</a></p>}
        </section>}
        <details open={!mapRow}><summary>核对目录条目（{result.entries.length}）</summary>
        <p className="muted">标题和书内页码可修改。编号或父子关系不匹配时会阻止保存，不会自动省略节点。</p>
        <ol className="outline-entries">{result.entries.map(entry=><li key={entry.id} style={{paddingLeft:`${Math.min(entry.level-1,8)*16}px`}}>
          <span className="outline-number">{entry.number}</span>
          <input aria-label={`目录标题 ${entry.number||entry.title}`} value={entry.title} disabled={busy} onChange={event=>edit(entry.id,{title:event.target.value,user_corrected:true,needs_review:true,reviewed:false})}/>
          <label className="outline-page">书内页码<input aria-label={`书内页码 ${entry.number||entry.title}`} type="number" min={1} max={100000} value={entry.printed_page??''} disabled={busy} onChange={event=>edit(entry.id,{printed_page:event.target.value?Number(event.target.value):null,user_corrected:true,needs_review:true,reviewed:false})}/></label>
          {entry.needs_review&&<label><input type="checkbox" aria-label={`确认目录 ${entry.number||entry.title}`} checked={!!entry.reviewed} disabled={busy} onChange={event=>edit(entry.id,{reviewed:event.target.checked})}/>已核对</label>}
        </li>)}</ol></details>
        {!!result.unparsed_lines.length&&<details><summary>未可靠识别的行（{result.unparsed_lines.length}）</summary>
          {result.unparsed_lines.map((line,index)=><p key={index}>PDF第{line.toc_pdf_page}页：{line.text} · {line.reason}</p>)}
        </details>}
        {!!result.ignored_headers?.length&&<details><summary>已分离的重复页眉（{result.ignored_headers.length}）</summary>
          {result.ignored_headers.map((line,index)=><p key={index}>PDF第{line.toc_pdf_page}页：{line.text}</p>)}
        </details>}
        {!!result.warnings.length&&<p className="source-warning">{result.warnings.join('；')}</p>}
        <div className="learning-toolbar"><button className="button" onClick={()=>download('md')}>下载可读目录</button><button className="button" onClick={()=>download('json')}>下载目录JSON</button></div>
      </>}
    </section>}
  </div>;
}
