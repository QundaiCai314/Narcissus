"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  LearningSet,
  LearningItem,
  LearningContext,
  OnCitation,
} from "@/lib/learning";
import { ReferenceList } from "./writing-view";
import { NodeExplanation } from "./node-explanation";
import {DirectoryCoveragePanel} from './directory-coverage';
import {DirectoryPageMapping} from './directory-page-mapping';

import {layoutMindmap,mindmapSvg,revealPath} from '@/lib/mindmap-layout';
import {fitCamera,graphSignature,progressKey,readPosition,resizeCamera,type ViewportSize,type ReadingPosition} from '@/lib/mindmap-progress';
import {useMindmapOwner} from '@/hooks/use-mindmap-owner';
import {mindmapHtml,repeatedTopics} from '@/lib/mindmap-sharing';
function overview(items: LearningItem[]) {
  const root = items.find((item) => !item.parent_id);
  return new Set(items.filter((item) => item.parent_id && item.directory?.kind!=='part' && (items.length > 24 || item.parent_id !== root?.id)).map((item) => item.id));
}
export function MindMap({
  row,
  notebookId,
  onCitation,
  onAsk,
}: {
  row: LearningSet;
  notebookId?:string;
  onCitation: OnCitation;
  onAsk: (context: LearningContext, title: string) => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => overview(row.items || []));
  const [selected, setSelected] = useState(row.items?.[0]?.id || "");
  const [view, setView] = useState({ x: 20, y: 20, z: 1 });
  const viewport = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(
    null,
  );
  const layout=useMemo(()=>layoutMindmap(row.items||[],collapsed),[row.items,collapsed]);
  const [query,setQuery]=useState(''),[pendingFocus,setPendingFocus]=useState<string|null>(null);
  const focusTarget=useRef<string|null>(null);
  const layoutRef=useRef(layout);layoutRef.current=layout;
  const selectedRef=useRef(selected);selectedRef.current=selected;
  const sizeRef=useRef<ViewportSize>({width:0,height:0});
  const [size,setSize]=useState<ViewportSize>(sizeRef.current);
  const persist=!!notebookId&&row.id!=='directory-preview';
  const owner=useMindmapOwner(persist);
  const storageKey=progressKey(owner.id||undefined,notebookId,row.id,row.version);
  const signature=graphSignature(row.items||[]);
  const [loaded,setLoaded]=useState<string|null>(null),[progress,setProgress]=useState('');
  const [shareStatus,setShareStatus]=useState('');
  const activeIdentity=storageKey?storageKey+signature:null;
  const hydrated=useRef(false),write=useRef<()=>void>(()=>{});
  const directoryOnly=row.params.origin==='outline';
  const fit = useCallback(() => {
    const w = viewport.current?.clientWidth || 0;
    if (!w) return;
    const current=layoutRef.current;
    const focused=current.nodes.find(item=>item.node.id===focusTarget.current);
    if(focused){setView({z:1,x:w/2-focused.x-110,y:(viewport.current?.clientHeight||430)/2-focused.y-focused.height/2});return;}
    setView(fitCamera(current.width,current.height,{width:w,height:viewport.current?.clientHeight||430}));
  }, []);
  useEffect(() => {
    const target = viewport.current;
    if (!target) return;
    const resize=()=>{
      const next={width:target.clientWidth,height:target.clientHeight};
      if(next.width<1||next.height<1)return;
      const previous=sizeRef.current;
      if(next.width===previous.width&&next.height===previous.height)return;
      sizeRef.current=next;setSize(next);
      if(hydrated.current)setView(camera=>resizeCamera(camera,previous,next,layoutRef.current.nodes.find(n=>n.node.id===selectedRef.current)));
      else fit();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(target);
    resize();
    return () => observer.disconnect();
  }, [fit]);
  const visible=size.width>0&&size.height>0;
  useEffect(()=>{
    if(!owner.checked||!visible)return;
    hydrated.current=false;setLoaded(null);focusTarget.current=null;
    let saved:ReadingPosition|null=null,blocked=false;
    if(storageKey){try{saved=readPosition(localStorage.getItem(storageKey),signature,row.items||[]);}catch{blocked=true;}}
    const nextCollapsed=saved?new Set(saved.collapsed):overview(row.items||[]);
    const nextSelected=saved?.selected||row.items?.find(item=>!item.parent_id)?.id||'';
    const nextLayout=layoutMindmap(row.items||[],nextCollapsed),target=nextLayout.nodes.find(n=>n.node.id===nextSelected);
    setCollapsed(nextCollapsed);setSelected(nextSelected);setPendingFocus(null);
    setView(saved?resizeCamera(saved.camera,saved.viewport,sizeRef.current,target):fitCamera(nextLayout.width,nextLayout.height,sizeRef.current));
    setQuery('');hydrated.current=true;
    setLoaded(blocked?null:activeIdentity);
    setProgress(!persist?'':blocked?'浏览器存储不可用，本次位置不保存':!storageKey?'未能确认账号，本次位置不保存':saved?'已恢复上次阅读位置 · 仅本机':'阅读位置自动保存 · 仅本机');
    // Restore only on identity/topology changes, never on ordinary window resizing.
  },[activeIdentity,owner.checked,visible,signature,persist]);
  const snapshot:ReadingPosition={schema:1,signature,selected,collapsed:[...collapsed].filter(id=>layout.children.has(id)),camera:view,viewport:size,savedAt:Date.now()};
  write.current=()=>{
    if(!storageKey||loaded!==activeIdentity||!visible)return;
    try{localStorage.setItem(storageKey,JSON.stringify(snapshot));}
    catch{setLoaded(null);setProgress('浏览器存储不可用，本次位置不保存');}
  };
  useEffect(()=>{
    if(!storageKey||loaded!==activeIdentity||!visible)return;
    const timer=setTimeout(()=>write.current(),400);return()=>clearTimeout(timer);
  },[storageKey,activeIdentity,loaded,selected,collapsed,view,size,visible]);
  useEffect(()=>{
    const flush=()=>write.current(),hidden=()=>{if(document.visibilityState==='hidden')flush();};
    window.addEventListener('pagehide',flush);document.addEventListener('visibilitychange',hidden);
    return()=>{flush();window.removeEventListener('pagehide',flush);document.removeEventListener('visibilitychange',hidden);};
  },[]);
  useEffect(() => {
    const target = viewport.current;
    if (!target) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      focusTarget.current=null;
      const w = target.clientWidth;
      setView((v) => {
        const z = Math.max(
          0.12,
          Math.min(2.5, v.z * (e.deltaY < 0 ? 1.08 : 1 / 1.08)),
        );
        return {
          z,
          x: w / 2 - ((w / 2 - v.x) * z) / v.z,
          y: (target.clientHeight / 2) - (((target.clientHeight / 2) - v.y) * z) / v.z,
        };
      });
    };
    target.addEventListener("wheel", handler, { passive: false });
    return () => target.removeEventListener("wheel", handler);
  }, []);
  const node = (row.items || []).find((n) => n.id === selected);
  const trail: LearningItem[] = [];
  const trailIds=new Set<string>();
  let ancestor = node;
  while (ancestor&&!trailIds.has(ancestor.id)) {
    trailIds.add(ancestor.id);
    trail.unshift(ancestor);
    ancestor = row.items?.find((item) => item.id === ancestor?.parent_id);
  }
  const valid = row.sources.every((s) => s.state === "active");
  function focusNode(id: string) {
    setSelected(id);
    focusTarget.current=id;
    setCollapsed(previous=>revealPath(row.items||[],id,previous));
    setPendingFocus(id);
  }
  useEffect(()=>{
    if(!pendingFocus||!layout.nodes.some(item=>item.node.id===pendingFocus))return;
    fit();setPendingFocus(null);
  },[pendingFocus,layout.nodes,fit]);
  function download(format:'json'|'svg'|'html') {
    const styles=getComputedStyle(document.documentElement);
    const colors={paper:styles.getPropertyValue('--paper').trim(),ink:styles.getPropertyValue('--ink').trim(),line:styles.getPropertyValue('--line').trim(),accent:styles.getPropertyValue('--green').trim()};
    const directoryEntries=directoryOnly?(row.directory_reference?.entries||(row.items||[]).filter(item=>item.directory).map(item=>({...item.directory,id:item.id,parent_id:item.parent_id==='__outline_root__'?null:item.parent_id}))):undefined;
    const content=format==='html'?mindmapHtml(row.items||[],row.title):format==='svg'?mindmapSvg(row.items||[],row.title,colors):JSON.stringify({title:row.title,items:row.items,outline:row.outline,entries:directoryEntries,directory_reference:row.directory_reference,directory_coverage:row.directory_coverage,source_pdf:row.directory_reference?.source_pdf,page_mapping:row.page_mapping,page_locations:row.page_locations,source_name:row.outline?.source_name,pages_read:row.outline?.pages_read,unparsed_lines:[],warnings:[]},null,2);
    const url=URL.createObjectURL(new Blob([content],{type:format==='html'?'text/html;charset=utf-8':format==='svg'?'image/svg+xml;charset=utf-8':'application/json;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download=`narcissus-mindmap.${format}`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async function share(){
    const file=new File([mindmapHtml(row.items||[],row.title)],'narcissus-mindmap.html',{type:'text/html'});
    try{if(navigator.canShare?.({files:[file]})){await navigator.share({files:[file],title:row.title});setShareStatus('已打开系统分享');}else{download('html');setShareStatus('已下载只读HTML，可将文件发给他人；不授予笔记本访问权限。');}}
    catch(error){if(!(error instanceof Error&&error.name==='AbortError'))setShareStatus('系统分享不可用，请下载只读HTML文件。');}
  }
  function zoom(factor: number) {
    focusTarget.current=null;
    const w = viewport.current?.clientWidth || 600;
    setView((v) => {
      const z = Math.max(0.12, Math.min(2.5, v.z * factor));
      return {
        z,
        x: w / 2 - ((w / 2 - v.x) * z) / v.z,
        y: (viewport.current?.clientHeight || 430) / 2 - (((viewport.current?.clientHeight || 430) / 2 - v.y) * z) / v.z,
      };
    });
  }
  function toggleNode(id: string) {
    focusTarget.current=null;
    if (!collapsed.has(id)) {
      let current = node;
      const seen=new Set<string>();
      while (current?.parent_id&&!seen.has(current.id)) {
        seen.add(current.id);
        if (current.parent_id === id) {
          setSelected(id);
          break;
        }
        current = row.items?.find((item) => item.id === current?.parent_id);
      }
    }
    setCollapsed((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setPendingFocus(id);
  }
  return (
    <div className="learning-detail">
      {row.outline&&<p className="muted" role="status">{row.directory_coverage?.available?`目录保留 ${row.directory_coverage.present_entries} / ${row.directory_coverage.expected_entries} 项，其中 ${row.directory_coverage.healthy_entries} 项符合基准`:row.id==='directory-preview'?`本次构建保留 ${row.outline.covered_entries} / ${row.outline.entry_count} 项`:`当前 ${row.count} 个节点，尚无独立目录基准`} · {row.outline.chapter_count} 章 · 目录{row.outline.directory_depth}层，含书名导航共{row.outline.map_depth}层 · 大模型调用 0 次</p>}
      {directoryOnly&&row.id!=='directory-preview'&&<DirectoryCoveragePanel row={row} selectedId={selected} onFocus={focusNode}/>}
      {!directoryOnly&&row.coverage_review&&<p className="source-warning">当前覆盖检查依据是模型规划的主题，不是已确认的教材目录。{row.coverage_review.missing_sections.length?`仍缺：${row.coverage_review.missing_sections.join('、')}。`:''}主题数量不能证明章节完整。</p>}
      <div className="learning-toolbar">
        <button
          className="button"
          onClick={() => zoom(1.2)}
          aria-label="放大导图"
        >
          ＋
        </button>
        <button
          className="button"
          onClick={() => zoom(1 / 1.2)}
          aria-label="缩小导图"
        >
          −
        </button>
        <button className="button" onClick={()=>{focusTarget.current=null;fit();}}>
          适应屏幕
        </button>
        <button className="button" onClick={() => focusNode(selected)}>
          实际大小
        </button>
        <button className="text-button" onClick={() => {focusTarget.current=null;setCollapsed(new Set());}}>
          展开全部
        </button>
        <button className="text-button" onClick={() => {
          focusTarget.current=null;
          const collapsed=overview(row.items||[]),next=layoutMindmap(row.items||[],collapsed);
          setCollapsed(collapsed);setPendingFocus(null);setQuery('');
          setSelected(row.items?.find((item) => !item.parent_id)?.id || "");
          setView(fitCamera(next.width,next.height,sizeRef.current));
        }}>
          恢复章节总览
        </button>
        <span className="muted">
          {Math.round(view.z * 100)}% · 拖动画布移动
        </span>
        <button className="text-button" onClick={()=>download('svg')}>下载完整SVG</button>
        <button className="text-button" onClick={()=>download('json')}>下载导图JSON</button>
        <button className="text-button" onClick={()=>download('html')}>下载只读HTML</button>
        <button className="text-button" onClick={()=>void share()}>分享导图</button>
      </div>
      {progress&&<p className="mindmap-reading-status muted" role="status">{progress}</p>}
      {shareStatus&&<p className="muted" role="status">{shareStatus}</p>}
      <details className="directory-coverage"><summary>主题分类核对</summary><p className="muted">自动检查只能发现同名主题，不能判定分类语义正确；跨章节重复概念也可能合理，需人工核对原文。</p>{repeatedTopics(row.items||[]).length?repeatedTopics(row.items||[]).map(item=><p key={item.title}>{item.title}出现在不同分支：{item.ids.map((id,i)=><button className="text-button" key={id} onClick={()=>focusNode(id)}>位置{i+1}</button>)}</p>):<p className="muted">未发现需提示的跨分支同名主题。此结果不代表分类已通过语义审核。</p>}</details>
      <div className="mindmap-search">
        <input aria-label="搜索导图节点" placeholder="搜索章节或知识点…" value={query} onChange={event=>setQuery(event.target.value)}/>
        {query.trim()&&<div aria-label="节点搜索结果">{(row.items||[]).filter(item=>(item.title||'').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).slice(0,20).map(item=><button className="text-button" key={item.id} onClick={()=>{focusNode(item.id);setQuery('');}}>{item.title}</button>)}
          {!(row.items||[]).some(item=>(item.title||'').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))&&<p className="muted">未找到匹配节点</p>}
        </div>}
      </div>
      <nav aria-label="当前知识点路径" className="learning-toolbar">
        {trail.map((item, index) => <span key={item.id}>
          {index > 0 && <span aria-hidden="true"> / </span>}
          <button className="text-button" onClick={() => focusNode(item.id)}>{item.title}</button>
        </span>)}
      </nav>
      <div className="mindmap-viewport" ref={viewport}>
        <svg
          width="100%"
          height="100%"
          tabIndex={0}
          role="group"
          aria-label="知识导图画布"
          onKeyDown={(e) => {
            if (e.target !== e.currentTarget) return;
            if (e.key === "+") zoom(1.2);
            else if (e.key === "-") zoom(1 / 1.2);
            else if (
              ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(
                e.key,
              )
            ) {
              e.preventDefault();
              setView((v) => ({
                ...v,
                x:
                  v.x +
                  (e.key === "ArrowLeft"
                    ? 30
                    : e.key === "ArrowRight"
                      ? -30
                      : 0),
                y:
                  v.y +
                  (e.key === "ArrowUp" ? 30 : e.key === "ArrowDown" ? -30 : 0),
              }));
            }
          }}
          onPointerDown={(e) => {
            if ((e.target as Element).closest("button")) return;
            focusTarget.current=null;
            drag.current = {
              x: e.clientX,
              y: e.clientY,
              vx: view.x,
              vy: view.y,
            };
            e.currentTarget.setPointerCapture(e.pointerId);
          }}
          onPointerMove={(e) => {
            const d = drag.current;
            if (d)
              setView((v) => ({
                ...v,
                x: d.vx + e.clientX - d.x,
                y: d.vy + e.clientY - d.y,
              }));
          }}
          onPointerUp={() => (drag.current = null)}
          onPointerCancel={() => (drag.current = null)}
        >
          <g transform={`translate(${view.x},${view.y}) scale(${view.z})`}>
            {layout.nodes.map((n) => {
              const parent = layout.nodes.find(
                (p) => p.node.id === n.node.parent_id,
              );
              return parent ? (
                <path
                  key={"link" + n.node.id}
                  d={`M${parent.x + 220} ${parent.y + parent.height / 2} C${parent.x + 255} ${parent.y + parent.height / 2},${n.x - 35} ${n.y + n.height / 2},${n.x} ${n.y + n.height / 2}`}
                  fill="none"
                  stroke="#b0c7b5"
                  strokeWidth="2"
                />
              ) : null;
            })}
            {layout.nodes.map((n) => (
              <foreignObject
                key={n.node.id}
                x={n.x}
                y={n.y}
                width={220}
                height={n.height}
              >
                <div
                  className={
                    "mindmap-node " + (selected === n.node.id ? "selected" : "")
                  }
                  style={{ height: n.height - 2 }}
                >
                  <button
                    className="node-title"
                    onClick={() => focusNode(n.node.id)}
                  >
                    {n.node.title}
                  </button>
                  {layout.children.has(n.node.id) && (
                    <button
                      className="node-toggle"
                      aria-label={`${collapsed.has(n.node.id) ? "展开" : "折叠"}${n.node.title}`}
                      aria-expanded={!collapsed.has(n.node.id)}
                      onClick={() => toggleNode(n.node.id)}
                    >
                      {collapsed.has(n.node.id) ? "＋" : "−"}
                    </button>
                  )}
                </div>
              </foreignObject>
            ))}
          </g>
        </svg>
      </div>
      {node ? (
        <section className="learning-explanation">
          <span className="eyebrow">{directoryOnly?'目录结构 · 未读取正文':node.parent_id ? "知识点详解" : "知识导航"}</span>
          <h3>{node.title}</h3>
          {directoryOnly?<>
            <p className="muted">{row.outline?.source_name}{node.directory?.toc_pdf_page?` · 目录位于PDF第${node.directory.toc_pdf_page}页`:''}{node.directory?.printed_page?` · 书内第${node.directory.printed_page}页`:''}</p>
            <p className="muted">当前仅有目录结构，尚未读取正文。书内印刷页码不直接作为PDF跳转位置。</p>
            {row.id!=='directory-preview'&&<DirectoryPageMapping row={row} node={node}/>}
          </>:node.parent_id ? <NodeExplanation row={row} node={node} valid={valid} onCitation={onCitation}/> :
            <p className="muted">选择导图中的具体知识点，在这里查看详细讲解与原文依据。</p>}
          {!directoryOnly&&<button
            className="button primary"
            disabled={!valid}
            onClick={() =>
              onAsk(
                { set_id: row.id, node_id: node.id },
                node.title || "此知识点",
              )
            }
          >
            继续追问这个知识点
          </button>}
          {!valid && (
            <p className="muted">资料已更新或删除，请生成新版后继续提问。</p>
          )}
          {!directoryOnly&&!node.parent_id && <ReferenceList
            citations={row.citations || []}
            content={node.refs.map((n) => `[${n}]`).join("")}
            onCitation={onCitation}
          />}
        </section>
      ) : (
        <p>请选择一个知识点。</p>
      )}
    </div>
  );
}
