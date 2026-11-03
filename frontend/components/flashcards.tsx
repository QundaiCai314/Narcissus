"use client";
import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "@/lib/api";
import { LearningSet, CardProgress, OnCitation } from "@/lib/learning";
import { ReferenceList } from "./writing-view";

export function Flashcards({
  row,
  onCitation,
  onChanged,
}: {
  row: LearningSet;
  onCitation: OnCitation;
  onChanged: () => Promise<void>;
}) {
  const [progress, setProgress] = useState<CardProgress | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [flipped, setFlipped] = useState(false),
    [saveState, setSaveState] = useState("");
  const path = `/learning/${row.id}/flashcards/progress`;
  const load = useCallback(async () => {
    setProgress(await api<CardProgress>(path));
    setError("");
    setSaveState("进度已保存");
  }, [path]);
  useEffect(() => {
    load().catch((e) => setError(errorText(e)));
  }, [load]);
  useEffect(() => setFlipped(false), [progress?.current_id]);
  async function update(data: Record<string, unknown>) {
    if (!progress || busy) return;
    setBusy(true);
    setSaveState("保存中…");
    try {
      setProgress(
        await api<CardProgress>(path, {
          method: "PATCH",
          body: JSON.stringify({ revision: progress.revision, ...data }),
        }),
      );
      setError("");
      setSaveState("进度已保存");
      await onChanged();
    } catch (e) {
      setError(errorText(e));
      setSaveState("保存失败");
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    if (
      !progress?.current_id ||
      !window.confirm("删除这张闪卡？本版本将不再显示它。")
    )
      return;
    setBusy(true);
    try {
      await api(`/learning/${row.id}/flashcards/${progress.current_id}`, {
        method: "DELETE",
      });
      await onChanged();
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  const items = row.items || [],
    current = items.find((c) => c.id === progress?.current_id),
    position = progress?.order.indexOf(progress.current_id || "") ?? -1;
  const mastered = items.filter(
      (c) => progress?.states[c.id] === "mastered",
    ).length,
    review = items.filter((c) => progress?.states[c.id] === "review").length;
  return (
    <div className="learning-detail">
      {error && (
        <div className="save-error" role="alert">
          {error}
          <button
            className="button"
            onClick={() => load().catch((e) => setError(errorText(e)))}
          >
            重新加载进度
          </button>
        </div>
      )}
      {!progress ? (
        <p role="status">正在读取复习进度…</p>
      ) : (
        <>
          <div className="mastery-strip">
            <strong>
              已掌握 {mastered} / {items.length}
            </strong>
            <span>需复习 {review}</span>
            <span role="status">{saveState}</span>
          </div>
          <progress
            className="mastery-bar"
            value={mastered}
            max={Math.max(1, items.length)}
            aria-label="闪卡掌握进度"
          />
          <div className="learning-toolbar">
            <label>
              复习范围
              <select
                aria-label="闪卡复习范围"
                disabled={busy}
                value={progress.mode}
                onChange={(e) => update({ mode: e.target.value })}
              >
                <option value="all">全部卡片</option>
                <option value="review">只看需复习</option>
              </select>
            </label>
            <label>
              顺序
              <select
                aria-label="闪卡顺序"
                disabled={busy}
                value={progress.shuffled ? "shuffle" : "original"}
                onChange={(e) =>
                  update({ shuffle: e.target.value === "shuffle" })
                }
              >
                <option value="original">原始顺序</option>
                <option value="shuffle">打乱顺序</option>
              </select>
            </label>
          </div>
          {current ? (
            <>
              <div className={"flashcard " + (flipped ? "flipped" : "")}>
                <span className="eyebrow">
                  {position + 1} / {progress.order.length} · {current.point}
                </span>
                <h3>{current.question}</h3>
                {flipped ? (
                  <div className="flashcard-answer">
                    <h4>答案</h4>
                    <p>{current.answer}</p>
                    <h4>为什么</h4>
                    <p>{current.explanation}</p>
                    <ReferenceList
                      citations={row.citations || []}
                      content={current.refs.map((n) => `[${n}]`).join("")}
                      onCitation={onCitation}
                    />
                  </div>
                ) : (
                  <p className="muted">先试着回想，再翻面核对。</p>
                )}
                <button
                  className="button"
                  onClick={() => setFlipped((v) => !v)}
                >
                  {flipped ? "返回正面" : "翻面查看答案"}
                </button>
              </div>
              <div className="learning-toolbar spread">
                <button
                  className="button"
                  disabled={busy || position <= 0}
                  onClick={() =>
                    update({ current_id: progress.order[position - 1] })
                  }
                >
                  上一张
                </button>
                <span className="muted">
                  {progress.states[current.id] === "mastered"
                    ? "已掌握"
                    : progress.states[current.id] === "review"
                      ? "需复习"
                      : "尚未标记"}
                </span>
                <button
                  className="button"
                  disabled={busy || position >= progress.order.length - 1}
                  onClick={() =>
                    update({ current_id: progress.order[position + 1] })
                  }
                >
                  下一张
                </button>
              </div>
              <div className="learning-toolbar">
                <button
                  className="button primary"
                  disabled={busy}
                  onClick={() =>
                    update({ card_id: current.id, state: "mastered" })
                  }
                >
                  标记已掌握
                </button>
                <button
                  className="button"
                  disabled={busy}
                  onClick={() =>
                    update({ card_id: current.id, state: "review" })
                  }
                >
                  标记需复习
                </button>
                <button
                  className="text-button danger"
                  disabled={busy}
                  onClick={remove}
                >
                  删除这张卡片
                </button>
              </div>
            </>
          ) : (
            <div className="writing-empty">
              <h3>
                {progress.mode === "review"
                  ? "暂时没有需要复习的卡片"
                  : "这一组没有可用卡片"}
              </h3>
              <p>
                {progress.mode === "review"
                  ? "切换到全部卡片，标记希望再次复习的内容。"
                  : "可以保留此版本，或重新生成一组闪卡。"}
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
