"use client";
import {useEffect,useState} from "react";
import {api,post,errorText} from "@/lib/api";
import {ImportLimits} from "@/lib/sources";

export function SourceImport({notebookId,onImported,onDirty}:{notebookId:string;onImported:()=>void;onDirty:(value:boolean)=>void}) {
 const [mode,setMode]=useState("file"),[title,setTitle]=useState(""),[text,setText]=useState(""),[url,setUrl]=useState(""),[copy,setCopy]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState("");
 const [limits,setLimits]=useState<ImportLimits|null>(null),[files,setFiles]=useState<{file:File;state:string;error?:string}[]>([]);
 useEffect(()=>{api<ImportLimits>("/import-limits").then(setLimits).catch(e=>setError(errorText(e)));},[]);
 useEffect(()=>{const dirty=!!text || busy; onDirty(dirty); const warn=(e:BeforeUnloadEvent)=>{if(dirty){e.preventDefault();e.returnValue="";}};window.addEventListener("beforeunload",warn);return()=>window.removeEventListener("beforeunload",warn);},[text,busy,onDirty]);
 async function upload(items:File[]){
  if(!limits)return;
  if(items.length>limits.max_batch_files){setError(`一次最多添加 ${limits.max_batch_files} 份文件`);return;}
  setBusy(true);setError("");setNotice("");setFiles(items.map(file=>({file,state:"等待上传"})));
  for(let i=0;i<items.length;i++){
   const file=items[i];
   const update=(state:string,error?:string)=>setFiles(v=>v.map((f,n)=>n===i?{file,state,error}:f));
   update("上传中");
   try{if(file.size>limits.max_upload_mb*1024*1024)throw Error(`每份不能超过 ${limits.max_upload_mb}MB`);
    const body=new FormData();body.append("file",file);await api(`/notebooks/${notebookId}/documents?keep_copy=${copy}`,{method:"POST",body});update("已上传，后台处理中");onImported();
   }catch(e){update("失败",errorText(e));}
  }setBusy(false);
 }
 async function submit(){setBusy(true);setError("");setNotice("");try{
  await api(`/notebooks/${notebookId}/sources/${mode==="paste"?"text":"web"}`,post(mode==="paste"?{title,text,keep_copy:copy}:{url,keep_copy:copy}));
  setText("");setTitle("");setUrl("");setNotice(mode==="web"?"正在读取网页。请在资料列表打开预览，核对后确认入库。":"文字已保存，正在处理。");onImported();
 }catch(e){setError(errorText(e));}finally{setBusy(false);}}
 return <section className="import-panel"><h2>添加资料</h2><p className="muted">资料仅你可见。处理完成后，可用于对话、总结和学习。</p>
  <div className="source-tabs">{[["file","上传文件"],["paste","粘贴文字"],["web","网页链接"]].map(([id,label])=><button key={id} className={mode===id?"button primary":"button"} onClick={()=>setMode(id)} disabled={busy}>{label}</button>)}</div>
  <label className="copy-option"><input type="checkbox" checked={copy} onChange={e=>setCopy(e.target.checked)}/>重复时保留独立副本（会重新处理）</label>
  {mode==="file"?<><label className="file-drop">选择文件，可一次选择多份<input type="file" multiple accept=".pdf,.docx,.txt,.md,.markdown,.png,.jpg,.jpeg" disabled={busy||!limits} onChange={e=>{void upload(Array.from(e.target.files||[]));e.target.value="";}}/></label><p className="muted">PDF、Word DOCX、TXT、Markdown、PNG、JPG。每份 {limits?.max_upload_mb??"…"}MB；PDF 最多 {limits?.max_pdf_pages??"…"} 页，一次最多 {limits?.max_batch_files??"…"} 份。旧版 DOC 请先另存为 DOCX。</p>
   {files.map((f,i)=><div className="upload-result" key={i}><strong>{f.file.name}</strong><span>{f.state}</span>{f.error&&<p role="alert">{f.error}</p>}{f.state==="失败"&&!busy&&<button className="text-button" onClick={()=>upload([f.file])}>重试此文件</button>}</div>)}</>:
   <form onSubmit={e=>{e.preventDefault();void submit();}}>
    {mode==="paste"?<><label>资料标题<input required maxLength={240} value={title} onChange={e=>setTitle(e.target.value)} disabled={busy}/></label><label>正文<textarea required rows={14} minLength={20} maxLength={limits?.max_document_chars??500000} value={text} onChange={e=>setText(e.target.value)} disabled={busy}/></label><small>{text.length.toLocaleString()} / {(limits?.max_document_chars??500000).toLocaleString()} 字 · 离开前会提醒未保存内容</small></>:
    <><label>公开网页地址<input type="url" required placeholder="https://…" value={url} onChange={e=>setUrl(e.target.value)} disabled={busy}/></label><p className="muted">先预览正文，再确认入库。暂不支持登录、付费、验证码或主要依赖脚本的网站；无法读取时可切换到“粘贴文字”。</p></>}
    <button className="button primary" disabled={busy||!limits}>{busy?"正在提交…":mode==="paste"?"保存并处理":"读取网页预览"}</button>
   </form>}
  {error&&<p role="alert" className="document-error">{error}</p>}{notice&&<p role="status">{notice}</p>}
 </section>;
}
