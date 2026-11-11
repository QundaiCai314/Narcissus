"use client";
import { useEffect, useState, useCallback, useRef, FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Plus,
  ArrowUpRight,
  ArrowRight,
  BookOpen,
  Files,
  Pencil,
  Trash2,
  X,
  Search,
  Library,
  LockKeyhole,
} from "lucide-react";
import { api, post, errorText, Notebook, Page } from "@/lib/api";
import { Header, Loading, ErrorNotice, PaperStudy } from "@/components/shared";

type Cleanup = {
  id: string;
  filename: string;
  status: string;
  error: string | null;
};
export default function Home() {
  const router = useRouter();
  const [items, setItems] = useState<Notebook[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const [modal, setModal] = useState<"create" | Notebook | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [paging, setPaging] = useState(false);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("recent");
  const [cleanup, setCleanup] = useState<Cleanup[]>([]);
  const dialog = useRef<HTMLDialogElement>(null);
  const load = useCallback(async () => {
    try {
      const [page, jobs] = await Promise.all([
        api<Page<Notebook>>("/notebooks?limit=100"),
        api<{ items: Cleanup[] }>("/cleanup"),
      ]);
      setItems(page.items);
      setTotal(page.total);
      setCleanup(jobs.items);
      setError("");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    api<{ email: string }>("/auth/me")
      .then((u) => {
        setEmail(u.email);
        void load();
      })
      .catch(() => router.replace("/login"));
  }, [load, router]);
  useEffect(() => {
    if (modal && !dialog.current?.open) dialog.current?.showModal();
    if (!modal && dialog.current?.open) dialog.current?.close();
  }, [modal]);
  function create() {
    setError("");
    setName("");
    setModal("create");
  }
  async function save(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      if (modal === "create") {
        const n = await api<Notebook>(
          "/notebooks",
          post({ name: name.trim() }),
        );
        router.push("/notebooks/" + n.id);
      } else if (modal) {
        await api("/notebooks/" + modal.id, {
          method: "PATCH",
          body: JSON.stringify({ name: name.trim() }),
        });
        await load();
      }
      setModal(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function remove(n: Notebook) {
    if (
      !window.confirm(`删除“${n.name}”及其中的全部资料和对话？此操作无法撤销。`)
    )
      return;
    try {
      await api("/notebooks/" + n.id, { method: "DELETE" });
      await load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function more() {
    setPaging(true);
    try {
      const page = await api<Page<Notebook>>(
        `/notebooks?limit=100&offset=${items.length}`,
      );
      setItems((v) => [
        ...new Map([...v, ...page.items].map((n) => [n.id, n])).values(),
      ]);
      setTotal(page.total);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setPaging(false);
    }
  }
  const recent = [...items].sort(
    (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at),
  )[0];
  const filtered = items
    .filter((n) =>
      n.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
    )
    .sort((a, b) =>
      sort === "name"
        ? a.name.localeCompare(b.name, "zh-CN")
        : Date.parse(b.updated_at) - Date.parse(a.updated_at),
    );
  return (
    <div className="library-shell">
      <a className="skip-link" href="#library">
        跳到笔记本
      </a>
      <Header>
        <span className="account">
          <span className="account-initial" aria-hidden="true">
            {email.charAt(0).toUpperCase() || "知"}
          </span>
          <span>{email}</span>
        </span>
      </Header>
      <div className="library-layout">
        <aside className="library-sidebar">
          <div className="sidebar-caption">你的个人书房</div>
          <nav aria-label="书房导航">
            <a className="sidebar-link active" href="#library">
              <Library size={18} />
              我的笔记本<span>{total}</span>
            </a>
          </nav>
          <button className="sidebar-create" onClick={create}>
            <Plus size={17} />
            新建笔记本
          </button>
          <div className="sidebar-colophon">
            <span className="colophon-rule" />
            <p>
              读有所思，
              <br />
              思有所据。
            </p>
            <span>
              YOUR THOUGHTS,
              <br />
              IN GOOD COMPANY.
            </span>
          </div>
          <div className="sidebar-private">
            <LockKeyhole size={13} />
            仅自己可见
          </div>
        </aside>
        <main className="library-main">
          <section className="editorial-hero" aria-labelledby="welcome-title">
            <div className="hero-copy">
              <span className="eyebrow">
                <span className="edition-mark" /> A QUIET PLACE FOR IDEAS
              </span>
              <h1 id="welcome-title">
                让好奇有处安放，
                <br />
                让知识<span>慢慢成章。</span>
              </h1>
              <p>
                收好一份资料，读懂一个问题。
                <br />
                在这里，把零散的发现写成自己的见解。
              </p>
              {recent ? (
                <Link
                  className="hero-continue"
                  href={"/notebooks/" + recent.id}
                >
                  <span>
                    继续研读<strong>{recent.name}</strong>
                  </span>
                  <ArrowRight size={20} />
                </Link>
              ) : (
                <button className="button primary" onClick={create}>
                  <Plus size={17} />
                  开启第一本笔记
                </button>
              )}
            </div>
            <PaperStudy />
          </section>
          <section
            className="library-section"
            id="library"
            aria-labelledby="library-title"
          >
            <div className="library-section-heading">
              <div>
                <span className="eyebrow">THE PERSONAL COLLECTION</span>
                <h2 id="library-title">
                  我的笔记本 <span>{total.toString().padStart(2, "0")}</span>
                </h2>
              </div>
              <button className="button primary" onClick={create}>
                <Plus size={17} />
                新建笔记本
              </button>
            </div>
            <div className="library-toolbar">
              <span className="collection-label">
                <span className="dot" />
                全部收藏{search && <small> / {filtered.length} 个匹配</small>}
              </span>
              <div className="library-controls">
                <label className="collection-search">
                  <Search size={16} />
                  <input
                    aria-label="搜索笔记本"
                    placeholder="搜索笔记本…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                  {search && (
                    <button aria-label="清空搜索" onClick={() => setSearch("")}>
                      <X size={14} />
                    </button>
                  )}
                </label>
                <select
                  aria-label="笔记本排序"
                  value={sort}
                  onChange={(e) => setSort(e.target.value)}
                >
                  <option value="recent">最近更新</option>
                  <option value="name">名称排序</option>
                </select>
              </div>
            </div>
            {error && !modal && <ErrorNotice message={error} retry={load} />}
            {loading ? (
              <Loading text="正在打开你的书房…" />
            ) : (
              <>
                {filtered.length === 0 && search ? (
                  <div className="library-empty">
                    <Search size={25} />
                    <h3>还没有找到这本笔记</h3>
                    <p>换一个关键词，或查看全部笔记本。</p>
                    <button
                      className="text-button"
                      onClick={() => setSearch("")}
                    >
                      清空搜索 <ArrowRight size={15} />
                    </button>
                  </div>
                ) : (
                  <div className="collection-grid">
                    {filtered.map((n, index) => (
                      <article
                        className={"collection-card palette-" + (index % 4)}
                        key={n.id}
                      >
                        <Link
                          href={"/notebooks/" + n.id}
                          className="collection-card-main"
                        >
                          <div className="book-jacket">
                            <div className="jacket-meta">
                              <span>Narcissus · 研读集</span>
                              <span>{String(index + 1).padStart(2, "0")}</span>
                            </div>
                            <h3>{n.name}</h3>
                            <div className="jacket-bottom">
                              <span>READ · THINK · CONNECT</span>
                              <ArrowUpRight size={20} />
                            </div>
                          </div>
                          <div className="collection-meta">
                            <span>
                              <Files size={14} />
                              {n.document_count} 份资料
                            </span>
                            <time dateTime={n.updated_at}>
                              {new Date(n.updated_at).toLocaleDateString(
                                "zh-CN",
                                { month: "long", day: "numeric" },
                              )}{" "}
                              更新
                            </time>
                          </div>
                        </Link>
                        <div className="collection-actions">
                          <button
                            aria-label={"重命名" + n.name}
                            title="重命名"
                            onClick={() => {
                              setError("");
                              setModal(n);
                              setName(n.name);
                            }}
                          >
                            <Pencil size={14} />
                          </button>
                          <button
                            aria-label={"删除" + n.name}
                            title="删除笔记本"
                            onClick={() => remove(n)}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </article>
                    ))}
                    <button className="collection-new" onClick={create}>
                      <span className="new-book-mark">
                        <Plus size={24} strokeWidth={1.2} />
                      </span>
                      <strong>留一页，给新的好奇</strong>
                      <span>添加资料，开始下一段探索</span>
                    </button>
                  </div>
                )}
                {items.length < total && (
                  <button
                    className="button collection-more"
                    disabled={paging}
                    onClick={more}
                  >
                    {paging
                      ? "正在加载…"
                      : `加载更多 · 已显示 ${items.length} / ${total}`}
                  </button>
                )}
              </>
            )}
          </section>
          {cleanup.length > 0 && (
            <section className="cleanup">
              <h3>文件清理记录</h3>
              {cleanup.map((j) => (
                <div key={j.id}>
                  {j.filename} ·{" "}
                  {j.status === "failed"
                    ? "清理失败，文件仍处于私有存储"
                    : "正在清理"}
                </div>
              ))}
            </section>
          )}
          <footer className="library-footer">
            <span>Narcissus</span>
            <span>每一页，都是思考的开始。</span>
            <BookOpen size={16} />
          </footer>
        </main>
      </div>
      <dialog
        ref={dialog}
        className="notebook-dialog"
        aria-labelledby="notebook-dialog-title"
        onClose={() => setModal(null)}
        onCancel={(e) => {
          if (busy) e.preventDefault();
        }}
      >
        <form onSubmit={save}>
          <div className="panel-title">
            <span className="eyebrow">A NEW CHAPTER</span>
            <button
              type="button"
              className="icon-button"
              aria-label="关闭"
              disabled={busy}
              onClick={() => setModal(null)}
            >
              <X size={19} />
            </button>
          </div>
          <h2 id="notebook-dialog-title">
            {modal === "create"
              ? "为新的好奇，起个名字。"
              : "给这本笔记换个名字。"}
          </h2>
          <p>一个主题，一本笔记。之后也可以随时修改。</p>
          {error && <ErrorNotice message={error} />}
          <label>
            笔记本名称
            <input
              autoFocus
              required
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：城市、空间与日常生活"
            />
          </label>
          <button
            className="button primary full"
            disabled={busy || !name.trim()}
          >
            {busy
              ? "正在保存…"
              : modal === "create"
                ? "创建笔记本"
                : "保存名称"}
            <ArrowRight size={16} />
          </button>
        </form>
      </dialog>
    </div>
  );
}
