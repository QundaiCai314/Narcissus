import re
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal
from .config import settings
from .learning_validation import decode, normalize
from .model_service import ModelError


class Paragraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    chapter: str = Field(min_length=1, max_length=100)
    speaker: Literal["A", "B"]
    text: str = Field(min_length=1, max_length=700)
    refs: list[int] = Field(min_length=1, max_length=15)


class ScriptEdit(BaseModel):
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=120)
    intro: str = Field(max_length=600)
    paragraphs: list[Paragraph] = Field(min_length=1, max_length=40)


def validate_script(data, mode, evidence, generated=False):
    try:
        raw = decode(data) if isinstance(data, str) else data
        if not raw.get("paragraphs"):
            raise ModelError("当前资料中未找到足够依据，请补充资料或调整主题")
        paragraphs = []
        source_map = {e["label"]: e for e in evidence}
        for item in raw["paragraphs"]:
            paragraph = Paragraph.model_validate({k: v for k, v in item.items() if k not in ("quotes", "edited")}).model_dump()
            if mode == "single" and paragraph["speaker"] != "A":
                raise ValueError()
            if any(type(n) is not int or n not in source_map for n in item["refs"]):
                raise ModelError("讲稿引用不属于本次资料证据")
            if generated and "quotes" in item:
                matched = set()
                for q in item.get("quotes", []):
                    if q.get("ref") not in paragraph["refs"] or not isinstance(q.get("text"), str):
                        raise ValueError()
                    quote = normalize(q["text"])
                    if not 6 <= len(quote) <= 400 or quote not in normalize(source_map[q["ref"]]["text"]):
                        raise ModelError("讲稿引文与原文不匹配")
                    matched.add(q["ref"])
                if matched != set(paragraph["refs"]):
                    raise ModelError("讲稿段落缺少逐字依据")
            # Citation labels are metadata and are never sent to speech synthesis.
            paragraph["text"] = re.sub(r"\[\d+\]", "", paragraph["text"]).strip()
            if not paragraph["text"]:
                raise ValueError()
            paragraphs.append(paragraph)
        if len({p["id"] for p in paragraphs}) != len(paragraphs):
            raise ValueError()
        if mode == "duo" and {p["speaker"] for p in paragraphs} != {"A", "B"}:
            raise ModelError("双人讲稿需要两位讲解者参与")
        if len(paragraphs) > min(settings().audio_max_segments, 40) or sum(len(p["text"]) for p in paragraphs) > min(settings().audio_max_chars, 10000):
            raise ModelError("讲稿规模超出限制，请缩短内容")
        result = ScriptEdit(revision=1, title=raw["title"], intro=raw.get("intro", ""), paragraphs=paragraphs).model_dump(exclude={"revision"})
        return result
    except ModelError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ModelError("讲稿结构不完整或不符合限制，请重试") from None
