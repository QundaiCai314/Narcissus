"""Question contracts and deterministic grading. No model or database side effects."""
import re
import unicodedata
from .model_service import ModelError

TYPES = {
    "single": ("单项选择题", 2), "multiple": ("多项选择题", 3),
    "true_false": ("判断题", 2), "fill_blank": ("填空题", 4),
    "term": ("名词解释", 5), "short_answer": ("简答题", 8),
    "calculation": ("计算与证明题", 10), "essay": ("论述题", 12),
    "case_analysis": ("材料分析题", 12),
}
OBJECTIVE = {"single", "multiple", "true_false"}


def kind(q):
    return q.get("question_type", "single")


def points(q):
    return q.get("points", 1)  # Historical sets retain equal weighting.


def plan(params):
    types = params.get("question_types") or ["single"]
    return [{"question_type": t, "name": TYPES[t][0],
             "count": params["count"] // len(types) + (i < params["count"] % len(types)),
             "points": TYPES[t][1]} for i, t in enumerate(types)]


def compact(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s)).casefold()


def validate_question(item, params):
    t = item.get("question_type", "single")
    if t not in (params.get("question_types") or ["single"]) or t not in TYPES:
        raise ModelError("题型不在所选范围内，请按出题方案生成")
    clean = {"question_type": t, "points": TYPES[t][1], "options": []}
    if t in OBJECTIVE:
        options = item.get("options")
        count = 2 if t == "true_false" else 4
        if not isinstance(options, list) or len(options) != count or any(
            not isinstance(o, str) or not o.strip() or len(o) > 500 for o in options
        ):
            raise ModelError(f"{TYPES[t][0]}必须有{count}个非空选项")
        options = [re.sub(r"^[A-DＡ-Ｄ][.．、]\s*", "", o.strip()) for o in options]
        if any(not o for o in options) or len({compact(o) for o in options}) != count:
            raise ModelError("选项重复或为空，请给出独立、无歧义的选项")
        if t == "true_false" and options != ["正确", "错误"]:
            raise ModelError("判断题选项固定为正确、错误")
        if any(re.search(r"以上(皆|都|全)|以上选项|以上各项", o) for o in options):
            raise ModelError("避免使用以上皆是、以上皆非等组合选项")
        answers = item.get("correct_indices") if t == "multiple" else [item.get("correct_index")]
        if not isinstance(answers, list) or any(type(n) is not int or not 0 <= n < count for n in answers) or len(set(answers)) != len(answers):
            raise ModelError("正确选项编号无效")
        if (t == "multiple" and not 2 <= len(answers) <= 4) or (t != "multiple" and len(answers) != 1):
            raise ModelError("单选和判断只有一个正确答案，多选至少有两个正确答案")
        clean.update(options=options, correct_indices=sorted(answers))
        if t != "multiple":
            clean["correct_index"] = answers[0]
    else:
        answer = item.get("answer")
        rubric = item.get("rubric")
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 6000:
            raise ModelError("非选择题必须提供完整参考答案，最多6000字")
        if not isinstance(rubric, list) or not 1 <= len(rubric) <= 8:
            raise ModelError("非选择题必须提供1至8条可核对的评分要点")
        rules = []
        for i, r in enumerate(rubric):
            if not isinstance(r, dict) or not isinstance(r.get("text"), str) or not r["text"].strip() or len(r["text"]) > 700 or type(r.get("points")) is not int or not 1 <= r["points"] <= clean["points"]:
                raise ModelError("评分要点须包含明确内容与正整数分值")
            rules.append({"id": f"r{i+1}", "text": r["text"].strip(), "points": r["points"]})
        if sum(r["points"] for r in rules) != clean["points"]:
            raise ModelError("评分要点的分值总和必须等于该题满分")
        if len({compact(r["text"]) for r in rules}) != len(rules):
            raise ModelError("评分要点不能重复计分")
        if t == "fill_blank" and not re.search(r"_{3,}|＿{3,}|（\s*）|\(\s*\)", item["question"]):
            raise ModelError("填空题必须标明空格，多个空按（1）（2）编号")
        clean.update(answer=answer.strip(), rubric=rules)
    return clean


def public_question(q):
    return {"id": q["id"], "question": q["question"], "options": q.get("options", []),
            "question_type": kind(q), "points": points(q)}


def response_value(q, data, allow_empty=True):
    """Validate untrusted answers against this question, not generic request types."""
    t = kind(q)
    if t in {"single", "true_false"}:
        value = data.selected
        if data.selected_indices is not None or data.text is not None:
            raise ValueError("本题请选择一个选项")
        if value is not None and (type(value) is not int or not 0 <= value < len(q["options"])):
            raise ValueError("选项超出本题范围")
        result = {"selected": value}
        empty = value is None
    elif t == "multiple":
        values = data.selected_indices or []
        if data.selected is not None or data.text is not None or len(set(values)) != len(values) or any(type(i) is not int or not 0 <= i < len(q["options"]) for i in values):
            raise ValueError("多选答案必须是互不重复的有效选项")
        result, empty = {"selected_indices": sorted(values)}, not values
    else:
        if data.selected is not None or data.selected_indices is not None:
            raise ValueError("本题请填写文字答案或解题过程")
        value = (data.text or "").strip()
        result, empty = {"text": value}, not value
    if empty and not allow_empty:
        raise ValueError("请先作答再提交本题")
    return result


def has_answer(q, response):
    if kind(q) in {"single", "true_false"}: return response.get("selected") is not None
    if kind(q) == "multiple": return bool(response.get("selected_indices"))
    return bool(response.get("text", "").strip())


def grade(q, response):
    value = dict(response, submitted=True)
    if not has_answer(q, value):
        return dict(value, earned=0, correct=False, grading="unanswered")
    if kind(q) in OBJECTIVE:
        expected = q.get("correct_indices", [q.get("correct_index")])
        actual = value.get("selected_indices", [value.get("selected")])
        correct = sorted(actual) == sorted(expected)
        return dict(value, earned=points(q) if correct else 0, correct=correct, grading="automatic")
    return dict(value, earned=None, correct=None, grading="self_pending")


def assess(q, answer, rubric_scores):
    if kind(q) in OBJECTIVE or not answer.get("submitted") or answer.get("grading") == "unanswered":
        raise ValueError("请先提交非选择题答案，再按要点自评")
    rubric = q["rubric"]
    if set(rubric_scores) != {r["id"] for r in rubric}:
        raise ValueError("请逐项确认全部评分要点")
    for r in rubric:
        n = rubric_scores[r["id"]]
        if type(n) is not int or not 0 <= n <= r["points"]:
            raise ValueError("每项自评分不得超过该要点满分")
    earned = sum(rubric_scores.values())
    return dict(answer, rubric_scores=rubric_scores, earned=earned,
                correct=earned == points(q), grading="self_assessed")


def summary(a):
    values = [v for v in a.answers.values() if v.get("submitted")]
    pending = sum(v.get("grading") == "self_pending" for v in values)
    earned = sum(v.get("earned", int(bool(v.get("correct")))) or 0 for v in values)
    maximum = sum(a.answers.get(i, {}).get("max_points", 1) for i in a.question_ids)
    return {"answered": len(values), "correct": sum(v.get("correct") is True for v in values),
            "total": len(a.question_ids), "score": round(earned * 100 / maximum) if a.status == "complete" and maximum else None,
            "earned_points": earned, "total_points": maximum, "pending_review": pending,
            "self_assessed": any(v.get("grading") == "self_assessed" for v in values)}


def finish(a):
    all_submitted = all(a.answers.get(i, {}).get("submitted") for i in a.question_ids)
    pending = any(a.answers.get(i, {}).get("grading") == "self_pending" for i in a.question_ids)
    a.status = "reviewing" if all_submitted and pending else "complete" if all_submitted else "active"
