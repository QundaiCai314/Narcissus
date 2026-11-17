"use client";
import {useEffect,useRef,useState} from 'react';
import {Citation,WritingCitation} from '@/lib/api';
import {sourcePosition} from '@/lib/sources';
import {PdfPreview} from './pdf-preview';

export function NodeEvidence({citations,selected,onSelect,onCitation,allowOriginal}:{citations:WritingCitation[];selected:number|null;onSelect:(label:number|null)=>void;onCitation:(c:Citation)=>void;allowOriginal:boolean}){
  const [page,setPage]=useState<number|null>(null),target=useRef<HTMLElement>(null);
  const source=citations.find(c=>c.label===selected);
  useEffect(()=>{setPage(null);if(selected!==null)target.current?.scrollIntoView({block:'nearest',behavior:'smooth'});},[selected]);
  if(!citations.length)return <p className="node-evidence-empty muted">当前节点没有可展示的原文片段。</p>;
  const usable=allowOriginal&&source?.state==='active'&&source.kind==='document'&&!!source.document_id;
  const pdf=source?.source_type==='pdf'||/\.pdf$/i.test(source?.filename||'');
  const exactPdf=usable&&pdf&&Number.isInteger(source?.page)&&Number(source?.page)>0;
  return <section className="node-evidence" ref={target} aria-label="知识点原文依据">
    <div className="node-evidence-heading"><h4>原文依据</h4><span>{citations.length}条片段</span></div>
    <div className="node-evidence-tabs" aria-label="选择原文片段">{citations.map(c=><button className="text-button" aria-pressed={selected===c.label} key={c.label} onClick={()=>onSelect(selected===c.label?null:c.label)}>[{c.label}] {sourcePosition(c)}</button>)}</div>
    {source&&<div className="node-evidence-reader"><div className="node-evidence-heading"><span>{source.filename} · {sourcePosition(source)} · 版本{source.version}</span><button className="text-button" onClick={()=>onSelect(null)}>收起片段</button></div>
      <p className="source-snapshot">{source.text}</p>
      {source.kind==='note'&&<p className="muted">用户笔记快照，未经原始资料核验。</p>}
      {(!allowOriginal||source.state!=='active')&&<p className="source-warning">来源已更新或失效；以上仅为保存时的片段快照。</p>}
      {usable&&(exactPdf?<button className="text-button" onClick={()=>setPage(page===source.label?null:source.label)}>{page===source.label?'收起PDF页面':`查看对应PDF第${source.page}页`}</button>:<button className="text-button" onClick={()=>onCitation(source as Citation)}>打开原文核对</button>)}
      {page===source.label&&exactPdf&&<div className="node-evidence-pdf"><PdfPreview key={`${source.document_id}:${source.version}:${source.page}`} documentId={source.document_id} version={source.version} page={source.page!} filename={source.filename}/></div>}
    </div>}
  </section>;
}
