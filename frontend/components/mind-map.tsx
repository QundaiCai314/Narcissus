"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  LearningSet,
  LearningItem,
  LearningContext,
  OnCitation,
} from "@/lib/learning";
import { ReferenceList } from "./writing-view";

type Positioned = { node: LearningItem; x: number; y: number; height: number };
function overview(items: LearningItem[]) {
  const root = items.find((item) => !item.parent_id);
  return new Set(items.filter((item) => item.parent_id && item.parent_id !== root?.id).map((item) => item.id));
}
export function MindMap({
  row,
  onCitation,
  onAsk,
}: {
  row: LearningSet;
  onCitation: OnCitation;
  onAsk: (context: LearningContext, title: string) => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => overview(row.items || []));
  const [selected, setSelected] = useState(row.items?.[0]?.id || "");
  const [view, setView] = useState({ x: 20, y: 20, z: 1 });
  const viewport = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(
    null,
  );
  const layout = useMemo(() => {
    const all = row.items || [],
      children = new Map<string, LearningItem[]>();
    all.forEach((n) => {
      if (n.parent_id)
        children.set(n.parent_id, [...(children.get(n.parent_id) || []), n]);
    });
    const nodes: Positioned[] = [];
    const heights = new Map<string, number>();
    const height = (n: LearningItem) =>
      Math.max(76, Math.ceil((n.title || "").length / 12) * 24 + 30);
    function measure(n: LearningItem): number {
      const kids = collapsed.has(n.id) ? [] : children.get(n.id) || [];
      const h = Math.max(
        height(n),
        kids.reduce((sum, k) => sum + measure(k), 0) +
          Math.max(0, kids.length - 1) * 24,
      );
      heights.set(n.id, h);
      return h;
    }
    function place(n: LearningItem, depth: number, top: number) {
      const h = heights.get(n.id) || 76;
      nodes.push({
        node: n,
        x: 20 + depth * 292,
        y: top + h / 2 - height(n) / 2,
        height: height(n),
      });
      let offset = top;
      if (!collapsed.has(n.id))
        for (const c of children.get(n.id) || []) {
          place(c, depth + 1, offset);
          offset += (heights.get(c.id) || 76) + 24;
        }
    }
    const root = all.find((n) => !n.parent_id);
    if (root) {
      measure(root);
      place(root, 0, 20);
    }
    return {
      nodes,
      children,
      width: Math.max(280, ...nodes.map((n) => n.x + 240)),
      height: Math.max(180, ...nodes.map((n) => n.y + n.height + 20)),
    };
  }, [row.items, collapsed]);
  const fit = useCallback(() => {
    const w = viewport.current?.clientWidth || 0;
    if (!w) return;
    const z = Math.max(
      0.12,
      Math.min(1.2, (w - 24) / layout.width, 400 / layout.height),
    );
    setView({
      x: (w - layout.width * z) / 2,
      y: (430 - layout.height * z) / 2,
      z,
    });
  }, [layout.width, layout.height]);
  useEffect(() => {
    const target = viewport.current;
    if (!target) return;
    const observer = new ResizeObserver(fit);
    observer.observe(target);
    fit();
    return () => observer.disconnect();
  }, [fit]);
  useEffect(() => {
    const target = viewport.current;
    if (!target) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      const w = target.clientWidth;
      setView((v) => {
        const z = Math.max(
          0.12,
          Math.min(2.5, v.z * (e.deltaY < 0 ? 1.08 : 1 / 1.08)),
        );
        return {
          z,
          x: w / 2 - ((w / 2 - v.x) * z) / v.z,
          y: 215 - ((215 - v.y) * z) / v.z,
        };
      });
    };
    target.addEventListener("wheel", handler, { passive: false });
    return () => target.removeEventListener("wheel", handler);
  }, []);
  const node = (row.items || []).find((n) => n.id === selected);
  const trail: LearningItem[] = [];
  let ancestor = node;
  while (ancestor) {
    trail.unshift(ancestor);
    ancestor = row.items?.find((item) => item.id === ancestor?.parent_id);
  }
  const valid = row.sources.every((s) => s.state === "active");
  function focusNode(id: string) {
    setSelected(id);
    const item = layout.nodes.find((n) => n.node.id === id);
    if (item) setView({
      z: 1,
      x: (viewport.current?.clientWidth || 600) / 2 - item.x - 110,
      y: 215 - item.y - item.height / 2,
    });
  }
  function zoom(factor: number) {
    const w = viewport.current?.clientWidth || 600;
    setView((v) => {
      const z = Math.max(0.12, Math.min(2.5, v.z * factor));
      return {
        z,
        x: w / 2 - ((w / 2 - v.x) * z) / v.z,
        y: 215 - ((215 - v.y) * z) / v.z,
      };
    });
  }
  function toggleNode(id: string) {
    if (!collapsed.has(id)) {
      let current = node;
      while (current?.parent_id) {
        if (current.parent_id === id) {
          setSelected(id);
          break;
        }
        current = row.items?.find((item) => item.id === current?.parent_id);
      }
    }
    setCollapsed((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  return (
    <div className="learning-detail">
      <div className="learning-toolbar">
        <button
          className="button"
          onClick={() => zoom(1.2)}
          aria-label="放大导图"
        >
          ＋
        </button>
        <button
          className="button"
          onClick={() => zoom(1 / 1.2)}
          aria-label="缩小导图"
        >
          −
        </button>
        <button className="button" onClick={fit}>
          适应屏幕
        </button>
        <button className="button" onClick={() => focusNode(selected)}>
          实际大小
        </button>
        <button className="text-button" onClick={() => setCollapsed(new Set())}>
          展开全部
        </button>
        <button className="text-button" onClick={() => {
          setCollapsed(overview(row.items || []));
          setSelected(row.items?.find((item) => !item.parent_id)?.id || "");
        }}>
          章节总览
        </button>
        <span className="muted">
          {Math.round(view.z * 100)}% · 拖动画布移动
        </span>
      </div>
      <nav aria-label="当前知识点路径" className="learning-toolbar">
        {trail.map((item, index) => <span key={item.id}>
          {index > 0 && <span aria-hidden="true"> / </span>}
          <button className="text-button" onClick={() => focusNode(item.id)}>{item.title}</button>
        </span>)}
      </nav>
      <div className="mindmap-viewport" ref={viewport}>
        <svg
          width="100%"
          height="430"
          tabIndex={0}
          role="group"
          aria-label="知识导图画布"
          onKeyDown={(e) => {
            if (e.target !== e.currentTarget) return;
            if (e.key === "+") zoom(1.2);
            else if (e.key === "-") zoom(1 / 1.2);
            else if (
              ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(
                e.key,
              )
            ) {
              e.preventDefault();
              setView((v) => ({
                ...v,
                x:
                  v.x +
                  (e.key === "ArrowLeft"
                    ? 30
                    : e.key === "ArrowRight"
                      ? -30
                      : 0),
                y:
                  v.y +
                  (e.key === "ArrowUp" ? 30 : e.key === "ArrowDown" ? -30 : 0),
              }));
            }
          }}
          onPointerDown={(e) => {
            if ((e.target as Element).closest("button")) return;
            drag.current = {
              x: e.clientX,
              y: e.clientY,
              vx: view.x,
              vy: view.y,
            };
            e.currentTarget.setPointerCapture(e.pointerId);
          }}
          onPointerMove={(e) => {
            const d = drag.current;
            if (d)
              setView((v) => ({
                ...v,
                x: d.vx + e.clientX - d.x,
                y: d.vy + e.clientY - d.y,
              }));
          }}
          onPointerUp={() => (drag.current = null)}
          onPointerCancel={() => (drag.current = null)}
        >
          <g transform={`translate(${view.x},${view.y}) scale(${view.z})`}>
            {layout.nodes.map((n) => {
              const parent = layout.nodes.find(
                (p) => p.node.id === n.node.parent_id,
              );
              return parent ? (
                <path
                  key={"link" + n.node.id}
                  d={`M${parent.x + 220} ${parent.y + parent.height / 2} C${parent.x + 255} ${parent.y + parent.height / 2},${n.x - 35} ${n.y + n.height / 2},${n.x} ${n.y + n.height / 2}`}
                  fill="none"
                  stroke="#b0c7b5"
                  strokeWidth="2"
                />
              ) : null;
            })}
            {layout.nodes.map((n) => (
              <foreignObject
                key={n.node.id}
                x={n.x}
                y={n.y}
                width={220}
                height={n.height}
              >
                <div
                  className={
                    "mindmap-node " + (selected === n.node.id ? "selected" : "")
                  }
                  style={{ height: n.height - 2 }}
                >
                  <button
                    className="node-title"
                    onClick={() => focusNode(n.node.id)}
                  >
                    {n.node.title}
                  </button>
                  {layout.children.has(n.node.id) && (
                    <button
                      className="node-toggle"
                      aria-label={`${collapsed.has(n.node.id) ? "展开" : "折叠"}${n.node.title}`}
                      aria-expanded={!collapsed.has(n.node.id)}
                      onClick={() => toggleNode(n.node.id)}
                    >
                      {collapsed.has(n.node.id) ? "＋" : "−"}
                    </button>
                  )}
                </div>
              </foreignObject>
            ))}
          </g>
        </svg>
      </div>
      {node ? (
        <section className="learning-explanation">
          <span className="eyebrow">探索知识点</span>
          <h3>{node.title}</h3>
          <p>{node.explanation}</p>
          <button
            className="button primary"
            disabled={!valid}
            onClick={() =>
              onAsk(
                { set_id: row.id, node_id: node.id },
                node.title || "此知识点",
              )
            }
          >
            围绕此知识点提问
          </button>
          {!valid && (
            <p className="muted">资料已更新或删除，请生成新版后继续提问。</p>
          )}
          <ReferenceList
            citations={row.citations || []}
            content={node.refs.map((n) => `[${n}]`).join("")}
            onCitation={onCitation}
          />
        </section>
      ) : (
        <p>请选择一个知识点。</p>
      )}
    </div>
  );
}
