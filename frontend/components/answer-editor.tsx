"use client";
import { useEffect, useRef, useState } from "react";
import { QuizImage } from "@/lib/learning";
import { MarkdownRenderer } from "./markdown-renderer";

const formulas = [
  ["行内公式", "x^{2}+y^{2}=1"],
  ["分数", "\\frac{a}{b}"],
  ["根号", "\\sqrt{x}"],
  ["上下标", "x_{n}^{2}"],
  ["积分", "\\int_{a}^{b} f(x)\\,dx"],
  ["求和", "\\sum_{i=1}^{n} x_i"],
  ["极限", "\\lim_{x\\to 0}\\frac{\\sin x}{x}"],
  ["矩阵", "\\begin{pmatrix}a & b \\\\ c & d\\end{pmatrix}"],
] as const;

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
  const textarea = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const [formulaOpen, setFormulaOpen] = useState(false);
  const [preview, setPreview] = useState(false);
  const [pending, setPending] = useState<{ file: File; key: string } | null>(
    null,
  );
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    onPendingChange(!!pending);
    return () => onPendingChange(false);
  }, [pending, onPendingChange]);

  function insertFormula(tex: string) {
    const start = textarea.current?.selectionStart ?? text.length;
    const end = textarea.current?.selectionEnd ?? start;
    const value = `$${tex}$`;
    if (text.length - (end - start) + value.length > 12000) {
      setNotice("加入公式后超过 12000 字，请先精简作答。");
      return;
    }
    onChange(text.slice(0, start) + value + text.slice(end));
    setPreview(true);
    setNotice("");
    requestAnimationFrame(() => {
      textarea.current?.focus();
      textarea.current?.setSelectionRange(start + 1, start + value.length - 1);
    });
  }
  async function upload(file: File, key = crypto.randomUUID()) {
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setNotice("请选择 JPG、PNG 或 WebP 图片。");
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      setNotice("每张图片不能超过 8 MB。");
      return;
    }
    setPending({ file, key });
    setUploading(true);
    setNotice("");
    try {
      if (await onUpload(file, key)) setPending(null);
      else setNotice("图片上传未完成，请重试。文字答案仍保留。");
    } finally {
      setUploading(false);
    }
  }
  const locked = disabled || submitted || uploading;
  return (
    <div className="exam-answer-editor">
      <div className="answer-editor-heading">
        <label htmlFor="written-answer">我的作答</label>
        <div className="answer-editor-actions">
          {!submitted && (
            <button
              type="button"
              className="button"
              disabled={locked}
              aria-expanded={formulaOpen}
              onClick={() => setFormulaOpen(!formulaOpen)}
            >
              插入公式
            </button>
          )}
          <button
            type="button"
            className="button"
            aria-pressed={preview}
            onClick={() => setPreview(!preview)}
          >
            {preview ? "收起预览" : "预览作答"}
          </button>
          {!submitted && (
            <button
              type="button"
              className="button"
              disabled={locked || images.length >= 4 || !!pending}
              onClick={() => picker.current?.click()}
            >
              {uploading ? "正在上传…" : "上传图片"}
            </button>
          )}
        </div>
      </div>
      {formulaOpen && !submitted && (
        <div className="answer-formulas">
          <div className="answer-formula-buttons" aria-label="常用公式模板">
            {formulas.map(([name, tex]) => (
              <button
                type="button"
                className="button"
                key={name}
                disabled={locked}
                onClick={() => insertFormula(tex)}
              >
                {name}
              </button>
            ))}
          </div>
          <p className="muted">
            点击模板插入当前位置，再修改字母、上下限或数字。行内公式用
            $…$；独立公式将 $$ 放在公式前后的单独一行。
          </p>
        </div>
      )}
      <label className="exam-written-answer" htmlFor="written-answer">
        <textarea
          id="written-answer"
          ref={textarea}
          aria-label="我的作答"
          value={text}
          maxLength={12000}
          rows={short ? 3 : 8}
          disabled={locked}
          onChange={(e) => onChange(e.target.value)}
          placeholder={
            short
              ? "按（1）（2）顺序填写各空答案，注意单位与精度"
              : "写出解题步骤，可插入公式或上传手写答案图片。"
          }
        />
        <small>{text.length} / 12000</small>
      </label>
      {(preview || submitted) && (
        <section className="answer-preview" aria-label="作答预览">
          <h4>作答预览</h4>
          {text.trim() ? (
            <MarkdownRenderer content={text} />
          ) : (
            <p className="muted">
              {images.length
                ? "本题以图片作答，见下方图片。"
                : "输入文字或插入公式后，在这里查看效果。"}
            </p>
          )}
        </section>
      )}
      {!submitted && (
        <>
          <input
            ref={picker}
            className="answer-file-input"
            type="file"
            aria-label="选择作答图片"
            accept="image/jpeg,image/png,image/webp"
            disabled={locked || images.length >= 4}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) void upload(file);
            }}
          />
          <p className="muted answer-image-help">
            支持 JPG、PNG、WebP，每张最多 8 MB，每题最多 4
            张。可直接拍照上传，交卷后结合参考答案自评。
          </p>
        </>
      )}
      {notice && <p role="alert">{notice}</p>}
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
            className="button"
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
                    className="button"
                    disabled={locked}
                    onClick={() => void onRemove(image.id)}
                    aria-label={`删除作答图片 ${i + 1}`}
                  >
                    删除
                  </button>
                )}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </div>
  );
}
