"use client";
import { useRef, useState } from "react";
import { History, Search, Check, X } from "lucide-react";
import { Conversation } from "@/lib/api";

export function ConversationHistory({
  items,
  total,
  current,
  disabled,
  onSelect,
  onMore,
}: {
  items: Conversation[];
  total: number;
  current: string;
  disabled: boolean;
  onSelect: (id: string) => void;
  onMore: () => Promise<void>;
}) {
  const trigger = useRef<HTMLButtonElement>(null),
    panel = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false),
    [search, setSearch] = useState("");
  const [paging, setPaging] = useState(false);
  const [position, setPosition] = useState({ left: 16, bottom: 60 });
  function toggle() {
    const rect = trigger.current!.getBoundingClientRect();
    setPosition({
      left: Math.max(16, Math.min(rect.left, innerWidth - 336)),
      bottom: Math.max(16, innerHeight - rect.top + 8),
    });
    panel.current?.togglePopover();
  }
  return (
    <div className="source-history">
      <button
        ref={trigger}
        className="source-history-trigger"
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-haspopup="dialog"
        disabled={disabled}
      >
        <History size={16} />
        <span>历史对话</span>
        <small>{total}</small>
      </button>
      <div
        ref={panel}
        popover="auto"
        role="dialog"
        aria-label="历史对话"
        className="history-popover"
        style={position}
        onToggle={(e) => setOpen(e.newState === "open")}
      >
        <div className="history-heading">
          <strong>历史对话</strong>
          <button
            type="button"
            className="icon-button"
            aria-label="关闭历史对话"
            onClick={() => panel.current?.hidePopover()}
          >
            <X size={16} />
          </button>
        </div>
        <label className="history-search">
          <Search size={15} />
          <input
            aria-label="搜索历史对话"
            placeholder="搜索对话…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <div className="history-list">
          {items
            .filter((c) => c.title.toLowerCase().includes(search.toLowerCase()))
            .map((c) => (
              <button
                key={c.id}
                type="button"
                disabled={disabled}
                className={current === c.id ? "active" : ""}
                aria-current={current === c.id ? "true" : undefined}
                title={c.title}
                onClick={() => {
                  onSelect(c.id);
                  panel.current?.hidePopover();
                }}
              >
                <span>{c.title}</span>
                {current === c.id && <Check size={14} />}
              </button>
            ))}
          {!items.length && <p className="muted">还没有历史对话</p>}
          {!!items.length &&
            !items.some((c) =>
              c.title.toLowerCase().includes(search.toLowerCase()),
            ) && <p className="muted">没有匹配的对话</p>}
        </div>
        {items.length < total && (
          <button
            type="button"
            className="text-button history-more"
            disabled={paging}
            onClick={async () => {
              setPaging(true);
              try {
                await onMore();
              } finally {
                setPaging(false);
              }
            }}
          >
            {paging ? "正在加载…" : "加载更多历史"}
          </button>
        )}
      </div>
    </div>
  );
}
