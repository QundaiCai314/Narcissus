"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  post,
  stream,
  errorText,
  Notebook,
  Document,
  Conversation,
  Message,
  Citation,
  Page,
} from "@/lib/api";

export function useWorkspace(id: string) {
  const [notebook, setNotebook] = useState<Notebook | null>(null),
    [docs, setDocs] = useState<Document[]>([]),
    [convs, setConvs] = useState<Conversation[]>([]),
    [convTotal, setConvTotal] = useState(0);
  const [conv, setConv] = useState(""),
    [messages, setMessages] = useState<Message[]>([]),
    [messageTotal, setMessageTotal] = useState(0),
    [selected, setSelected] = useState<string[] | null>(null);
  const [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [messagesLoading, setMessagesLoading] = useState(false),
    [busy, setBusy] = useState(false),
    [uploading, setUploading] = useState(false),
    [question, setQuestion] = useState("");
  const [preview, setPreview] = useState<import("@/lib/sources").SourcePointer | null>(null);
  const fileRef = useRef<HTMLInputElement>(null),
    abortRef = useRef<AbortController | null>(null),
    activeMessage = useRef(""),
    endRef = useRef<HTMLDivElement>(null),
    currentConv = useRef("");
  const load = useCallback(async () => {
    const [n, d, c] = await Promise.all([
      api<Notebook>("/notebooks/" + id),
      api<{ items: Document[] }>("/notebooks/" + id + "/documents"),
      api<Page<Conversation>>("/notebooks/" + id + "/conversations?limit=100"),
    ]);
    setNotebook(n);
    setDocs(d.items);
    setConvs(c.items);
    setConvTotal(c.total);
    return c.items;
  }, [id]);
  const loadMessages = useCallback(async (cid: string) => {
    if (!cid) return;
    setMessagesLoading(true);
    try {
      const p = await api<Page<Message>>(
        "/conversations/" + cid + "/messages?limit=100&newest=true",
      );
      if (currentConv.current === cid) {
        setMessages(p.items);
        setMessageTotal(p.total);
      }
    } finally {
      setMessagesLoading(false);
    }
  }, []);
  useEffect(() => {
    load()
      .then((c) => {
        if (c[0]) {
          setConv(c[0].id);
          currentConv.current = c[0].id;
          return loadMessages(c[0].id);
        }
      })
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
    return () => {
      abortRef.current?.abort();
    };
  }, [load, loadMessages]);
  const hasActiveDocs =
    uploading ||
    docs.some(
      (d) =>
        ["uploading", "queued", "processing"].includes(d.status) ||
        (d.import_status &&
          ["uploading", "queued", "processing"].includes(d.import_status)),
    );
  useEffect(() => {
    if (!hasActiveDocs) return;

    let active = true;
    const timer = setInterval(() => {
      if (document.hidden) return;
      api<{ items: Document[] }>("/notebooks/" + id + "/documents")
        .then((d) => {
          if (active) setDocs(d.items);
        })
        .catch(() => {});
    }, 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [id, hasActiveDocs]);
  useEffect(() => {
    const onFocus = () => {
      api<{ items: Document[] }>("/notebooks/" + id + "/documents")
        .then((d) => setDocs(d.items))
        .catch(() => {});
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [id]);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);
  useEffect(() => {
    if (busy || !messages.some((m) => m.status === "generating")) return;
    const timer = setInterval(() => {
      loadMessages(conv).catch((e) => setError(errorText(e)));
    }, 3000);
    return () => clearInterval(timer);
  }, [messages, busy, conv, loadMessages]);
  async function newConversation() {
    try {
      const c = await api<Conversation>(
        "/notebooks/" + id + "/conversations",
        post(),
      );
      setConvs((v) => [c, ...v]);
      setConvTotal((v) => v + 1);
      setConv(c.id);
      currentConv.current = c.id;
      setMessages([]);
      setMessageTotal(0);
      return c.id;
    } catch (e) {
      setError(errorText(e));
      return "";
    }
  }
  async function upload(files: FileList | null) {
    if (!files) return;
    setUploading(true);
    setError("");
    try {
      for (const file of Array.from(files)) {
        if (file.size > 200 * 1024 * 1024)
          throw new Error("单份 PDF 不能超过 200MB");
        const body = new FormData();
        body.append("file", file);
        await api("/notebooks/" + id + "/documents", { method: "POST", body });
      }
      await load();
    } catch (e) {
      setError(errorText(e));
      await load().catch(() => {});
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }
  async function remove(doc: Document) {
    if (!window.confirm(`删除“${doc.filename}”？相关引用将不再可用。`)) return;
    try {
      await api("/documents/" + doc.id, { method: "DELETE" });
      setSelected((v) => v?.filter((x) => x !== doc.id) ?? null);
      if (preview?.document_id === doc.id) setPreview(null);
      await load();
      if (conv) await loadMessages(conv);
    } catch (e) {
      setError(errorText(e));
    }
  }
  function toggle(docId: string) {
    const base =
      selected ?? docs.filter((d) => d.status === "ready").map((d) => d.id);
    setSelected(
      base.includes(docId) ? base.filter((x) => x !== docId) : [...base, docId],
    );
  }
  async function generate(
    retryId?: string,
    preset?: {
      question: string;
      source_ids?: string[];
      learning_context?: { set_id: string; node_id: string };
    },
  ) {
    if (busy || (!retryId && !(preset?.question ?? question).trim())) return;
    const text = (preset?.question ?? question).trim();
    setBusy(true);
    setError("");
    activeMessage.current = "";
    let cid = conv;
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      if (!cid) cid = await newConversation();
      if (!cid) return;
      if (!retryId) {
        setQuestion("");
        setMessages((v) => [
          ...v,
          {
            id: "optimistic-user",
            role: "user",
            content: text,
            status: "complete",
            error: null,
            citations: [],
          },
        ]);
      }
      let sourceList: Citation[] = [];
      await stream(
        retryId
          ? "/messages/" + retryId + "/retry"
          : "/conversations/" + cid + "/ask",
        {
          ...post(
            retryId
              ? undefined
              : {
                  question: text,
                  source_ids: preset?.source_ids ?? selected,
                  learning_context: preset?.learning_context,
                },
          ),
          signal: controller.signal,
        },
        (event, data) => {
          if (event === "meta") {
            const mid = String(data.message_id);
            activeMessage.current = mid;
            setMessages((v) => [
              ...v.filter((m) => m.id !== mid),
              {
                id: mid,
                role: "assistant",
                content: "",
                status: "generating",
                error: null,
                citations: [],
              },
            ]);
          }
          if (event === "sources") {
            sourceList = data.items as Citation[];
            setMessages((v) =>
              v.map((m) =>
                m.id === activeMessage.current
                  ? { ...m, citations: sourceList }
                  : m,
              ),
            );
          }
          if (event === "delta")
            setMessages((v) =>
              v.map((m) =>
                m.id === activeMessage.current
                  ? { ...m, content: m.content + String(data.text) }
                  : m,
              ),
            );
          if (event === "error") setError(String(data.message));
          if (event === "done")
            setMessages((v) =>
              v.map((m) =>
                m.id === activeMessage.current
                  ? { ...m, status: String(data.status) }
                  : m,
              ),
            );
        },
      );
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError"))
        setError(errorText(e));
      if (!activeMessage.current && !retryId) setQuestion(text);
    } finally {
      setBusy(false);
      abortRef.current = null;
      if (cid) await loadMessages(cid).catch((e) => setError(errorText(e)));
      await load().catch(() => {});
    }
  }
  async function stop() {
    try {
      const mid =
        activeMessage.current ||
        messages.find((m) => m.status === "generating")?.id;
      if (mid) await api("/messages/" + mid + "/stop", post());
      abortRef.current?.abort();
      if (!busy && conv) await loadMessages(conv);
    } catch (e) {
      setError(errorText(e));
    }
  }
  const generating = busy || messages.some((m) => m.status === "generating");
  return {
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
  };
}
