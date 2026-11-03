from .source_references import position
"""Private Markdown/DOCX export. No remote images, links, macros or model calls are fetched."""

import io
import re
from typing import Literal
from urllib.parse import quote
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.oxml.ns import qn
from markdown_it import MarkdownIt
from .db import db_session
from .security import current_user, rate_limit
from .writings import owned, references, ensure_idle

router = APIRouter(tags=["导出"])


def markdown(row, citations):
    content = "# " + row.title.replace("\n", " ") + "\n\n"
    if row.edited:
        content += (
            "> 本文含用户编辑内容；保留引用仅指向来源快照，不表示全部文字均已验证。\n\n"
        )
    content += row.content + "\n\n## 来源引用\n\n"
    used = {int(n) for n in re.findall(r"\[(\d+)\]", row.content)}
    matched = set()
    for cite in citations:
        if cite["label"] not in used:
            continue
        matched.add(cite["label"])
        name = cite["filename"].replace("\n", " ")
        content += f"### [{cite['label']}] {name}\n\n"
        if cite["kind"] == "note":
            content += (
                f"来源：用户笔记（未经原始资料核验），保存版本 {cite['version']}。\n\n"
            )
            if cite["state"] == "deleted":
                content += "原始笔记已删除；以下为保存时的快照。\n\n"
        else:
            content += f"{position(cite)}，片段 {cite['ordinal']}，资料版本 {cite['version']}。\n\n"
            if cite["state"] == "deleted":
                content += (
                    "原始资料已删除；以下仅为历史原文快照，无法回到原文件核验。\n\n"
                )
        if cite["state"] == "changed":
            content += "原始来源已更新；以下为保存时快照，请重新核对当前版本。\n\n"
        if cite.get("source_url"):
            content += f"原始链接：{cite['source_url']}\n\n获取时间：{cite.get('fetched_at') or '未记录'}\n\n"
        content += (
            "原文快照：\n\n"
            + "\n".join("> " + line for line in cite["text"].splitlines())
            + "\n\n"
        )
    for label in sorted(used - matched):
        content += f"- [{label}] 未关联可核验来源，可能为用户输入或引用已移除。\n"
    if not used:
        content += "本文没有保留关联引用。\n"
    return content


def word_document(text):
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    document = Document()
    section = document.sections[0]
    section.top_margin = section.bottom_margin = Inches(0.8)
    section.left_margin = section.right_margin = Inches(0.85)
    for name in (
        "Normal",
        "Title",
        "Heading 1",
        "Heading 2",
        "Heading 3",
        "List Bullet",
        "List Number",
    ):
        style = document.styles[name]
        style.font.name = "Arial"
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        if name == "Normal":
            style.font.size = Pt(11)
            style.paragraph_format.space_after = Pt(7)
            style.paragraph_format.line_spacing = 1.25
        elif name.startswith("Heading") or name == "Title":
            style.font.color.rgb = RGBColor.from_string("28624D")

    def inline(paragraph, children):
        bold = italic = False
        for token in children or []:
            if token.type == "strong_open":
                bold = True
            elif token.type == "strong_close":
                bold = False
            elif token.type == "em_open":
                italic = True
            elif token.type == "em_close":
                italic = False
            elif token.type in ("softbreak", "hardbreak"):
                paragraph.add_run().add_break()
            elif token.type in ("text", "code_inline", "image", "html_inline"):
                value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", token.content)
                run = paragraph.add_run(value)
                run.bold, run.italic = bold, italic
                if token.type == "code_inline":
                    run.font.name = "Consolas"

    tokens = MarkdownIt("commonmark").enable("table").parse(text)
    paragraph, lists, quote_depth, table, cells, cell_index = None, [], 0, None, None, 0
    for token in tokens:
        if token.type in ("bullet_list_open", "ordered_list_open"):
            lists.append(token.type)
        elif token.type in ("bullet_list_close", "ordered_list_close"):
            lists.pop()
        elif token.type == "blockquote_open":
            quote_depth += 1
        elif token.type == "blockquote_close":
            quote_depth -= 1
        elif token.type == "heading_open":
            level = min(int(token.tag[1:]), 3)
            paragraph = document.add_paragraph(
                style="Title" if level == 1 else f"Heading {level - 1}"
            )
        elif token.type == "paragraph_open":
            style = (
                ("List Number" if lists[-1] == "ordered_list_open" else "List Bullet")
                if lists
                else "Normal"
            )
            paragraph = document.add_paragraph(style=style)
            if lists or quote_depth:
                paragraph.paragraph_format.left_indent = Inches(
                    0.2 * (len(lists) + quote_depth)
                )
            if quote_depth:
                paragraph.paragraph_format.space_after = Pt(4)
        elif token.type == "inline":
            if paragraph is None:
                paragraph = document.add_paragraph()
            inline(paragraph, token.children)
        elif token.type in ("fence", "code_block"):
            p = document.add_paragraph()
            run = p.add_run(token.content)
            run.font.name = "Consolas"
            run.font.size = Pt(9)
        elif token.type == "table_open":
            table = None
        elif token.type == "tr_open":
            cells, cell_index = [], 0
        elif token.type in ("th_open", "td_open"):
            if table is None:
                # Collect first row in temporary paragraph references; make real cells at tr_close.
                paragraph = document.add_paragraph()
                cells.append(paragraph)
            else:
                if cell_index == 0:
                    cells = table.add_row().cells
                paragraph = cells[cell_index].paragraphs[0]
                cell_index += 1
        elif token.type == "tr_close" and table is None:
            table = document.add_table(
                rows=1, cols=len(cells), style="Light Shading Accent 1"
            )
            for i, p in enumerate(cells):
                table.rows[0].cells[i].text = p.text
                p._element.getparent().remove(p._element)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


@router.get("/writings/{writing_id}/export")
def export(
    writing_id: str,
    format: Literal["md", "docx"] = "md",
    user=Depends(current_user),
    db=Depends(db_session),
):
    row = owned(db, user.id, writing_id)
    ensure_idle(db, row)
    rate_limit("exports:" + user.id, 120, 3600)
    text = markdown(row, references(db, row))
    data = word_document(text) if format == "docx" else text.encode("utf-8")
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", row.title)[:100]
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if format == "docx"
        else "text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=note.{format}; filename*=UTF-8''{quote(name + '.' + format)}",
            "Cache-Control": "private, no-store",
        },
    )
