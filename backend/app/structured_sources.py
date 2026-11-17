"""Bounded local CSV, PPTX and transcript readers. No model or network calls."""
import csv,io,re,zipfile
from xml.etree import ElementTree as ET
from .config import settings
from .pdf_processing import InvalidPDF

def csv_units(data):
    from .source_parsing import decode_text,unit
    text,encoding=decode_text(data)
    if len(text)>settings().max_document_chars:raise InvalidPDF('表格文字过长，请拆分资料')
    try:
        try:dialect=csv.Sniffer().sniff(text[:8192],delimiters=',;\t')
        except csv.Error:dialect=csv.excel
        rows=list(csv.reader(io.StringIO(text,newline=''),dialect,strict=True))
        if not rows or len(rows)>5000 or any(len(row)>100 for row in rows):raise InvalidPDF('CSV需包含1至5000行，最多100列')
        width=max(map(len,rows));result=[]
        for n,row in enumerate(rows,1):
            if not row or not any(c.strip() for c in row):continue
            if any(len(c)>10000 for c in row):raise InvalidPDF('CSV单元格过长')
            cells=row+['']*(width-len(row));u=unit(' | '.join(cells),len(result)+1,f'表格1 · 第{n}行',kind='table',table=1,row=n)
            u['cells']=cells;result.append(u)
        return result,dict(method='csv',encoding=encoding,warnings=[],tables=1)
    except csv.Error:raise InvalidPDF('CSV格式无法可靠读取，请核对分隔符和引号') from None

def pptx_units(data):
    from .source_parsing import unit
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            files=archive.infolist();names=[f.filename for f in files]
            if len(files)>3000 or len(set(names))!=len(names) or sum(f.file_size for f in files)>settings().max_unpacked_mb*1024*1024:raise InvalidPDF('PPTX解压后过大或包含重复条目')
            if any(f.flag_bits&1 for f in files) or 'ppt/presentation.xml' not in names:raise InvalidPDF('不是可读取的PPTX，或文件已加密')
            def xml(name):
                raw=archive.read(name)
                if b'\x00' in raw or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise InvalidPDF('PPTX包含不支持的XML声明')
                return ET.fromstring(raw)
            ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
            main=xml('ppt/presentation.xml');rels=xml('ppt/_rels/presentation.xml.rels')
            targets={e.attrib['Id']:e.attrib.get('Target','') for e in rels if e.attrib.get('TargetMode')!='External'}
            ordered=[]
            for entry in main.findall('p:sldIdLst/p:sldId',ns):
                target=targets.get(entry.attrib.get('{'+ns['r']+'}id'),'')
                if not re.fullmatch(r'slides/slide[0-9]+\.xml',target):raise InvalidPDF('PPTX幻灯片引用无效')
                ordered.append('ppt/'+target)
            if not 1<=len(ordered)<=100:raise InvalidPDF('PPTX最多100张幻灯片')
            result=[];tables=0
            def paragraphs(element):return [''.join(p.itertext()).strip() for p in element.findall('.//a:p',ns)]
            for number,name in enumerate(ordered,1):
                for shape in xml(name).findall('.//p:spTree/*',ns):
                    if shape.tag.endswith('}graphicFrame'):
                        for table in shape.findall('.//a:tbl',ns):
                            tables+=1
                            for row_no,row in enumerate(table.findall('a:tr',ns),1):
                                cells=['\n'.join(paragraphs(cell)) for cell in row.findall('a:tc',ns)]
                                if not any(c.strip() for c in cells):continue
                                u=unit(' | '.join(cells),len(result)+1,f'幻灯片{number} · 表格{tables} · 第{row_no}行',slide=number,kind='table',table=tables,row=row_no);u['cells']=cells;result.append(u)
                    elif shape.tag.endswith('}sp'):
                        text='\n'.join(p for p in paragraphs(shape) if p)
                        if text:result.append(unit(text,len(result)+1,f'幻灯片{number}',slide=number,kind='paragraph'))
                if len(result)>5000 or sum(len(u['text']) for u in result)>settings().max_document_chars:raise InvalidPDF('PPTX正文过长，请拆分文件')
            if not result:raise InvalidPDF('PPTX未找到可读取文字，请导出PDF或补充文字')
            return result,dict(method='pptx',slides=len(ordered),tables=tables,warnings=['仅提取文字和原生表格；图片、公式对象、图表、备注及动画需核对原件。'])
    except InvalidPDF:raise
    except (zipfile.BadZipFile,KeyError,ET.ParseError,ValueError):raise InvalidPDF('PPTX损坏或结构不支持，请重新导出') from None

def subtitle_units(data):
    from .source_parsing import decode_text,unit
    text,encoding=decode_text(data)
    if len(text)>settings().max_document_chars:raise InvalidPDF('字幕过长，请拆分资料')
    matches=list(re.finditer(r'(?m)^((?:\d{2}:)?\d{2}:\d{2}[.,]\d{3})\s+-->\s+((?:\d{2}:)?\d{2}:\d{2}[.,]\d{3})[^\n]*\n',text));result=[]
    def seconds(stamp):
        parts=stamp.replace(',','.').split(':');minutes,sec=int(parts[-2]),float(parts[-1])
        if minutes>=60 or sec>=60:raise InvalidPDF('字幕时间轴超出有效分秒范围')
        return (int(parts[0])*3600 if len(parts)==3 else 0)+minutes*60+sec
    previous=-1
    for i,match in enumerate(matches):
        start,end=seconds(match[1]),seconds(match[2])
        if start<previous or end<=start:raise InvalidPDF('字幕时间轴倒序或结束时间无效，请先校对')
        previous=start
        body=text[match.end():matches[i+1].start() if i+1<len(matches) else len(text)]
        body=re.sub(r'\n\s*\d+\s*$','',body).strip();body=re.sub(r'<[^>]+>','',body)
        if body:result.append(unit(body,len(result)+1,f'{match[1]}–{match[2]}',kind='transcript',start=match[1],end=match[2]))
    if not result or len(result)>5000:raise InvalidPDF('未识别到有效SRT/VTT字幕时间轴，或字幕条目过多')
    return result,dict(method='subtitles',encoding=encoding,warnings=['仅导入字幕文字；未获取视频或音频，也未核实字幕与原声一致。'])
