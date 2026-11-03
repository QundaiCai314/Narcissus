"""Strict structural and evidence validation before atomic learning publication."""

import json
import re
import unicodedata
from .model_service import ModelError


class InsufficientEvidence(ModelError):
    pass


def normalize(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def fingerprint(value):
    return re.sub(r"[^\w]", "", normalize(value)).casefold()


def decode(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except json.JSONDecodeError as exc:
        # Some providers report stop after the complete items array but omit ONLY
        # the enclosing object terminator. Do not invent text, items or fields.
        if exc.pos == len(raw) and raw.startswith('{') and raw.endswith(']'):
            try:
                value = json.loads(raw + '}')
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                pass
        raise ModelError("模型未返回完整结构，请重新生成合法 JSON") from None
    except (ValueError, TypeError):
        raise ModelError("模型未返回完整结构，请重新生成合法 JSON") from None


def navigation_root(raw, sources):
    """A server-owned navigation header, never a model-authored factual claim.

    Knowledge-bearing children keep their model text and undergo full review.
    The root references the selected files rather than pretending a single
    snippet substantiates an entire cross-chapter summary.
    """
    data = decode(raw)
    items = data.get('items')
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        return raw
    roots = [i for i in items if i.get('parent_id') is None]
    if len(roots) != 1:
        return raw  # The structural validator reports malformed trees.
    files = {}
    for source in sources:
        files.setdefault(source.get('document_id', source['label']), source)
    chosen = list(files.values())[:10]
    if not chosen:
        return raw
    root = roots[0]
    root['title'] = '所选资料知识导图'
    root['explanation'] = '从下方分支探索知识点，点击引用可核对相应原文。'
    root['refs'] = [s['label'] for s in chosen]
    root['quotes'] = [{'ref': s['label'], 'text': s['text'][:100]} for s in chosen]
    return json.dumps(data, ensure_ascii=False)


def split_exact_quotes(raw, sources):
    """Split an overly long exact quotation without truncating or changing evidence.

    Fabricated or edited quotations are deliberately untouched and still fail
    validation. This prevents a long valid parent quote removing its entire tree.
    """
    data = decode(raw)
    evidence = {s['label']: normalize(s['text']) for s in sources}
    for item in data.get('items', []) if isinstance(data.get('items'), list) else []:
        if not isinstance(item, dict) or not isinstance(item.get('quotes'), list):
            continue
        quotes = []
        for quote in item['quotes']:
            if not isinstance(quote, dict) or type(quote.get('ref')) is not int or not isinstance(quote.get('text'), str):
                quotes.append(quote)
                continue
            value = normalize(quote['text'])
            if len(value) > 400 and value in evidence.get(quote['ref'], ''):
                parts = [value[i:i+350] for i in range(0, len(value), 350)]
                if len(parts[-1]) < 6:
                    tail = parts.pop()
                    parts[-1] += tail
                quotes.extend({'ref': quote['ref'], 'text': part} for part in parts)
            else:
                quotes.append(quote)
        item['quotes'] = quotes
    return json.dumps(data, ensure_ascii=False)


def validate_result(raw, kind, params, sources, check_tree=True):
    data = decode(raw)
    items = data.get("items")
    if (
        items == []
        and isinstance(data.get("insufficient_reason"), str)
        and data["insufficient_reason"].strip()
    ):
        raise InsufficientEvidence(
            "当前资料中未找到足够依据，无法生成可靠学习内容；请补充资料或缩小主题"
        )
    if not isinstance(items, list) or not items or len(items) > params["count"]:
        raise ModelError("学习内容数量或结构不符合要求，请在服务端数量限制内生成")
    source_map = {s["label"]: s for s in sources}
    seen_ids, seen_questions = set(), set()
    cleaned = []

    def text(item, field, limit):
        value = item.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ModelError(
                "学习内容存在空字段或文字过长，请检查标题、问题、答案和解释"
            )
        return value.strip()

    for item in items:
        if not isinstance(item, dict):
            raise ModelError("学习条目必须是对象")
        iid = item.get("id")
        if (
            not isinstance(iid, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}", iid)
            or iid in seen_ids
        ):
            raise ModelError("知识点或题目编号重复或无效")
        seen_ids.add(iid)
        labels = item.get("refs")
        if isinstance(labels, list) and len(labels) > 10:
            raise ModelError("单条引用过多：每条最多10个来源编号，请只保留直接支撑该条结论的证据，并为每个编号提供逐字引文")
        if (
            not isinstance(labels, list)
            or not 1 <= len(labels) <= 10
            or any(type(n) is not int or n not in source_map for n in labels)
        ):
            raise ModelError("来源编号不属于本次证据，或缺少来源引用")
        labels = list(dict.fromkeys(labels))
        quotes = item.get("quotes")
        if not isinstance(quotes, list) or not 1 <= len(quotes) <= 30:
            raise ModelError("每个引用必须提供一段对应证据中的逐字原文")
        matched = set()
        for quote in quotes:
            if (
                not isinstance(quote, dict)
                or type(quote.get("ref")) is not int
                or quote["ref"] not in labels
            ):
                raise ModelError("证据引文与引用编号不匹配")
            value = quote.get("text")
            if (
                not isinstance(value, str)
                or not 6 <= len(normalize(value)) <= 400
                or normalize(value) not in normalize(source_map[quote["ref"]]["text"])
            ):
                raise ModelError("证据引文不是所选资料片段的实际原文，请逐字引用")
            matched.add(quote["ref"])
        if matched != set(labels):
            raise ModelError("每个引用必须提供至少一段对应证据中的逐字原文")
        clean = {"id": iid, "refs": labels, "quotes": quotes}
        if kind == "mindmap":
            clean.update(
                title=text(item, "title", 80),
                explanation=text(item, "explanation", 800),
                parent_id=item.get("parent_id"),
            )
        else:
            question = text(item, "question", 400)
            if fingerprint(question) in seen_questions:
                raise ModelError("生成内容含重复问题，请减少数量或更换知识点")
            seen_questions.add(fingerprint(question))
            clean.update(
                question=question,
                explanation=text(item, "explanation", 900),
                point=text(item, "point", 80),
            )
            if kind == "flashcards":
                clean["answer"] = text(item, "answer", 900)
            else:
                options = item.get("options")
                answer = item.get("correct_index")
                if (
                    not isinstance(options, list)
                    or len(options) != 4
                    or any(
                        not isinstance(o, str) or not o.strip() or len(o) > 250
                        for o in options
                    )
                ):
                    raise ModelError("每道单选题必须有四个非空选项")
                if len({fingerprint(o) for o in options}) != 4:
                    raise ModelError("单选题选项重复，请生成四个不同且无歧义的选项")
                if type(answer) is not int or not 0 <= answer <= 3:
                    raise ModelError(
                        "单选题必须有唯一正确答案，correct_index 为 0 至 3"
                    )
                clean.update(options=[o.strip() for o in options], correct_index=answer)
        cleaned.append(clean)
    if kind == "mindmap" and check_tree:
        nodes = {n["id"]: n for n in cleaned}
        roots = [n for n in cleaned if n["parent_id"] is None]
        if len(roots) != 1:
            raise ModelError("导图必须恰好有一个根节点，根节点 parent_id 为 null")
        for node in cleaned:
            seen, current = set(), node
            while current is not None:
                if current["id"] in seen:
                    raise ModelError("导图父子关系存在循环")
                seen.add(current["id"])
                parent = current["parent_id"]
                if parent is not None and (
                    not isinstance(parent, str) or parent not in nodes
                ):
                    raise ModelError("导图存在无效父节点")
                current = nodes.get(parent)
            if len(seen) > 3:
                raise ModelError("导图不能超过三层，请压缩层级")
    return {"items": cleaned}


def filter_invalid_items(raw, kind, params, sources):
    """After bounded repair, reject unsupported items instead of inventing replacements."""
    data = decode(raw)
    kept = []
    for item in data["items"]:
        try:
            checked = validate_result(
                json.dumps({"items": [item]}), kind, params, sources, check_tree=False
            )
            kept.extend(checked["items"])
        except ModelError:
            continue
    if kind == "mindmap":
        changed = True
        while changed:
            ids = {i["id"] for i in kept}
            next_items = [
                i for i in kept if i["parent_id"] is None or i["parent_id"] in ids
            ]
            changed = len(next_items) != len(kept)
            kept = next_items
    if not kept:
        raise InsufficientEvidence(
            "当前资料中未找到足够依据，修复后仍无法形成可靠学习内容"
        )
    result = validate_result(json.dumps({"items": kept}), kind, params, sources)
    return result, len(data["items"]) - len(kept)


def review_result(raw, result, kind):
    value = decode(raw)
    ids = {i["id"] for i in result["items"]}
    approved = value.get("approved_ids")
    if (
        not isinstance(approved, list)
        or any(not isinstance(i, str) or i not in ids for i in approved)
        or len(set(approved)) != len(approved)
    ):
        raise ModelError("质量复核未返回有效的知识点编号")
    accepted = set(approved)
    if kind == "quiz":
        answers = value.get("answers")
        if not isinstance(answers, list):
            raise ModelError("测验复核缺少独立作答结果")
        checked = {}
        for answer in answers:
            if (
                not isinstance(answer, dict)
                or not isinstance(answer.get("id"), str)
                or answer["id"] not in ids
                or answer["id"] in checked
            ):
                raise ModelError("测验复核题目编号无效")
            options = answer.get("valid_options")
            if (
                not isinstance(options, list)
                or any(type(i) is not int or not 0 <= i <= 3 for i in options)
                or len(set(options)) != len(options)
            ):
                raise ModelError("测验复核选项无效")
            checked[answer["id"]] = options
        for item in result["items"]:
            if checked.get(item["id"]) != [item["correct_index"]]:
                accepted.discard(item["id"])
    if kind == "mindmap":
        root = next(n for n in result["items"] if n["parent_id"] is None)
        if root["id"] not in accepted:
            raise InsufficientEvidence("导图主题缺少可靠依据，请调整主题或补充资料")
        # Descendants of rejected nodes cannot remain as orphan branches.
        changed = True
        while changed:
            changed = False
            for n in result["items"]:
                if (
                    n["id"] in accepted
                    and n["parent_id"] is not None
                    and n["parent_id"] not in accepted
                ):
                    accepted.remove(n["id"])
                    changed = True
    filtered = [i for i in result["items"] if i["id"] in accepted]
    if not filtered:
        raise InsufficientEvidence(
            "当前资料无法支持可靠且无歧义的学习内容，请补充资料或调整主题"
        )
    return {"items": filtered}, len(ids) - len(filtered)
