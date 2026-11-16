import io
from types import SimpleNamespace
import pytest
from pypdf import PdfWriter
from app import pdf_outline as toc


def test_page_selection_is_explicit_and_bounded():
    assert toc.page_range('',354)==[]
    assert toc.page_range('12-20',354)==list(range(12,21))
    for value in ['1-354','20-12','0','355','12,12','1;2','1-12,13']:
        with pytest.raises(ValueError):toc.page_range(value,354)


def test_missing_bookmarks_never_extracts_any_page(monkeypatch):
    class Page:
        def extract_text(self):raise AssertionError('Body text must not be read')
    monkeypatch.setattr(toc,'PdfReader',lambda *args,**kwargs:SimpleNamespace(is_encrypted=False,pages=[Page()]*354,outline=[]))
    result=toc.preview(b'fake')
    assert result['status']=='needs_pages' and result['pages_read']==[] and result['model_calls']==0


def test_only_selected_text_pages_are_read(monkeypatch):
    seen=[]
    class Page:
        def __init__(self,index):self.index=index
        def extract_text(self):
            assert self.index in [12,13]
            seen.append(self.index)
            return '第1章 网络安全基础........................1\n1.1 计算机安全的基本概念........................2'
    monkeypatch.setattr(toc,'PdfReader',lambda *args,**kwargs:SimpleNamespace(is_encrypted=False,pages=[Page(i) for i in range(1,355)],outline=[]))
    result=toc.preview(b'fake','12-13')
    assert seen==[12,13] and result['ocr_pages']==[]


def test_chapter_section_and_appendix_hierarchy():
    lines=['第1部分 密码学','第2章 对称密码','2.1 对称加密','2.1.1 组成要素','第2部分 网络应用','第4章 身份认证','4.1 基本方法','附录A 标准','A.1 标准组织']
    parsed=toc.parse_lines([dict(pdf_page=12,lines=[dict(text=t,printed_page=i+1,confidence=92) for i,t in enumerate(lines)])])
    entries=parsed['entries']
    assert [n['level'] for n in entries]==[1,2,3,4,1,2,3,1,2]
    assert entries[3]['parent_id']==entries[2]['id']
    assert entries[3]['toc_pdf_page']==12 and entries[3]['printed_page']==4
    assert entries[3]['target_pdf_page'] is None


def test_orphans_are_flagged_instead_of_inventing_chapters():
    parsed=toc.parse_lines([dict(pdf_page=12,lines=[dict(text='3.2 未找到上级',printed_page=20,confidence=90)])])
    assert not parsed['entries'] and len(parsed['unparsed_lines'])==1


def test_ocr_join_keeps_chinese_titles_numbers_and_printed_pages():
    def box(x,y,w,h,text):return [[[x,y],[x+w,y],[x+w,y+h],[x,y+h]],text,.99]
    lines=toc.box_lines([box(10,10,80,20,'第1章引言'),box(900,12,12,16,'1'),
        box(40,50,30,20,'1.1'),box(80,50,200,20,'计算机安全概念'),box(900,52,12,16,'.2')],1000)
    result=toc.parse_lines([dict(pdf_page=12,lines=lines)])
    assert [(e['number'],e['title'],e['printed_page']) for e in result['entries']]==[
        ('第1章','引言',1),('1.1','计算机安全概念',2)]


def test_wrong_chapter_number_is_retained_for_review():
    result=toc.parse_lines([dict(pdf_page=12,lines=[dict(text=t,printed_page=2,confidence=99)
        for t in ['第1章 引言','11.1识别丢失小数点']])])
    assert len(result['entries'])==1 and len(result['unparsed_lines'])==1
    result=toc.parse_lines([dict(pdf_page=12,lines=[dict(text=t,printed_page=2,confidence=99)
        for t in ['第1章 引言','1.1 正确条目','第7章 无线网络安全','1.2 漏识别章号']])])
    assert len(result['entries'])==3 and len(result['unparsed_lines'])==1


def test_repeated_running_headers_remain_auditable():
    result=toc.parse_lines([dict(pdf_page=p,lines=[
        dict(text=f'{p} 同一本教材的重复页眉',y=100,printed_page=None,confidence=99),
        dict(text=f'第{p}章 标题',y=300,printed_page=p,confidence=99)]) for p in [1,2]])
    assert len(result['entries'])==2 and len(result['ignored_headers'])==2
    assert not result['unparsed_lines']


def test_preview_jobs_are_owner_scoped_and_limit_concurrency(monkeypatch):
    import threading,time
    from app import outline_jobs
    started=threading.Event();release=threading.Event()
    def recognize(*args,**kwargs):
        started.set();assert release.wait(5)
        return dict(ocr_pages=[12],entries=[],status='needs_review')
    monkeypatch.setattr(outline_jobs,'preview',recognize)
    job=outline_jobs.start(b'fake','12','owner','notebook')
    try:
        assert started.wait(2)
        assert outline_jobs.lookup(job['job_id'],'other','notebook') is None
        assert outline_jobs.lookup(job['job_id'],'owner','other') is None
        with pytest.raises(RuntimeError):outline_jobs.start(b'fake','12','owner','notebook')
    finally:release.set()
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        state=outline_jobs.lookup(job['job_id'],'owner','notebook')
        if state['status']=='done':break
        time.sleep(.01)
    assert state['result']['status']=='needs_review'


def test_pdf_bookmarks_keep_real_pdf_destinations():
    writer=PdfWriter();writer.add_blank_page(100,100);writer.add_blank_page(100,100)
    root=writer.add_outline_item('第1章 概论',0)
    writer.add_outline_item('1.1 基本概念',1,parent=root)
    buf=io.BytesIO();writer.write(buf)
    result=toc.preview(buf.getvalue())
    assert result['method']=='bookmarks' and result['pages_read']==[]
    assert [e['target_pdf_page'] for e in result['entries']]==[1,2]
    assert result['entries'][1]['parent_id']==result['entries'][0]['id']


def test_empty_user_password_is_openable_but_required_password_is_not():
    for password in ['', 'required-password']:
        writer=PdfWriter();writer.add_blank_page(100,100);writer.encrypt(password,owner_password='owner',algorithm='AES-256')
        buf=io.BytesIO();writer.write(buf)
        if password:
            with pytest.raises(ValueError,match='加密'):toc.preview(buf.getvalue())
        else:assert toc.preview(buf.getvalue())['total_pdf_pages']==1
