from uuid import uuid4
import pytest
from app.directory_maps import DirectoryMapInput,build


def sample(**changes):
    value=dict(title='课程目录',source_name='课程.pdf',pages_read=[12],request_key=uuid4(),entries=[
        dict(id='part',kind='part',number='第1部分',title='基础'),
        dict(id='chapter',parent_id='part',kind='chapter',number='第1章',title='安全基础',printed_page=1,toc_pdf_page=12),
        dict(id='section',parent_id='chapter',kind='section',number='1.1',title='安全概念',printed_page=2,toc_pdf_page=12),
        dict(id='leaf',parent_id='section',kind='section',number='1.1.1',title='基本定义',printed_page=2,toc_pdf_page=12)])
    value.update(changes);return DirectoryMapInput(**value)


def test_complete_directory_keeps_hierarchy_and_page_meaning():
    result=build(sample());items=result['items']
    assert len(items)==5 and sum(n['parent_id'] is None for n in items)==1
    assert items[-1]['parent_id']=='section'
    assert result['outline']['covered_entries']==result['outline']['entry_count']==4
    assert result['outline']['directory_depth']==4 and result['outline']['map_depth']==5
    assert items[-1]['directory']['printed_page']==2 and items[-1]['directory']['toc_pdf_page']==12
    assert items[-1]['directory']['target_pdf_page'] is None
    assert all(not n['refs'] for n in items)
    assert result['outline']['model_calls']==result['outline']['embedding_calls']==0


def test_directory_is_not_limited_by_generation_node_cap():
    entries=[dict(id='c',kind='chapter',number='第一章',title='基础')]+[
        dict(id=f's{i}',parent_id='c',kind='section',number=f'1.{i}',title=f'第{i}节') for i in range(1,151)]
    result=build(sample(entries=entries))
    assert len(result['items'])==152 and result['outline']['covered_entries']==151


@pytest.mark.parametrize('fault',['cycle','missing','wrong_number','duplicate_id','duplicate_number','wrong_part'])
def test_invalid_parentage_is_rejected_instead_of_dropping_nodes(fault):
    data=sample();entries=[e.model_dump() for e in data.entries]
    if fault=='cycle':entries[0]['parent_id']='leaf'
    if fault=='missing':entries[-1]['parent_id']='missing'
    if fault=='wrong_number':entries[-1]['number']='2.1.1'
    if fault=='duplicate_id':entries[-1]['id']='section'
    if fault=='duplicate_number':entries[-1]['number']='1.1'
    if fault=='wrong_part':entries[1]['parent_id']='section'
    with pytest.raises(ValueError):build(sample(entries=entries))


def test_incomplete_recognition_is_blocked_and_depth_is_bounded():
    with pytest.raises(ValueError):build(sample(unresolved_lines=1))
    with pytest.raises(ValueError):build(sample(failed_pages=[13]))
    entries=[dict(id=f'b{i}',parent_id=f'b{i-1}' if i else None,kind='bookmark',title='书签') for i in range(13)]
    with pytest.raises(ValueError):build(sample(entries=entries))
