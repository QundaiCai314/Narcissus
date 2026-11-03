"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, post, errorText, Document, Page } from "@/lib/api";
import {
  LearningKind,
  LearningSet,
  LearningContext,
  OnCitation,
  kindNames,
  phaseNames,
} from "@/lib/learning";
import { MindMap } from "./mind-map";
import { Flashcards } from "./flashcards";
import { Quiz } from "./quiz";

export function LearningPanel({
  notebookId,
  docs,
  onCitation,
  onAsk,
  studioRequest,
}: {
  notebookId: string;
  docs: Document[];
  onCitation: OnCitation;
  onAsk: (context: LearningContext, title: string, sourceIds: string[]) => void;
  studioRequest?: { key: number; id?: string; kind?: LearningKind; documentIds?: string[] };
}) {
  const [items, setItems] = useState<LearningSet[]>([]),
    [total, setTotal] = useState(0),
    [row, setRow] = useState<LearningSet | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [form, setForm] = useState(false);
  const [kind, setKind] = useState<LearningKind>("mindmap"),
    [sourceIds, setSourceIds] = useState<string[]>([]),
    [topic, setTopic] = useState(""),
    [audience, setAudience] = useState(""),
    [difficulty, setDifficulty] = useState("standard"),
    [count, setCount] = useState(15),
    [filter, setFilter] = useState("all");
  const requestKey = useRef<{ signature: string; key: string } | null>(null);
  const selected = useRef("");
  const loadedPages = useRef(1);
  const handledRequest = useRef(0);
  useEffect(() => {
    if (!studioRequest || studioRequest.key === handledRequest.current) return;
    handledRequest.current = studioRequest.key;
    if (studioRequest.id) {
      setFilter("all");
      void open(studioRequest.id);
    } else {
      const nextKind = studioRequest.kind || "mindmap";
      setKind(nextKind);
      setCount(nextKind === "quiz" ? 10 : 15);
      newForm(studioRequest.documentIds);
    }
  }, [studioRequest]);
  const load = useCallback(async () => {
    const pages = await Promise.all(Array.from({ length: loadedPages.current }, (_, i) =>
      api<Page<LearningSet>>(`/notebooks/${notebookId}/learning?limit=100&offset=${i * 100}`),
    ));
    setItems([...new Map(pages.flatMap(p => p.items).map(x => [x.id, x])).values()]);
    setTotal(pages[0].total);
  }, [notebookId]);
  useEffect(() => {
    load()
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
  }, [load]);
  const refresh = useCallback(async () => {
    await load();
    const id = selected.current;
    if (id) {
      const next = await api<LearningSet>(`/learning/${id}`);
      if (selected.current === id) setRow(next);
    }
  }, [load]);
  useEffect(() => {
    let alive = true;
    const timer = setInterval(() => {
      if (alive)
        refresh().catch((e) => {
          if (alive) setError(errorText(e));
        });
    }, 4000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [refresh]);
  async function open(id: string) {
    selected.current = id;
    setError("");
    setForm(false);
    setRow(null);
    if (!id) return;
    try {
      const next = await api<LearningSet>(`/learning/${id}`);
      if (selected.current === id) setRow(next);
    } catch (e) {
      setError(errorText(e));
    }
  }
  function newForm(documentIds?: string[]) {
    setForm(true);
    setError("");
    setSourceIds(docs.filter((d) => d.status === "ready" && (!documentIds || documentIds.includes(d.id))).map((d) => d.id));
    requestKey.current = null;
  }
  async function generate() {
    setBusy(true);
    setError("");
    const params = {
      kind,
      document_ids: sourceIds,
      topic,
      audience,
      difficulty,
      count: kind === "mindmap" ? 40 : count,
    };
    const signature = JSON.stringify(params);
    if (requestKey.current?.signature !== signature)
      requestKey.current = { signature, key: crypto.randomUUID() };
    try {
      const next = await api<LearningSet>(
        `/notebooks/${notebookId}/learning`,
        post({ ...params, request_key: requestKey.current.key }),
      );
      requestKey.current = null;
      selected.current = next.id;
      setRow(next);
      setForm(false);
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function task(action: "cancel" | "retry" | "regenerate") {
    if (!row) return;
    setBusy(true);
    try {
      const signature = row.id + action;
      if (
        action === "regenerate" &&
        requestKey.current?.signature !== signature
      )
        requestKey.current = { signature, key: crypto.randomUUID() };
      const next = await api<LearningSet>(
        `/learning/${row.id}/${action}`,
        post(
          action === "regenerate"
            ? { request_key: requestKey.current!.key }
            : undefined,
        ),
      );
      requestKey.current = null;
      selected.current = next.id;
      setRow(next);
      setError("");
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  const active = row && ["queued", "running"].includes(row.status),
    visible = items.filter((x) => filter === "all" || x.kind === filter);
  return (
    <section className="writing-area learning-area">
      <div className="writing-heading">
        <div>
          <span className="eyebrow">从理解，到掌握</span>
          <h2>主动学习</h2>
        </div>
        <button className="button primary" onClick={() => newForm()} disabled={busy}>
          ＋ 创建学习内容
        </button>
      </div>
      {error && (
        <p className="message-error writing-error" role="alert">
          {error}
          <button
            className="text-button"
            onClick={() =>
              refresh()
                .then(() => setError(""))
                .catch((e) => setError(errorText(e)))
            }
          >
            重新加载
          </button>
        </p>
      )}
      <div className="learning-library">
        <div className="learning-filters">
          {[
            ["all", "全部"],
            ["mindmap", "思维导图"],
            ["flashcards", "闪卡"],
            ["quiz", "测验"],
          ].map(([value, label]) => (
            <button
              key={value}
              className={filter === value ? "active" : ""}
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
          <span className="muted">{total} 个版本</span>
        </div>
        <select
          aria-label="选择学习成果"
          value={visible.some((i) => i.id === row?.id) ? row?.id || "" : ""}
          onChange={(e) => open(e.target.value)}
        >
          <option value="">选择已生成的学习内容</option>
          {visible.map((x) => (
            <option key={x.id} value={x.id}>
              {x.title} · 第 {x.version} 版 · {phaseNames[x.phase] || x.status}
            </option>
          ))}
        </select>
        {items.length < total && (
          <button
            onClick={async () => {
              try {
                const p = await api<Page<LearningSet>>(
                  `/notebooks/${notebookId}/learning?limit=100&offset=${items.length}`,
                );
                loadedPages.current += 1;
                setItems((v) => [...new Map([...v, ...p.items].map(x => [x.id, x])).values()]);
              } catch (e) {
                setError(errorText(e));
              }
            }}
          >
            加载更多
          </button>
        )}
      </div>
      <div className="writing-scroll learning-scroll">
        {form ? (
          <div className="summary-form learning-form">
            <h3>把资料变成学习内容</h3>
            <p className="muted">
              仅以选定原始资料为事实依据。可用笔记或总结描述学习目标，但不会把其中观点当作已核实事实。
            </p>
            <label>
              内容类型
              <select
                aria-label="学习内容类型"
                value={kind}
                onChange={(e) => {
                  const k = e.target.value as LearningKind;
                  setKind(k);
                  setCount(k === "quiz" ? 10 : 15);
                }}
              >
                {Object.entries(kindNames).map(([value, name]) => (
                  <option key={value} value={value}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <fieldset>
              <legend>选择资料</legend>
              {docs
                .filter((d) => d.status === "ready")
                .map((d) => (
                  <label className="source-option" key={d.id}>
                    <input
                      type="checkbox"
                      checked={sourceIds.includes(d.id)}
                      onChange={(e) =>
                        setSourceIds((v) =>
                          e.target.checked
                            ? [...v, d.id]
                            : v.filter((x) => x !== d.id),
                        )
                      }
                    />
                    {d.filename}
                  </label>
                ))}
              {!docs.some((d) => d.status === "ready") && (
                <p>请先上传并等待资料处理完成。</p>
              )}
            </fieldset>
            <label>
              学习主题或目标（可选）
              <textarea
                value={topic}
                maxLength={500}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="例如：理解核心概念，掌握容易混淆的细节"
              />
              <div className="learning-presets">
                <span className="presets-label">选择一个出题方向：</span>
                {[
                  "重点难点梳理与定义考查",
                  "易错点辨析与常见混淆项",
                  "核心考点自测与应用推理",
                  "章节知识脉络与综合理解",
                ].map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    className="preset-chip"
                    onClick={() => setTopic(preset)}
                  >
                    {preset}
                  </button>
                ))}
              </div>
            </label>
            <label>
              目标受众（可选）
              <input
                value={audience}
                maxLength={200}
                onChange={(e) => setAudience(e.target.value)}
                placeholder="例如：初次阅读者"
              />
            </label>
            <div className="learning-form-grid">
              <label>
                难度
                <select
                  aria-label="学习难度"
                  value={difficulty}
                  onChange={(e) => setDifficulty(e.target.value)}
                >
                  <option value="easy">简单 · 理解基础</option>
                  <option value="standard">标准 · 联系与区分</option>
                  <option value="advanced">进阶 · 基于资料推理</option>
                </select>
              </label>
              {kind === "mindmap" ? (
                <p className="muted">最多 3 层、40 个节点</p>
              ) : (
                <label>
                  {kind === "flashcards" ? "闪卡数量" : "测验题数"}
                  <select
                    aria-label="学习数量"
                    value={count}
                    onChange={(e) => setCount(Number(e.target.value))}
                  >
                    {(kind === "flashcards"
                      ? [10, 15, 20, 25, 30]
                      : [5, 10, 15, 20]
                    ).map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>
            <p className="muted">
              资料不足时会减少数量或明确说明。生成后先核对证据，再整体显示成果。
            </p>
            <div className="learning-toolbar">
              <button
                className="button primary"
                disabled={busy || !sourceIds.length}
                onClick={generate}
              >
                {busy ? "正在提交…" : "开始生成"}
              </button>
              <button
                className="button"
                disabled={busy}
                onClick={() => setForm(false)}
              >
                返回
              </button>
            </div>
          </div>
        ) : row ? (
          <>
            <div className="learning-result-heading">
              <span className="eyebrow">
                {kindNames[row.kind]} · 第 {row.version} 版
              </span>
              <h3>{row.title}</h3>
              <p className="muted">
                {new Date(row.created_at).toLocaleString("zh-CN")} ·{" "}
                {row.sources.length} 份资料
                {row.status === "complete"
                  ? ` · ${row.count} ${row.kind === "mindmap" ? "个节点" : row.kind === "flashcards" ? "张卡片" : "道题"}`
                  : ""}
              </p>
              <div className="learning-sources">
                {row.sources.map((s) => (
                  <span key={s.id}>
                    {s.filename} · 资料版本 {s.version}
                    {s.state === "deleted"
                      ? " · 原始资料已删除"
                      : s.state === "changed"
                        ? " · 资料已更新"
                        : ""}
                  </span>
                ))}
              </div>
              {row.sources.some((s) => s.state !== "active") && (
                <p className="source-warning">
                  保留的是历史学习版本和来源快照。失效来源不可跳转核验；原有学习记录仍然保留。
                </p>
              )}
              <div className="learning-toolbar">
                <span role="status">{phaseNames[row.phase] || row.status}</span>
                {active ? (
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() => task("cancel")}
                  >
                    取消生成
                  </button>
                ) : (
                  <>
                    <button
                      className="button"
                      disabled={
                        busy || row.sources.some((s) => s.state === "deleted")
                      }
                      onClick={() => task("regenerate")}
                    >
                      生成新版
                    </button>
                    {["failed", "cancelled"].includes(row.status) && row.sources.every(s => s.state === "active") && (
                      <button
                        className="button"
                        disabled={busy}
                        onClick={() => task("retry")}
                      >
                        重试生成
                      </button>
                    )}
                  </>
                )}
              </div>
              {row.error && (
                <p className="message-error" role="alert">
                  {row.error}
                </p>
              )}
              {row.warning && <p className="source-warning">{row.warning}</p>}
            </div>
            {active && (
              <div className="learning-pending">
                <div className="learning-pulse" />
                <h3>{phaseNames[row.phase]}</h3>
                <p>
                  可以离开此页面，完成后会保存到本笔记本。内容通过检查后才会显示。
                </p>
              </div>
            )}
            {row.status === "complete" &&
              (row.kind === "mindmap" ? (
                <MindMap
                  key={row.id}
                  row={row}
                  onCitation={onCitation}
                  onAsk={(context, title) =>
                    onAsk(
                      context,
                      title,
                      row.sources.map((s) => s.id),
                    )
                  }
                />
              ) : row.kind === "flashcards" ? (
                <Flashcards
                  key={row.id}
                  row={row}
                  onCitation={onCitation}
                  onChanged={refresh}
                />
              ) : (
                <Quiz
                  key={row.id}
                  row={row}
                  onCitation={onCitation}
                  onChanged={refresh}
                />
              ))}
          </>
        ) : loading ? (
          <p role="status">正在读取学习内容…</p>
        ) : (
          <div className="learning-empty">
            <span className="eyebrow">你的下一步，不止于阅读</span>
            <h3>梳理知识，主动回想，检验理解。</h3>
            <p>从一份或多份资料开始，生成可以追溯原文的学习内容。</p>
            <div className="learning-type-cards">
              {Object.entries(kindNames).map(([k, name]) => (
                <button
                  key={k}
                  onClick={() => {
                    newForm();
                    setKind(k as LearningKind);
                    setCount(k === "quiz" ? 10 : 15);
                  }}
                >
                  <strong>{name}</strong>
                  <span>
                    {k === "mindmap"
                      ? "看见主题之间的联系"
                      : k === "flashcards"
                        ? "用问答逐步巩固记忆"
                        : "发现薄弱点并回到原文"}
                  </span>
                </button>
              ))}
            </div>
            {visible.map((x) => (
              <button
                className="learning-list-card"
                key={x.id}
                onClick={() => open(x.id)}
              >
                <strong>
                  {x.title} · 第 {x.version} 版
                </strong>
                <span>
                  {phaseNames[x.phase]} · {x.sources.length} 份资料 ·{" "}
                  {new Date(x.created_at).toLocaleDateString("zh-CN")}
                  {x.mastery
                    ? ` · 已掌握 ${x.mastery.mastered}/${x.mastery.total}`
                    : ""}
                  {x.latest_attempt?.score != null
                    ? ` · 最近 ${x.latest_attempt.score} 分`
                    : ""}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
