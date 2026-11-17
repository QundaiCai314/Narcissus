"use client";
import {useEffect,useRef,useState} from 'react';
import {api,request,errorText} from '@/lib/api';
import type {Visual} from '@/lib/visuals';
import type {AudioOverview,AudioRender} from '@/lib/audio';
import {composeVideo} from '@/lib/video-overview';
export function VideoOverview({notebookId}:{notebookId:string}){
 const [visuals,setVisuals]=useState<Visual[]>([]),[audios,setAudios]=useState<AudioOverview[]>([]),[visual,setVisual]=useState(''),[audio,setAudio]=useState(''),[confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false),[progress,setProgress]=useState(0),[error,setError]=useState(''),[url,setUrl]=useState('');
 const abort=useRef<AbortController|null>(null);
 useEffect(()=>{let active=true;Promise.all([api<{items:Visual[]}>(`/notebooks/${notebookId}/visuals?kind=presentation&limit=100`),api<{items:AudioOverview[]}>(`/notebooks/${notebookId}/audio?limit=100`)]).then(([v,a])=>{if(active){setVisuals(v.items);setAudios(a.items.filter(row=>row.latest_render?.status==='complete'));}}).catch(e=>{if(active)setError(errorText(e));});return()=>{active=false;abort.current?.abort();};},[notebookId]);
 useEffect(()=>()=>{if(url)URL.revokeObjectURL(url);},[url]);
 async function compose(){
  if(!confirmed||!visual||!audio)return;setBusy(true);setError('');setProgress(0);setUrl('');const controller=new AbortController();abort.current=controller;let context:AudioContext|undefined;
  try{
   context=new AudioContext();await context.resume();
   const v=await api<Visual>(`/visuals/${visual}`),a=await api<AudioOverview>(`/audio/${audio}`),render=await api<AudioRender>(`/audio-renders/${a.latest_render?.id}`),file=v.files.find(f=>f.format==='pdf'&&f.revision===v.revision);
   if(!file||render.status!=='complete'||render.revision!==a.revision||v.source_state!=='active'||a.sources.some(s=>s.state!=='active'))throw new Error('请先完成当前版本PDF导出和音频合成，且来源均须有效');
   const sourceSet=(values:{document_id?:string;id?:string;version?:number}[])=>[...new Set(values.map(s=>`${s.document_id||s.id}:${s.version}`))].sort().join('|');
   const left=sourceSet(v.evidence.filter(e=>e.kind==='document')),right=sourceSet((render.citations||[]).filter(e=>e.kind==='document'));
   if(!left||left!==right)throw new Error('演示文稿与音频的来源版本不一致，请选择同一组资料生成的成果');
   const [pdfBytes,audioBytes]=await Promise.all([request(`/visual-files/${file.id}`,{signal:controller.signal}).then(r=>r.arrayBuffer()),request(`/audio-renders/${render.id}/file`,{signal:controller.signal}).then(r=>r.arrayBuffer())]);
   const blob=await composeVideo(pdfBytes,audioBytes,context,setProgress,controller.signal);if(!controller.signal.aborted)setUrl(URL.createObjectURL(blob));
  }catch(e){setError(errorText(e));if(context&&context.state!=='closed')await context.close();}finally{setBusy(false);}
 }
 return <section className="writing-area parity-tool"><div className="writing-heading"><h2>视频概览</h2></div><div className="writing-scroll parity-tool-body"><p>把已核对的演示文稿PDF与已合成音频组合为有声视频，不重新生成内容。</p><label>演示文稿<select aria-label="视频演示文稿" disabled={busy} value={visual} onChange={e=>{setVisual(e.target.value);setConfirmed(false);}}><option value="">请选择…</option>{visuals.map(v=><option key={v.id} value={v.id}>{v.title}</option>)}</select></label><label>已完成音频<select aria-label="视频音频" disabled={busy} value={audio} onChange={e=>{setAudio(e.target.value);setConfirmed(false);}}><option value="">请选择…</option>{audios.map(a=><option key={a.id} value={a.id}>{a.title}</option>)}</select></label><p className="muted">各页按音频总时长平均分配，最多30页、5分钟；不是自动语义对齐。导出按实际时长录制，请保持页面打开。支持Chrome/Edge的WebM格式。</p><label><input type="checkbox" disabled={busy} checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>已核对文稿、音频内容与页序，接受平均分配停留时间</label><button className="button primary" disabled={busy||!confirmed||!visual||!audio} onClick={()=>void compose()}>组合并导出有声视频</button>{busy&&<><p role="status">正在导出 {Math.round(progress)}%</p><button className="text-button" onClick={()=>abort.current?.abort()}>取消导出</button></>}{error&&<p role="alert">{error}</p>}{url&&<><video preload="metadata" controls src={url} style={{maxWidth:'100%'}}/><a className="button" download="narcissus-overview.webm" href={url}>下载WebM视频</a></>}</div></section>;
}
