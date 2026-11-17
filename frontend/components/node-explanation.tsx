"use client";
import { useEffect, useRef, useState } from "react";
import { api, post, errorText, WritingCitation, ApiError } from "@/lib/api";
import { LearningItem, LearningSet, OnCitation } from "@/lib/learning";
import { MarkdownRenderer } from "./markdown-renderer";
import { NodeEvidence } from './node-evidence';

type Detail={title:string;sections:{id:string;title:string;content:string;refs:number[]}[];citations:WritingCitation[];warning:string|null};
type Lookup={status:'ready'|'missing'|'pending';detail:Detail|null};
type View={key:string;phase:'loading'|'missing'|'pending'|'ready'|'error';detail?:Detail;error?:string;origin?:'lookup'|'generate'};

export function NodeExplanation({row,node,valid,onCitation}:{row:LearningSet;node:LearningItem;valid:boolean;onCitation:OnCitation}){
  const key=`${row.id}:${node.id}`,path=`/learning/${encodeURIComponent(row.id)}/nodes/${encodeURIComponent(node.id)}/explanation`;
  const [view,setView]=useState<View>({key,phase:'loading'}),[retry,setRetry]=useState(0),[citation,setCitation]=useState<number|null>(null);
  const current=useRef(key);current.current=key;
  const generating=useRef(new Map<string,Promise<Detail>>());
  const shown=view.key===key?view:{key,phase:'loading' as const};
  const directory=row.params.origin==='outline';
  useEffect(()=>{
    let disposed=false,timer:ReturnType<typeof setTimeout>|undefined;
    const started=Date.now();setCitation(null);setView({key,phase:'loading'});
    if(!valid||directory)return;
    async function lookup(){
      try{
        const value=await api<Lookup>(path);
        if(disposed)return;
        if(value.status==='ready'){
          if(!value.detail?.sections.length)throw new Error('当前没有可显示的原文讲解，请选择其他知识点。');
          setView({key,phase:'ready',detail:value.detail});
        }else if(value.status==='pending'){
          if(Date.now()-started>130000)throw new Error('生成仍未完成，请稍后重新检查。');
          setView({key,phase:'pending'});timer=setTimeout(lookup,3000);
        }else setView({key,phase:'missing'});
      }catch(reason){if(!disposed)setView({key,phase:'error',error:errorText(reason),origin:'lookup'});}
    }
    timer=setTimeout(lookup,200);
    return()=>{disposed=true;clearTimeout(timer);};
  },[key,path,valid,directory,retry]);
  async function generate(){
    if(!valid||directory||generating.current.has(key))return;
    setView({key,phase:'pending'});
    const request=api<Detail>(path,post());generating.current.set(key,request);
    try{
      const detail=await request;
      if(!detail.sections.length)throw new Error('原文未支持可用讲解，请选择其他知识点。');
      if(current.current===key)setView({key,phase:'ready',detail});
    }catch(reason){
      if(current.current===key){
        // Competing requests only trigger cache reads, never automatic generation retries.
        if(reason instanceof ApiError&&reason.status===409)setRetry(value=>value+1);
        else setView({key,phase:'error',error:errorText(reason),origin:'generate'});
      }
    }finally{generating.current.delete(key);}
  }
  const detail=shown.detail;
  const labels=detail?[...new Set(detail.sections.flatMap(section=>section.refs))]:node.refs;
  const citations=(detail?.citations||row.citations||[]).filter(c=>labels.includes(c.label));
  return <div className="node-detail-content" aria-busy={!directory&&valid&&(shown.phase==='loading'||shown.phase==='pending')}>
    {directory?<p className="muted">当前只有目录结构，尚无正文讲解。</p>:!valid?<p className="source-warning">资料已更新或删除，请生成新版导图后查看详解。</p>:<>
      <div className="node-detail-meta"><span>{shown.phase==='ready'?'已保存的原文详解':'依据所选资料'}</span><span>{shown.phase==='ready'?'AI整理 · 请核对原文':'来源片段可直接查看'}</span></div>
      {shown.phase==='loading'?<div className="node-detail-loading" role="status"><p>正在查找已有讲解…</p><div/><div/><div/></div>:
       shown.phase==='pending'?<div className="node-detail-loading" role="status"><p>正在整理并核验原文讲解…</p><small>切换知识点不会重复提交；完成后可再次打开查看。</small><div/><div/><div/></div>:
       shown.phase==='missing'?<div className="node-detail-empty"><h4>这个知识点还没有详解</h4><p>按需整理概念、关键关系与易混点；生成后可在有效期内复用。</p><button className="button" onClick={()=>void generate()}>生成原文详解</button><small>此操作将调用模型。仅查看已有讲解与来源片段不会触发生成。</small></div>:
       shown.phase==='error'?<div className="node-detail-error" role="alert"><p>{shown.error}</p><button className="text-button" onClick={()=>setRetry(value=>value+1)}>重新检查已有讲解</button>{shown.origin==='generate'&&<button className="button" onClick={()=>void generate()}>重试生成详解</button>}</div>:
       detail&&<>{detail.sections.map(section=><section className="node-detail-section" key={section.id}><h4>{section.title}</h4><MarkdownRenderer content={section.content+' '+section.refs.map(ref=>`[${ref}]`).join(' ')} citations={detail.citations} onCitation={c=>setCitation(c.label)}/></section>)}{detail.warning&&<p className="source-warning">{detail.warning}</p>}</>}
    </>}
    {!directory&&<NodeEvidence key={key} citations={citations} selected={citation} onSelect={setCitation} onCitation={onCitation} allowOriginal={valid}/>}
  </div>;
}
