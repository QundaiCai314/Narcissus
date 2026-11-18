"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowUpRight, AtSign, Library, WalletCards, Headphones } from "lucide-react";
import { api, ApiError, errorText } from "@/lib/api";
import { Header, Loading, ErrorNotice } from "@/components/shared";
import { ProfileAvatar, type AccountUser } from "@/components/profile-link";

export default function Account() {
  const router = useRouter();
  const [user, setUser] = useState<AccountUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true); setError("");
    try { setUser(await api<AccountUser>("/auth/me", { signal })); }
    catch (e) {
      if (signal?.aborted) return;
      if (e instanceof ApiError && e.status === 401) { router.replace("/login"); return; }
      setError(errorText(e));
    } finally { if (!signal?.aborted) setLoading(false); }
  }, [router]);
  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);
  return <div className="profile-shell">
    <Header profile={false}><Link className="back-link" href="/"><ArrowLeft size={16} />回到书房</Link></Header>
    <main className="profile-main">
      <div className="profile-page-heading"><span>你的个人书房</span><h1>个人资料</h1></div>
      {loading ? <Loading text="正在读取账户资料…" /> : error ? <ErrorNotice message={error} retry={() => void load()} /> : user && <>
        <section className="profile-window" aria-labelledby="profile-heading">
          <div className="profile-window-bar" aria-hidden="true"><span><i /><i /><i /></span><span>Narcissus</span><i /></div>
          <div className="profile-identity">
            <ProfileAvatar email={user.email} large />
            <div><span className="profile-overline">你好，研读者</span><h2 id="profile-heading">给好奇，留一个位置。</h2><p>{user.email}</p></div>
          </div>
          <dl className="profile-fields"><div><dt><AtSign size={16} />登录邮箱</dt><dd>{user.email}</dd></div><div><dt>账户状态</dt><dd><span className="profile-status-dot" />已登录</dd></div></dl>
        </section>
        <nav className="profile-shortcuts" aria-label="账户导航">
          <Link href="/"><Library size={20} /><span><strong>我的笔记本</strong><small>回到正在研读的资料</small></span><ArrowUpRight size={18} /></Link>
          <Link href="/billing"><WalletCards size={20} /><span><strong>会员与额度</strong><small>查看权益、额度与订单</small></span><ArrowUpRight size={18} /></Link>
          <Link href="/offline"><Headphones size={20} /><span><strong>离线音频</strong><small>收听已保存在此设备的音频</small></span><ArrowUpRight size={18} /></Link>
        </nav>
      </>}
    </main>
  </div>;
}
