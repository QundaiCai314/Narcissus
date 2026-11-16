import copy
from uuid import uuid4
import pytest
from app.directory_maps import build
from app.directory_coverage import audit,plan,reference_for,BranchInput,descendants
from .test_directory_maps import sample


def fixture_result():
    data=sample(confirmed=True)
    data=sample(confirmed=True,entries=[e.model_dump() for e in data.entries]+[
        dict(id='chapter2',parent_id='part',kind='chapter',number='第2章',title='第二章'),
        dict(id='section2',parent_id='chapter2',kind='section',number='2.1',title='其他分支')])
    compiled=build(data)
    return data,dict(items=compiled['items'],outline=compiled['outline'],directory_reference=compiled['reference'])


def request(**changes):return BranchInput(request_key=uuid4(),**changes)


def test_coverage_uses_separate_reference_not_current_node_count():
    data,result=fixture_result();compiled=reference_for(result)
    assert audit(result['items'],compiled)['complete']
    assert not audit(result['items'],None)['available']
    subset=descendants(result['directory_reference']['entries'],'chapter')
    damaged=[n for n in result['items'] if n.get('source_entry_id') not in subset]
    report=audit(damaged,compiled)
    assert report['expected_entries']==6 and report['present_entries']==3
    assert len(report['missing'])==3 and not report['complete']
    assert report['chapters'][0]['missing']==3 and report['chapters'][1]['healthy']==2


def test_titles_parentage_duplicates_and_unexpected_nodes_are_distinct():
    _,result=fixture_result();nodes=copy.deepcopy(result['items']);leaf=next(n for n in nodes if n['id']=='leaf')
    leaf['title']='被修改的标题';leaf['parent_id']='part'
    nodes.append(dict(id='extra',parent_id='__outline_root__',title='额外条目',refs=[]))
    report=audit(nodes,reference_for(result))
    assert [n['id'] for n in report['misplaced']]==['leaf']
    assert [n['id'] for n in report['changed']]==['leaf'] and len(report['unexpected'])==1
    nodes.append(dict(leaf,id='duplicate-leaf'))
    assert [n['id'] for n in audit(nodes,reference_for(result))['duplicates']]==['leaf']


def test_restore_only_selected_branch_preserves_every_outside_field_and_order():
    _,result=fixture_result();branch=descendants(result['directory_reference']['entries'],'chapter')
    result['items']=[n for n in result['items'] if n.get('source_entry_id') not in branch]
    result['items'][-1]['custom_note']='保留这段分支外内容'
    before=copy.deepcopy(result)
    staged=plan(result,request(branch_id='chapter'))
    assert staged['added']==3 and staged['after']['complete'] and staged['outside_unchanged']
    assert [n for n in staged['items'] if n.get('source_entry_id') not in branch]==before['items']
    assert result==before


def test_required_missing_ancestors_are_added_without_modifying_siblings():
    _,result=fixture_result()
    removed={'part','chapter','section','leaf'}
    result['items']=[n for n in result['items'] if n.get('source_entry_id') not in removed]
    outside=copy.deepcopy(result['items'])
    staged=plan(result,request(branch_id='leaf'))
    assert staged['ancestor_count']==3 and staged['added']==4 and staged['after']['complete']
    assert [n for n in staged['items'] if n.get('source_entry_id') not in removed]==outside


def test_other_missing_chapter_remains_visible_after_local_restore():
    _,result=fixture_result();result['items']=[n for n in result['items'] if n['id'] in ['__outline_root__','part']]
    staged=plan(result,request(branch_id='chapter'))
    assert staged['after']['present_entries']==4 and len(staged['after']['missing'])==2
    assert not staged['after']['complete']


def test_legacy_reference_must_be_explicitly_confirmed_and_can_be_saved_without_node_changes():
    data,result=fixture_result();result.pop('directory_reference')
    with pytest.raises(ValueError,match='没有独立'):plan(result,request(branch_id='chapter'))
    data.confirmed=False
    with pytest.raises(ValueError,match='确认'):plan(result,request(reference=data))
    data.confirmed=True
    staged=plan(result,request(reference=data))
    assert staged['has_changes'] and not staged['changes'] and staged['items']==result['items']
    assert not audit(result['items'],reference_for(result,sample(confirmed=False)))['reference_confirmed']


def test_complete_branch_is_noop_and_conflicts_are_not_silently_removed():
    _,result=fixture_result()
    assert not plan(result,request(branch_id='chapter'))['has_changes']
    leaf=next(n for n in result['items'] if n['id']=='leaf');leaf['id']='alias'
    result['items'].append(dict(id='leaf',parent_id='__outline_root__',title='分支外冲突',refs=[]))
    with pytest.raises(ValueError,match='冲突'):plan(result,request(branch_id='leaf'))


def test_pending_review_and_invalid_external_graph_block_publication():
    data,result=fixture_result();data.entries[-1].needs_review=True
    with pytest.raises(ValueError,match='未确认'):plan(result,request(branch_id='chapter',reference=data))
    result['items'].append(dict(id='orphan',parent_id='missing',title='分支外孤立节点',refs=[]))
    with pytest.raises(ValueError,match='分支外'):plan(result,request(branch_id='chapter'))
