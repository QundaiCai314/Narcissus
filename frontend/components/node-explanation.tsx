"use client";
import { useEffect, useRef, useState } from "react";
import { api, post, errorText, WritingCitation } from "@/lib/api";
import { LearningItem, LearningSet, OnCitation } from "@/lib/learning";
import { MarkdownRenderer } from "./markdown-renderer";
import { ReferenceList } from "./writing-view";

type Detail = { title: string; sections: {id:string;title:string;content:string;refs:number[]}[];
  citations: WritingCitation[]; warning: string | null };

export function NodeExplanation({row,node,valid,onCitation}:{
  row:LearningSet;node:LearningItem;valid:boolean;onCitation:OnCitation;
}) {
  const [detail,setDetail] = useState<Detail | null>(null);
  const [error,setError] = useState("");
  const [retry,setRetry] = useState(0);
  const pending = useRef(new Map<string,Promise<Detail>>());
  useEffect(() => {
    let disposed = false;
    setDetail(null); setError("");
    if (!valid) return;
    const key = `${row.id}:${node.id}`;
    // Briefly defer rapid clicks; responses never replace a different node's text.
    const timer = setTimeout(() => {
      let request = pending.current.get(key);
      if (!request) {
        request = api<Detail>(`/learning/${row.id}/nodes/${node.id}/explanation`,post());
        pending.current.set(key,request);
        request.catch(() => pending.current.delete(key));
      }
      request.then(value => { if (!disposed) setDetail(value); })
        .catch(reason => { if (!disposed) setError(errorText(reason)); });
    },600);
    return () => { disposed=true;clearTimeout(timer); };
  },[row.id,node.id,valid,retry]);
  const refs = detail ? [...new Set(detail.sections.flatMap(section=>section.refs))] : node.refs;
  return <div className="node-detail-content" aria-busy={valid && !detail && !error}>
    {!valid ? <p className="muted">资料已更新或删除，请生成新版导图后查看详解。</p> :
      error ? <div className="node-detail-error" role="alert"><p>{error}</p>
        <button className="text-button" onClick={()=>setRetry(value=>value+1)}>重试讲解</button></div> :
      !detail ? <div className="node-detail-loading" role="status">
        <p>正在依据原文整理详细讲解…</p><div/><div/><div/>
      </div> : <>
        {detail.sections.map(section=><section className="node-detail-section" key={section.id}>
          <h4>{section.title}</h4>
          <MarkdownRenderer content={section.content + " " + section.refs.map(ref=>`[${ref}]`).join(" ")}
            citations={detail.citations} onCitation={onCitation}/>
        </section>)}
        {detail.warning && <p className="source-warning">{detail.warning}</p>}
      </>}
    <ReferenceList citations={detail?.citations || row.citations || []}
      content={refs.map(ref=>`[${ref}]`).join("")} onCitation={onCitation}/>
  </div>;
}
