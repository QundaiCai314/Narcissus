"use client";
import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Bold, Italic, ImagePlus, Smile, X, Upload } from "lucide-react";
import { QuizImage } from "@/lib/learning";
import { answerFormulas, FormulaRange } from "@/lib/formula-templates";
import { MarkdownRenderer } from "./markdown-renderer";
const FormulaPicker = dynamic(
  () => import("./formula-picker").then((m) => m.FormulaPicker),
  { ssr: false, loading: () => <p role="status">正在载入公式面板…</p> },
);
const emojis = [
  "🙂",
  "😊",
  "👍",
  "✅",
  "⭐",
  "💡",
  "❓",
  "📌",
  "🎯",
  "🎉",
  "✍️",
  "🔍",
];
type FormulaSession = FormulaRange & { original: string; editing: boolean };
export function AnswerEditor({
  text,
  images,
  disabled,
  submitted,
  short,
  onChange,
  onUpload,
  onRemove,
  onPendingChange,
}: {
  text: string;
  images: QuizImage[];
  disabled: boolean;
  submitted: boolean;
  short: boolean;
  onChange: (value: string) => void;
  onUpload: (file: File, requestKey: string) => Promise<boolean>;
  onRemove: (id: string) => Promise<boolean>;
  onPendingChange: (pending: boolean) => void;
}) {
  const textarea = useRef<HTMLTextAreaElement>(null),
    picker = useRef<HTMLInputElement>(null);
  const selection = useRef({ start: text.length, end: text.length }),
    uploadInFlight = useRef(false);
  const [formula, setFormula] = useState<FormulaSession | null>(null),
    [formulaDirty, setFormulaDirty] = useState(false);
  const [palette, setPalette] = useState<"emoji" | "image" | null>(null),
    [preview, setPreview] = useState(false);
  const [pending, setPending] = useState<{ file: File; key: string } | null>(
    null,
  );
  const [uploading, setUploading] = useState(false),
    [dragging, setDragging] = useState(false),
    [notice, setNotice] = useState("");
  const locked = disabled || submitted || uploading;
  useEffect(() => {
    onPendingChange(!!pending || formulaDirty);
    return () => onPendingChange(false);
  }, [pending, formulaDirty, onPendingChange]);
  function rememberSelection() {
    if (textarea.current)
      selection.current = {
        start: textarea.current.selectionStart,
        end: textarea.current.selectionEnd,
      };
  }
  function replace(start: number, end: number, value: string) {
    if (text.length - (end - start) + value.length > 12000) {
      setNotice("加入内容后超过 12000 字，请先精简作答。");
      return false;
    }
    onChange(text.slice(0, start) + value + text.slice(end));
    selection.current = {
      start: start + value.length,
      end: start + value.length,
    };
    setNotice("");
    return true;
  }
  function insertText(value: string, wrap = false) {
    const { start, end } = selection.current;
    if (
      replace(
        start,
        end,
        wrap ? value + (text.slice(start, end) || "文字") + value : value,
      )
    ) {
      setPreview(false);
      setPalette(null);
      requestAnimationFrame(() => {
        textarea.current?.focus();
        textarea.current?.setSelectionRange(
          selection.current.start,
          selection.current.end,
        );
      });
    }
  }
  function openFormula(range?: FormulaRange) {
    if (locked) return;
    const { start, end } = selection.current;
    const existing =
      range ||
      answerFormulas(text).find((r) =>
        (start > r.start && start < r.end && end <= r.end) ||
        (start === r.start && end === r.end),
      );
    setFormula(
      existing
        ? {
            ...existing,
            original: text.slice(existing.start, existing.end),
            editing: true,
          }
        : {
            start,
            end,
            original: text.slice(start, end),
            latex: "",
            display: false,
            editing: false,
          },
    );
    setPalette(null);
    setFormulaDirty(false);
  }
  function closeFormula() {
    setFormula(null);
    setFormulaDirty(false);
  }
  async function upload(file: File, key = crypto.randomUUID()) {
    if (locked || uploadInFlight.current || images.length >= 4) {
      setNotice(
        images.length >= 4 ? "每题最多上传 4 张图片。" : "请等待当前操作完成。",
      );
      return;
    }
    if (pending && pending.key !== key) {
      setNotice("请先重试或取消待上传的图片。");
      return;
    }
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setNotice("请选择 JPG、PNG 或 WebP 图片。");
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      setNotice("每张图片不能超过 8 MB。");
      return;
    }
    uploadInFlight.current = true;
    setPending({ file, key });
    setUploading(true);
    setNotice("");
    setPalette(null);
    try {
      if (await onUpload(file, key)) setPending(null);
      else setNotice("图片上传未完成，请重试。文字答案仍保留。");
    } catch {
      setNotice("图片上传未完成，请重试。文字答案仍保留。");
    } finally {
      uploadInFlight.current = false;
      setUploading(false);
    }
  }
  function acceptFiles(files: File[]) {
    if (files.length !== 1) {
      setNotice("请每次上传一张图片，每题最多 4 张。");
      return;
    }
    void upload(files[0]);
  }
  return (
    <div
      className={`exam-answer-editor forum-composer${dragging ? " is-dragging" : ""}`}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("Files")) {
          e.preventDefault();
          if (!locked) setDragging(true);
        }
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null))
          setDragging(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (!locked) acceptFiles(Array.from(e.dataTransfer.files));
      }}
      onPaste={(e) => {
        if (formula || locked) return;
        const files = Array.from(e.clipboardData.files);
        if (files.length) {
          e.preventDefault();
          acceptFiles(files);
        }
      }}
    >
      <div className="answer-editor-heading">
        <label htmlFor="written-answer">我的作答</label>
        <small>{submitted ? "已交卷" : "文字 · 公式 · 手写图片"}</small>
      </div>
      <div className="compose-surface">
        <div className="compose-toolbar">
          <div className="compose-tools" aria-label="作答工具栏">
            <button
              type="button"
              className="compose-icon"
              title="加粗"
              aria-label="加粗"
              disabled={locked || !!formula}
              onClick={() => insertText("**", true)}
            >
              <Bold size={17} />
            </button>
            <button
              type="button"
              className="compose-icon"
              title="斜体"
              aria-label="斜体"
              disabled={locked || !!formula}
              onClick={() => insertText("*", true)}
            >
              <Italic size={17} />
            </button>
            <span className="compose-divider" />
            <button
              type="button"
              className="compose-icon compose-formula-icon"
              title="插入或编辑公式"
              aria-label="插入公式"
              aria-expanded={!!formula}
              disabled={locked}
              onClick={() => (formula ? closeFormula() : openFormula())}
            >
              ƒ<span>(x)</span>
            </button>
            <button
              type="button"
              className="compose-icon"
              title="表情"
              aria-label="插入表情"
              aria-expanded={palette === "emoji"}
              disabled={locked || !!formula}
              onClick={() => setPalette(palette === "emoji" ? null : "emoji")}
            >
              <Smile size={18} />
            </button>
            <button
              type="button"
              className="compose-icon"
              title="上传图片，也可拖入或粘贴截图"
              aria-label="上传图片"
              aria-expanded={palette === "image"}
              disabled={locked || !!formula || images.length >= 4 || !!pending}
              onClick={() => setPalette(palette === "image" ? null : "image")}
            >
              <ImagePlus size={18} />
            </button>
          </div>
          <div className="compose-tabs" aria-label="作答显示方式">
            <button
              type="button"
              disabled={submitted}
              aria-pressed={!preview && !submitted}
              onClick={() => setPreview(false)}
            >
              编辑
            </button>
            <button
              type="button"
              aria-pressed={preview || submitted}
              onClick={() => setPreview(true)}
            >
              预览
            </button>
          </div>
        </div>
        {palette && (
          <div
            className={palette === "image" ? "compose-image-strip" : "compose-palette"}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                e.stopPropagation();
                setPalette(null);
              }
            }}
          >
            {palette === "emoji" && <div className="compose-palette-heading">
              <span>表情</span>
              <button
                type="button"
                className="compose-icon"
                aria-label="关闭工具面板"
                onClick={() => setPalette(null)}
              >
                <X size={16} />
              </button>
            </div>}
            {palette === "emoji" ? (
              <div className="emoji-grid">
                {emojis.map((emoji) => (
                  <button
                    key={emoji}
                    type="button"
                    onClick={() => insertText(emoji)}
                    aria-label={`插入 ${emoji}`}
                  >
                    {emoji}
                  </button>
                ))}
              </div>
            ) : (
              <div className="image-upload-panel">
                <button
                  type="button"
                  className="image-upload-action"
                  onClick={() => picker.current?.click()}
                >
                  <Upload size={16} />
                  选择图片
                </button>
                <div className="image-upload-copy">
                  <p>也可拖入图片，或直接粘贴截图</p>
                  <small>JPG / PNG / WebP · 单张 ≤ 8 MB · 最多 4 张</small>
                </div>
                <button type="button" className="compose-icon" aria-label="关闭工具面板" onClick={() => setPalette(null)}><X size={16} /></button>
              </div>
            )}
          </div>
        )}
        {formula && (
          <FormulaPicker
            initial={formula.latex}
            initialDisplay={formula.display}
            editing={formula.editing}
            onDirty={setFormulaDirty}
            onClose={closeFormula}
            onInsert={(latex, display) => {
              if (locked) {
                setNotice("请等待当前操作完成。");
                return false;
              }
              if (text.slice(formula.start, formula.end) !== formula.original) {
                setNotice("作答内容已更新，请重新选择公式位置。");
                return false;
              }
              const ok = replace(
                formula.start,
                formula.end,
                display ? `\n$$\n${latex}\n$$\n` : `$${latex}$`,
              );
              if (ok) setPreview(true);
              return ok;
            }}
          />
        )}
        <label
          className="exam-written-answer"
          htmlFor="written-answer"
          hidden={preview || submitted}
        >
          <textarea
            id="written-answer"
            ref={textarea}
            aria-label="我的作答"
            value={text}
            maxLength={12000}
            rows={short ? 3 : 8}
            disabled={locked}
            readOnly={!!formula}
            onSelect={rememberSelection}
            onBlur={rememberSelection}
            onChange={(e) => onChange(e.target.value)}
            placeholder={
              short
                ? "按（1）（2）顺序填写各空答案，注意单位与精度"
                : "写出解题步骤，或拖入、粘贴手写答案图片…"
            }
          />
        </label>
        {(preview || submitted) && (
          <section
            className="answer-preview"
            aria-label="作答预览"
            onDoubleClick={(e) => {
              if (submitted || formula) return;
              const hit = (e.target as HTMLElement).closest(".katex, .md-math-inline, .md-math-block");
              const target = hit?.matches(".katex") ? hit : hit?.querySelector(".katex");
              if (!target) return;
              const index = Array.from(
                e.currentTarget.querySelectorAll(".katex"),
              ).indexOf(target);
              const range = answerFormulas(text)[index];
              if (range) openFormula(range);
            }}
          >
            {text.trim() ? (
              <MarkdownRenderer content={text} />
            ) : (
              <p className="muted">
                {images.length
                  ? "本题以图片作答，见下方图片。"
                  : "输入文字或插入公式后，在这里查看效果。"}
              </p>
            )}
            {!submitted && answerFormulas(text).length > 0 && (
              <details className="answer-edit-formulas">
                <summary>修改已插入的公式</summary>
                {answerFormulas(text).map((r, i) => (
                  <button
                    type="button"
                    className="text-button"
                    key={r.start}
                    disabled={locked || !!formula}
                    onClick={() => openFormula(r)}
                  >
                    编辑公式 {i + 1}
                  </button>
                ))}
              </details>
            )}
          </section>
        )}
        {!!images.length && (
          <div className="answer-images">
            {images.map((image, i) => (
              <figure key={image.id}>
                <a
                  href={image.url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={`查看作答图片 ${i + 1} 原图`}
                >
                  <img
                    src={image.url}
                    width={image.width}
                    height={image.height}
                    alt={`作答图片 ${i + 1}`}
                  />
                </a>
                <figcaption>
                  <a href={image.url} target="_blank" rel="noreferrer">
                    图片 {i + 1} · 查看大图
                  </a>
                  {!submitted && (
                    <button
                      type="button"
                      className="compose-icon"
                      disabled={locked || !!formula}
                      onClick={() => void onRemove(image.id)}
                      aria-label={`删除作答图片 ${i + 1}`}
                    >
                      <X size={15} />
                    </button>
                  )}
                </figcaption>
              </figure>
            ))}
          </div>
        )}
        <div className="compose-status">
          <span role="status">
            {uploading
              ? "正在上传图片…"
              : dragging
                ? "松开即可上传图片"
                : `${images.length} / 4 张图片`}
          </span>
          <span>{text.length} / 12000</span>
        </div>
      </div>
      {!submitted && (
        <input
          ref={picker}
          className="answer-file-input"
          type="file"
          aria-label="选择作答图片"
          accept="image/jpeg,image/png,image/webp"
          disabled={locked || images.length >= 4 || !!pending}
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) void upload(file);
          }}
        />
      )}
      {notice && (
        <p className="compose-error" role="alert">
          {notice}
        </p>
      )}
      {pending && !uploading && (
        <div className="answer-upload-retry">
          <span>待上传：{pending.file.name}</span>
          <button
            type="button"
            className="button"
            disabled={locked}
            onClick={() => void upload(pending.file, pending.key)}
          >
            重试上传
          </button>
          <button
            type="button"
            className="text-button"
            disabled={locked}
            onClick={() => {
              setPending(null);
              setNotice("");
            }}
          >
            取消上传
          </button>
        </div>
      )}
    </div>
  );
}
