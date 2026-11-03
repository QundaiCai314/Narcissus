"use client";
import { useEffect, useState } from "react";
import { api, post, errorText, Writing, Document, Citation } from "@/lib/api";
import { WritingView, ReferenceList } from "./writing-view";

export function GuidePanel({
  docs,
  documentId,
  onSelect,
  onAsk,
  onCitation,
}: {
  docs: Document[];
  documentId: string;
  onSelect: (id: string) => void;
  onAsk: (text: string, id: string) => void;
  onCitation: (c: Citation) => void;
}) {
  const [guide, setGuide] = useState<Writing | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false);
  const doc = docs.find((d) => d.id === documentId);
  const outdated = !!guide?.content && guide.details.inputs?.documents[0]?.version !== doc?.generation;
  useEffect(() => {
    let active = true;
    async function load() {
      if (!documentId) return;
      try {
        const value = await api<Writing | null>(
          `/documents/${documentId}/guide`,
        );
        if (active) {
          setGuide(value);
          setError("");
        }
      } catch (e) {
          if (active) { setError(errorText(e)); setGuide(null); }
      } finally {
        if (active) setLoading(false);
      }
    }
    setGuide(null);
    setLoading(!!documentId);
    load();
    const timer = setInterval(load, 4000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [documentId]);
  async function regenerate() {
    try {
      setError("");
      setGuide(await api<Writing>(`/documents/${documentId}/guide`, post()));
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <section className="writing-area">
      <div className="writing-heading">
        <h2>资料导读</h2>
        <select
          aria-label="选择导读资料"
          value={documentId}
          onChange={(e) => onSelect(e.target.value)}
        >
          <option value="">选择一份资料</option>
          {docs.map((d) => (
            <option key={d.id} value={d.id}>
              {d.filename}
            </option>
          ))}
        </select>
      </div>
      <div className="writing-scroll">
        {error && (
          <p role="alert" className="message-error">
            {error}
          </p>
        )}
        {!doc && (
          <p className="muted">选择资料，查看摘要、关键主题和建议问题。</p>
        )}
        {doc && doc.status !== "ready" && <p>资料处理完成后会自动准备导读。</p>}
        {loading && <p role="status">正在读取导读…</p>}
        {doc?.status === "ready" && !loading && (
          <>
            <div className="generation-status">
              <span>
                {!guide
                  ? "正在准备导读…"
                  : guide.job?.status === "queued"
                    ? "等待生成"
                    : guide.job?.status === "running"
                      ? "正在阅读并整理…"
                      : guide.job?.status === "complete"
                        ? "导读已就绪"
                        : "导读未完成"}
              </span>
              <button
                className="button"
                onClick={regenerate}
                disabled={
                  guide?.job?.status === "queued" ||
                  guide?.job?.status === "running"
                }
              >
                重新生成
              </button>
            </div>
            {guide?.job?.error && (
              <p className="message-error">{guide.job.error}</p>
            )}
            {outdated && <p className="source-warning">资料已更新，正在准备新版导读；旧版建议问题暂不显示。</p>}
            {guide?.content && !outdated && (
              <>
                <WritingView
                  content={guide.content.split("## 建议问题")[0]}
                  citations={guide.citations}
                  onCitation={onCitation}
                />
                <h3>从一个问题开始</h3>
                <div className="guide-questions">
                  {guide.details.structured?.questions?.map((q, i) => (
                    <button key={i} onClick={() => onAsk(q.text, documentId)}>
                      {q.text}
                      <span>开始提问 →</span>
                    </button>
                  ))}
                </div>
                <ReferenceList
                  citations={guide.citations}
                  content={guide.content}
                  onCitation={onCitation}
                />
                <p className="muted">
                  依据资料版本 {guide.details.inputs?.documents[0]?.version} ·{" "}
                  {new Date(guide.updated_at).toLocaleString("zh-CN")}
                </p>
              </>
            )}
          </>
        )}
      </div>
    </section>
  );
}
