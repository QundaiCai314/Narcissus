"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, post, errorText, Page } from "@/lib/api";
import {
  LearningSet,
  QuizAttempt,
  AttemptBrief,
  OnCitation,
} from "@/lib/learning";
import { Check, Sparkles, AlertCircle } from "lucide-react";
import { ReferenceList } from "./writing-view";

export function Quiz({
  row,
  onCitation,
  onChanged,
}: {
  row: LearningSet;
  onCitation: OnCitation;
  onChanged: () => Promise<void>;
}) {
  const [history, setHistory] = useState<AttemptBrief[]>([]),
    [total, setTotal] = useState(0),
    [attempt, setAttempt] = useState<QuizAttempt | null>(null),
    [index, setIndex] = useState(0),
    [onlyWrong, setOnlyWrong] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true),
    [saveState, setSaveState] = useState("");
  const startKey = useRef<{
    mode: string;
    previous: string | null;
    key: string;
  } | null>(null);
  const loadHistory = useCallback(async () => {
    const result = await api<Page<AttemptBrief>>(
      `/learning/${row.id}/attempts?limit=100`,
    );
    setHistory(result.items);
    setTotal(result.total);
    return result.items;
  }, [row.id]);
  const open = useCallback(async (id: string) => {
    const value = await api<QuizAttempt>(`/quiz-attempts/${id}`);
    setAttempt(value);
    const next = value.items.findIndex((q) => !q.submitted);
    setIndex(next < 0 ? 0 : next);
    setOnlyWrong(false);
    setError("");
    setSaveState(value.status === "complete" ? "本轮已完成" : "进度已恢复");
  }, []);
  useEffect(() => {
    let alive = true;
    loadHistory()
      .then(async (rows) => {
        if (alive && rows.length) await open(rows[0].id);
      })
      .catch((e) => {
        if (alive) setError(errorText(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [loadHistory, open]);
  async function start(mode: "all" | "wrong") {
    setBusy(true);
    setError("");
    const previous = mode === "wrong" ? attempt?.id || null : null;
    if (
      !startKey.current ||
      startKey.current.mode !== mode ||
      startKey.current.previous !== previous
    )
      startKey.current = { mode, previous, key: crypto.randomUUID() };
    try {
      const value = await api<QuizAttempt>(
        `/learning/${row.id}/attempts`,
        post({
          request_key: startKey.current.key,
          mode,
          previous_id: previous,
        }),
      );
      startKey.current = null;
      setAttempt(value);
      setIndex(0);
      setOnlyWrong(false);
      setSaveState("进度已保存");
      await loadHistory();
      await onChanged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  const questions =
      attempt?.items.filter((q) => !onlyWrong || (q.submitted && !q.correct)) ||
      [],
    q = questions[index];
  async function save(selected: number, submit = false) {
    if (!attempt || !q || busy) return;
    setBusy(true);
    setSaveState("保存中…");
    try {
      const value = await api<QuizAttempt>(
        `/quiz-attempts/${attempt.id}/answers/${q.id}${submit ? "/submit" : ""}`,
        {
          method: submit ? "POST" : "PATCH",
          body: JSON.stringify({ selected, revision: attempt.revision }),
        },
      );
      setAttempt(value);
      setSaveState(submit ? "答案已提交" : "选择已保存");
      setError("");
      if (submit) {
        await loadHistory();
        await onChanged();
      }
    } catch (e) {
      setError(errorText(e));
      setSaveState("保存失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="learning-detail">
      {error && (
        <div className="save-error" role="alert">
          {error}
          {attempt && (
            <button
              className="button"
              onClick={() =>
                open(attempt.id).catch((e) => setError(errorText(e)))
              }
            >
              重新加载作答进度
            </button>
          )}
        </div>
      )}
      <div className="learning-toolbar">
        <button
          className="button primary"
          disabled={busy}
          onClick={() => start("all")}
        >
          {attempt ? "开始新一轮测验" : "开始测验"}
        </button>
        {attempt?.status === "complete" && (
          <button
            className="button"
            disabled={busy || !attempt.weak_points.length}
            onClick={() => start("wrong")}
          >
            只练习本轮错题
          </button>
        )}
      </div>
      {!!history.length && (
        <label className="attempt-history">
          历史尝试
          <select
            aria-label="测验历史尝试"
            value={attempt?.id || ""}
            disabled={busy}
            onChange={(e) =>
              open(e.target.value).catch((e) => setError(errorText(e)))
            }
          >
            <option value="" disabled>
              选择一次测验
            </option>
            {history.map((a, i) => (
              <option value={a.id} key={a.id}>
                {new Date(a.created_at).toLocaleString("zh-CN")} ·{" "}
                {a.status === "complete"
                  ? `${a.score} 分`
                  : `进行中 ${a.answered}/${a.total}`}{" "}
                · {a.mode === "wrong" ? "错题练习" : "完整测验"}
                {i === 0 ? " · 最近" : ""}
              </option>
            ))}
          </select>
          {history.length < total && (
            <button
              onClick={async () => {
                try {
                  const p = await api<Page<AttemptBrief>>(
                    `/learning/${row.id}/attempts?limit=100&offset=${history.length}`,
                  );
                  setHistory((v) => [...v, ...p.items]);
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
      {loading ? (
        <p role="status">正在读取测验记录…</p>
      ) : !attempt ? (
        <div className="quiz-ready-card">
          <div className="quiz-ready-badge">
            <Sparkles size={14} />
            <span>测验已生成 · 待开始</span>
          </div>
          <h3>{row.title}</h3>
          <p className="quiz-ready-desc">
            系统已严格基于所选资料考点生成 <strong>{row.count || questions.length || 6} 道</strong> 专项试题，杜绝幻觉与凑数。
          </p>

          <div className="quiz-ready-meta">
            <div className="ready-meta-item">
              <span className="meta-label">试题数量</span>
              <strong className="meta-val">{row.count || 6} 题</strong>
            </div>
            <div className="ready-meta-item">
              <span className="meta-label">出题模式</span>
              <strong className="meta-val">单项客观题</strong>
            </div>
            <div className="ready-meta-item">
              <span className="meta-label">批改规则</span>
              <strong className="meta-val">逐题即时批改 · 出处核验</strong>
            </div>
          </div>

          <div className="quiz-ready-action">
            <button
              className="button primary quiz-start-btn"
              disabled={busy}
              onClick={() => start("all")}
            >
              <Check size={16} />
              <span>立即开始答题</span>
            </button>
          </div>

          <ul className="quiz-ready-tips">
            <li>• <strong>单题即时反馈</strong>：作答后点击“提交本题”，系统立即判定对错并展示原文证据链。</li>
            <li>• <strong>考后弱项雷达</strong>：全部提交后自动归纳薄弱知识点，支持原文一键对照。</li>
            <li>• <strong>错题本重练机制</strong>：支持开启“只练习本轮错题”模式，开展针对性错题攻坚。</li>
          </ul>
        </div>
      ) : (
        <>
          <div className="mastery-strip">
            <strong>
              {attempt.status === "complete"
                ? `本轮成绩 ${attempt.score} 分`
                : `已提交 ${attempt.answered} / ${attempt.total} 题`}
            </strong>
            <span>
              答对 {attempt.correct} / {attempt.total}
            </span>
            <span role="status">{saveState}</span>
          </div>
          {attempt.status === "complete" && (
            <>
              <div className="weak-points">
                <h3>薄弱知识点</h3>
                {attempt.weak_points.length ? (
                  attempt.weak_points.map((p) => (
                    <div key={p.point}>
                      <strong>
                        {p.point} · 错 {p.wrong} 题
                      </strong>
                      <ReferenceList
                        citations={attempt.citations}
                        content={p.refs.map((n) => `[${n}]`).join("")}
                        onCitation={onCitation}
                      />
                    </div>
                  ))
                ) : (
                  <p>本轮全部答对，可以继续探索其他资料。</p>
                )}
              </div>
              <label className="source-option">
                <input
                  type="checkbox"
                  checked={onlyWrong}
                  onChange={(e) => {
                    setOnlyWrong(e.target.checked);
                    setIndex(0);
                  }}
                />
                只看本轮错题
              </label>
            </>
          )}

          {/* 题目答题卡导航条 */}
          {questions.length > 0 && (
            <div className="quiz-stepper">
              <span className="stepper-label">题目导航</span>
              <div className="stepper-list">
                {questions.map((quest, i) => {
                  const isCurrent = i === index;
                  const isDone = quest.submitted;
                  const isCorrect = isDone && quest.correct;
                  const isWrong = isDone && !quest.correct;
                  return (
                    <button
                      key={quest.id}
                      type="button"
                      className={`stepper-item ${isCurrent ? "current" : ""} ${
                        isDone ? (isCorrect ? "correct" : "incorrect") : "pending"
                      }`}
                      onClick={() => setIndex(i)}
                      title={`第 ${i + 1} 题${
                        quest.submitted
                          ? quest.correct
                            ? " (回答正确)"
                            : " (答错)"
                          : " (待作答)"
                      }`}
                    >
                      <span>{i + 1}</span>
                      {isDone && (
                        <span className="stepper-mark">
                          {isCorrect ? "✓" : "✗"}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {q ? (
            <>
              <section className="quiz-question">
                <span className="eyebrow">
                  第 {index + 1} / {questions.length} 题{q.point ? ` · ${q.point}` : ""}
                </span>
                <h3>{q.question}</h3>
                <fieldset
                  disabled={busy || q.submitted}
                  className="quiz-options"
                >
                  <legend className="sr-only">选择一个答案</legend>
                  {q.options.map((option, i) => (
                    <label
                      key={i}
                      className={
                        (q.selected === i ? "selected " : "") +
                        (q.submitted && q.correct_index === i
                          ? "correct "
                          : "") +
                        (q.submitted && q.selected === i && !q.correct
                          ? "incorrect"
                          : "")
                      }
                    >
                      <input
                        type="radio"
                        name={`${attempt.id}-${q.id}`}
                        checked={q.selected === i}
                        onChange={() => save(i)}
                      />
                      <span>{String.fromCharCode(65 + i)}.</span>
                      <span>{option}</span>
                    </label>
                  ))}
                </fieldset>
                {!q.submitted ? (
                  <button
                    className="button primary"
                    disabled={
                      busy || q.selected === null || q.selected === undefined
                    }
                    onClick={() => save(q.selected!, true)}
                  >
                    提交本题
                  </button>
                ) : (
                  <div
                    className={
                      "quiz-feedback " + (q.correct ? "correct" : "incorrect")
                    }
                  >
                    <strong>
                      {q.correct ? "回答正确" : "本题答错了"} · 正确答案{" "}
                      {String.fromCharCode(65 + (q.correct_index ?? 0))}
                    </strong>
                    <p>{q.explanation}</p>
                    <ReferenceList
                      citations={attempt.citations}
                      content={(q.refs || []).map((n) => `[${n}]`).join("")}
                      onCitation={onCitation}
                    />
                  </div>
                )}
              </section>
              <div className="learning-toolbar spread">
                <button
                  className="button"
                  disabled={busy || index <= 0}
                  onClick={() => setIndex((v) => v - 1)}
                >
                  上一题
                </button>
                <span>
                  {index + 1} / {questions.length}
                </span>
                <button
                  className="button"
                  disabled={busy || index >= questions.length - 1}
                  onClick={() => setIndex((v) => v + 1)}
                >
                  下一题
                </button>
              </div>
            </>
          ) : (
            <p>这个范围内没有题目。</p>
          )}
        </>
      )}
    </div>
  );
}
