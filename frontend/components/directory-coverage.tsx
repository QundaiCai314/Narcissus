"use client";
import {useState} from 'react';
import {api,errorText} from '@/lib/api';
import type {LearningSet,DirectoryReference,DirectoryCoverage} from '@/lib/learning';

type ReferenceInput=DirectoryReference&{request_key:string;confirmed:boolean;unresolved_lines:number;failed_pages:number[]};
type Plan={base_fingerprint:string;plan_fingerprint:string;branch_id:string|null;has_changes:boolean;added:number;restored:number;ancestor_count:number;outside_unchanged:boolean;before:DirectoryCoverage;after:DirectoryCoverage;changes:{id:string;number:string|null;title:string;action:string;ancestor:boolean}[]};

export function DirectoryCoveragePanel({row,onFocus,selectedId}:{row:LearningSet;onFocus:(id:string)=>void;selectedId:string}) {
  const [report,setReport]=useState<DirectoryCoverage>(row.directory_coverage||{available:false,reason:'没有独立目录基准'});
  const [reference,setReference]=useState<ReferenceInput|null>(null),[referenceConfirmed,setReferenceConfirmed]=useState(false);
  const [plan,setPlan]=useState<Plan|null>(null),[requestKey,setRequestKey]=useState(''),[confirmed,setConfirmed]=useState(false);
  const [saved,setSaved]=useState<{id:string;version:number}|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const base=`/learning/${row.id}`;
  const selected=row.items?.find(item=>item.id===selectedId);
  const provided=()=>reference?{...reference,confirmed:referenceConfirmed}:null;
  async function check(override?:ReferenceInput){
    setBusy(true);setError('');setPlan(null);setSaved(null);setConfirmed(false);
    try{setReport(await api<DirectoryCoverage>(`${base}/directory-coverage`,{method:'POST',body:JSON.stringify({reference:override||provided()})}));}
    catch(reason){setError(errorText(reason));}finally{setBusy(false);}
  }
  async function load(file:File){
    try{
      if(file.size>3*1024*1024)throw new Error('目录JSON不能超过3MB');
      const raw=JSON.parse(await file.text()),value=raw.directory_reference||raw;
      if(!Array.isArray(value.entries)||!value.entries.length||value.entries.length>2000)throw new Error('请选择已核对的目录JSON');
      if(value.unparsed_lines!==undefined&&!Array.isArray(value.unparsed_lines))throw new Error('目录核对记录格式错误');
      const next:ReferenceInput={title:typeof value.title==='string'?value.title:(row.params.topic||row.title).slice(0,100),
        source_name:typeof value.source_name==='string'?value.source_name:file.name,entries:value.entries,
        pages_read:value.pages_read||[],source_pdf:value.source_pdf,unresolved_lines:value.unparsed_lines?.length||0,
        failed_pages:(value.failed_pages||[]).map((page:number|{pdf_page:number})=>typeof page==='number'?page:page.pdf_page),
        request_key:crypto.randomUUID(),confirmed:false};
      setReference(next);setReferenceConfirmed(false);await check(next);
    }catch(reason){setError(errorText(reason));}
  }
  async function preview(branchId:string|null){
    setBusy(true);setError('');setSaved(null);setConfirmed(false);
    const key=crypto.randomUUID();setRequestKey(key);
    try{const value=await api<Plan>(`${base}/directory-branch/preview`,{method:'POST',body:JSON.stringify({reference:provided(),branch_id:branchId,request_key:key})});setPlan(value);}
    catch(reason){setPlan(null);setError(errorText(reason));}finally{setBusy(false);}
  }
  async function save(){
    if(!plan||!confirmed)return;
    setBusy(true);setError('');
    try{setSaved(await api<LearningSet>(`${base}/directory-branch`,{method:'POST',body:JSON.stringify({reference:provided(),branch_id:plan.branch_id,request_key:requestKey,confirmed:true,base_fingerprint:plan.base_fingerprint,plan_fingerprint:plan.plan_fingerprint})}));}
    catch(reason){setError(errorText(reason));}finally{setBusy(false);}
  }
  return <details className="directory-coverage">
    <summary>章节覆盖核对 · {report.available?`${report.healthy_entries} / ${report.expected_entries} 项符合基准`:'尚无独立基准'}</summary>
    <p className="muted">按已核对目录逐项比较标题、父子关系和页码；这里检查目录结构，不代表已阅读正文。</p>
    <p className="muted">当前导图来源：{row.outline?.source_name||'未记录'}</p>
    <div className="learning-toolbar"><button className="button" disabled={busy} onClick={()=>check()}>重新核对</button>
      <label>导入核对基准<input aria-label="导入章节覆盖核对基准" type="file" accept=".json,application/json" disabled={busy} onChange={event=>{const file=event.target.files?.[0];if(file)void load(file);event.target.value='';}}/></label></div>
    {reference&&<>
      <label className="copy-option"><input type="checkbox" disabled={busy} checked={referenceConfirmed} onChange={event=>{setReferenceConfirmed(event.target.checked);setPlan(null);setSaved(null);setConfirmed(false);}}/>已确认这份目录属于当前教材，且标记条目已经核对</label>
      <button className="text-button" disabled={busy||!referenceConfirmed} onClick={()=>preview(null)}>预览保存此基准（保留当前节点）</button>
    </>}
    {report.available?<>
      <p>基准：{report.source_name} · {reference?'导入预览，尚未保存':'已保存的独立目录快照'}</p>
      <p role="status">保留 {report.present_entries} / {report.expected_entries} 项；缺失 {report.missing.length} 项，挂错位置 {report.misplaced.length} 项，标题或页码变化 {report.changed.length} 项，重复绑定 {report.duplicates.length} 项。</p>
      {selected?.source_entry_id&&<button className="text-button" disabled={busy||report.review_pending>0||!!reference&&!referenceConfirmed} onClick={()=>preview(selected.source_entry_id!)}>预览恢复所选分支：{selected.title}</button>}
      {!!report.review_pending&&<p className="source-warning">基准还有{report.review_pending}个未核对条目，请先在目录核对中处理。</p>}
      {!!report.structural_issues.length&&<p className="source-warning">{report.structural_issues.join('；')}。部分节点可能无法显示，请先预览恢复相关分支。</p>}
      {!!report.unexpected.length&&<p className="source-warning">有{report.unexpected.length}个节点不在基准中。分支恢复会保留分支外节点，不会自动删除。</p>}
      <div className="directory-coverage-table"><table><thead><tr><th>章节</th><th>符合 / 基准</th><th>差异</th><th>操作</th></tr></thead><tbody>{report.chapters.map(chapter=>{
        const issues=chapter.missing+chapter.misplaced+chapter.changed+chapter.duplicates;
        const node=row.items?.find(item=>item.source_entry_id===chapter.id);
        return <tr key={chapter.id}><td>{node?<button className="text-button" onClick={()=>onFocus(node.id)}>{chapter.number} {chapter.title}</button>:<span>{chapter.number} {chapter.title}</span>}</td>
          <td>{chapter.healthy} / {chapter.expected}</td><td>{issues?`缺${chapter.missing} · 挂错${chapter.misplaced} · 变更${chapter.changed} · 重复${chapter.duplicates}`:'完整'}</td>
          <td>{issues>0&&<button className="text-button" disabled={busy||report.review_pending>0||!!reference&&!referenceConfirmed} onClick={()=>preview(chapter.id)}>预览恢复</button>}</td></tr>;
      })}</tbody></table></div>
      {report.missing.length>0&&<details><summary>缺失条目（{report.missing.length}）</summary><ul>{report.missing.map(item=><li key={item.id}>{item.number} {item.title}</li>)}</ul></details>}
    </>:<p className="source-warning">{report.reason}。已有节点数量不能证明目录完整。</p>}
    {busy&&<p className="muted" role="status">正在核对目录结构…</p>}
    {error&&<p className="document-error" role="alert">{error}</p>}
    {plan&&<section className="directory-repair-plan" aria-label="目录分支恢复预览">
      <h4>{plan.branch_id?'分支恢复预览':'核对基准保存预览'}</h4>
      <p>新增{plan.added}项，恢复{plan.restored}项{plan.ancestor_count?`，其中补齐缺失上级${plan.ancestor_count}项`:''}。分支外节点保持原样。</p>
      {!!plan.changes.length&&<ul>{plan.changes.map(item=><li key={item.id}>{item.action==='added'?'补入':'恢复'}：{item.number} {item.title}{item.ancestor?'（必要上级）':''}</li>)}</ul>}
      {plan.after.available&&<p>预览后：{plan.after.healthy_entries} / {plan.after.expected_entries}项符合基准{plan.after.complete?'，结构核对完整':'，其他差异仍保留并继续提示'}。</p>}
      {!plan.has_changes?<p className="muted">当前分支和基准已一致，无需恢复。</p>:saved?<p role="status">已生成第{saved.version}版。<a href={`?tab=mindmap&item=${saved.id}`}>打开新版本</a>；当前版本保留。</p>:<>
        <label className="copy-option"><input aria-label="确认目录分支恢复方案" type="checkbox" checked={confirmed} disabled={busy} onChange={event=>setConfirmed(event.target.checked)}/>已核对本次变化，保存为新版本</label>
        <button className="button primary" disabled={busy||!confirmed} onClick={save}>保存新版本</button>
      </>}
    </section>}
  </details>;
}
