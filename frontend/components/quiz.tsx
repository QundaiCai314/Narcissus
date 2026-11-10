"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, post, errorText, Page } from "@/lib/api";
import {
  LearningSet,
  QuizAttempt,
  QuizQuestion,
  AttemptBrief,
  OnCitation,
  questionTypes,
  objectiveTypes,
} from "@/lib/learning";
import { ReferenceList } from "./writing-view";
import { MarkdownRenderer } from "./markdown-renderer";

type Draft = {
  selected?: number | null;
  selected_indices?: number[];
  text?: string;
};
const typeOf = (q: QuizQuestion) => q.question_type || "single";
const draftOf = (q: QuizQuestion): Draft =>
  typeOf(q) === "multiple"
    ? { selected_indices: q.selected_indices || [] }
    : objectiveTypes.includes(typeOf(q))
      ? { selected: q.selected ?? null }
      : { text: q.text || "" };
const filled = (d: Draft) =>
  d.selected != null || !!d.selected_indices?.length || !!d.text?.trim();
const same = (a: Draft, b: Draft) => {
  // The API trims written answers; trailing newlines must not trigger endless saves.
  const normalized = (value: Draft) =>
    value.text === undefined ? value : { ...value, text: value.text.trim() };
  return JSON.stringify(normalized(a)) === JSON.stringify(normalized(b));
};

export function Quiz({
  row,
  onCitation,
  onChanged,
  onDirtyChange,
}: {
  row: LearningSet;
  onCitation: OnCitation;
  onChanged: () => Promise<void>;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [history, setHistory] = useState<AttemptBrief[]>([]),
    [total, setTotal] = useState(0);
  const [attempt, setAttempt] = useState<QuizAttempt | null>(null),
    [index, setIndex] = useState(0);
  const [draft, setDraft] = useState<Draft>({}),
    [rubric, setRubric] = useState<Record<string, number>>({});
  const [delivery, setDelivery] = useState<"practice" | "exam">("practice");
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [saveState, setSaveState] = useState(""),
    [filter, setFilter] = useState("all"),
    [confirmFinish, setConfirmFinish] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const questionRef = useRef<HTMLElement>(null);
  const focusQuestion = () => {
    questionRef.current?.scrollIntoView({
      block: "start",
      behavior: "instant",
    });
    questionRef.current?.focus({ preventScroll: true });
  };
  const locked = useRef(false),
    alive = useRef(true),
    current = useRef<QuizAttempt | null>(null);
  const startKey = useRef<{ signature: string; key: string } | null>(null);
  const questions =
    attempt?.items.filter(
      (q) =>
        filter === "all" ||
        (filter === "wrong"
          ? q.correct === false
          : q.grading === "self_pending"),
    ) || [];
  const q = questions[index];
  const dirty = !!q && !q.submitted && !same(draft, draftOf(q));
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);
  const setValue = useCallback((value: QuizAttempt) => {
    current.current = value;
    setAttempt(value);
  }, []);
  const loadHistory = useCallback(async () => {
    const result = await api<Page<AttemptBrief>>(
      `/learning/${row.id}/attempts?limit=100`,
    );
    if (alive.current) {
      setHistory(result.items);
      setTotal(result.total);
    }
    return result.items;
  }, [row.id]);
  const open = useCallback(
    async (id: string) => {
      const value = await api<QuizAttempt>(`/quiz-attempts/${id}`);
      if (!alive.current) return;
      setValue(value);
      setFilter("all");
      const first = value.items.findIndex(
        (item) => !item.submitted || item.grading === "self_pending",
      );
      setIndex(first < 0 ? 0 : first);
      setError("");
      setSaveState("已恢复作答进度");
      setToolsOpen(false);
    },
    [setValue],
  );
  useEffect(() => {
    alive.current = true;
    loadHistory()
      .then(async (rows) => {
        if (alive.current && rows.length) await open(rows[0].id);
      })
      .catch((e) => {
        if (alive.current) setError(errorText(e));
      })
      .finally(() => {
        if (alive.current) setLoading(false);
      });
    return () => {
      alive.current = false;
    };
  }, [loadHistory, open]);
  useEffect(() => {
    setDraft(q ? draftOf(q) : {});
    setRubric(q?.rubric_scores || {});
  }, [q?.id, attempt?.id]);
  useEffect(() => {
    if (q) {
      setSheetOpen(false);
      focusQuestion();
    }
  }, [q?.id, attempt?.id]);
  useEffect(() => {
    const leave = (event: BeforeUnloadEvent) => {
      if (dirtyRef.current) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", leave);
    return () => window.removeEventListener("beforeunload", leave);
  }, []);
  async function refreshHistory() {
    try {
      await loadHistory();
      await onChanged();
    } catch {
      setError("作答已保存，但列表刷新失败；可重新加载记录。");
    }
  }
  async function persist(submit = false): Promise<QuizAttempt | null> {
    const value = current.current;
    if (!value || !q || locked.current) return null;
    if (!dirty && !submit) return value;
    locked.current = true;
    setBusy(true);
    setSubmitting(submit);
    setSaveState("正在保存…");
    try {
      const result = await api<QuizAttempt>(
        `/quiz-attempts/${value.id}/answers/${q.id}${submit ? "/submit" : ""}`,
        {
          method: submit ? "POST" : "PATCH",
          body: JSON.stringify({ ...draft, revision: value.revision }),
        },
      );
      if (!alive.current) return null;
      setValue(result);
      setSaveState(submit ? "本题已提交" : "作答已保存");
      setError("");
      if (submit) await refreshHistory();
      return result;
    } catch (e) {
      setError(errorText(e));
      setSaveState("尚未保存，请重试");
      return null;
    } finally {
      locked.current = false;
      if (alive.current) {
        setBusy(false);
        setSubmitting(false);
      }
    }
  }
  useEffect(() => {
    if (!dirty || busy || saveState === "尚未保存，请重试") return;
    const timer = setTimeout(() => {
      void persist();
    }, 900);
    return () => clearTimeout(timer);
  }, [draft, dirty, busy, saveState]);
  function updateDraft(value: Draft) {
    setDraft(value);
    setSaveState("待保存");
  }
  async function navigate(next: () => void) {
    if (locked.current) return;
    if (dirty && !(await persist())) return;
    next();
    setConfirmFinish(false);
  }
  async function start(mode: "all" | "wrong") {
    if (locked.current) return;
    if (dirty && !(await persist())) return;
    if (
      attempt?.status === "active" &&
      !window.confirm(
        "当前练习尚未完成。已有进度会保留在历史记录中，仍要开始新一轮吗？",
      )
    )
      return;
    locked.current = true;
    setBusy(true);
    setError("");
    const previous = mode === "wrong" ? attempt?.id : undefined;
    const signature = [mode, previous, delivery].join(":");
    if (startKey.current?.signature !== signature)
      startKey.current = { signature, key: crypto.randomUUID() };
    try {
      const result = await api<QuizAttempt>(
        `/learning/${row.id}/attempts`,
        post({
          request_key: startKey.current.key,
          mode,
          previous_id: previous,
          delivery,
        }),
      );
      startKey.current = null;
      setValue(result);
      setIndex(0);
      setFilter("all");
      setConfirmFinish(false);
      setSaveState("已开始，可随时继续");
      setToolsOpen(false);
      await refreshHistory();
    } catch (e) {
      setError(errorText(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  async function finish() {
    if (locked.current) return;
    const saved = dirty ? await persist() : current.current;
    if (!saved) return;
    locked.current = true;
    setBusy(true);
    try {
      const result = await api<QuizAttempt>(
        `/quiz-attempts/${saved.id}/finish`,
        post({ revision: saved.revision }),
      );
      setValue(result);
      setConfirmFinish(false);
      setFilter("all");
      const first = result.items.findIndex(
        (item) => item.grading === "self_pending",
      );
      setIndex(first < 0 ? 0 : first);
      setSaveState("已交卷");
      setError("");
      await refreshHistory();
    } catch (e) {
      setError(errorText(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  async function assess() {
    if (!attempt || !q || locked.current) return;
    locked.current = true;
    setBusy(true);
    try {
      const result = await api<QuizAttempt>(
        `/quiz-attempts/${attempt.id}/answers/${q.id}/assess`,
        post({ revision: current.current!.revision, rubric_scores: rubric }),
      );
      setValue(result);
      setSaveState("自评已记录");
      setError("");
      // Keep the reviewed question visible even when the pending-review filter shrinks.
      if (filter === "review") {
        setFilter("all");
        setIndex(result.items.findIndex((item) => item.id === q.id));
      }
      await refreshHistory();
    } catch (e) {
      setError(errorText(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  function exportReview() {
    if (!attempt || attempt.status !== "complete") return;
    const text = [
      `# ${row.title}`,
      `练习成绩：${attempt.score} / 100${attempt.self_assessed ? "（含主观题自评）" : ""}`,
      ...attempt.items.map((item, i) => {
        const choice = (
          item.selected_indices ||
          (item.selected != null ? [item.selected] : [])
        )
          .map((n) =>
            item.question_type === "true_false"
              ? item.options[n]
              : String.fromCharCode(65 + n),
          )
          .join("、");
        const answer =
          item.answer ||
          (item.correct_indices || [item.correct_index!])
            .map((n) =>
              item.question_type === "true_false"
                ? item.options[n]
                : String.fromCharCode(65 + n),
            )
            .join("、");
        return `## ${i + 1}. ${questionTypes[typeOf(item)].label}\n\n${item.question}\n\n${item.options.map((o, n) => `${String.fromCharCode(65 + n)}. ${o}`).join("\n")}\n\n我的作答：${item.text || choice || "未作答"}\n\n参考答案：${answer}\n\n解析：${item.explanation || ""}\n\n得分：${item.earned ?? (item.correct ? 1 : 0)} / ${item.points || 1}${item.grading === "self_assessed" ? "（自评）" : ""}\n\n${(item.rubric || []).map((r) => `- ${r.text}（${r.points} 分）`).join("\n")}\n\n依据：${(
          item.refs || []
        )
          .map((n) => {
            const c = attempt.citations.find((c) => c.label === n);
            return c ? `[${n}] ${c.filename}` : `[${n}]`;
          })
          .join("；")}`;
      }),
    ].join("\n\n");
    const url = URL.createObjectURL(
      new Blob([text], { type: "text/markdown;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "Narcissus-练习复盘.md";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const unanswered =
    attempt?.items.filter(
      (item) =>
        !item.submitted && !filled(item.id === q?.id ? draft : draftOf(item)),
    ).length || 0;
  return (
    <div className="learning-detail exam-workspace">
      {error && (
        <div className="save-error" role="alert">
          {error}
          {attempt && (
            <button
              className="button"
              disabled={busy}
              onClick={() => {
                if (
                  !dirty ||
                  window.confirm("重新加载将放弃本页尚未保存的修改，继续吗？")
                )
                  void open(attempt.id).catch((e) => setError(errorText(e)));
              }}
            >
              重新加载记录
            </button>
          )}
        </div>
      )}
      <details
        className="exam-session-tools"
        open={!attempt || toolsOpen}
        onToggle={(e) => setToolsOpen(e.currentTarget.open)}
      >
        <summary>
          练习记录与设置<span>切换记录 / 开始新一轮</span>
        </summary>
        <div className="exam-mode-picker">
          <label>
            作答方式
            <select
              aria-label="作答方式"
              value={delivery}
              disabled={busy}
              onChange={(e) => setDelivery(e.target.value as typeof delivery)}
            >
              <option value="practice">逐题练习 · 提交后看解析</option>
              <option value="exam">整卷自测 · 交卷后看答案</option>
            </select>
          </label>
          <button
            className={attempt ? "button" : "button primary"}
            disabled={busy || loading}
            onClick={() => start("all")}
          >
            {attempt ? "开始新一轮" : "开始答题"}
          </button>
          {attempt?.status === "complete" && (
            <button
              className="button"
              disabled={busy || !attempt.weak_points.length}
              onClick={() => start("wrong")}
            >
              重练本轮错题
            </button>
          )}
        </div>
        {!!history.length && (
          <label className="attempt-history">
            练习记录
            <select
              aria-label="练习记录"
              value={attempt?.id || ""}
              disabled={busy}
              onChange={(e) => {
                const id = e.target.value;
                void navigate(
                  () => void open(id).catch((err) => setError(errorText(err))),
                );
              }}
            >
              <option value="" disabled>
                选择记录
              </option>
              {history.map((a) => (
                <option value={a.id} key={a.id}>
                  {new Date(a.created_at).toLocaleString("zh-CN")} ·{" "}
                  {a.status === "complete"
                    ? `${a.score} 分${a.self_assessed ? "（含自评）" : ""}`
                    : a.status === "reviewing"
                      ? `待自评 ${a.pending_review} 题`
                      : `进行中 ${a.answered}/${a.total}`}{" "}
                  · {a.mode === "wrong" ? "错题" : "完整练习"} ·{" "}
                  {a.delivery === "exam" ? "整卷" : "逐题"}
                </option>
              ))}
            </select>
            {history.length < total && (
              <button
                className="button"
                disabled={busy}
                onClick={async () => {
                  try {
                    const p = await api<Page<AttemptBrief>>(
                      `/learning/${row.id}/attempts?limit=100&offset=${history.length}`,
                    );
                    setHistory((v) => [
                      ...new Map(
                        [...v, ...p.items].map((a) => [a.id, a]),
                      ).values(),
                    ]);
                  } catch (e) {
                    setError(errorText(e));
                  }
                }}
              >
                更多记录
              </button>
            )}
          </label>
        )}
      </details>
      {loading ? (
        <p role="status">正在恢复练习…</p>
      ) : !attempt ? (
        <div className="exam-intro">
          <span className="eyebrow">PRACTICE & REFLECT</span>
          <h3>先独立作答，再对照理解。</h3>
          <p>
            本套共 {row.count} 题。选择题使用 A、B、C、D
            作答；多选须全部选对，少选、多选、错选均不得分。填空与主观题先提交，再按参考答案逐项自评。
          </p>
          <p>
            可选择逐题反馈或整卷交卷。进度自动保存，未完成的练习可从记录继续；完成后可重练错题、导出复盘。
          </p>
        </div>
      ) : (
        <>
          <div className="mastery-strip">
            <strong>
              {attempt.status === "complete"
                ? `练习成绩 ${attempt.earned_points ?? attempt.correct} / ${attempt.total_points ?? attempt.total} 分`
                : attempt.status === "reviewing"
                  ? "已交卷，待完成自评"
                  : `${attempt.delivery === "exam" ? "整卷自测" : "逐题练习"} · 已作答 ${attempt.total - unanswered}/${attempt.total}`}
            </strong>
            {attempt.status === "complete" && (
              <span>
                折合 {attempt.score} / 100
                {attempt.self_assessed ? "（含自评）" : ""}
              </span>
            )}
            <span role="status">
              {saveState === "尚未保存，请重试" || saveState === "正在保存…"
                ? saveState
                : dirty
                  ? "有待保存的作答"
                  : saveState}
            </span>
          </div>
          {!!attempt.pending_review && (
            <p className="exam-notice">
              还有 {attempt.pending_review}{" "}
              道题待按评分要点自评。完成后汇总成绩；自评分不代表教师或官方评分。
            </p>
          )}
          <div
            className={`exam-reading-layout ${sheetOpen ? "sheet-open" : ""}`}
          >
            <aside className="exam-navigation" aria-label="题目导航">
              <button
                className="exam-sheet-toggle"
                aria-expanded={sheetOpen}
                onClick={() => setSheetOpen((v) => !v)}
              >
                答题卡{" "}
                <span>
                  {sheetOpen
                    ? "收起"
                    : `${attempt.total - unanswered} / ${attempt.total} 已作答`}
                </span>
              </button>
              <div className="exam-navigation-content">
                <div className="exam-filters">
                  <label>
                    题目范围
                    <select
                      aria-label="题目范围"
                      value={filter}
                      disabled={busy}
                      onChange={(e) => {
                        const f = e.target.value;
                        void navigate(() => {
                          setFilter(f);
                          setIndex(0);
                        });
                      }}
                    >
                      <option value="all">全部题目</option>
                      <option value="wrong">错题与未得满分题</option>
                      <option value="review">待自评</option>
                    </select>
                  </label>
                  {attempt.status === "complete" && (
                    <button className="button" onClick={exportReview}>
                      导出本轮复盘
                    </button>
                  )}
                </div>
                <nav className="exam-answer-sheet" aria-label="答题卡">
                  <span>答题卡</span>
                  <div>
                    {questions.map((item, i) => (
                      <button
                        type="button"
                        key={item.id}
                        disabled={busy}
                        aria-current={i === index ? "step" : undefined}
                        aria-label={`第${attempt.items.findIndex((x) => x.id === item.id) + 1}题${item.grading === "self_pending" ? "，待自评" : item.submitted ? (item.correct ? "，已掌握" : "，待巩固") : filled(item.id === q?.id ? draft : draftOf(item)) ? "，已作答" : "，未作答"}`}
                        className={`${i === index ? "current " : ""}${item.grading === "self_pending" ? "review" : item.submitted ? (item.correct ? "correct" : "incorrect") : filled(item.id === q?.id ? draft : draftOf(item)) ? "draft" : ""}`}
                        onClick={() => void navigate(() => setIndex(i))}
                      >
                        {attempt.items.findIndex((x) => x.id === item.id) + 1}
                      </button>
                    ))}
                  </div>
                  <small>
                    描边：当前题 · 浅绿：已作答 · 深绿：已掌握 · 赭色：待巩固 ·
                    虚线：待自评
                  </small>
                </nav>
              </div>
            </aside>
            <div className="exam-paper-column">
              {q ? (
                <section
                  ref={questionRef}
                  tabIndex={-1}
                  aria-label={`第${attempt.items.findIndex((item) => item.id === q.id) + 1}题内容`}
                  className="quiz-question exam-question"
                  key={q.id}
                >
                  <div className="exam-question-meta">
                    <strong>
                      第{" "}
                      {attempt.items.findIndex((item) => item.id === q.id) + 1}{" "}
                      题
                    </strong>
                    <span>{questionTypes[typeOf(q)].label}</span>
                    <span>{q.points || 1} 分</span>
                    {q.point && <span>{q.point}</span>}
                  </div>
                  <MarkdownRenderer content={q.question} />
                  {!objectiveTypes.includes(typeOf(q)) ? (
                    <label className="exam-written-answer">
                      我的作答
                      <textarea
                        aria-label="我的作答"
                        value={draft.text || ""}
                        maxLength={12000}
                        rows={typeOf(q) === "fill_blank" ? 3 : 8}
                        disabled={q.submitted || submitting}
                        onChange={(e) => updateDraft({ text: e.target.value })}
                        placeholder={
                          typeOf(q) === "fill_blank"
                            ? "按（1）（2）顺序填写各空答案，注意单位与精度"
                            : "分点写出答案；计算与证明题请保留步骤。支持输入 LaTeX 公式。"
                        }
                      />
                      <small>{(draft.text || "").length} / 12000</small>
                    </label>
                  ) : (
                    <fieldset
                      className="quiz-options exam-options"
                      disabled={busy || q.submitted}
                    >
                      <legend>
                        {typeOf(q) === "multiple"
                          ? "可选多项；全部选对得分，少选、多选、错选不得分"
                          : typeOf(q) === "true_false"
                            ? "判断命题是否成立"
                            : "请选择一个最符合题意的选项"}
                      </legend>
                      {q.options.map((option, i) => {
                        const chosen =
                          typeOf(q) === "multiple"
                            ? (draft.selected_indices || []).includes(i)
                            : draft.selected === i;
                        const correct = (
                          q.correct_indices || [q.correct_index]
                        ).includes(i);
                        return (
                          <label
                            key={i}
                            className={`${chosen ? "selected " : ""}${q.submitted && correct ? "correct " : ""}${q.submitted && chosen && !correct ? "incorrect" : ""}`}
                          >
                            <input
                              type={
                                typeOf(q) === "multiple" ? "checkbox" : "radio"
                              }
                              name={`${attempt.id}-${q.id}`}
                              checked={chosen}
                              onChange={() =>
                                updateDraft(
                                  typeOf(q) === "multiple"
                                    ? {
                                        selected_indices: chosen
                                          ? (
                                              draft.selected_indices || []
                                            ).filter((v) => v !== i)
                                          : [
                                              ...(draft.selected_indices || []),
                                              i,
                                            ].sort(),
                                      }
                                    : { selected: i },
                                )
                              }
                            />
                            <span>
                              {typeOf(q) === "true_false"
                                ? i === 0
                                  ? "√"
                                  : "×"
                                : String.fromCharCode(65 + i) + "."}
                            </span>
                            <MarkdownRenderer content={option} />
                          </label>
                        );
                      })}
                    </fieldset>
                  )}
                  {!q.submitted ? (
                    <div className="learning-toolbar">
                      <button
                        className="button"
                        disabled={busy || !dirty}
                        onClick={() => void persist()}
                      >
                        保存作答
                      </button>
                      {attempt.delivery !== "exam" && (
                        <button
                          className="button primary"
                          disabled={busy || !filled(draft)}
                          onClick={() => void persist(true)}
                        >
                          提交本题，查看解析
                        </button>
                      )}
                      {attempt.delivery === "exam" && (
                        <span className="muted">
                          交卷前可修改，答案与解析暂不显示。
                        </span>
                      )}
                    </div>
                  ) : (
                    <div className="exam-feedback">
                      <h4>
                        {q.grading === "self_pending"
                          ? "参考答案与评分要点"
                          : q.grading === "unanswered"
                            ? "本题未作答 · 0 分"
                            : `${q.correct ? "本题已掌握" : "本题待巩固"} · ${q.earned ?? (q.correct ? 1 : 0)} / ${q.points || 1} 分${q.grading === "self_assessed" ? "（自评）" : ""}`}
                      </h4>
                      {objectiveTypes.includes(typeOf(q)) ? (
                        <p>
                          <strong>正确答案：</strong>
                          {(q.correct_indices || [q.correct_index!])
                            .map((i) =>
                              typeOf(q) === "true_false"
                                ? q.options[i]
                                : String.fromCharCode(65 + i),
                            )
                            .join("、")}
                        </p>
                      ) : (
                        <MarkdownRenderer content={q.answer || ""} />
                      )}
                      <h4>解析</h4>
                      <MarkdownRenderer content={q.explanation || ""} />
                      {!!q.rubric?.length && (
                        <fieldset
                          className="exam-rubric"
                          disabled={busy || q.grading !== "self_pending"}
                        >
                          <legend>
                            按评分要点自评 · 等价表述与合理替代解法可得分
                          </legend>
                          {q.rubric.map((r, i) => (
                            <label key={r.id}>
                              <span>
                                {i + 1}. {r.text}
                                <small>满分 {r.points} 分</small>
                              </span>
                              <select
                                aria-label={`要点${i + 1}得分`}
                                value={
                                  rubric[r.id] ?? q.rubric_scores?.[r.id] ?? ""
                                }
                                onChange={(e) =>
                                  setRubric((v) => ({
                                    ...v,
                                    [r.id]: Number(e.target.value),
                                  }))
                                }
                              >
                                <option value="" disabled>
                                  请选择
                                </option>
                                {Array.from(
                                  { length: r.points + 1 },
                                  (_, i) => (
                                    <option key={i} value={i}>
                                      {i} 分
                                    </option>
                                  ),
                                )}
                              </select>
                            </label>
                          ))}
                        </fieldset>
                      )}
                      {q.grading === "self_pending" && (
                        <>
                          <p className="muted">
                            结合自己的原始作答逐项给分，不能因看过答案就给分。确认后保留该次自评记录。
                          </p>
                          <button
                            className="button primary"
                            disabled={
                              busy ||
                              !q.rubric?.every(
                                (r) => rubric[r.id] !== undefined,
                              )
                            }
                            onClick={() => void assess()}
                          >
                            确认本题自评
                          </button>
                        </>
                      )}
                      <ReferenceList
                        citations={attempt.citations}
                        content={(q.refs || []).map((n) => `[${n}]`).join("")}
                        onCitation={onCitation}
                      />
                    </div>
                  )}
                </section>
              ) : (
                <p className="exam-notice">
                  当前范围没有题目，可切换回“全部题目”。
                </p>
              )}
              <div className="learning-toolbar spread exam-page-controls">
                <button
                  className="button"
                  disabled={busy || index <= 0}
                  onClick={() => void navigate(() => setIndex((i) => i - 1))}
                >
                  上一题
                </button>
                <button
                  className="exam-mobile-map button"
                  aria-expanded={sheetOpen}
                  onClick={() => {
                    setSheetOpen((v) => !v);
                    if (!sheetOpen)
                      questionRef.current
                        ?.closest(".exam-reading-layout")
                        ?.scrollIntoView({ block: "start" });
                  }}
                >
                  答题卡 · {questions.length ? index + 1 : 0}/{questions.length}
                </button>
                <span className="exam-desktop-count">
                  {questions.length ? index + 1 : 0} / {questions.length}
                </span>
                <button
                  className="button"
                  disabled={busy || index >= questions.length - 1}
                  onClick={() => void navigate(() => setIndex((i) => i + 1))}
                >
                  下一题
                </button>
              </div>
              {attempt.status === "active" && (
                <div className="exam-submit">
                  {confirmFinish ? (
                    <div role="alert">
                      <strong>
                        {unanswered
                          ? `还有 ${unanswered} 题未作答，交卷后这些题计 0 分。`
                          : "已填写的作答将一并提交。"}
                      </strong>
                      <p>
                        交卷后答案锁定，显示解析；非选择题需继续按评分要点自评。
                      </p>
                      <button
                        className="button primary"
                        disabled={busy}
                        onClick={() => void finish()}
                      >
                        确认交卷
                      </button>
                      <button
                        className="button"
                        disabled={busy}
                        onClick={() => setConfirmFinish(false)}
                      >
                        返回检查
                      </button>
                    </div>
                  ) : (
                    <button
                      className="button primary"
                      disabled={busy}
                      onClick={() => setConfirmFinish(true)}
                    >
                      {attempt.delivery === "exam"
                        ? "交卷并查看解析"
                        : "结束本轮，汇总作答"}
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
          {!!attempt.weak_points.length && attempt.status !== "active" && (
            <div className="weak-points">
              <h3>下一轮重点复习</h3>
              {attempt.weak_points.map((p) => (
                <div key={p.point}>
                  <strong>
                    {p.point} · {p.wrong} 道待巩固题
                  </strong>
                  <ReferenceList
                    citations={attempt.citations}
                    content={p.refs.map((n) => `[${n}]`).join("")}
                    onCitation={onCitation}
                  />
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
