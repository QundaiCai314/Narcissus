"use client";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import {
  api,
  post,
  request,
  errorText,
  ApiError,
  Writing,
  Citation,
  Document,
  Page,
} from "@/lib/api";
import { ReferenceList, WritingView } from "./writing-view";

type EditorHandle = { save: () => Promise<boolean> };
const activeJob = (w: Writing) =>
  ["queued", "running"].includes(w.job?.status || "");

export function WritingPanel({
  notebookId,
  kind,
  docs,
  selectedId,
  onSelect,
  onCitation,
  studioRequest,
}: {
  notebookId: string;
  kind: "note" | "summary";
  docs: Document[];
  selectedId: string;
  onSelect: (id: string) => void;
  onCitation: (c: Citation) => void;
  studioRequest?: { key: number; id?: string; documentIds?: string[] };
}) {
  const [items, setItems] = useState<Writing[]>([]),
    [total, setTotal] = useState(0),
    [row, setRow] = useState<Writing | null>(null),
    [error, setError] = useState(""),
    [creating, setCreating] = useState(false);
  const [form, setForm] = useState(false),
    [noteOptions, setNoteOptions] = useState<Writing[]>([]);
  const [docIds, setDocIds] = useState<string[]>([]),
    [noteIds, setNoteIds] = useState<string[]>([]);
  const [purpose, setPurpose] = useState(""),
    [audience, setAudience] = useState(""),
    [length, setLength] = useState("medium"),
    [title, setTitle] = useState("资料总结");
  const editor = useRef<EditorHandle>(null);
  const handledRequest = useRef(0);
  useEffect(() => {
    if (!studioRequest || studioRequest.key === handledRequest.current) return;
    handledRequest.current = studioRequest.key;
    if (studioRequest.id) void select(studioRequest.id);
    else void create(studioRequest.documentIds);
  }, [studioRequest]);
  const load = useCallback(async () => {
    const p = await api<Page<Writing>>(
      `/notebooks/${notebookId}/writings?kind=${kind}&limit=100`,
    );
    setItems(p.items);
    setTotal(p.total);
  }, [notebookId, kind]);
  useEffect(() => {
    load().catch((e) => setError(errorText(e)));
  }, [load]);
  useEffect(() => {
    let current = true;
    async function switchDocument() {
      if (editor.current && !(await editor.current.save())) { if(current) onSelect(row?.id || ""); return; }
      if(!current) return;
      setRow(null);
      load().catch((e) => setError(errorText(e)));
      if(selectedId) try { const next = await api<Writing>(`/writings/${selectedId}`); if(current) setRow(next); } catch(e) { if(current) setError(errorText(e)); }
    }
    switchDocument();
    return () => {
      current = false;
    };
  }, [selectedId]);
  useEffect(() => {
    if (!row || !activeJob(row)) return;
    let current = true;
    const timer = setInterval(async () => {
      try {
        const value = await api<Writing>(`/writings/${row.id}`);
        if (current) {
          setRow(value);
          if (!activeJob(value)) load();
        }
      } catch (e) {
        if (current) setError(errorText(e));
      }
    }, 2500);
    return () => {
      current = false;
      clearInterval(timer);
    };
  }, [row?.id, row?.job?.status, load]);
  async function select(id: string) {
    if (editor.current && !(await editor.current.save())) return;
    setError("");
    onSelect(id);
    setForm(false);
  }
  async function create(documentIds?: string[]) {
    if (editor.current && !(await editor.current.save())) return;
    if (kind === "summary") {
      try {
        let offset = 0,
          all: Writing[] = [];
        while (true) {
          const p = await api<Page<Writing>>(
            `/notebooks/${notebookId}/writings?limit=100&offset=${offset}`,
          );
          all = all.concat(p.items);
          offset += p.items.length;
          if (offset >= p.total || !p.items.length) break;
        }
        setNoteOptions(all.filter((w) => w.kind !== "guide" && !activeJob(w)));
        setDocIds(docs.filter((d) => d.status === "ready" && (!documentIds || documentIds.includes(d.id))).map((d) => d.id));
        setNoteIds([]);
        setForm(true);
      } catch (e) {
        setError(errorText(e));
      }
      return;
    }
    try {
      setCreating(true);
      const value = await api<Writing>(
        `/notebooks/${notebookId}/notes`,
        post({ title: "未命名笔记" }),
      );
      await load();
      onSelect(value.id);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setCreating(false);
    }
  }
  async function generate() {
    try {
      setCreating(true);
      setError("");
      const value = await api<Writing>(
        `/notebooks/${notebookId}/summaries`,
        post({
          title,
          document_ids: docIds,
          note_ids: noteIds,
          purpose,
          audience,
          length,
        }),
      );
      setForm(false);
      onSelect(value.id);
      setRow(value);
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setCreating(false);
    }
  }
  async function remove() {
    if (
      !row ||
      !window.confirm(`删除“${row.title}”？引用它的总结会保留历史快照。`)
    )
      return;
    try {
      await api(`/writings/${row.id}`, { method: "DELETE" });
      setRow(null);
      onSelect("");
      await load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <section className="writing-area">
      <div className="writing-heading">
        <h2>{kind === "note" ? "我的笔记" : "结构化总结"}</h2>
        <button className="button" onClick={() => create()} disabled={creating}>
          {kind === "note" ? "＋ 新建笔记" : "＋ 生成总结"}
        </button>
      </div>
      {error && (
        <p role="alert" className="message-error writing-error">
          {error}
        </p>
      )}
      <div className="writing-library">
        <label>
          {kind === "note" ? "笔记" : "总结"}
          <select
            aria-label={kind === "note" ? "选择笔记" : "选择总结"}
            value={selectedId}
            onChange={(e) => select(e.target.value)}
          >
            <option value="">按最近更新查看</option>
            {items.map((w) => (
              <option key={w.id} value={w.id}>
                {w.title}
                {activeJob(w) ? " · 生成中" : ""}
              </option>
            ))}
          </select>
        </label>
        <span className="muted">{total} 篇</span>
        {items.length < total && (
          <button
            onClick={async () => {
              try {
                const p = await api<Page<Writing>>(
                  `/notebooks/${notebookId}/writings?kind=${kind}&limit=100&offset=${items.length}`,
                );
                setItems((v) => [...v, ...p.items]);
              } catch (e) {
                setError(errorText(e));
              }
            }}
          >
            更多
          </button>
        )}
      </div>
      {form ? (
        <div className="writing-scroll summary-form">
          <h3>选择这次总结的依据</h3>
          <label>
            总结标题
            <input
              value={title}
              maxLength={120}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <fieldset>
            <legend>原始资料</legend>
            {docs
              .filter((d) => d.status === "ready")
              .map((d) => (
                <label className="source-option" key={d.id}>
                  <input
                    type="checkbox"
                    checked={docIds.includes(d.id)}
                    onChange={(e) =>
                      setDocIds((v) =>
                        e.target.checked
                          ? [...v, d.id]
                          : v.filter((x) => x !== d.id),
                      )
                    }
                  />
                  {d.filename}
                </label>
              ))}
            {!docs.some((d) => d.status === "ready") && (
              <p className="muted">还没有可用资料，可单独选择笔记。</p>
            )}
          </fieldset>
          <fieldset>
            <legend>用户笔记 / 已有总结（最多 20 篇）</legend>
            {noteOptions.map((n) => (
              <label className="source-option" key={n.id}>
                <input
                  type="checkbox"
                  checked={noteIds.includes(n.id)}
                  disabled={!noteIds.includes(n.id) && noteIds.length >= 20}
                  onChange={(e) =>
                    setNoteIds((v) =>
                      e.target.checked
                        ? [...v, n.id]
                        : v.filter((x) => x !== n.id),
                    )
                  }
                />
                {n.title}
              </label>
            ))}
          </fieldset>
          <label>
            用途
            <textarea
              value={purpose}
              maxLength={500}
              rows={2}
              placeholder="例如：准备项目评审，重点比较预算与风险"
              onChange={(e) => setPurpose(e.target.value)}
            />
          </label>
          <label>
            读者
            <input
              value={audience}
              maxLength={200}
              placeholder="例如：项目负责人"
              onChange={(e) => setAudience(e.target.value)}
            />
          </label>
          <label>
            篇幅
            <select value={length} onChange={(e) => setLength(e.target.value)}>
              <option value="short">简短 · 约 300 字</option>
              <option value="medium">适中 · 约 800 字</option>
              <option value="long">详细 · 约 1500 字</option>
            </select>
          </label>
          <p className="muted">
            用户笔记中的观点会单独标明。资料冲突与依据不足会保留在总结中。
          </p>
          <button
            className="button primary"
            disabled={
              creating || !title.trim() || (!docIds.length && !noteIds.length)
            }
            onClick={generate}
          >
            {creating ? "正在提交…" : "开始生成"}
          </button>
          <button className="text-button" onClick={() => setForm(false)}>
            取消
          </button>
        </div>
      ) : row ? (
        <>
          {activeJob(row) ? (
            <div className="writing-scroll">
              <h3>{row.title}</h3>
              <p role="status">
                {row.job?.status === "queued"
                  ? "等待生成…"
                  : "正在阅读来源并整理总结…"}
              </p>
              <p className="muted">可以切换页面，完成后会保存在这里。</p>
              <button className="text-button" onClick={remove}>
                取消并删除这份总结
              </button>
            </div>
          ) : (
            <>
              {row.job && ["failed", "cancelled"].includes(row.job.status) && (
                <div className="generation-status">
                  <p role="alert">{row.job.error}</p>
                  <button
                    className="button"
                    onClick={async () => {
                      try {
                        setRow(
                          await api<Writing>(
                            `/writings/${row.id}/retry`,
                            post(),
                          ),
                        );
                      } catch (e) {
                        setError(errorText(e));
                      }
                    }}
                  >
                    重试生成
                  </button>
                </div>
              )}
              <WritingEditor
                key={row.id}
                ref={editor}
                initial={row}
                onCitation={onCitation}
                onSaved={load}
                onDelete={remove}
              />
            </>
          )}
        </>
      ) : (
        <div className="writing-scroll writing-empty">
          <h3>
            {kind === "note"
              ? "把值得留下的思考，写在这里。"
              : "将资料与思考整理成一篇总结。"}
          </h3>
          <p>
            {kind === "note"
              ? "手动创建笔记，或在回答下点击“保存为笔记”。"
              : "选择资料和笔记，按用途生成可编辑、可导出的总结。"}
          </p>
        </div>
      )}
    </section>
  );
}

const WritingEditor = forwardRef<
  EditorHandle,
  {
    initial: Writing;
    onCitation: (c: Citation) => void;
    onSaved: () => Promise<void>;
    onDelete: () => void;
  }
>(function WritingEditor({ initial, onCitation, onSaved, onDelete }, ref) {
  const [row, setRow] = useState(initial),
    [title, setTitle] = useState(initial.title),
    [content, setContent] = useState(initial.content);
  const [status, setStatus] = useState("已保存"),
    [error, setError] = useState(""),
    [conflict, setConflict] = useState<Writing | null>(null),
    [preview, setPreview] = useState(false);
  const current = useRef(initial),
    draft = useRef({ title: initial.title, content: initial.content }),
    dirty = useRef(false),
    failure = useRef(false),
    saving = useRef<Promise<boolean> | null>(null);
  const save = useCallback(async (): Promise<boolean> => {
    if (saving.current) return saving.current;
    if (failure.current) return false;
    if (!dirty.current) return true;
    const work = async () => {
      while (dirty.current) {
        const sent = { ...draft.current };
        setStatus("保存中…");
        try {
          const next = await api<Writing>(`/writings/${current.current.id}`, {
            method: "PATCH",
            body: JSON.stringify({ ...sent, version: current.current.version }),
          });
          current.current = next;
          setRow(next);
          dirty.current =
            sent.title !== draft.current.title ||
            sent.content !== draft.current.content;
          setStatus(dirty.current ? "保存中…" : "已保存");
          setError("");
        } catch (e) {
          failure.current = true;
          setStatus("保存失败");
          setError(errorText(e));
          if (e instanceof ApiError && e.status === 409) {
            try {
              setConflict(
                await api<Writing>(`/writings/${current.current.id}`),
              );
            } catch {}
          }
          return false;
        }
      }
      onSaved().catch(() => {});
      return true;
    };
    saving.current = work();
    try {
      return await saving.current;
    } finally {
      saving.current = null;
    }
  }, [onSaved]);
  useEffect(() => {
    return () => {
      if (dirty.current) {
        void save();
      }
    };
  }, [save]);
  useEffect(() => {
    let alive = true;
    const updateCitations = async () => {
      try {
        const next = await api<Writing>(`/writings/${initial.id}`);
        if (alive) setRow(previous => ({ ...previous, citations: next.citations }));
      } catch {}
    };
    const timer = setInterval(() => {
      if (!document.hidden) void updateCitations();
    }, 20000);
    const onFocus = () => { if (!document.hidden) void updateCitations(); };
    window.addEventListener("focus", onFocus);
    return () => {
      alive = false;
      clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [initial.id]);
  useEffect(() => {
    const timer = setTimeout(() => {
      if (dirty.current) save();
    }, 700);
    return () => clearTimeout(timer);
  }, [title, content, save]);
  useEffect(() => {
    const unload = (e: BeforeUnloadEvent) => {
      if (dirty.current) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    const navigate = (e: MouseEvent) => {
      const target = (e.target as HTMLElement).closest("a");
      if (
        dirty.current &&
        target &&
        target.target !== "_blank" &&
        !target.hasAttribute("download")
      ) {
        e.preventDefault();
        e.stopPropagation();
        save().then((ok) => {
          if (ok) window.location.assign(target.href);
        });
      }
    };
    window.addEventListener("beforeunload", unload);
    document.addEventListener("click", navigate, true);
    return () => {
      window.removeEventListener("beforeunload", unload);
      document.removeEventListener("click", navigate, true);
    };
  }, [save]);
  function edit(field: "title" | "content", value: string) {
    draft.current = { ...draft.current, [field]: value };
    dirty.current = true;
    if (field === "title") setTitle(value);
    else setContent(value);
    if (!failure.current) setStatus("等待保存…");
  }
  async function download(format: "md" | "docx") {
    if (!(await save())) return;
    try {
      const response = await request(
        `/writings/${row.id}/export?format=${format}`,
      );
      const url = URL.createObjectURL(await response.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `${draft.current.title}.${format}`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setError(errorText(e));
    }
  }
  function localCopy() {
    const url = URL.createObjectURL(
      new Blob([`# ${title}\n\n${content}`], { type: "text/markdown" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "尚未保存的笔记.md";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <div className="writing-scroll editor-scroll">
      <div className="editor-tools">
        <span role="status" className={error ? "save-failed" : "save-state"}>
          {status}
        </span>
        <button className="text-button" onClick={() => setPreview((v) => !v)}>
          {preview ? "继续编辑" : "阅读预览"}
        </button>
        <button className="text-button" onClick={() => download("md")}>
          导出 Markdown
        </button>
        <button className="text-button" onClick={() => download("docx")}>
          导出 Word
        </button>
        <button className="text-button danger" onClick={onDelete}>
          删除
        </button>
      </div>
      {error && (
        <div className="save-error" role="alert">
          <p>{error}</p>
          <button className="button" onClick={localCopy}>
            下载本地草稿
          </button>
          {!conflict && (
            <button
              className="button"
              onClick={() => {
                failure.current = false;
                save();
              }}
            >
              重试保存
            </button>
          )}
        </div>
      )}
      {conflict && (
        <div className="save-conflict">
          <h3>服务器上的最新版本</h3>
          <pre>{conflict.title + "\n\n" + conflict.content}</pre>
          <p>本地输入仍保留。比较后选择要保存的版本。</p>
          <button
            className="button"
            onClick={() => {
              current.current = conflict;
              setRow(conflict);
              setTitle(conflict.title);
              setContent(conflict.content);
              draft.current = {
                title: conflict.title,
                content: conflict.content,
              };
              dirty.current = false;
              failure.current = false;
              setConflict(null);
              setError("");
              setStatus("已保存");
            }}
          >
            采用服务器版本
          </button>
          <button
            className="button"
            onClick={() => {
              current.current = conflict;
              setConflict(null);
              failure.current = false;
              save();
            }}
          >
            以本地内容覆盖此版本
          </button>
        </div>
      )}
      <label className="editor-title-label">
        标题
        <input
          className="editor-title"
          aria-label="笔记或总结标题"
          value={title}
          maxLength={120}
          onChange={(e) => edit("title", e.target.value)}
        />
      </label>
      <p className="editing-notice">
        可自由编辑。保留的引用指向来源片段，不表示修改后的全部文字均已验证。
      </p>
      {preview ? (
        <WritingView
          content={content}
          citations={row.citations}
          onCitation={onCitation}
        />
      ) : (
        <textarea
          className="markdown-editor"
          aria-label="Markdown 正文"
          value={content}
          maxLength={100000}
          placeholder="用 Markdown 记录你的思考…"
          onChange={(e) => edit("content", e.target.value)}
        />
      )}
      <ReferenceList
        citations={row.citations}
        content={content}
        onCitation={onCitation}
      />
      {row.details.inputs && (
        <details className="summary-inputs">
          <summary>本次生成使用的来源与要求</summary>
          <p>
            用途：{row.details.inputs.purpose || "未指定"} · 读者：
            {row.details.inputs.audience || "未指定"}
          </p>
          {row.details.inputs.documents.map((d) => (
            <p key={d.id}>
              资料：{d.filename} · 版本 {d.version}
            </p>
          ))}
          {row.details.inputs.notes.map((n) => (
            <p key={n.id}>
              用户笔记：{n.title} · 保存版本 {n.version}
            </p>
          ))}
        </details>
      )}
    </div>
  );
});
