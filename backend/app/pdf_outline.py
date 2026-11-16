"""Local-only PDF contents preview. Never embeds or sends pages to a model."""
import io
import re
import json
import subprocess
import sys
import time
import statistics
from pypdf import PdfReader
from .ocr import LocalOCR, OCRFailure
from .config import settings


def page_range(value, total, limit=12):
    if not value.strip():
        return []
    pages = []
    for part in value.replace('，', ',').split(','):
        match = re.fullmatch(r'\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*', part)
        if not match:
            raise ValueError('请输入PDF页码，例如12-20或3,5-8')
        start, end = int(match[1]), int(match[2] or match[1])
        if not 1 <= start <= end <= total or end-start+1 > limit:
            raise ValueError(f'页码超出范围，且每次最多识别{limit}页目录')
        pages.extend(range(start, end+1))
    if len(pages) > limit or len(set(pages)) != len(pages):
        raise ValueError(f'页码不能重复，每次最多识别{limit}页目录')
    return sorted(pages)


def box_lines(boxes,width):
    words=[]
    for box,text,score in boxes:
        if not text.strip() or re.fullmatch(r'[.·…_－-]+',text.strip()):continue
        xs,ys=zip(*box);words.append(dict(text=text.strip(),x=min(xs),y=min(ys),h=max(ys)-min(ys),confidence=score*100))
    tolerance=max(4,statistics.median([w['h'] for w in words] or [12])*.55);groups=[]
    for word in sorted(words,key=lambda w:w['y']+w['h']/2):
        center=word['y']+word['h']/2
        if not groups or abs(center-groups[-1]['center'])>tolerance:groups.append(dict(center=center,words=[]))
        groups[-1]['words'].append(word)
    lines=[]
    for group in groups:
        words=sorted(group['words'],key=lambda w:w['x']);raw=' '.join(w['text'] for w in words);page=None
        if words[-1]['x']>width*.80:
            match=re.fullmatch(r'\D*(\d{1,4})\D*',words[-1]['text'])
            if match:page=int(match[1]);words=words[:-1]
        text=' '.join(w['text'] for w in words)
        text=re.sub(r'(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])','',text)
        text=re.sub(r'(?<=\d)\s*[.．]\s*(?=\d)', '.', text)
        text=re.sub(r'[.·．…_\s－-]+$','',text)
        if text:lines.append(dict(text=text,raw=raw,printed_page=page,confidence=round(statistics.mean([w['confidence'] for w in words] or [0]),1),y=round(group['center'])))
    return lines


def parse_lines(pages):
    entries, uncertain, warnings, ignored = [], [], [], []
    header_pages={}
    for page in pages:
        for line in page['lines']:
            if line.get('y',9999)>200:continue
            text=line['text'].strip()
            if re.match(r'^(第|附录|参考文献|[A-Z]?\d+\.)',text):continue
            key=re.sub(r'^\d+\s*','',text)
            if len(key)>5:header_pages.setdefault(key,set()).add(page['pdf_page'])
    part_id, current_number = None, None
    numbers = {}; last_sections = {}; seen_numbers = set()
    for page in pages:
        for line in page['lines']:
            text = line['text'].strip()
            if line.get('y',9999)<=200 and len(header_pages.get(re.sub(r'^\d+\s*','',text),set()))>=2:
                ignored.append(dict(line,toc_pdf_page=page['pdf_page'],reason='重复页眉'));continue
            kind, number, title, parent = None, None, None, None
            heading = re.match(r'^第\s*([\d一二三四五六七八九十百]+)\s*(部分|篇|章)\s*(.+)$',text)
            appendix = re.match(r'^附录\s*([A-Z])\s*(.+)$',text,re.I)
            numeric = re.match(r'^([A-Z]?\d*(?:\.\d+){1,4})[.：:，,\s]*([^\d.].*)$',text)
            if heading:
                number, marker, title = heading.groups()
                kind = 'chapter' if marker == '章' else 'part'
                parent = part_id if kind == 'chapter' else None
                number = ('第'+number+marker)
            elif appendix:
                letter,title=appendix.groups();number='附录'+letter.upper();kind='appendix'
            elif numeric:
                number,title=numeric.groups();kind='section'
                ancestor = number.rsplit('.',1)[0]
                if number.split('.')[0]!=current_number:
                    uncertain.append(dict(line,toc_pdf_page=page['pdf_page'],reason='编号与当前章不匹配'));continue
                parent = numbers.get(ancestor) or numbers.get(number.split('.')[0])
                if not parent:
                    uncertain.append(dict(line,toc_pdf_page=page['pdf_page'],reason='没有找到所属章节'));continue
                if '.' in ancestor and ancestor not in numbers:
                    warnings.append(f'编号{number}缺少上一级{ancestor}，暂挂在当前章下')
            elif text.startswith('参考文献'):
                kind='reference';title=text
            else:
                if re.search(r'[\u3400-\u9fff]',text) and not re.fullmatch(r'目\s*录',text):
                    uncertain.append(dict(line,toc_pdf_page=page['pdf_page'],reason='编号或标题未可靠识别'))
                continue
            if not title or len(title)>180:
                uncertain.append(dict(line,toc_pdf_page=page['pdf_page'],reason='标题长度异常'));continue
            title=title.lstrip(' ：:，,')
            ident=f'toc-{len(entries)+1}'
            entry=dict(id=ident,parent_id=parent,kind=kind,number=number,title=title,
                       toc_pdf_page=page['pdf_page'],printed_page=line.get('printed_page'),
                       target_pdf_page=None,confidence=line.get('confidence'),needs_review=line.get('confidence',100)<95 or (kind!='part' and (line.get('printed_page') is None or line.get('page_confidence',100)<85)),
                       raw_line=line.get('raw',text))
            if number and number in seen_numbers:
                warnings.append(f'编号{number}重复，请核对');entry['needs_review']=True
            if kind=='section':
                prefix,index=number.rsplit('.',1);index=int(index)
                expected=last_sections.get(prefix,0)+1
                if index!=expected:
                    warnings.append(f'编号{number}与相邻条目不连续，请核对');entry['needs_review']=True
                last_sections[prefix]=index
            if number:seen_numbers.add(number)
            entries.append(entry)
            if kind=='part':part_id=ident;current_number=None
            elif kind=='chapter':current_number=number[1:-1];numbers[current_number]=ident
            elif kind=='appendix':current_number=number[-1];numbers[current_number]=ident;part_id=None
            elif number:numbers[number]=ident
    by_id={item['id']:item for item in entries}
    for entry in entries:
        current=entry;level=1
        while current['parent_id']:
            current=by_id[current['parent_id']];level+=1
        entry['level']=level
    return dict(entries=entries,unparsed_lines=uncertain,ignored_headers=ignored,warnings=list(dict.fromkeys(warnings)))


def preview(data, requested_pages='', progress=None):
    reader=PdfReader(io.BytesIO(data),strict=False)
    if reader.is_encrypted and not reader.decrypt(''):
        raise ValueError('暂不支持加密PDF')
    total=len(reader.pages)
    selected=page_range(requested_pages,total)
    base=dict(total_pdf_pages=total,model_calls=0,embedding_calls=0,pages_read=[],ocr_pages=[],warnings=[])
    if progress:progress(0,len(selected))
    if not selected:
        bookmarks=[]
        def walk(items,parent=None,level=1):
            previous=parent
            for item in items:
                if len(bookmarks)>=2000 or level>12:return
                if isinstance(item,list):walk(item,previous,level+1)
                else:
                    try:page=reader.get_destination_page_number(item)
                    except Exception:page=None
                    previous=f'bookmark-{len(bookmarks)+1}'
                    bookmarks.append(dict(id=previous,parent_id=parent,level=level,title=str(item.title),
                                          kind='bookmark',target_pdf_page=page+1 if page is not None else None,
                                          printed_page=None,toc_pdf_page=None,confidence=None,needs_review=page is None))
        walk(reader.outline)
        return dict(base,status='ready' if bookmarks else 'needs_pages',method='bookmarks' if bookmarks else 'none',entries=bookmarks,unparsed_lines=[])
    pages=[];ocr=None;failed=[];jobs=[]
    try:
        for number in selected:
            text=reader.pages[number-1].extract_text() or ''
            base['pages_read'].append(number)
            if len(re.sub(r'\s','',text)) >= 30:
                lines=[dict(text=t,raw=t,printed_page=None,confidence=100) for t in text.splitlines() if t.strip()]
                for line in lines:
                    match=re.match(r'^(.*?)\s*[.·．…_]{2,}\s*(\d+)\s*$',line['text'])
                    if match:line.update(text=match[1].strip(),printed_page=int(match[2]))
            else:
                if ocr is None:ocr=LocalOCR(data)
                image=ocr.root/f'toc-{number}'
                try:
                    ocr.run(['pdftoppm','-f',str(number),'-l',str(number),'-singlefile','-scale-to','2600','-gray','-png',str(ocr.pdf),str(image)])
                    jobs.append(dict(pdf_page=number,path=str(image)+'.png'))
                except OCRFailure as exc:
                    failed.append(dict(pdf_page=number,error=str(exc)))
                continue
            pages.append(dict(pdf_page=number,lines=lines))
        if jobs:
            job_file=ocr.root/'jobs.json';result_file=ocr.root/'results.json'
            job_file.write_text(json.dumps(jobs),encoding='utf-8')
            timeout=max(1,min(600,settings().outline_timeout_seconds)-(time.monotonic()-ocr.started))
            try:
                with subprocess.Popen([sys.executable,'-m','app.outline_ocr',str(job_file),str(result_file)],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) as process:
                    deadline=time.monotonic()+timeout
                    while process.poll() is None:
                        if time.monotonic()>=deadline:
                            process.kill();process.wait();break
                        if progress and result_file.exists():
                            progress(len(json.loads(result_file.read_text(encoding='utf-8'))),len(jobs))
                        time.sleep(.5)
            except OSError:pass
            recognized=json.loads(result_file.read_text(encoding='utf-8')) if result_file.exists() else []
            for job in jobs:
                match=next((item for item in recognized if item['pdf_page']==job['pdf_page']),None)
                if match is None or not match['lines']:
                    failed.append(dict(pdf_page=job['pdf_page'],error='本地目录识别失败或超时'));continue
                pages.append(dict(pdf_page=job['pdf_page'],lines=match['lines']))
                base['ocr_pages'].append(job['pdf_page'])
    finally:
        if ocr:ocr.close()
    pages.sort(key=lambda page:page['pdf_page']);parsed=parse_lines(pages)
    warnings=parsed['warnings']+[f"PDF第{item['pdf_page']}页识别失败，可单独重试此页" for item in failed]
    return dict(base,**{k:v for k,v in parsed.items() if k!='warnings'},warnings=warnings,failed_pages=failed,
                status='ready' if parsed['entries'] and not failed and not parsed['unparsed_lines'] and not warnings and not any(e['needs_review'] for e in parsed['entries']) else 'needs_review',method='contents_pages',page_lines=pages)
