import io,zipfile
from xml.etree import ElementTree as ET
import pytest
from app.source_parsing import parse_file
from app.pdf_processing import InvalidPDF
from app.data_tables import collect,csv_export,xlsx_export

def test_csv_preserves_cells_quoted_newline_leading_zeros_and_no_evaluation():
    raw='名称,编号,说明\n甲,0012,"第一行\n第二行"\n乙,=1+1,"含,逗号"\n'
    units,info=parse_file('csv',raw.encode('utf-8'))
    assert units[1]['cells']==['甲','0012','第一行\n第二行']
    assert units[2]['cells'][1]=='=1+1' and len(collect(units)['t1'])==3
    assert info['method']=='csv' and units[2]['location']['row']==3

def pptx(order=('two','one'),unsafe=False):
    out=io.BytesIO();ns='http://schemas.openxmlformats.org/presentationml/2006/main';a='http://schemas.openxmlformats.org/drawingml/2006/main'
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('ppt/presentation.xml',f'<p:presentation xmlns:p="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst>'+''.join(f'<p:sldId id="{i+1}" r:id="{v}"/>' for i,v in enumerate(order))+'</p:sldIdLst></p:presentation>')
        z.writestr('ppt/_rels/presentation.xml.rels','<Relationships><Relationship Id="one" Target="slides/slide1.xml"/><Relationship Id="two" Target="slides/slide2.xml"/></Relationships>')
        for number in (1,2):z.writestr(f'ppt/slides/slide{number}.xml',(' <!DOCTYPE test>'.strip() if unsafe else '')+f'<p:sld xmlns:p="{ns}" xmlns:a="{a}"><p:cSld><p:spTree><p:sp><a:p><a:r><a:t>第{number}张内容</a:t></a:r></a:p></p:sp><p:graphicFrame><a:tbl><a:tr><a:tc><a:p><a:r><a:t>表格文字{number}</a:t></a:r></a:p></a:tc></a:tr></a:tbl></p:graphicFrame></p:spTree></p:cSld></p:sld>')
    return out.getvalue()

def test_pptx_uses_relationship_order_and_keeps_tables():
    units,info=parse_file('pptx',pptx())
    assert units[0]['text']=='第2张内容' and units[0]['location']['slide']==1
    assert units[1]['cells']==['表格文字2'] and info['slides']==2
    assert units[2]['text']=='第1张内容' and info['warnings']

def test_pptx_rejects_unsafe_xml_and_broken_zip():
    with pytest.raises(InvalidPDF):parse_file('pptx',pptx(unsafe=True))
    with pytest.raises(InvalidPDF):parse_file('pptx',b'not-a-zip')

def test_subtitles_keep_real_timestamps_and_do_not_claim_transcription():
    raw='WEBVTT\n\n00:00.000 --> 00:02.100\n<b>模拟字幕内容</b>\n\n00:02.100 --> 00:03.000\n第二段测试字幕\n'
    units,info=parse_file('subtitle',raw.encode())
    assert units[0]['location']['start']=='00:00.000' and units[0]['text']=='模拟字幕内容'
    assert units[1]['text']=='第二段测试字幕' and info['warnings']
    with pytest.raises(InvalidPDF):parse_file('subtitle','没有时间轴的普通文字'.encode())
    with pytest.raises(InvalidPDF):parse_file('subtitle','00:02.000 --> 00:01.000\n倒序字幕'.encode())
    with pytest.raises(InvalidPDF):parse_file('subtitle','00:61.000 --> 01:02.000\n无效时间'.encode())

def test_spreadsheet_exports_are_literal_and_csv_blocks_formula_injection():
    rows=[['标题','数值'],['001','=HYPERLINK("https://example.test")'],['甲','-123'],['乙','<script>&']]
    value=csv_export(rows).decode('utf-8-sig')
    assert "'=HYPERLINK" in value and "'-123" in value
    with zipfile.ZipFile(io.BytesIO(xlsx_export(rows))) as z:
        sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        cells=list(sheet.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'))
        assert all(c.attrib['t']=='inlineStr' for c in cells)
        assert not list(sheet.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}f'))
        assert '<script>&' in ''.join(sheet.itertext())
