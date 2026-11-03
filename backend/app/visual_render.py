"""One measured scene for web PNG, PDF and native editable PowerPoint objects."""
import io
import json
import subprocess
import tempfile
import re
from html import escape
from pathlib import Path
from PIL import ImageFont
from .config import settings
from .model_service import ModelError
from .visual_schema import THEMES

FONT="Noto Sans CJK SC"

def wrap(text, width, size):
    font=ImageFont.truetype(settings().visual_font_path, size, index=2)
    result=[]
    for paragraph in str(text).splitlines() or [""]:
        line=""
        tokens=[]
        for char in re.findall(r"\[\d+\]|[A-Za-z0-9_]+(?:[./:-][A-Za-z0-9_]+)*|.",paragraph):
            if char in "，。！？；：、）】》”’.,;!?" and tokens:
                tokens[-1]+=char
            else:tokens.append(char)
        for char in tokens:
            if font.getlength(char)>width:
                raise ModelError("英文标识或地址超出当前栏宽，请精简或改用更宽版式")
            if line and font.getlength(line+char)>width:
                result.append(line);line=char
            else:line+=char
        result.append(line)
    return result


def page_refs(page):
    return sorted({n for p in page["points"] for n in p["refs"]} | {n for d in page["data"] for n in d["refs"]} | {n for row in page.get("rows",[]) for n in row["refs"]})


def source_notes(snapshot,page):
    lines=[page["notes"]]
    if page.get("edited"):lines.append("内容已修改，引用仅表示原有关联，需人工核对。")
    known={e["label"]:e for e in snapshot["evidence"]}
    for label in page_refs(page):
        e=known[label]
        lines.append(f"[{label}] {e['filename']} · 版本 {e['version']} · {e.get('position','用户笔记')}" + (" · 原始资料已删除" if e.get("state")=="deleted" else " · 资料已更新" if e.get("state")=="changed" else ""))
        lines += [e.get("source_url") or "",e["text"]]
    for d in page["data"]:lines.append(f"{d['label']}：{d['value']}；原始单位 {d['unit']}；适用时间 {d['period']}；计算方法 {d['method']}")
    return "\n".join(lines)


def scene(snapshot,page,index=0):
    params=snapshot["params"];info=snapshot["kind"]=="infographic"
    width,height=((1200,1600) if params["orientation"]=="portrait" else (1600,900)) if info else (1280,720)
    theme=dict(THEMES[params["template"]]);theme["accent"]=params.get("color") or theme["accent"]
    nodes=[];margin=56;inner=width-2*margin
    def rect(x,y,w,h,color):nodes.append({"type":"rect","x":x,"y":y,"w":w,"h":h,"color":color})
    def text(value,x,y,w,size=28,color=None,bold=False,max_lines=None):
        lines=wrap(value,w,size)
        if max_lines and len(lines)>max_lines:raise ModelError(f"第{index+1}页文字超出空间，请精简或拆页（{page['title'][:20]}）")
        step=round(size*1.48,2)
        for i,line in enumerate(lines):nodes.append({"type":"text","text":line,"x":x,"y":y+i*step,"w":w,"h":step,"size":size,"color":color or theme["ink"],"bold":bold})
        return y+len(lines)*step
    rect(0,0,width,height,theme["background"]);rect(margin,38,64,6,theme["accent"])
    top=66
    title_size=52 if page["layout"]=="cover" else 44
    top=text(page["title"],margin,top,inner,title_size,bold=True,max_lines=3 if info else 2)+18
    if page["claim"]:top=text(page["claim"],margin,top,inner,26 if not info else 30,max_lines=3)+22
    refs=page_refs(page);known={e["label"]:e for e in snapshot["evidence"]}
    if len(refs)>10:raise ModelError("单页引用过多，请分成多页")
    footer_lines=[]
    for n in refs:
        e=known[n]
        name=e["filename"] if len(e["filename"])<=34 else e["filename"][:31]+"…"
        footer_lines.append(f"[{n}] {name} · {e.get('position','用户笔记观点')}"+(" · 原始资料已删除" if e.get("state")=="deleted" else " · 资料已更新" if e.get("state")=="changed" else ""))
    if not info:footer_lines=["来源："+" ".join(f"[{n}]" for n in refs)+" · 完整原文与位置见讲解备注"] if refs else ["手动编写／资料不足，未声明来源核验"]
    footer_height=sum(len(wrap(line,inner,17))*25 for line in footer_lines)+24
    bottom=height-36-footer_height
    body_size=(26 if params["mode"]=="reading" else 30) if not info else {"low":36,"standard":32,"high":28}[params["density"]]
    points=page["points"]
    def point_text(p):
        return ("用户观点：" if p["basis"]=="opinion" else "资料缺口：" if p["basis"]=="gap" else "")+p["text"]+" "+" ".join(f"[{n}]" for n in p["refs"])
    layout=page["layout"]
    if info and points:
        # Bounded cards distribute actual content across the canvas without changing font size.
        columns=2 if layout=="comparison" or (width>height and layout=="bullets") else 1
        gap=28;card_w=(inner-gap*(columns-1))/columns
        counts=[len(points[side::columns]) for side in range(columns)]
        positions=[top]*columns
        for i,p in enumerate(points):
            side=i%columns;x=margin+side*(card_w+gap);y=positions[side]
            left=86 if layout=="timeline" else 28
            body=point_text(p);needed=len(wrap(body,card_w-left-28,body_size))*body_size*1.48+66
            slot=(bottom-top-gap*(counts[side]-1))/counts[side]
            h=min(slot,max(needed,180 if width<height else 150))
            if needed>slot:raise ModelError("信息图内容超出空间，请减少要点或精简文案")
            rect(x,y,card_w,h,"FFFFFF")
            rect(x,y,5,h,theme["accent"])
            if layout=="timeline":
                rect(x+20,y+28,44,44,theme["accent"])
                text(f"{i+1:02d}",x+25,y+29,40,25,color="FFFFFF")
                if i<len(points)-1:rect(x+40,y+h,3,gap,theme["accent"])
            text(body,x+left,y+28,card_w-left-28,body_size)
            positions[side]=y+h+gap
    elif layout=="comparison":
        gap=48;col=(inner-gap)/2
        for side in range(2):
            y=top
            for p in points[side::2]:
                y=text(point_text(p),margin+side*(col+gap),y,col,body_size,max_lines=6)+22
            if y>bottom:raise ModelError(f"第{index+1}页双栏内容过多，请精简或拆页")
        rect(width/2-1,top,2,max(0,bottom-top),"D9DFDC")
    elif layout=="chart":
        if bottom-top<220:raise ModelError("图表空间不足，请缩短标题和概述")
        slot=(bottom-top)/len(page["data"])
        for d in page["data"]:
            label=d["label"]+" "+" ".join(f"[{r}]" for r in d["refs"])
            value=f"{d['value']:g}{'%' if d['operation']=='ratio_percent' else d['unit']} · {d['period']}"
            if max(len(wrap(label,230,22))*30,len(wrap(value,190,19))*26)+14>slot:
                raise ModelError("图表标签过长或数据项过多，请精简或拆页")
        nodes.append({"type":"chart","x":margin,"y":top,"w":inner,"h":bottom-top,"data":page["data"],"color":theme["accent"]})
    elif layout=="table":
        n=len(page["columns"]);col=inner/n;y=top
        for ri,row in enumerate([{"cells":page["columns"],"refs":[]}]+page["rows"]):
            cells=list(row["cells"]);cells[-1]+=" "+" ".join(f"[{x}]" for x in row["refs"])
            line_count=max(len(wrap(c,col-24,24)) for c in cells);rh=line_count*36+24
            if y+rh>bottom:raise ModelError(f"第{index+1}页表格超出空间，请减少行数或缩短单元格")
            rect(margin,y,inner,rh,"E4ECE8" if ri==0 else ("FFFFFF" if ri%2 else theme["background"]))
            for ci,cell in enumerate(cells):text(cell,margin+ci*col+12,y+12,col-24,24,bold=ri==0)
            y+=rh
    else:
        y=top+(20 if layout in ("cover","section") else 0)
        for i,p in enumerate(points):
            prefix=f"{i+1:02d}  " if layout=="timeline" else "•  " if layout not in ("cover","section") else ""
            y=text(prefix+point_text(p),margin,y,inner,body_size,max_lines=5)+18
        if y>bottom:raise ModelError(f"第{index+1}页内容超出空间，请精简或拆页")
    rect(margin,bottom+12,inner,1,"D9DFDC")
    y=bottom+23
    for line in footer_lines:y=text(line,margin,y,inner,17,color="52635D")+1
    if page.get("edited"):text("内容已修改，引用需核对",margin,height-24,inner,13,color="946028")
    if not info:text(f"{index+1:02d}",width-90,height-30,40,16,color="52635D")
    return {"width":width,"height":height,"nodes":nodes,"notes":source_notes(snapshot,page),"title":page["title"]}


def svg(scene):
    body=[]
    def tx(text,x,y,size,color):return f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" fill="#{color}">{escape(str(text))}</text>'
    for n in scene["nodes"]:
        if n["type"]=="rect":body.append(f'<rect x="{n["x"]}" y="{n["y"]}" width="{n["w"]}" height="{n["h"]}" fill="#{n["color"]}"/>')
        elif n["type"]=="text":
            # Single measured lines avoid browser-dependent wrapping.
            body.append(tx(n["text"],n["x"],n["y"]+n["size"],n["size"],n["color"]))
        else:
            data=n["data"];extent=max(abs(d["value"]) for d in data) or 1
            slot=n["h"]/len(data);label_w=250;bar_w=n["w"]-label_w-210
            if bar_w<100:raise ModelError("图表空间不足")
            # All bars share a zero baseline; negative values extend left of it.
            negative=any(d["value"]<0 for d in data);scale=bar_w/(2 if negative else 1)/extent;origin=n["x"]+label_w+(bar_w/2 if negative else 0)
            for i,d in enumerate(data):
                y=n["y"]+i*slot+10;length=abs(d["value"])*scale
                label=d["label"]+" "+" ".join(f"[{r}]" for r in d["refs"])
                for j,line in enumerate(wrap(label,label_w-20,22)):body.append(tx(line,n["x"],y+24+j*30,22,"26344B"))
                x=origin-length if d["value"]<0 else origin
                body.append(f'<rect x="{x}" y="{y+4}" width="{length}" height="{min(36,slot-34)}" fill="#{n["color"]}"/>')
                value=f"{d['value']:g}{'%' if d['operation']=='ratio_percent' else d['unit']} · {d['period']}"
                for j,line in enumerate(wrap(value,190,19)):body.append(tx(line,n["x"]+n["w"]-190,y+24+j*26,19,"26344B"))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{scene["width"]}" height="{scene["height"]}" viewBox="0 0 {scene["width"]} {scene["height"]}">'+"".join(body)+"</svg>").encode()


def png(data,scale=1):
    import cairosvg
    return cairosvg.svg2png(bytestring=data,scale=scale)


def export(scenes,fmt):
    if fmt=="png":return png(svg(scenes[0]),2)
    if fmt=="pdf":
        import cairosvg
        from pypdf import PdfWriter, PdfReader
        from pypdf.annotations import Text
        output=PdfWriter()
        for i,s in enumerate(scenes):
            output.append(PdfReader(io.BytesIO(cairosvg.svg2pdf(bytestring=svg(s)))))
            output.add_annotation(page_number=i,annotation=Text(rect=(18,18,34,34),text=s["notes"],open=False))
        buffer=io.BytesIO();output.write(buffer);return buffer.getvalue()
    with tempfile.TemporaryDirectory(prefix="narcissus-visual-") as folder:
        source=Path(folder)/"scene.json";target=Path(folder)/"slides.pptx"
        source.write_text(json.dumps(scenes,ensure_ascii=False),encoding="utf8")
        result=subprocess.run(["node",str(Path(__file__).parent.parent/"renderer"/"pptx.cjs"),str(source),str(target)],capture_output=True,timeout=settings().visual_render_timeout)
        if result.returncode or not target.exists():raise ModelError("演示文稿导出失败，请检查导出工具与字体配置")
        return target.read_bytes()
