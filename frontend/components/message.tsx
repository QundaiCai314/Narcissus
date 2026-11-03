"use client";
import { useState } from "react";
import { sourcePosition } from "@/lib/sources";
import { Pin, Copy, Check, RotateCcw, Sparkles } from "lucide-react";
import { Message, Citation } from "@/lib/api";
import { MarkdownRenderer } from "./markdown-renderer";

export function ChatMessage({
  message,
  onCitation,
  onRetry,
  busy,
  onSave,
}: {
  message: Message;
  onCitation: (c: Citation) => void;
  onRetry: (id: string) => void;
  busy: boolean;
  onSave?: (id: string) => Promise<void> | void;
}) {
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  async function handleSave() {
    if (!onSave || saving || saved) return;
    setSaving(true);
    try {
      await onSave(message.id);
      setSaved(true);
    } finally {
      setSaving(false);
    }
  }

  async function handleCopy() {
    if (!message.content) return;
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore clipboard error
    }
  }

  return (
    <article className={"message " + message.role}>
      <div className="message-header">
        <div className="message-author">
          {message.role === "user" ? (
            <span className="user-mark">提问</span>
          ) : (
            <>
              <span className="assistant-mark">
                <Sparkles size={13} />
              </span>
              <span className="author-name">资料提炼</span>
            </>
          )}
          {message.status === "generating" && (
            <span className="generation-label">正在研读资料并梳理出处…</span>
          )}
        </div>

        {message.role === "assistant" &&
          message.status === "complete" &&
          message.content && (
            <div className="message-actions">
              {onSave && (
                <button
                  type="button"
                  className={`message-action-btn ${saved ? "saved" : ""}`}
                  onClick={handleSave}
                  disabled={saving}
                  title={saved ? "已收录至右侧笔记" : "钉选为笔记 (Pin to Note)"}
                  aria-label="钉选为笔记"
                >
                  {saved ? <Check size={12} className="text-green" /> : <Pin size={12} />}
                  <span>{saved ? "已钉选为笔记" : saving ? "保存中…" : "钉选为笔记"}</span>
                </button>
              )}
              <button
                type="button"
                className="message-action-btn"
                onClick={handleCopy}
                title="复制内容"
                aria-label="复制内容"
              >
                {copied ? <Check size={12} /> : <Copy size={12} />}
                <span>{copied ? "已复制" : "复制"}</span>
              </button>
              <button
                type="button"
                className="message-action-btn"
                disabled={busy}
                onClick={() => onRetry(message.id)}
                title="重新生成回答"
                aria-label="重新生成回答"
              >
                <RotateCcw size={12} />
                <span>重答</span>
              </button>
            </div>
          )}
      </div>

      <div className="message-content">
        <MarkdownRenderer
          content={message.content}
          citations={message.citations}
          onCitation={onCitation}
        />
        {message.status === "generating" && !message.content && (
          <span className="thinking-dots">● ● ●</span>
        )}
      </div>

      {message.error && <p className="message-error">{message.error}</p>}
      {message.status === "stopped" && <p className="muted">已停止生成</p>}
      {["failed", "stopped"].includes(message.status) && (
        <button
          className="text-button"
          disabled={busy}
          onClick={() => onRetry(message.id)}
        >
          <RotateCcw size={14} />
          重新回答
        </button>
      )}

      {message.citations.length > 0 && message.content && (
        <div className="source-chips-wrap">
          <span className="source-chips-label">参考出处</span>
          <div className="source-chips">
            {message.citations
              .filter((c) => message.content.includes(`[${c.label}]`))
              .map((c) => (
                <button key={c.label} onClick={() => onCitation(c)}>
                  <span>{c.label}</span>
                  {c.filename}
                  <small>{sourcePosition(c)}</small>
                </button>
              ))}
          </div>
        </div>
      )}
    </article>
  );
}
