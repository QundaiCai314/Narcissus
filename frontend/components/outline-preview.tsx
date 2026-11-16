"use client";
import { useState } from "react";
import { api, errorText } from "@/lib/api";

type Entry = {id:string;parent_id:string|null;level:number;kind:string;number?:string|null;title:string;
  toc_pdf_page:number|null;printed_page:number|null;target_pdf_page:number|null;needs_review:boolean;user_corrected?:boolean};
type Result = {status:string;method:string;total_pdf_pages:number;pages_read:number[];ocr_pages:number[];
  model_calls:number;embedding_calls:number;entries:Entry[];warnings:string[];
  unparsed_lines:{text:string;toc_pdf_page:number;reason:string}[];
  ignored_headers?:{text:string;toc_pdf_page:number}[]};

export function OutlinePreview({notebookId,onBusy}:{notebookId:string;onBusy:(value:boolean)=>void}) {
  const [file,setFile]=useState<File|null>(null),[pages,setPages]=useState("");
  const [result,setResult]=useState<Result|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
  const [progress,setProgress]=useState("");
  async function run() {
    if(!file)return;
    setBusy(true);onBusy(true);setError("");setResult(null);setProgress('正在检查PDF目录…');
    try {
      const body=new FormData();body.append('file',file);body.append('pages',pages);
      const job=await api<{job_id:string}>(`/notebooks/${notebookId}/outline-preview`,{method:'POST',body});
      const deadline=Date.now()+660000;
      while(Date.now()<deadline){
        const state=await api<{status:string;completed_pages:number;total_pages:number;result?:Result;error?:string}>(`/notebooks/${notebookId}/outline-preview/${job.job_id}`);
        if(state.status==='error')throw new Error(state.error||'目录识别失败');
        if(state.status==='done'&&state.result){setResult(state.result);return;}
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
      ...result.entries.map(entry=>`${'  '.repeat(Math.max(0,entry.level-1))}- ${entry.number||''} ${entry.title}${entry.printed_page!==null?`（书内${entry.printed_page}页）`:''}${entry.needs_review?' [待核对]':''}`),
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
    <button className="button primary" disabled={!file||busy} onClick={run}>{busy?'正在本地识别目录…':'识别目录'}</button>
    {busy&&<p className="muted" role="status" aria-live="polite">{progress}</p>}
    {error&&<p className="document-error" role="alert">{error}</p>}
    {result&&<section className="outline-result" aria-label="目录识别结果">
      {result.status==='needs_pages'?<p role="status">未找到书签。共{result.total_pdf_pages}页，请填写目录页范围后识别；尚未读取正文。</p>:<>
        <h3>目录核对</h3><p className="muted">{result.entries.length}个条目 · {result.entries.filter(e=>e.kind==='chapter').length}章 · 读取{result.pages_read.length}页 · 大模型调用{result.model_calls}次</p>
        {result.status==='needs_review'&&<p className="source-warning" role="status">识别结果需要核对：{result.entries.filter(e=>e.needs_review).length}个条目待检查，{result.unparsed_lines.length}行未可靠识别。此结果尚未保存为正式知识结构。</p>}
        <p className="muted">标题可直接修改。未识别的行和待核对条目会保留，避免静默漏项。</p>
        <ol className="outline-entries">{result.entries.map(entry=><li key={entry.id} style={{paddingLeft:`${Math.min(entry.level-1,8)*16}px`}}>
          <span className="outline-number">{entry.number}</span>
          <input aria-label={`目录标题 ${entry.number||entry.title}`} value={entry.title} onChange={event=>setResult(previous=>previous?{...previous,entries:previous.entries.map(item=>item.id===entry.id?{...item,title:event.target.value,user_corrected:true}:item)}:previous)}/>
          <small>{entry.printed_page!==null?`书内 ${entry.printed_page} 页`:entry.target_pdf_page?`PDF ${entry.target_pdf_page} 页`:'页码待核对'}{entry.needs_review?' · 待核对':''}</small>
        </li>)}</ol>
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
