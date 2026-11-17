"""Read-only tables from confirmed source units, with cell-safe local exports."""
import csv,io,re,zipfile
from xml.sax.saxutils import escape
from fastapi import APIRouter,Depends
from fastapi.responses import Response
from sqlalchemy import select
from . import access
from .db import db_session
from .models import Document,SourceVersion
from .security import current_user
from .errors import fail
router=APIRouter(tags=['来源数据表'])

def collect(units):
    groups={}
    for u in units:
        if u.get('location',{}).get('kind')!='table' or not isinstance(u.get('cells'),list):continue
        identity='t'+str(u['location'].get('table',1))
        groups.setdefault(identity,[]).append(dict(cells=[str(c) for c in u['cells']],unit_id=u['id'],location=u['location']))
    return groups

def published(db,doc):
    if not doc.active_version:fail(409,'unconfirmed','请先核对并确认入库')
    row=db.scalar(select(SourceVersion).where(SourceVersion.document_id==doc.id,SourceVersion.version==doc.active_version))
    if not row or row.status!='ready':fail(409,'unavailable','当前来源版本尚不可用')
    return row

@router.get('/notebooks/{notebook_id}/data-tables')
def listing(notebook_id:str,user=Depends(current_user),db=Depends(db_session)):
    access.notebook(db,user.id,notebook_id);items=[]
    for doc in db.scalars(select(Document).where(Document.notebook_id==notebook_id,Document.deleted_at.is_(None),Document.active_version>0).limit(200)):
        version=published(db,doc)
        for ident,rows in collect(version.units).items():items.append(dict(id=ident,document_id=doc.id,filename=doc.filename,version=version.version,rows=len(rows),columns=max(len(r['cells']) for r in rows)))
    return dict(items=items)

def table(db,user_id,document_id,table_id):
    doc=access.document(db,user_id,document_id);version=published(db,doc)
    rows=collect(version.units).get(table_id)
    if not rows:fail(404,'not_found','来源表格不存在')
    return dict(id=table_id,document_id=doc.id,filename=doc.filename,version=version.version,rows=rows)

@router.get('/documents/{document_id}/tables/{table_id}')
def read(document_id:str,table_id:str,user=Depends(current_user),db=Depends(db_session)):
    return table(db,user.id,document_id,table_id)

def csv_export(rows):
    out=io.StringIO(newline='');writer=csv.writer(out)
    for row in rows:
        writer.writerow(["'"+c if re.match(r'^[\s\x00-\x1f]*[=+@-]',c) else c for c in row])
    return ('\ufeff'+out.getvalue()).encode('utf-8')

def xlsx_export(rows):
    def column(i):
        value=''
        while i:i,r=divmod(i-1,26);value=chr(65+r)+value
        return value
    def clean(s):return escape(re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',s))
    body=''.join('<row r="'+str(i)+'">'+''.join(f'<c r="{column(j)}{i}" t="inlineStr"><is><t xml:space="preserve">{clean(c)}</t></is></c>' for j,c in enumerate(row,1))+'</row>' for i,row in enumerate(rows,1))
    files={'[Content_Types].xml':'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
      '_rels/.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
      'xl/workbook.xml':'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="来源数据" sheetId="1" r:id="r1"/></sheets></workbook>',
      'xl/_rels/workbook.xml.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
      'xl/worksheets/sheet1.xml':'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+body+'</sheetData></worksheet>'}
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,content in files.items():z.writestr(name,content)
    return out.getvalue()

@router.get('/documents/{document_id}/table-exports/{table_id}/{format}')
def export(document_id:str,table_id:str,format:str,user=Depends(current_user),db=Depends(db_session)):
    value=table(db,user.id,document_id,table_id);rows=[r['cells'] for r in value['rows']]
    if format not in ('csv','xlsx'):fail(422,'format','请选择CSV或XLSX')
    data=csv_export(rows) if format=='csv' else xlsx_export(rows)
    mime='text/csv; charset=utf-8' if format=='csv' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    return Response(data,media_type=mime,headers={'Content-Disposition':f'attachment; filename="narcissus-table.{format}"'})
