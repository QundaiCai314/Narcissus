"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowUpRight, BookOpen } from "lucide-react";
import { api, post, errorText } from "@/lib/api";
import { Header } from "@/components/shared";
import "./billing.css";

type Product = { id: string; title: string; kind: "membership" | "credits"; amount_cents: number; credits: number; member_days: number };
type Order = Product & { status: string; created_at: string; environment: string };
type Catalog = { available: boolean; environment: string | null; products: Product[]; message?: string };
type Wallet = { credits: number; member_until: string | null; member_active: boolean };
const labels: Record<string, string> = { pending: "待付款或待确认", paid: "已到账", closed: "已关闭", refund_pending: "退款确认中", refunded: "已退款", review_required: "待人工核对" };
const money = (cents: number) => (cents / 100).toFixed(2);

export default function Billing() {
  const [catalog, setCatalog] = useState<Catalog | null>(null), [wallet, setWallet] = useState<Wallet | null>(null);
  const [orders, setOrders] = useState<Order[]>([]), [kind, setKind] = useState<"membership" | "credits">("membership");
  const [busy, setBusy] = useState(""), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const keys = useRef(new Map<string, string>());
  useEffect(() => {
    let active = true;
    api<Catalog>("/billing/catalog").then(async (value) => {
      if (!active) return;
      setCatalog(value);
      if (value.available) {
        const [balance, history] = await Promise.all([api<Wallet>("/billing/wallet"), api<{items: Order[]}>("/billing/orders")]);
        if (active) { setWallet(balance); setOrders(history.items); }
      }
    }).catch((e) => { if (active) setError(errorText(e)); });
    return () => { active = false; };
  }, []);
  async function buy(product: Product) {
    if (busy) return;
    setBusy(product.id); setError("");
    const request_key = keys.current.get(product.id) || crypto.randomUUID(); keys.current.set(product.id, request_key);
    try {
      const order = await api<Order>("/billing/orders", post({product_id: product.id, request_key}));
      keys.current.delete(product.id);
      try { sessionStorage.setItem("narcissus:pending-payment", order.id); } catch { /* URL still carries the owned order. */ }
      // This is OUR HTML endpoint: the official SDK form is rendered and POSTed there.
      window.location.assign(order.status === "pending" ? `/api/billing/orders/${order.id}/pay` : `/billing/return?order=${order.id}`);
    } catch (e) { setError(errorText(e)); setBusy(""); }
  }
  async function close(order: Order) {
    if (busy) return;
    setBusy(order.id); setError(""); setNotice("");
    try {
      const updated = await api<Order>(`/billing/orders/${order.id}/close`, post());
      setOrders((rows) => rows.map((item) => item.id === updated.id ? updated : item));
      setNotice(updated.status === "closed" ? "未付款订单已关闭。" : updated.status === "paid" ? "已确认付款，订单已到账。" : "关闭结果尚未确认，后台会继续核对。");
    } catch (e) { setError(errorText(e)); } finally { setBusy(""); }
  }
  return <div className="billing-shell">
    <Header><Link className="billing-back" href="/"><ArrowLeft size={16} />回到书房</Link></Header>
    <main className="billing-main">
      <div className="billing-heading"><div><p className="billing-kicker">给下一次发现，多一点余地。</p><h1>会员与额度</h1></div><BookOpen size={40} strokeWidth={1} aria-hidden="true" /></div>
      {error && <p className="billing-error" role="alert">{error}</p>}
      {notice && <p role="status" className="billing-notice">{notice}</p>}
      {!catalog && !error && <p role="status">正在读取商品与账户…</p>}
      {catalog && !catalog.available && <section className="billing-empty"><h2>收款尚未开通</h2><p>暂时没有可购买的商品。你的笔记本与现有学习内容仍可正常使用。</p><Link href="/">继续阅读 <ArrowUpRight size={16} /></Link></section>}
      {catalog?.available && <>
        {catalog.environment === "sandbox" && <p className="billing-notice" role="status">当前为支付宝沙箱，仅使用沙箱账号测试，不收取真实资金。</p>}
        <section className="billing-balance" aria-label="账户权益"><div><span>可用额度</span><strong>{wallet?.credits ?? "—"}</strong></div><div><span>会员状态</span><strong>{wallet ? wallet.member_active ? "使用中" : "未开通" : "—"}</strong>{wallet?.member_active && wallet.member_until && <p>有效至 {new Date(wallet.member_until).toLocaleDateString("zh-CN")}</p>}</div></section>
        <div className="billing-tabs" aria-label="商品类别"><button aria-pressed={kind === "membership"} onClick={() => setKind("membership")}>会员套餐</button><button aria-pressed={kind === "credits"} onClick={() => setKind("credits")}>使用额度</button></div>
        <div className="billing-products">{catalog.products.filter((p) => p.kind === kind).map((p) => <article className="billing-product" key={p.id}>
          <h2>{p.title}</h2><p className="billing-price"><span>¥</span>{money(p.amount_cents)}</p>
          <p>{p.kind === "membership" ? `${p.member_days} 天会员，测验、导图与闪卡生成免扣额度。` : `${p.credits} 额度，可用于学习内容生成。`}</p>
          {p.kind === "membership" && p.credits > 0 && <p>同时获得 {p.credits} 额度。</p>}
          <button className="billing-purchase" disabled={!!busy} onClick={() => buy(p)}>{busy === p.id ? "正在创建订单…" : "通过支付宝购买"}<ArrowUpRight size={18} /></button>
        </article>)}</div>
        {!catalog.products.some((p) => p.kind === kind) && <p className="billing-empty">该类别暂无上架商品。</p>}
        <p className="billing-policy">会员按次购买，到期后不会自动扣款。现有功能的使用上限仍适用。到账与退款状态以核验结果为准。</p>
        <section className="billing-history"><h2>最近订单</h2>{orders.length ? orders.map((order) => <article className="billing-order" key={order.id}><div><strong>{order.title}</strong><p>{new Date(order.created_at).toLocaleString("zh-CN")}</p></div><span>¥{money(order.amount_cents)}</span><span>{labels[order.status] || "确认中"}</span><Link href={`/billing/return?order=${order.id}`}>查看结果</Link>{order.status === "pending" && <button disabled={!!busy} onClick={() => close(order)}>关闭未付款订单</button>}</article>) : <p>还没有购买记录。</p>}</section>
      </>}
    </main>
  </div>;
}
