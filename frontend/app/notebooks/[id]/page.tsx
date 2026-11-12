"use client";
import { use, FormEvent, useRef, useState, useEffect, useCallback } from "react";
import { useWorkspace } from "@/hooks/use-workspace";
import Link from "next/link";
import {
  ArrowLeft,
  Plus,
  FileText,
  Upload,
  X,
  MessageSquare,
  ArrowUp,
  Square,
  ExternalLink,
  Trash2,
  RotateCcw,
  PanelRightClose,
  Quote,
  Check,
  LoaderCircle,
} from "lucide-react";
import {
  api,
  post,
  errorText,
  Conversation,
  Message,
  Page,
  Writing,
} from "@/lib/api";
import { Brand, Header, Loading, ErrorNotice } from "@/components/shared";
import { ChatMessage } from "@/components/message";
import { SourceImport } from "@/components/source-import";
import { SourcePreview } from "@/components/source-preview";
import { sourceNames, importStates } from "@/lib/sources";
import { GuidePanel } from "@/components/guide-panel";
import { WritingPanel } from "@/components/writing-panel";
import { AudioPanel } from "@/components/audio-panel";
import { ConversationHistory } from "@/components/conversation-history";
import { LearningPanel } from "@/components/learning-panel";
import { VisualPanel } from "@/components/visual-panel";
import { ResearchPanel } from "@/components/research-panel";

import { StudioPanel, StudioKind } from "@/components/studio-panel";
import { WorkspaceDialog } from "@/components/workspace-dialog";
import { LearningKind } from "@/lib/learning";

type StudioRequest = { key: number; id?: string; kind?: LearningKind; documentIds?: string[] };
const statusText: Record<string, string> = {
  uploading: "正在上传",
  queued: "等待处理",
  processing: "正在处理",
  ready: "可用",
  failed: "处理失败",
};
export default function Workspace({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [mobilePanel, setMobilePanel] = useState<"sources" | "chat" | "studio">("chat");
  const [view, setView] = useState<
    "chat" | "guide" | "note" | "summary" | "learning" | "audio" | "research" | "presentation" | "infographic"
  >("chat");
  const [guideDoc, setGuideDoc] = useState(""),
    [noteId, setNoteId] = useState(""),
    [summaryId, setSummaryId] = useState(""),
    [studioTick, setStudioTick] = useState(0);
  const [adding, setAdding] = useState(false), [importDirty, setImportDirty] = useState(false), [previewDirty, setPreviewDirty] = useState(false);
  const requestSequence = useRef(0);
  const [noteRequest, setNoteRequest] = useState<StudioRequest>();
  const [summaryRequest, setSummaryRequest] = useState<StudioRequest>();
  const [audioRequest, setAudioRequest] = useState<StudioRequest>();
  const [presentationRequest, setPresentationRequest] = useState<StudioRequest>();
  const [infographicRequest, setInfographicRequest] = useState<StudioRequest>();
  const [learningRequest, setLearningRequest] = useState<StudioRequest>();
  const [quizFocused, setQuizFocused] = useState(false);
  const learningDirty = useRef(false);
  const reportLearningDirty = useCallback((dirty: boolean) => { learningDirty.current = dirty; }, []);
  const {
    notebook,
    docs,
    convs,
    convTotal,
    conv,
    messages,
    messageTotal,
    selected,
    error,
    loading,
    messagesLoading,
    busy,
    uploading,
    question,
    preview,
    fileRef,
    endRef,
    currentConv,
    generating,
    setConv,
    setMessages,
    setConvs,
    setSelected,
    setError,
    setQuestion,
    setPreview,
    load,
    loadMessages,
    newConversation,
    upload,
    remove,
    toggle,
    generate,
    stop,
  } = useWorkspace(id);
  const chosenSources = docs.filter(d => d.status === "ready" && (selected === null || selected.includes(d.id))).map(d => d.id);
  function openStudio(kind: StudioKind, itemId?: string, documentId?: string | null, pushState: boolean = true) {
    if (learningDirty.current && !window.confirm("当前作答尚未保存，切换会放弃这些修改。仍要切换吗？")) return;
    const request = { key: ++requestSequence.current, id: itemId, documentIds: chosenSources };
    if (kind === "presentation") { setPresentationRequest(request); setView("presentation");
    } else if (kind === "infographic") { setInfographicRequest(request); setView("infographic");
    } else if (kind === "research") {
      setView("research");
    } else if (kind === "guide") {
      setGuideDoc(documentId || chosenSources[0] || docs.find(d => d.status === "ready")?.id || "");
      setView("guide");
    } else if (kind === "note") {
      setNoteRequest(request); setView("note");
      if (itemId) setNoteId(itemId);
    } else if (kind === "summary") {
      setSummaryRequest(request); setView("summary");
      if (itemId) setSummaryId(itemId);
    } else if (kind === "audio") {
      setAudioRequest(request); setView("audio");
    } else {
      setLearningRequest({ ...request, kind }); setView("learning");
    }
    if (pushState && typeof window !== "undefined") {
      const q = new URLSearchParams(window.location.search);
      q.set("tab", kind);
      if (itemId) q.set("item", itemId); else q.delete("item");
      if (documentId) q.set("doc", documentId); else q.delete("doc");
      window.history.pushState(null, "", `${window.location.pathname}?${q.toString()}`);
    }
  }

  function closeStudio(pushState: boolean = true) {
    if (learningDirty.current && !window.confirm("当前作答尚未保存，离开会放弃这些修改。仍要离开吗？")) return;
    setView("chat");
    if (pushState && typeof window !== "undefined") {
      const q = new URLSearchParams(window.location.search);
      q.delete("tab");
      q.delete("item");
      q.delete("doc");
      const search = q.toString();
      window.history.pushState(null, "", search ? `${window.location.pathname}?${search}` : window.location.pathname);
    }
  }

  useEffect(() => {
    if (typeof window === "undefined") return;
    const q = new URLSearchParams(window.location.search);
    const tab = q.get("tab") as StudioKind | null;
    const item = q.get("item") || undefined;
    const doc = q.get("doc") || undefined;
    if (tab) {
      openStudio(tab, item, doc, false);
    }
    const onPop = () => {
      const p = new URLSearchParams(window.location.search);
      const t = p.get("tab") as StudioKind | null;
      const it = p.get("item") || undefined;
      const d = p.get("doc") || undefined;
      if (t) {
        openStudio(t, it, d, false);
      } else {
        closeStudio(false);
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  if (loading)
    return (
      <>
        <Header />
        <Loading />
      </>
    );
  if (!notebook)
    return (
      <>
        <Header />
        <main className="home">
          <ErrorNotice message={error || "笔记本不存在"} />
          <Link href="/">返回笔记本</Link>
        </main>
      </>
    );
  return (
    <div className="workspace-shell" data-mobile-panel={mobilePanel}>
      <Header>
        <Link href="/" className="back-link">
          <ArrowLeft size={16} />
          全部笔记本
        </Link>
      </Header>
      <div className="workspace-title">
        <div>
          <BookTitle />
          <h1>{notebook.name}</h1>
        </div>
        <span>
          私人笔记本 <span className="dot" />
        </span>
      </div>
      {error && (
        <div className="workspace-error">
          <ErrorNotice message={error} />
          <button
            className="icon-button"
            aria-label="关闭提示"
            onClick={() => setError("")}
          >
            <X size={16} />
          </button>
        </div>
      )}
      <nav className="mobile-workspace-nav" aria-label="工作区切换">
        <button aria-pressed={mobilePanel === "sources"} onClick={() => setMobilePanel("sources")}>资料</button>
        <button aria-pressed={mobilePanel === "chat"} onClick={() => setMobilePanel("chat")}>对话</button>
        <button aria-pressed={mobilePanel === "studio"} onClick={() => setMobilePanel("studio")}>创作</button>
      </nav>
      <main className="workspace studio-workspace">
        <aside className="sources-panel">
          <div className="panel-title">
            <h2>
              资料<span>{docs.length}/10</span>
            </h2>
            <FileText size={17} />
          </div>
          <p className="panel-description">你的答案，从这些资料开始。</p>
          <button className="upload-button" onClick={() => setAdding(true)}><Plus size={18}/>添加资料</button>
          <p className="upload-hint">PDF · Word · 文字 · 网页 · 图片<br/>支持中文图片文字识别</p>
          <label className="all-sources">
            <input
              type="checkbox"
              checked={selected === null}
              onChange={(e) => setSelected(e.target.checked ? null : [])}
            />
            使用全部可用资料
          </label>
          <div className="document-list">
            {docs.length === 0 ? (
              <div className="source-empty">
                <FileText size={32} />
                <p>这里还没有资料</p>
                <small>
                  添加你的第一份资料，
                  <br />
                  开启有依据的对话。
                </small>
              </div>
            ) : (
              docs.map((d) => (
                <article className="document-card" key={d.id}>
                  <div className="document-row">
                    <input
                      type="checkbox"
                      aria-label={"选择" + d.filename}
                      disabled={d.status !== "ready"}
                      checked={
                        d.status === "ready" &&
                        (selected === null || selected.includes(d.id))
                      }
                      onChange={() => toggle(d.id)}
                    />
                    <button
                      className="document-name"
                      onClick={() =>
                        setPreview({
                          document_id: d.id,
                          filename: d.filename,
                          page: 1,
                          version: d.latest_version,
                        })
                      }
                    >
                      <FileText size={19} />
                      <span>{d.filename}</span>
                    </button>
                  </div>
                  <div className="document-info"><small>{sourceNames[d.source_type]}</small>
                    <span className={"status " + d.status}>
                      {d.status === "ready" && <Check size={11} />}{" "}
                      {statusText[d.status] || importStates[d.status] || d.status}
                    </span>
                    <small>
                      {d.pages
                        ? `${d.pages} 页`
                        : `${(d.size / 1024 / 1024).toFixed(1)} MB`}
                    </small>
                    {d.status === "ready" && (
                      <button
                        className="text-button guide-link"
                        onClick={() => {
                          setGuideDoc(d.id);
                          setView("guide");
                        }}
                      >
                        导读
                      </button>
                    )}
                    <button
                      className="icon-button"
                      title="删除资料"
                      aria-label={"删除" + d.filename}
                      onClick={() => remove(d)}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                  {d.import_status && d.import_status !== "ready" && <button className="text-button" onClick={() => setPreview({document_id:d.id,filename:d.filename,version:d.latest_version,page:1})}>{d.status === "ready" ? "新版：" : ""}{importStates[d.import_status]} · 查看</button>}
                  {d.import_status === "processing" && d.processing && <p className="upload-hint">{d.processing.stage === "ocr" ? "正在识别图片文字" : "正在读取文字"} · {d.processing.page}/{d.processing.pages}</p>}
                  {!!d.extraction?.ocr_pages?.length && <p className="upload-hint">已识别 {d.extraction.ocr_pages.length} 页图片文字 · 请核对数字及公式</p>}
                  {(d.import_error || d.error) && <p className="document-error">{d.import_error || d.error}</p>}

                </article>
              ))
            )}
          </div>
          <ConversationHistory items={convs} total={convTotal} current={conv} disabled={generating}
            onSelect={cid => { setConv(cid); currentConv.current = cid; setMobilePanel("chat"); loadMessages(cid).catch(e => setError(errorText(e))); }}
            onMore={async () => { try { const p = await api<Page<Conversation>>(`/notebooks/${id}/conversations?limit=100&offset=${convs.length}`); setConvs(v => [...new Map([...v, ...p.items].map(c=>[c.id,c])).values()]); } catch(e) { setError(errorText(e)); } }}
          />
          <div className="sources-foot">
            <span className="dot" />
            资料仅你可见
          </div>
        </aside>
        <section className="chat-panel">
          <div style={{ display: "contents" }}>
            <div className="chat-heading">
              <h2>
                <MessageSquare size={18} />
                对话
              </h2>
              <div>
                <button
                  className="icon-button"
                  aria-label="新建对话"
                  title="新建对话"
                  disabled={generating}
                  onClick={newConversation}
                >
                  <Plus size={20} />
                </button>

              </div>
            </div>
            <div className="chat-scroll">
              {messages.length < messageTotal && (
                <button
                  className="button"
                  onClick={async () => {
                    try {
                      const p = await api<Page<Message>>(
                        `/conversations/${conv}/messages?limit=100&newest=true&offset=${messages.length}`,
                      );
                      setMessages((v) => [...p.items, ...v]);
                    } catch (e) {
                      setError(errorText(e));
                    }
                  }}
                >
                  加载更早的消息
                </button>
              )}
              {messagesLoading && <Loading text="正在读取对话…" />}
              {messages.length === 0 && !messagesLoading ? (
                <div className="chat-empty">
                  <div className="empty-mark">
                    <Quote size={32} />
                  </div>
                  <span className="eyebrow">READ BETWEEN THE LINES</span>
                  <h2>从一个好问题开始。</h2>
                  <p>
                    找到关键观点，连起不同线索，或读懂一个细节。
                    <br />
                    跟随引用回到原文，把新的理解留在笔记里。
                  </p>
                  <div className="suggestions">
                    {[
                      "概述这些资料的核心要点与主要结论",
                      "梳理核心观点及对应的原始证据链",
                      "对比不同资料的论述角度与异同点",
                    ].map((s) => (
                      <button key={s} onClick={() => setQuestion(s)}>
                        {s}
                        <ArrowUp size={14} />
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                messages.map((m) => (
                  <ChatMessage
                    key={m.id}
                    message={m}
                    busy={generating}
                    onCitation={setPreview}
                    onRetry={generate}
                    onSave={async (messageId) => {
                      try {
                        await api<Writing>(
                          `/messages/${messageId}/save-note`,
                          post(),
                        );
                        setStudioTick((t) => t + 1);
                      } catch (e) {
                        setError(errorText(e));
                      }
                    }}
                  />
                ))
              )}
              <div ref={endRef} />
            </div>
            <form
              className="composer-wrap"
              onSubmit={(e: FormEvent) => {
                e.preventDefault();
                generate();
              }}
            >
              <div className="composer">
                <textarea
                  aria-label="向资料提问"
                  rows={2}
                  maxLength={2000}
                  placeholder="关于这些资料，你想了解什么？"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => {
                    if (
                      e.key === "Enter" &&
                      !e.shiftKey &&
                      !e.nativeEvent.isComposing
                    ) {
                      e.preventDefault();
                      if (!generating) generate();
                    }
                  }}
                />
                <div className="composer-actions">
                  <span>
                    <span className="dot" />
                    {selected === null
                      ? `全部 ${docs.filter((d) => d.status === "ready").length} 份可用资料`
                      : `已选择 ${selected.length} 份资料`}
                  </span>
                  {generating ? (
                    <button
                      type="button"
                      className="send-button stop"
                      title="停止生成"
                      aria-label="停止生成"
                      onClick={stop}
                    >
                      <Square size={16} />
                    </button>
                  ) : (
                    <button
                      className="send-button"
                      disabled={
                        !question.trim() ||
                        (selected !== null && selected.length === 0)
                      }
                      title="发送问题"
                      aria-label="发送问题"
                    >
                      <ArrowUp size={20} />
                    </button>
                  )}
                </div>
              </div>
              <p className="composer-tip">
                <span>点击引用标号可直接定位原文段落</span>
                <span>Enter 发送 · Shift + Enter 换行</span>
              </p>
            </form>
          </div>
        </section>
        <StudioPanel
          notebookId={id}
          revision={`${view}:${noteId}:${summaryId}:${studioTick}`}
          selectedCount={chosenSources.length}
          onCreate={openStudio}
          onOpen={openStudio}
        />
      </main>
      <WorkspaceDialog className={view === "learning" ? `study-dialog ${quizFocused ? "quiz-focus" : "studio-modal"}` : "studio-modal"} open={view !== "chat"} label="工作室内容" onClose={() => closeStudio()}>
        {view !== "chat" && (
          <>
            <div className="studio-detail-heading">
              {view === "learning" && quizFocused ? <Brand onNavigate={() => !learningDirty.current || window.confirm("当前作答尚未保存，返回主页会放弃这些修改。仍要离开吗？")} /> : <span className="studio-modal-title">{{ presentation:"演示文稿", infographic:"信息图", research: "联网研究", guide: "资料导读", note: "笔记", summary: "总结", learning: "主动学习", audio: "音频概览", chat: "对话" }[view]}</span>}
              <button aria-label={view === "learning" && quizFocused ? "返回对话" : "关闭弹窗"} className={view === "learning" && quizFocused ? "study-return" : "studio-close"} onClick={() => closeStudio()}>
                {view === "learning" && quizFocused ? <span className="study-return-icon"><ArrowLeft size={16} aria-hidden="true" /></span> : <X size={16} />}
                {view === "learning" && quizFocused && <span>返回对话</span>}
              </button>
            </div>
            {view === "presentation" && <VisualPanel notebookId={id} kind="presentation" docs={docs} request={presentationRequest} onCitation={setPreview}/>}
            {view === "infographic" && <VisualPanel notebookId={id} kind="infographic" docs={docs} request={infographicRequest} onCitation={setPreview}/>}
            {view === "research" && <ResearchPanel notebookId={id} docs={docs} onImported={()=>{void load();}} onReport={reportId=>openStudio("summary",reportId)} onSource={document_id=>setPreview({document_id,filename:docs.find(d=>d.id===document_id)?.filename||"网页正文"})} onPaste={()=>setAdding(true)} onAsk={(text,source_ids)=>{if(generating){setError("请先停止当前回答");return;}setView("chat");setSelected(source_ids);generate(undefined,{question:`请围绕研究问题“${text}”解释所选原始资料的主要证据与尚不确定之处。`,source_ids});}}/>}
            {view === "guide" && (
              <GuidePanel
                docs={docs}
                documentId={guideDoc}
                onSelect={setGuideDoc}
                onCitation={setPreview}
                onAsk={(text, sourceId) => {
                  if (generating) {
                    setError("请先停止当前回答，再开始提问");
                    return;
                  }
                  setView("chat");
                  setSelected([sourceId]);
                  generate(undefined, { question: text, source_ids: [sourceId] });
                }}
              />
            )}
            {view === "note" && (
              <WritingPanel
                notebookId={id}
                kind="note"
                studioRequest={noteRequest}
                docs={docs}
                selectedId={noteId}
                onSelect={setNoteId}
                onCitation={setPreview}
              />
            )}
            {view === "summary" && (
              <WritingPanel
                notebookId={id}
                kind="summary"
                studioRequest={summaryRequest}
                docs={docs}
                selectedId={summaryId}
                onSelect={setSummaryId}
                onCitation={setPreview}
              />
            )}
            {view === "learning" && (
              <LearningPanel
                onFocusChange={setQuizFocused}
                onDirtyChange={reportLearningDirty}
                studioRequest={learningRequest}
                notebookId={id}
                docs={docs}
                onCitation={setPreview}
                onAsk={(context, title, sourceIds) => {
                  if (generating) {
                    setError("请先停止当前回答，再开始提问");
                    return;
                  }
                  setView("chat");
                  setSelected(sourceIds);
                  generate(undefined, {
                    question: `请依据资料解释“${title}”，说明关键依据和容易混淆的地方。`,
                    learning_context: context,
                    source_ids: sourceIds,
                  });
                }}
              />
            )}
            {view === "audio" && <AudioPanel notebookId={id} docs={docs} studioRequest={audioRequest} onCitation={setPreview}/>}
          </>
        )}
      </WorkspaceDialog>
      <WorkspaceDialog open={adding} label="添加资料" className="source-dialog" onClose={() => {if(!importDirty || confirm("还有未保存的文字或正在上传的文件，确定离开？")){setAdding(false);setImportDirty(false);}}}>
        {adding && <SourceImport notebookId={id} onImported={() => {void load();}} onDirty={setImportDirty}/>}
      </WorkspaceDialog>
      <WorkspaceDialog open={!!preview} label="原文核对" className="source-dialog" onClose={() => {if(!previewDirty || confirm("修改尚未保存，确定离开？")){setPreview(null);setPreviewDirty(false);}}}>
        {preview && <SourcePreview key={`${preview.document_id}:${preview.version}:${preview.location?.block_id}`} pointer={preview} onChanged={() => {void load();}} onDirty={setPreviewDirty}/>}
      </WorkspaceDialog>
    </div>
  );
}
function BookTitle() {
  return (
    <span className="title-icon">
      <FileText size={18} />
    </span>
  );
}
