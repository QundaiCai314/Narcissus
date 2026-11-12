"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import type { MathfieldElement } from "mathlive";
import katex from "katex";
import { Search, X } from "lucide-react";
import {
  formulaCategories,
  formulaTemplates,
  FormulaTemplate,
} from "@/lib/formula-templates";

function preview(latex: string) {
  return katex.renderToString(
    latex.replace(/\\placeholder(?:\[[^\]]*\])?\{\}/g, "\\square"),
    { displayMode: true, throwOnError: false, trust: false },
  );
}
export function FormulaPicker({
  initial,
  initialDisplay,
  editing,
  onInsert,
  onClose,
  onDirty,
}: {
  initial: string;
  initialDisplay: boolean;
  editing: boolean;
  onInsert: (latex: string, display: boolean) => boolean;
  onClose: () => void;
  onDirty: (dirty: boolean) => void;
}) {
  const root = useRef<HTMLDivElement>(null),
    host = useRef<HTMLDivElement>(null),
    field = useRef<MathfieldElement | null>(null);
  const [latex, setLatex] = useState(initial),
    [display, setDisplay] = useState(initialDisplay),
    [mode, setMode] = useState<"visual" | "latex">("visual");
  const [category, setCategory] = useState("分式"),
    [query, setQuery] = useState(""),
    [recent, setRecent] = useState<string[]>([]),
    [ready, setReady] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    try {
      const ids = JSON.parse(
        localStorage.getItem("narcissus.formula-recents") || "[]",
      );
      if (Array.isArray(ids))
        setRecent(ids.filter((x) => typeof x === "string").slice(0, 18));
    } catch {}
  }, []);
  useEffect(() => {
    onDirty(latex !== initial || display !== initialDisplay);
    return () => onDirty(false);
  }, [latex, display, initial, initialDisplay, onDirty]);
  useEffect(() => {
    let disposed = false;
    let cleanup = () => {};
    import("mathlive")
      .then(({ MathfieldElement }) => {
        if (disposed || !host.current) return;
        MathfieldElement.fontsDirectory = "/mathlive/fonts";
        MathfieldElement.soundsDirectory = null;
        MathfieldElement.locale = "zh-cn";
        MathfieldElement.computeEngine = null;
        const mf = new MathfieldElement();
        mf.mathVirtualKeyboardPolicy = "manual";
        mf.setAttribute("aria-label", "可视化公式");
        mf.value = initial;
        const input = () => setLatex(mf.getValue("latex"));
        mf.addEventListener("input", input);
        host.current.append(mf);
        mf.menuItems = [];
        field.current = mf;
        const previous = window.mathVirtualKeyboard.container;
        window.mathVirtualKeyboard.container = root.current;
        cleanup = () => {
          window.mathVirtualKeyboard.hide();
          window.mathVirtualKeyboard.container = previous;
          mf.removeEventListener("input", input);
          mf.remove();
          field.current = null;
        };
        setReady(true);
      })
      .catch(() =>
        setError("可视化编辑器加载失败，可切换 LaTeX 输入，或重新打开。"),
      );
    return () => {
      disposed = true;
      cleanup();
    };
  }, [initial]);
  const templates = useMemo(
    () =>
      formulaTemplates.filter((t) =>
        query.trim()
          ? `${t.label} ${t.category} ${t.latex}`
              .toLowerCase()
              .includes(query.trim().toLowerCase())
          : category === "最近使用"
            ? recent.includes(t.id)
            : t.category === category,
      ),
    [query, category, recent],
  );
  function choose(template: FormulaTemplate) {
    if (!field.current) return;
    if (mode === "latex") field.current.value = latex;
    field.current.insert(template.latex, {
      insertionMode: "replaceSelection",
      selectionMode: "placeholder",
      focus: true,
      format: "latex",
    });
    setLatex(field.current.getValue("latex"));
    setMode("visual");
    setError("");
    const next = [
      template.id,
      ...recent.filter((x) => x !== template.id),
    ].slice(0, 18);
    setRecent(next);
    try {
      localStorage.setItem("narcissus.formula-recents", JSON.stringify(next));
    } catch {}
  }
  function insert() {
    let value = latex.trim();
    if (!value) {
      setError("请先填写公式。");
      return;
    }
    if (/\\placeholder(?:\[[^\]]*\])?\{\s*\}/.test(value)) {
      setError("还有空白占位框，请填写后再插入。");
      return;
    }
    if (value.length > 6000) {
      setError("公式过长，请拆分为多个公式。");
      return;
    }
    try {
      katex.renderToString(value, { throwOnError: true, trust: false });
    } catch {
      setError("公式暂时无法排版，请检查括号和 LaTeX 命令。");
      return;
    }
    if (onInsert(value, display)) onClose();
  }
  return (
    <div
      ref={root}
      className="formula-picker"
      role="dialog"
      aria-label={editing ? "编辑公式" : "插入公式"}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          onClose();
        }
      }}
    >
      <div className="formula-picker-heading">
        <strong>{editing ? "编辑公式" : "公式"}</strong>
        <label>
          <Search size={16} />
          <input
            aria-label="搜索公式或符号"
            placeholder="搜索公式或符号"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="compose-icon"
          aria-label="关闭公式面板"
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </div>
      <div className="formula-browser">
        <nav aria-label="公式分类">
          {formulaCategories.map((name) => (
            <button
              type="button"
              key={name}
              aria-pressed={category === name && !query}
              onClick={() => {
                setCategory(name);
                setQuery("");
              }}
            >
              {name}
            </button>
          ))}
        </nav>
        <div className="formula-templates">
          <p>{query ? "搜索结果" : category}</p>
          <div className="formula-grid">
            {templates.map((t) => (
              <button
                type="button"
                key={t.id}
                disabled={!ready}
                aria-label={t.label}
                title={t.label}
                onClick={() => choose(t)}
              >
                <span
                  aria-hidden="true"
                  dangerouslySetInnerHTML={{ __html: preview(t.latex) }}
                />
                <small>{t.label}</small>
              </button>
            ))}
          </div>
          {!templates.length && (
            <p className="muted">
              {category === "最近使用" && !query
                ? "使用过的结构会保存在这里。"
                : "没有匹配的公式或符号。"}
            </p>
          )}
        </div>
      </div>
      <div className="formula-draft">
        <div className="compose-tabs" aria-label="公式输入方式">
          <button
            type="button"
            aria-pressed={mode === "visual"}
            onClick={() => {
              if (field.current) field.current.value = latex;
              setMode("visual");
            }}
          >
            可视化
          </button>
          <button
            type="button"
            aria-pressed={mode === "latex"}
            onClick={() => setMode("latex")}
          >
            LaTeX
          </button>
        </div>
        <div
          ref={host}
          hidden={mode !== "visual"}
          className="formula-mathfield"
        />
        {!ready && mode === "visual" && (
          <p role="status">正在载入公式编辑器…</p>
        )}
        {mode === "latex" && (
          <>
            <textarea
              aria-label="LaTeX 公式"
              value={latex}
              maxLength={6000}
              rows={3}
              onChange={(e) => {
                setLatex(e.target.value);
                setError("");
              }}
            />
            <div
              className="formula-live-preview"
              aria-label="公式预览"
              dangerouslySetInnerHTML={{ __html: preview(latex) }}
            />
          </>
        )}
        <p className="muted">
          点击空格填写 · Tab 切换位置 · 可继续点选结构组成嵌套公式
        </p>
        {error && (
          <p className="compose-error" role="alert">
            {error}
          </p>
        )}
        <div className="formula-footer">
          <div>
            <label>
              <input
                type="radio"
                name="formula-layout"
                checked={!display}
                onChange={() => setDisplay(false)}
              />
              行内公式
            </label>
            <label>
              <input
                type="radio"
                name="formula-layout"
                checked={display}
                onChange={() => setDisplay(true)}
              />
              独立公式
            </label>
          </div>
          <button type="button" className="text-button" onClick={onClose}>
            取消
          </button>
          <button type="button" className="button primary" onClick={insert}>
            {editing ? "更新公式" : "插入公式"}
          </button>
        </div>
      </div>
    </div>
  );
}
