"""Constrained content, provenance and deterministic numeric calculation. No model code/HTML."""
import copy
import re
from decimal import Decimal, InvalidOperation
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, ValidationError
from .model_service import ModelError

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Point(Strict):
    text: str = Field(min_length=1, max_length=220)
    refs: list[int] = Field(default_factory=list, max_length=8)
    basis: Literal["fact", "opinion", "gap"] = "fact"

class Datum(Strict):
    label: str = Field(min_length=1, max_length=24)
    raw: list[str] = Field(min_length=1, max_length=8)
    operation: Literal["value", "sum", "difference", "ratio_percent"] = "value"
    unit: str = Field(min_length=1, max_length=16)
    period: str = Field(min_length=1, max_length=30)
    refs: list[int] = Field(min_length=1, max_length=8)
    value: float | None = None
    method: str = ""

class TableRow(Strict):
    cells: list[str] = Field(min_length=1, max_length=4)
    refs: list[int] = Field(default_factory=list, max_length=8)

class Page(Strict):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    title: str = Field(min_length=1, max_length=64)
    claim: str = Field(default="", max_length=180)
    layout: Literal["cover", "section", "bullets", "comparison", "timeline", "chart", "sources", "table"] = "bullets"
    points: list[Point] = Field(default_factory=list, max_length=6)
    notes: str = Field(default="", max_length=1500)
    data: list[Datum] = Field(default_factory=list, max_length=6)
    columns: list[str] = Field(default_factory=list, max_length=4)
    rows: list[TableRow] = Field(default_factory=list, max_length=6)
    edited: bool = False

class Content(Strict):
    title: str = Field(min_length=1, max_length=120)
    pages: list[Page] = Field(min_length=1, max_length=15)

THEMES = {
    "business": {"name": "简洁商务", "accent": "17685B", "background": "F8FAF8", "ink": "183D36"},
    "teaching": {"name": "教学讲解", "accent": "B55B2D", "background": "FFFAF1", "ink": "423525"},
    "research": {"name": "研究汇报", "accent": "385CA1", "background": "F7F9FC", "ink": "26344B"},
}

def validate_content(raw, evidence, kind="presentation", generated=False):
    try:
        obj = Content.model_validate(raw).model_dump()
        known = {e["label"]: e for e in evidence}
        if kind == "infographic" and len(obj["pages"]) != 1:
            raise ValueError("信息图必须是一张完整画布")
        ids = [p["id"] for p in obj["pages"]]
        if len(ids) != len(set(ids)):
            raise ValueError("页面编号不能重复")
        for p in obj["pages"]:
            if kind == "infographic" and p["layout"] not in ("bullets", "comparison", "timeline"):
                raise ValueError("信息图支持要点概览、对比分析与流程步骤三种形式")
            if p["layout"] == "chart" and not p["data"]:
                raise ValueError("数据图表必须具有可追溯数据；无数据请使用要点版式")
            for point in p["points"]:
                if any(type(n) is not int or n not in known for n in point["refs"]):
                    raise ValueError("引用不属于本次来源")
                notes = [known[n] for n in point["refs"] if known[n]["kind"] == "note"]
                if notes and point["basis"] != "opinion":
                    raise ValueError("笔记或报告文字必须标注用户观点，不能当作原始证据")
                if generated and point["basis"] != "gap" and not point["refs"]:
                    raise ValueError("生成要点缺少证据；资料不足请说明缺口")
                if generated and point["basis"] == "fact" and point["refs"] and all(
                    re.fullmatch(r"[^\n。！？.!?]{1,120}¶",known[n]["text"].strip())
                    for n in point["refs"]
                ):
                    raise ValueError("事实要点仅引用了章节或属性标题，请引用包含结论的正文片段")
            if p["layout"] == "table" and (not p["columns"] or not p["rows"]):
                raise ValueError("表格需填写列标题与行内容")
            if any(len(c)>60 for c in p["columns"]):
                raise ValueError("表格列标题过长")
            for row in p["rows"]:
                if len(row["cells"]) != len(p["columns"]) or any(len(c)>70 for c in row["cells"]) or any(n not in known for n in row["refs"]):
                    raise ValueError("表格行、列或引用不符合限制")
                if generated and (not row["refs"] or any(known[n]["kind"] == "note" for n in row["refs"])):
                    raise ValueError("生成表格必须引用原始证据")
            for datum in p["data"]:
                if any(n not in known or known[n]["kind"] != "document" for n in datum["refs"]):
                    raise ValueError("图表数值必须来自原始资料")
                text = " ".join(known[n]["text"] for n in datum["refs"])
                # Numeric literals, unit and period must be present, not supplied by the model's arithmetic.
                if datum["unit"] not in text or datum["period"] not in text:
                    raise ValueError("数值的单位或适用时间未见于对应原文")
                nums = []
                for raw_number in datum["raw"]:
                    if len(raw_number)>24 or not re.fullmatch(r"-?\d+(?:\.\d+)?", raw_number) or not re.search(r"(?<![\d.])" + re.escape(raw_number) + r"(?![\d.])", text):
                        raise ValueError("图表原始数值与证据不一致")
                    nums.append(Decimal(raw_number))
                op = datum["operation"]
                if op == "value" and len(nums) == 1:
                    value = nums[0]
                elif op == "sum":
                    value = sum(nums)
                elif op == "difference" and len(nums) == 2:
                    value = nums[0] - nums[1]
                elif op == "ratio_percent" and len(nums) == 2 and nums[1]:
                    value = nums[0] / nums[1] * 100
                else:
                    raise ValueError("数值计算参数无效")
                if not value.is_finite() or abs(value) > Decimal("1e12"):
                    raise ValueError("图表数值超出允许范围")
                datum["value"] = float(value.quantize(Decimal("0.0001")))
                datum["method"] = {"value":"原文值", "sum":"求和", "difference":"第一项减第二项", "ratio_percent":"第一项除第二项乘100"}[op] + "：" + ", ".join(datum["raw"])
            if p["data"] and len({("%" if d["operation"] == "ratio_percent" else d["unit"]) for d in p["data"]}) != 1:
                raise ValueError("同一图表不能混用不同单位")
            if generated:
                p["edited"] = False
        return obj
    except (ValidationError, ValueError, InvalidOperation) as exc:
        message = "页面字段不符合限制，请精简标题或要点" if isinstance(exc, ValidationError) else str(exc)
        raise ModelError(message) from None

def mark_edits(content, previous):
    result = copy.deepcopy(content)
    old = {p["id"]: p for p in previous.get("pages", [])}
    for p in result["pages"]:
        before = old.get(p["id"], {})
        p["edited"] = bool(before.get("edited") or any(p.get(k) != before.get(k) for k in ("title", "claim", "points", "data", "notes", "columns", "rows")))
    return result
