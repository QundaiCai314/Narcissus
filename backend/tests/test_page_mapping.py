import io,copy
from types import SimpleNamespace
from uuid import uuid4
import pytest
from pypdf import PdfWriter
from app import page_mapping as mapping
from app.directory_coverage import reference_for
from .test_directory_coverage import fixture_result

SOURCE=dict(sha256='a'*64,total_pages=100)
def data(**changes):return mapping.MappingInput(source_pdf=SOURCE,request_key=uuid4(),**changes)
def rule(**changes):return dict(printed_start=1,printed_end=2,pdf_start=10,pdf_end=11,verified=True,**changes)


def test_metadata_does_not_read_text_or_invent_default_page_labels(monkeypatch):
    class Page:
        def extract_text(self):raise AssertionError('Body must not be read')
    class Reader:
        pages=[Page()]*354;is_encrypted=False;trailer={'/Root':{}}
        @property
        def page_labels(self):raise AssertionError('Default labels are not print-page evidence')
    monkeypatch.setattr(mapping,'PdfReader',lambda *args,**kwargs:Reader())
    result=mapping.metadata(b'fake')
    assert result['source_pdf']['total_pages']==354 and not result['explicit_page_labels']
    assert result['numeric_labels']=={} and result['text_pages_read']==[] and result['model_calls']==0


def test_real_pdf_label_duplicates_are_candidates_not_verified_positions():
    writer=PdfWriter()
    for _ in range(5):writer.add_blank_page(100,100)
    writer.set_page_label(0,1,style='/r',start=1)
    writer.set_page_label(2,3,style='/D',start=1)
    writer.set_page_label(4,4,style='/D',start=1)
    buf=io.BytesIO();writer.write(buf)
    result=mapping.metadata(buf.getvalue())
    assert result['explicit_page_labels'] and result['numeric_labels']=={'1':[3,5],'2':[4]}
    assert result['labels_are_candidates'] and not result['text_pages_read']


def test_unverified_legacy_targets_never_become_body_locations():
    _,result=fixture_result();result['directory_reference']['entries'][1]['target_pdf_page']=99
    compiled=reference_for(result)
    report=mapping.resolve(compiled['reference']['entries'],compiled['fingerprint'],SOURCE)
    assert report['mapped']==0 and all(item['body_pdf_page'] is None for item in report['locations'])
    assert any(item['legacy_target_ignored'] for item in report['locations'])


def test_verified_range_is_bounded_and_entry_override_has_priority():
    _,result=fixture_result()
    staged=mapping.plan(result,data(ranges=[rule()]))
    assert staged['report']['mapped']==3
    locations={item['entry_id']:item for item in staged['report']['locations']}
    assert locations['chapter']['body_pdf_page']==10 and locations['leaf']['body_pdf_page']==11
    assert locations['part']['body_pdf_page'] is None
    partial=mapping.plan(result,data(ranges=[dict(printed_start=2,printed_end=2,pdf_start=11,pdf_end=11,verified=True)]))
    assert partial['report']['mapped']==2
    assert next(item for item in partial['report']['locations'] if item['entry_id']=='chapter')['body_pdf_page'] is None
    targets=[dict(entry_id='chapter',pdf_page=25,verified=True)]
    overridden=mapping.plan(result,data(ranges=[rule()],entry_targets=targets))
    assert next(item for item in overridden['report']['locations'] if item['entry_id']=='chapter')['body_pdf_page']==25
    targets[0]['verified']=False
    pending=mapping.plan(result,data(ranges=[rule()],entry_targets=targets))
    assert pending['pending']==1 and next(item for item in pending['report']['locations'] if item['entry_id']=='chapter')['body_pdf_page'] is None


@pytest.mark.parametrize('ranges',[
    [dict(printed_start=2,printed_end=1,pdf_start=10,pdf_end=11,verified=True)],
    [dict(printed_start=1,printed_end=3,pdf_start=10,pdf_end=11,verified=True)],
    [dict(printed_start=1,printed_end=2,pdf_start=100,pdf_end=101,verified=True)],
    [rule(),dict(printed_start=2,printed_end=3,pdf_start=20,pdf_end=21,verified=True)],
    [rule(),dict(printed_start=3,printed_end=4,pdf_start=11,pdf_end=12,verified=True)],
])
def test_inconsistent_overlapping_and_out_of_bounds_ranges_are_rejected(ranges):
    _,result=fixture_result()
    with pytest.raises(ValueError):mapping.plan(result,data(ranges=ranges))


@pytest.mark.parametrize('targets',[
    [dict(entry_id='missing',pdf_page=1)],
    [dict(entry_id='leaf',pdf_page=101)],
    [dict(entry_id='leaf',pdf_page=1),dict(entry_id='leaf',pdf_page=2)],
])
def test_unknown_duplicate_and_out_of_bounds_targets_are_rejected(targets):
    _,result=fixture_result()
    with pytest.raises(ValueError):mapping.plan(result,data(entry_targets=targets))


def test_source_binding_and_directory_change_invalidate_old_mapping():
    _,result=fixture_result();before=copy.deepcopy(result)
    staged=mapping.plan(result,data(ranges=[rule()]));assert result==before
    saved={**result,'directory_reference':staged['reference'],'page_mapping':staged['settings']}
    assert mapping.current(saved)['mapped']==3
    wrong=dict(SOURCE,sha256='b'*64)
    with pytest.raises(ValueError):mapping.plan(saved,mapping.MappingInput(source_pdf=wrong,request_key=uuid4()))
    changed=copy.deepcopy(saved);changed['directory_reference']['entries'][1]['title']='目录已修改'
    stale=mapping.current(changed)
    assert stale['stale'] and stale['mapped']==0
    assert all(item['body_pdf_page'] is None for item in stale['locations'])


def test_boolean_page_numbers_are_not_accepted():
    with pytest.raises(ValueError):data(entry_targets=[dict(entry_id='leaf',pdf_page=True,verified=True)])
