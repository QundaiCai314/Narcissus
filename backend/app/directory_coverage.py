"""Compare and restore directory structure against a separate approved snapshot."""
import copy
import hashlib
import json
from collections import defaultdict
from uuid import UUID
from pydantic import BaseModel,Field
from .directory_maps import DirectoryMapInput,build


class CoverageInput(BaseModel):
    reference:DirectoryMapInput|None=None


class BranchInput(CoverageInput):
    branch_id:str|None=Field(default=None,max_length=80)
    request_key:UUID
    confirmed:bool=False
    base_fingerprint:str=Field(default='',max_length=64)
    plan_fingerprint:str=Field(default='',max_length=64)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def reference_for(result,provided=None):
    if provided is not None:return build(provided)
    snapshot=result.get('directory_reference')
    if snapshot is None:return None
    data=DirectoryMapInput(**snapshot,request_key=UUID(int=0),confirmed=True)
    return build(data)


def descendants(entries,ident):
    children=defaultdict(list)
    for entry in entries:
        if entry.get('parent_id'):children[entry['parent_id']].append(entry['id'])
    chosen=set();pending=[ident]
    while pending:
        current=pending.pop()
        if current in chosen:continue
        chosen.add(current);pending.extend(children[current])
    return chosen


def graph_issues(items):
    ids=[node['id'] for node in items];by_id={node['id']:node for node in items};issues=[]
    if len(set(ids))!=len(ids):issues.append('节点ID重复')
    roots=[node for node in items if node.get('parent_id') is None]
    if len(roots)!=1 or roots[0]['id']!='__outline_root__':issues.append('书名导航根节点异常')
    for node in items:
        seen={node['id']};current=node
        for _ in range(14):
            parent=current.get('parent_id')
            if not parent:break
            if parent not in by_id:issues.append('存在找不到上级的节点');break
            if parent in seen:issues.append('存在循环');break
            seen.add(parent);current=by_id[parent]
        else:issues.append('层级超过上限')
    return list(dict.fromkeys(issues))


def audit(items,compiled):
    if compiled is None:return dict(available=False,reason='本版本没有独立目录基准，请导入已核对目录进行比较')
    entries=compiled['reference']['entries'];expected={node['source_entry_id']:node for node in compiled['items'][1:]}
    actual=defaultdict(list);by_id={node['id']:node for node in items};unexpected=[]
    for node in items:
        if node['id']=='__outline_root__':continue
        key=node.get('source_entry_id')
        if key not in expected:unexpected.append(dict(id=node['id'],title=node.get('title','')))
        else:actual[key].append(node)
    missing=[];misplaced=[];changed=[];duplicates=[];healthy=set()
    semantic_fields=('number','title','kind','printed_page','toc_pdf_page','target_pdf_page')
    for entry in entries:
        key=entry['id'];label=dict(id=key,number=entry.get('number'),title=entry['title'])
        if not actual[key]:missing.append(label);continue
        if len(actual[key])!=1:duplicates.append(label);continue
        node=actual[key][0];parent=by_id.get(node.get('parent_id'))
        expected_parent=entry.get('parent_id')
        actual_parent=None if parent and parent['id']=='__outline_root__' else parent.get('source_entry_id') if parent else '__missing_parent__'
        wrong=actual_parent!=expected_parent
        modified=node.get('title')!=expected[key]['title'] or any(node.get('directory',{}).get(field)!=entry.get(field) for field in semantic_fields)
        if wrong:misplaced.append(dict(label,expected_parent=expected_parent,actual_parent=actual_parent))
        if modified:changed.append(label)
        if not wrong and not modified:healthy.add(key)
    chapter_rows=[]
    for entry in entries:
        if entry['kind'] not in ('chapter','appendix'):continue
        scope=descendants(entries,entry['id'])
        chapter_rows.append(dict(id=entry['id'],number=entry.get('number'),title=entry['title'],expected=len(scope),
            present=sum(bool(actual[key]) for key in scope),healthy=len(scope&healthy),
            missing=sum(item['id'] in scope for item in missing),misplaced=sum(item['id'] in scope for item in misplaced),
            changed=sum(item['id'] in scope for item in changed),duplicates=sum(item['id'] in scope for item in duplicates)))
    structure=graph_issues(items)
    confirmed=compiled.get('reference_confirmed',False)
    return dict(available=True,basis='confirmed_directory' if confirmed else 'reference_preview',reference_confirmed=confirmed,source_name=compiled['reference']['source_name'],
        expected_entries=len(entries),present_entries=sum(bool(actual[key]) for key in expected),healthy_entries=len(healthy),
        missing=missing,misplaced=misplaced,changed=changed,duplicates=duplicates,unexpected=unexpected,structural_issues=structure,
        chapters=chapter_rows,review_pending=compiled['outline']['review_pending'],reference_fingerprint=compiled['fingerprint'],
        complete=not(missing or misplaced or changed or duplicates or unexpected or structure or compiled['outline']['review_pending'] or not confirmed),model_calls=0,embedding_calls=0)


def plan(result,data:BranchInput):
    compiled=reference_for(result,data.reference)
    if compiled is None:raise ValueError('没有独立目录基准，不能推断并补齐缺失分支')
    items=result['items'];before=audit(items,compiled);base=digest(result)
    if compiled['outline']['review_pending']:raise ValueError('核对基准仍有未确认的标记条目')
    if data.reference is not None and not data.reference.confirmed:raise ValueError('请先确认导入的目录基准')
    entries=compiled['reference']['entries'];by_ref={entry['id']:entry for entry in entries}
    selected=set();ancestors=set();after_items=copy.deepcopy(items)
    if data.branch_id is not None:
        if data.branch_id not in by_ref:raise ValueError('所选分支不在核对目录中')
        selected=descendants(entries,data.branch_id)
        bindings=defaultdict(list)
        for node in items:
            if node.get('source_entry_id'):bindings[node['source_entry_id']].append(node)
        current=by_ref[data.branch_id]
        while current.get('parent_id'):
            parent=current['parent_id'];matches=bindings[parent]
            if len(matches)>1:raise ValueError('上级目录存在重复节点，请先选择上级分支修复')
            if not matches:ancestors.add(parent)
            current=by_ref[parent]
        replacement_ids=selected|ancestors
        kept=[copy.deepcopy(node) for node in items if node.get('source_entry_id') not in replacement_ids]
        ids={node['id'] for node in kept};expected={n['source_entry_id']:n for n in compiled['items'][1:]}
        order={entry['id']:i for i,entry in enumerate(entries)}
        for entry in entries:
            key=entry['id']
            if key not in replacement_ids:continue
            node=copy.deepcopy(expected[key]);parent=entry.get('parent_id')
            if parent and parent not in replacement_ids:
                if len(bindings[parent])!=1:raise ValueError('上级目录无法可靠定位')
                node['parent_id']=bindings[parent][0]['id']
            if node['id'] in ids:raise ValueError('分支节点ID与分支外节点冲突，请先核对目录')
            index=next((i for i,old in enumerate(kept) if order.get(old.get('source_entry_id'),-1)>order[key]),len(kept))
            kept.insert(index,node);ids.add(node['id'])
        after_items=kept
    issues=graph_issues(after_items)
    if '书名导航根节点异常' in issues:raise ValueError('书名导航根节点异常，请从核对目录重新创建独立导图')
    if issues:raise ValueError('分支外仍有结构问题，请选择包含问题的上级分支：'+'；'.join(issues))
    after=audit(after_items,compiled)
    scope=selected|ancestors
    outside_before=[node for node in items if node.get('source_entry_id') not in scope]
    outside_after=[node for node in after_items if node.get('source_entry_id') not in scope]
    if outside_before!=outside_after:raise ValueError('分支外节点发生变化，已阻止保存')
    changes=[]
    for key in scope:
        old=[n for n in items if n.get('source_entry_id')==key]
        new=next(n for n in after_items if n.get('source_entry_id')==key)
        if len(old)!=1 or old[0]!=new:
            changes.append(dict(id=key,number=by_ref[key].get('number'),title=by_ref[key]['title'],action='added' if not old else 'restored',ancestor=key in ancestors))
    changes.sort(key=lambda change:next(i for i,e in enumerate(entries) if e['id']==change['id']))
    reference_changed=result.get('directory_reference')!=compiled['reference']
    token=digest(dict(base=base,branch_id=data.branch_id,reference=compiled['fingerprint'],items=after_items))
    outline={**compiled['outline'],'covered_entries':after['present_entries'],'node_count':len(after_items)}
    return dict(base_fingerprint=base,plan_fingerprint=token,branch_id=data.branch_id,changes=changes,
        added=sum(c['action']=='added' for c in changes),restored=sum(c['action']=='restored' for c in changes),
        ancestor_count=sum(c['ancestor'] for c in changes),outside_unchanged=True,has_changes=bool(changes) or reference_changed,
        before=before,after=after,items=after_items,outline=outline,reference=compiled['reference'],reference_fingerprint=compiled['fingerprint'])
