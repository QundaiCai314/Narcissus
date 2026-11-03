"use client";
import { useState } from "react";
import {
  Presentation,
  Image,
  Globe,
  Headphones,
  BookOpen,
  GitBranch,
  Layers,
  CircleHelp,
  FileText,
  PenLine,
  Plus,
  ArrowUpRight,
  RefreshCw,
  LoaderCircle,
} from "lucide-react";
import { useStudio } from "@/hooks/use-studio";
import { LearningKind, phaseNames } from "@/lib/learning";
import { audioStatus } from "@/lib/audio";
import { visualStates } from "@/lib/visuals";

export type StudioKind =
  | "presentation"
  | "infographic"
  | "research"
  | "audio"
  | "guide"
  | "note"
  | "summary"
  | LearningKind;

const tools = [
  { kind: "presentation", title: "演示文稿", icon: Presentation },
  { kind: "infographic", title: "信息图", icon: Image },
  { kind: "research", title: "联网研究", icon: Globe },
  { kind: "audio", title: "音频概览", icon: Headphones },
  { kind: "guide", title: "资料导读", icon: BookOpen },
  { kind: "mindmap", title: "思维导图", icon: GitBranch },
  { kind: "flashcards", title: "闪卡", icon: Layers },
  { kind: "quiz", title: "测验", icon: CircleHelp },
  { kind: "summary", title: "总结", icon: FileText },
  { kind: "note", title: "笔记", icon: PenLine },
] as const;

const synthesizers = [
  { kind: "guide", title: "导读", icon: BookOpen },
  { kind: "summary", title: "总结", icon: FileText },
  { kind: "audio", title: "音频概览", icon: Headphones },
  { kind: "mindmap", title: "思维导图", icon: GitBranch },
  { kind: "quiz", title: "测验", icon: CircleHelp },
  { kind: "flashcards", title: "闪卡", icon: Layers },
  { kind: "research", title: "联网研究", icon: Globe },
  { kind: "presentation", title: "演示文稿", icon: Presentation },
  { kind: "infographic", title: "信息图", icon: Image },
] as const;

const statuses: Record<string, string> = {
  queued: "等待生成",
  running: "正在生成",
  failed: "生成失败",
  cancelled: "已取消",
  succeeded: "已完成",
  ready: "已就绪",
};

export function StudioPanel({
  notebookId,
  revision,
  selectedCount,
  onCreate,
  onOpen,
}: {
  notebookId: string;
  revision: string;
  selectedCount: number;
  onCreate: (kind: StudioKind) => void;
  onOpen: (kind: StudioKind, id: string, documentId?: string | null) => void;
}) {
  const { writings, learning, audio, visuals, loading, error, more, refresh, loadMore } =
    useStudio(notebookId, revision);
  const [filter, setFilter] = useState("all");
  const [limit, setLimit] = useState(16);

  const entries = [
    ...visuals.map((w) => ({
      id: w.id,
      kind: w.kind as StudioKind,
      title: w.title,
      date: w.updated_at,
      status: w.jobs[0]?.status || "ready",
      detail: `第 ${w.revision} 版 · ${visualStates[w.jobs[0]?.status] || "已保存"}`,
      documentId: null,
      extra:
        w.source_state === "deleted"
          ? "原始资料已删除"
          : w.source_state === "changed"
          ? "资料已更新"
          : "",
    })),
    ...writings.map((w) => ({
      id: w.id,
      kind: w.kind as StudioKind,
      title: w.title,
      date: w.updated_at,
      status: w.job?.status || "ready",
      detail: w.job ? statuses[w.job.status] || "已保存" : "已保存",
      documentId: w.document_id,
      extra: "",
    })),
    ...learning.map((w) => ({
      id: w.id,
      kind: w.kind as StudioKind,
      title: w.title,
      date: w.created_at,
      status: w.status,
      detail: `第 ${w.version} 版 · ${phaseNames[w.phase] || statuses[w.status] || "已完成"}`,
      documentId: null,
      extra: w.sources.some((s) => s.state === "deleted")
        ? "原始资料已删除"
        : w.sources.some((s) => s.state === "changed")
        ? "资料已更新"
        : w.mastery
        ? `已掌握 ${w.mastery.mastered}/${w.mastery.total} 张`
        : w.latest_attempt
        ? w.latest_attempt.score === null
          ? `测验进行中 · ${w.latest_attempt.answered}/${w.latest_attempt.total}`
          : `最近成绩 ${w.latest_attempt.score} 分`
        : "",
    })),
    ...audio.map((w) => ({
      id: w.id,
      kind: "audio" as StudioKind,
      title: w.title,
      date: w.created_at,
      status: w.latest_render?.status || w.status,
      detail: audioStatus[w.latest_render?.status || w.status],
      documentId: null,
      extra: w.sources.some((s) => s.state === "deleted")
        ? "原始资料已删除"
        : w.sources.some((s) => s.state === "changed")
        ? "资料已更新"
        : "",
    })),
  ].sort((a, b) => b.date.localeCompare(a.date));

  const filtered = entries.filter((e) => {
    if (filter === "all") return true;
    if (filter === "note") return e.kind === "note";
    if (filter === "summary") return ["summary", "guide", "research"].includes(e.kind);
    if (filter === "learning") return ["mindmap", "flashcards", "quiz"].includes(e.kind);
    if (filter === "visual") return ["presentation", "infographic"].includes(e.kind);
    if (filter === "audio") return e.kind === "audio";
    return true;
  });

  return (
    <aside className="studio-panel" aria-label="工作室与笔记">
      <div className="studio-heading">
        <div>
          <h2>知识沉淀与工作室</h2>
          <p>{selectedCount ? `基于已选 ${selectedCount} 份资料` : "选择左侧资料，开始研读与沉淀"}</p>
        </div>
        <button
          className="icon-button"
          aria-label="刷新工作室"
          title="刷新工作室"
          onClick={refresh}
        >
          <RefreshCw size={14} />
        </button>
      </div>

      {/* 1. 快速提炼工具栏：精致紧凑的微胶囊栏 */}
      <div className="studio-synthesizers-section">
        <div className="studio-section-label">
          <span>快速提炼</span>
          <small>结构化洞察</small>
        </div>
        <div className="studio-synthesizers-grid">
          {synthesizers.map(({ kind, title, icon: Icon }) => (
            <button
              key={kind}
              className={`studio-synth-pill synth-${kind}`}
              title={`生成${title}`}
              onClick={() => onCreate(kind)}
            >
              <Icon size={13} strokeWidth={1.8} />
              <span>{title}</span>
            </button>
          ))}
        </div>
      </div>

      {/* 2. 主角：新建空白笔记卡片 */}
      <div className="studio-new-note-wrap">
        <button
          className="studio-new-note-card"
          onClick={() => onCreate("note")}
          aria-label="新建空白笔记"
        >
          <span className="new-note-icon">
            <Plus size={15} />
          </span>
          <div className="new-note-text">
            <strong>新建空白笔记</strong>
            <small>记录个人思考、研究假设或从对话中整理摘录</small>
          </div>
        </button>
      </div>

      {/* 3. 笔记与资产分类与过滤 */}
      <div className="studio-library-header">
        <div className="studio-library-title">
          <span>沉淀内容</span>
          <small className="library-count">({entries.length})</small>
        </div>
        <div className="studio-filters" aria-label="分类过滤">
          {[
            ["all", "全部"],
            ["note", "笔记"],
            ["summary", "总结"],
            ["learning", "学习卡"],
            ["visual", "图文"],
            ["audio", "音频"],
          ].map(([value, label]) => (
            <button
              key={value}
              aria-pressed={filter === value}
              className={filter === value ? "active" : ""}
              onClick={() => {
                setFilter(value);
                setLimit(16);
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* 4. 笔记与沉淀卡片流 */}
      <div className="studio-library">
        {error && (
          <p className="message-error" role="alert">
            {error}
            <button className="text-button" onClick={refresh}>
              重试
            </button>
          </p>
        )}
        {loading ? (
          <p className="studio-empty" role="status">
            <LoaderCircle className="spin" size={18} />
            正在读取内容…
          </p>
        ) : filtered.length === 0 ? (
          <div className="studio-empty">
            <PenLine size={24} />
            <strong>知识，从这里开始沉淀</strong>
            <p>
              {filter === "all"
                ? "你写的笔记、钉选的回答和生成的内容都会保存在这里。"
                : "当前分类暂无内容。"}
            </p>
            <button className="text-button" onClick={() => onCreate("note")}>
              ＋ 写下第一篇笔记
            </button>
          </div>
        ) : (
          filtered.slice(0, limit).map((entry) => {
            const tool = tools.find((t) => t.kind === entry.kind)!;
            const Icon = tool.icon;
            const active = [
              "queued",
              "running",
              "generating",
              "synthesizing",
              "merging",
            ].includes(entry.status);
            return (
              <button
                key={entry.id}
                className="studio-entry"
                onClick={() => onOpen(entry.kind, entry.id, entry.documentId)}
              >
                <span className={`studio-entry-icon studio-${entry.kind}`}>
                  {active ? (
                    <LoaderCircle size={16} className="spin" />
                  ) : (
                    <Icon size={16} />
                  )}
                </span>
                <span className="studio-entry-copy">
                  <div className="entry-title-row">
                    <strong>{entry.title}</strong>
                    <span className={`entry-kind-tag tag-${entry.kind}`}>
                      {tool.title}
                    </span>
                  </div>
                  <small
                    className={
                      entry.status === "failed" ? "studio-failed" : ""
                    }
                  >
                    {entry.detail}
                    {entry.extra && ` · ${entry.extra}`}
                  </small>
                  <time dateTime={entry.date}>
                    {new Date(entry.date).toLocaleString("zh-CN", {
                      month: "numeric",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </time>
                </span>
                <ArrowUpRight className="studio-entry-arrow" size={13} />
              </button>
            );
          })
        )}
        {(filtered.length > limit || more) && (
          <button
            className="studio-more"
            onClick={() => {
              setLimit((n) => n + 12);
              if (filtered.length <= limit && more) loadMore();
            }}
          >
            加载更多内容
          </button>
        )}
      </div>
    </aside>
  );
}

