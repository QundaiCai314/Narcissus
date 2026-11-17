"use client";
import {use,useEffect,useState} from 'react';
import {api,errorText} from '@/lib/api';
import {Header} from '@/components/shared';
import {MarkdownRenderer} from '@/components/markdown-renderer';
type Note={id:string;title:string;content:string;version:number};
export default function Shared({params}:{params:Promise<{id:string}>}){
 const {id}=use(params),[data,setData]=useState<{name:string;role:string;notes:Note[]}|null>(null),[draft,setDraft]=useState<Note|null>(null),[error,setError]=useState('');
 async function load(){setData(await api(`/shared-notebooks/${id}`));}
 useEffect(()=>{load().catch(e=>setError(errorText(e)));},[id]);
 return <><Header/><main className="home parity-library"><h1>{data?.name||'共享手记'}</h1><p>仅展示已授权的手记。这里不开放笔记本的原始资料、对话或练习作答。</p>{error&&<p role="alert">{error}</p>}{data&&!data.notes.length&&<p>暂无手记。</p>}{data?.notes.map(note=><article className="directory-coverage" key={note.id}>{draft?.id===note.id?<><label>手记标题<input value={draft.title} onChange={e=>setDraft({...draft,title:e.target.value})}/></label><label>手记正文<textarea rows={12} value={draft.content} onChange={e=>setDraft({...draft,content:e.target.value})}/></label><button className="button" onClick={async()=>{try{await api(`/shared-notebooks/${id}/notes/${draft.id}`,{method:'PUT',body:JSON.stringify(draft)});setDraft(null);setError('');await load();}catch(e){setError(errorText(e));}}}>保存协作修改</button><button className="text-button" onClick={()=>{setDraft(null);void load();}}>放弃并重新加载</button></>:<><h2>{note.title}</h2><small>版本{note.version}</small><MarkdownRenderer content={note.content}/>{data.role!=='viewer'&&<button className="text-button" onClick={()=>setDraft({...note})}>编辑手记</button>}</>}</article>)}</main></>;
}
