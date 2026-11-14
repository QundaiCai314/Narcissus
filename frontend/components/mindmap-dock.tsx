"use client";
import { ReactNode } from "react";
import { GitBranch, Maximize2, Minimize2, X } from "lucide-react";

export function MindmapDock({ expanded, onExpand, onClose, children }: {
  expanded: boolean; onExpand: (value: boolean) => void;
  onClose: () => void; children: ReactNode;
}) {
  return <section className={`studio-panel mindmap-dock ${expanded ? "is-expanded" : ""}`}
    aria-label="思维导图工作区" onKeyDown={(event) => {
      if (event.key === "Escape" && expanded) { event.stopPropagation(); onExpand(false); }
    }}>
    <header className="mindmap-dock-heading">
      <div><GitBranch size={18} aria-hidden="true" /><h2>思维导图</h2></div>
      <div>
        <button className="icon-button" aria-label={expanded ? "收起导图视图" : "放大导图视图"}
          aria-pressed={expanded} onClick={() => onExpand(!expanded)}>
          {expanded ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
        </button>
        <button className="icon-button" aria-label="关闭导图，返回工作室" onClick={onClose}><X size={17} /></button>
      </div>
    </header>
    {children}
  </section>;
}
