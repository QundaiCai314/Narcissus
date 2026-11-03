"use client";
import { sourcePosition } from "@/lib/sources";
import { Citation, WritingCitation } from "@/lib/api";

import { MarkdownRenderer } from "./markdown-renderer";

export function WritingView({
  content,
  citations,
  onCitation,
}: {
  content: string;
  citations: WritingCitation[];
  onCitation: (c: Citation) => void;
}) {
  return (
    <div className="writing-preview">
      <MarkdownRenderer
        content={content}
        citations={citations}
        onCitation={onCitation}
      />
    </div>
  );
}

export function ReferenceList({
  citations,
  content,
  onCitation,
}: {
  citations: WritingCitation[];
  content: string;
  onCitation: (c: Citation) => void;
}) {
  const active = citations.filter((c) => content.includes(`[${c.label}]`));
  if (!active.length) return null;
  return (
    <div className="writing-references">
      <h3>保留的来源</h3>
      {active.map((c) => (
        <details key={c.label}>
          <summary>
            [{c.label}] {c.filename}{" "}
            {c.kind === "document" ? `· ${sourcePosition(c)}` : "· 用户笔记"}
            {c.state === "deleted" && (
              <span className="invalid-source">
                {c.kind === "document" ? "原始资料已删除" : "原始笔记已删除"}
              </span>
            )}
            {c.state === "changed" && (
              <span className="invalid-source">来源已更新 · 可查看旧版原文</span>
            )}
          </summary>
          <p className="source-snapshot">{c.text}</p>
          {c.kind === "note" && (
            <p className="muted">用户笔记快照，未经原始资料核验。</p>
          )}
          {c.kind === "document" && c.state !== "deleted" && (
            <button
              className="text-button"
              onClick={() => onCitation(c as Citation)}
            >
              打开对应原文
            </button>
          )}
          {c.state === "deleted" && (
            <p className="muted">
              以上为保存时的片段快照，不能作为当前可核验来源。
            </p>
          )}
        </details>
      ))}
    </div>
  );
}
