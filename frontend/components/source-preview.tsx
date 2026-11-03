"use client";
import {useCallback,useEffect,useRef,useState} from "react";
import {api,post,errorText} from "@/lib/api";
import {SourcePointer,SourceSnapshot,sourceNames,sourcePosition,importStates} from "@/lib/sources";
import {PdfPreview} from "./pdf-preview";

export function SourcePreview({pointer,onChanged,onDirty}:{pointer:SourcePointer;onChanged:()=>void;onDirty:(v:boolean)=>void}){
 const [version,setVersion]=useState(pointer.version),[data,setData]=useState<SourceSnapshot|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false),[editing,setEditing]=useState(false),[dirty,setDirty]=useState(false),[title,setTitle]=useState(""),[text,setText]=useState(""),[corrections,setCorrections]=useState<Record<string,string>>({}),[partial,setPartial]=useState(false),[copy,setCopy]=useState(false),[page,setPage]=useState(pointer.page||1);
 const dirtyRef=useRef(false),target=useRef<HTMLDivElement>(null);
 const load=useCallback(async()=>{const d=await api<SourceSnapshot>(`/documents/${pointer.document_id}/snapshot${version?`?version=${version}`:""}`);setData(d);if(!dirtyRef.current){setTitle(d.title);setText(d.units.map(u=>u.text).join("\n"));}return d;},[pointer.document_id,version]);
 useEffect(()=>{setData(null);load().catch(e=>setError(errorText(e)));},[load]);
 useEffect(()=>{if(!data||!["queued","processing","indexing"].includes(data.status))return;const t=setInterval(()=>load().catch(e=>setError(errorText(e))),2500);return()=>clearInterval(t);},[data,load]);
 useEffect(()=>{dirtyRef.current=dirty;onDirty(dirty||busy);const warn=(e:BeforeUnloadEvent)=>{if(dirty||busy){e.preventDefault();e.returnValue="";}};window.addEventListener("beforeunload",warn);return()=>window.removeEventListener("beforeunload",warn);},[dirty,busy,onDirty]);
 useEffect(()=>{target.current?.scrollIntoView({block:"center"});},[data?.version,data?.units.length]);
 async function action(path:string,body?:unknown,method="POST"){
  setBusy(true);setError("");try{await api(`/documents/${pointer.document_id}/${path}`,method==="POST"?post(body):{method,body:JSON.stringify(body)});dirtyRef.current=false;setDirty(false);setEditing(false);setCorrections({});onChanged();
   if(path==="content"||path==="reprocess"){const latest=await api<SourceSnapshot>(`/documents/${pointer.document_id}/snapshot`);setVersion(latest.versions[0].version);}else await load();
  }catch(e){setError(errorText(e));}finally{setBusy(false);}
 }
 if(!data)return <section className="import-panel">{error?<><p role="alert">{error}</p><button className="button" onClick={()=>load().catch(e=>setError(errorText(e)))}>重新加载</button></>:"正在加载原文…"}</section>;
 const pending=data.status==="awaiting_confirmation",latest=data.versions[0].version===data.version;
 const ocr=data.source_type==="pdf"||data.source_type==="image";
 const editable=latest&&["ready","failed","cancelled"].includes(data.status)&&(ocr?data.units.some(u=>u.ocr):data.source_type!=="docx");
 const file=`/api/documents/${data.document_id}/file?version=${data.version}`;
 return <section className="source-preview"><header><div><small>{sourceNames[data.source_type]} · {importStates[data.status]}</small><h2>{data.title}</h2></div><label>来源版本<select value={data.version} disabled={dirty||busy} onChange={e=>{setVersion(Number(e.target.value));setEditing(false);setPage(1);}}>{data.versions.map(v=><option key={v.version} value={v.version}>版本 {v.version} · {importStates[v.status]}</option>)}</select></label></header>
  {data.changed&&data.status==="ready"&&<p className="source-warning">资料已更新，当前展示引用所依据的历史版本。</p>}
  {data.details.user_adjusted&&<p className="source-warning">这是用户调整后的内容，原始获取快照或原件已保留。</p>}
  {data.source_url&&<p><a href={data.source_url} target="_blank" rel="noopener noreferrer">{data.details.domain||"打开原始网页"}</a> · 获取于 {data.details.fetched_at?new Date(data.details.fetched_at).toLocaleString():"读取中"}{data.details.author&&` · ${data.details.author}`}{data.details.published_at&&` · 发布于 ${data.details.published_at}`}</p>}
  {(data.details.warnings||[]).map((w,i)=><p key={i} className="source-warning">{w}</p>)}
  {!!data.details.failed_pages?.length&&<div className="source-warning"><strong>{data.details.partial_confirmed?"已确认使用部分内容，资料仍不完整":"资料不完整，尚未作为完整资料入库"}</strong>{data.details.failed_pages.map(p=><p key={p.page}>第 {p.page} 页：{p.error}</p>)}{pending&&<button className="button" disabled={busy} onClick={()=>action("retry")}>仅重试失败页</button>}</div>}
  {data.details.duplicate&&<p className="source-warning">已有相同正文「{data.details.duplicate.title}」，默认暂停处理。</p>}
  {pointer.text&&<blockquote className="citation-excerpt"><small>{sourcePosition(pointer)} · 片段 {pointer.ordinal}</small><p>{pointer.text}</p></blockquote>}
  <div className="source-actions">
   {editable&&!editing&&<button className="button" onClick={()=>setEditing(true)}>{ocr?"修正识别文字":"编辑正文"}</button>}
   {latest&&["ready","failed","cancelled"].includes(data.status)&&<button className="button" disabled={busy||dirty} onClick={()=>action("reprocess",{version:data.version})}>{data.source_type==="web"?"重新获取网页":"重新读取原件"}</button>}
   {latest&&["failed","cancelled"].includes(data.status)&&<button className="button" disabled={busy} onClick={()=>action("retry")}>重试处理</button>}
   {latest&&["queued","processing","indexing","awaiting_confirmation"].includes(data.status)&&<button className="button" disabled={busy} onClick={()=>action("cancel",{version:data.version})}>取消当前导入</button>}
   {data.source_type!=="paste"&&<a href={file} target="_blank" rel="noreferrer">{ocr?"打开原件":"下载原件"}</a>}
  </div>
  {(editing||(pending&&data.source_type==="web"))&&<label className="source-title-edit">资料标题<input value={title} maxLength={240} disabled={busy} onChange={e=>{setTitle(e.target.value);setDirty(true);}}/></label>}
  <div className={ocr?"source-reader with-original":"source-reader"}>
   {ocr&&<div className="source-original">{data.source_type==="pdf"?<><label className="pdf-toolbar">原件页码<input type="number" min={1} max={data.details.pages||100} value={page} onChange={e=>setPage(Math.max(1,Math.min(data.details.pages||100,Number(e.target.value)||1)))}/></label><PdfPreview documentId={data.document_id} version={data.version} page={page} filename={data.title}/></>:<img src={file} alt="上传的原始图片"/>}</div>}
   <div className="source-body">{!ocr&&(editing||(pending&&data.source_type==="web"))?<><textarea aria-label="资料正文" rows={20} maxLength={500000} value={text} disabled={busy} onChange={e=>{setText(e.target.value);setDirty(true);}}/><small>{text.length.toLocaleString()} / 500,000 字</small></>:data.units.map(u=><div key={u.id} ref={pointer.location?.block_id===u.location.block_id?target:undefined} className={pointer.location?.block_id===u.location.block_id?"source-unit cited":"source-unit"}>
    <small>{u.location.heading&&`${u.location.heading} · `}{u.location.label}{u.confidence!==undefined&&` · 识别置信度 ${u.confidence}%`}{u.user_corrected&&" · 用户已修正"}</small>
    {editing&&u.ocr?<textarea aria-label={`修正${u.location.label}`} rows={8} value={corrections[u.id]??u.text} onChange={e=>{setCorrections(v=>({...v,[u.id]:e.target.value}));setDirty(true);}}/>:<p>{u.text}</p>}
    {u.location.page&&<button className="text-button" onClick={()=>setPage(u.location.page!)}>查看第 {u.location.page} 页原件</button>}
   </div>)}{!data.units.length&&<p className="muted">{data.status==="failed"?"没有可显示的正文，请重试或粘贴文字。":"正文尚未解析完成。"}</p>}</div>
  </div>
  {editing&&<div className="source-actions"><button className="button primary" disabled={busy||!dirty||!title.trim()} onClick={()=>action("content",{version:data.version,title,...(ocr?{corrections}:{text})},"PUT")}>{busy?"保存中…":"保存为新版本并处理"}</button><button className="button" disabled={busy} onClick={()=>{setEditing(false);setDirty(false);dirtyRef.current=false;setCorrections({});void load();}}>放弃修改</button></div>}
  {pending&&<div className="source-confirm">{!!data.details.failed_pages?.length&&<label><input type="checkbox" checked={partial} onChange={e=>setPartial(e.target.checked)}/>确认仅使用成功内容，并保留不完整提示</label>}<label><input type="checkbox" checked={copy} onChange={e=>setCopy(e.target.checked)}/>重复时保留独立副本</label><button className="button primary" disabled={busy||!!data.details.failed_pages?.length&&!partial} onClick={()=>action("confirm",{version:data.version,title,...(data.source_type==="web"?{text}:{}),accept_partial:partial,keep_copy:copy})}>{busy?"提交中…":"确认入库"}</button></div>}
  {data.details.user_adjusted&&data.details.original_units&&<details><summary>查看调整前的提取快照</summary>{data.details.original_units.map(u=><p key={u.id} className="source-snapshot">{u.location.label}：{u.text}</p>)}</details>}
  {dirty&&<p role="status">有尚未保存的修改。</p>}{(error||data.error)&&<p role="alert" className="document-error">{error||data.error}</p>}
 </section>;
}
