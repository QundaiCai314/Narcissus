"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight, Check, Clock3 } from "lucide-react";
import { api, post, errorText } from "@/lib/api";
import { billingDate, billingMoney, orderStatusLabels, type BillingOrder, type BillingProduct } from "@/lib/billing";
import { BillingBook, BillingEmpty, BillingLoading, BillingSandboxNotice, BillingShell, BillingWindow } from "@/components/billing";
import "./billing.css";

type Catalog = { available: boolean; environment: string | null; products: BillingProduct[]; message?: string };
type Wallet = { credits: number; member_until: string | null; member_active: boolean };

export default function Billing() {
  const [catalog, setCatalog] = useState<Catalog | null>(null), [wallet, setWallet] = useState<Wallet | null>(null);
  const [orders, setOrders] = useState<BillingOrder[]>([]), [kind, setKind] = useState<"membership" | "credits">("membership");
  const [busy, setBusy] = useState(""), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const keys = useRef(new Map<string, string>());
  useEffect(() => {
    let active = true;
    api<Catalog>("/billing/catalog").then(async (value) => {
      if (!active) return;
      setCatalog(value);
      if (value.available) {
        const [balance, history] = await Promise.all([api<Wallet>("/billing/wallet"), api<{items: BillingOrder[]}>("/billing/orders")]);
        if (active) { setWallet(balance); setOrders(history.items); }
      }
    }).catch((e) => { if (active) setError(errorText(e)); });
    return () => { active = false; };
  }, []);

  async function buy(product: BillingProduct) {
    if (busy) return;
    setBusy(product.id); setError("");
    const request_key = keys.current.get(product.id) || crypto.randomUUID();
    keys.current.set(product.id, request_key);
    try {
      const order = await api<BillingOrder>("/billing/orders", post({ product_id: product.id, request_key }));
      keys.current.delete(product.id);
      try { sessionStorage.setItem("narcissus:pending-payment", order.id); } catch { /* The URL also identifies this order. */ }
      window.location.assign(order.status === "pending" ? `/billing/checkout?order=${order.id}` : `/billing/return?order=${order.id}`);
    } catch (e) { setError(errorText(e)); setBusy(""); }
  }

  async function close(order: BillingOrder) {
    if (busy) return;
    setBusy(order.id); setError(""); setNotice("");
    try {
      const updated = await api<BillingOrder>(`/billing/orders/${order.id}/close`, post());
      setOrders((rows) => rows.map((item) => item.id === updated.id ? updated : item));
      setNotice(updated.status === "closed" ? "未付款订单已关闭。" : updated.status === "paid" ? "已确认付款，订单已到账。" : "关闭结果尚未确认，后台会继续核对。");
    } catch (e) { setError(errorText(e)); } finally { setBusy(""); }
  }

  const products = catalog?.products.filter((product) => product.kind === kind) || [];
  return <BillingShell>
    <header className="billing-heading"><div><p className="billing-kicker">给好奇，多一点余地。</p><h1>会员与额度</h1></div><BillingBook /></header>
    {error && <p className="billing-error" role="alert">{error}</p>}
    {notice && <p className="billing-notice" role="status">{notice}</p>}
    {catalog?.environment === "sandbox" && catalog.available && <BillingSandboxNotice />}
    <div className="billing-store-grid">
      <aside className="billing-story" aria-label="阅读小憩">
        <div className="billing-story-art"><img src="/billing/reading-holiday-v1.webp" alt="浅蓝条纹躺椅上放着翻开的书，带有细腻网点质感的度假印画" width={1448} height={1086} /><span className="billing-story-stamp" aria-hidden="true"><BillingBook /></span></div>
        <h2>把时间，<br />留给理解。</h2><p>从一份资料，到一次新的发现。<br />按自己的节奏，继续读下去。</p>
      </aside>
      <div className="billing-purchase-column">
        <BillingWindow title="为下一次发现做准备">
          {!catalog && !error && <BillingLoading />}
          {catalog && !catalog.available && <BillingEmpty title="收款尚未开通">暂时没有可购买的商品。你的笔记本与现有学习内容仍可正常使用。</BillingEmpty>}
          {!catalog && error && <button className="billing-secondary" onClick={() => window.location.reload()}>重新加载</button>}
          {catalog?.available && <>
            <section className="billing-account" aria-label="账户权益">
              <div><span>可用额度</span><strong>{wallet?.credits ?? "—"}<small>额度</small></strong></div>
              <div><span>会员状态</span><strong className="billing-member-state">{wallet ? wallet.member_active ? "使用中" : "未开通" : "—"}</strong>{wallet?.member_active && wallet.member_until && <small>至 {new Date(wallet.member_until).toLocaleDateString("zh-CN")}</small>}</div>
            </section>
            <div className="billing-tabs" role="group" aria-label="商品类别"><button aria-pressed={kind === "membership"} onClick={() => setKind("membership")}>会员套餐</button><button aria-pressed={kind === "credits"} onClick={() => setKind("credits")}>使用额度</button></div>
            <div className="billing-products">{products.map((product) => <article className="billing-product" key={product.id}>
              <div className="billing-product-heading"><div><span className="billing-product-kind">{product.kind === "membership" ? "单次购买 · 不自动续费" : "按需补充 · 按次使用"}</span><h2>{product.title}</h2></div><p className="billing-price"><span>¥</span>{billingMoney(product.amount_cents)}</p></div>
              <ul className="billing-benefits">
                <li><Check size={16} aria-hidden="true" />{product.kind === "membership" ? `${product.member_days} 天会员有效期` : `${product.credits} 额度，按需使用`}</li>
                <li><Check size={16} aria-hidden="true" />{product.kind === "membership" ? "测验、导图与闪卡生成免扣额度" : "可用于测验、导图与闪卡生成"}</li>
                {product.kind === "membership" && product.credits > 0 && <li><Check size={16} aria-hidden="true" />同时获得 {product.credits} 额度</li>}
              </ul>
              <button className="billing-primary" disabled={!!busy} onClick={() => buy(product)}><span>{busy === product.id ? "正在创建订单…" : "确认订单"}</span><ArrowRight size={18} aria-hidden="true" /></button>
            </article>)}</div>
            {!products.length && <p className="billing-category-empty">该类别暂无上架商品，可以切换到另一类查看。</p>}
            <p className="billing-policy">确认订单后，可选择支付宝付款。会员到期不会自动扣款，现有功能的使用上限仍适用。</p>
          </>}
        </BillingWindow>
      </div>
    </div>
    {catalog?.available && <section className="billing-history" aria-label="最近订单">
      <div className="billing-history-heading"><h2><Clock3 size={18} aria-hidden="true" />最近订单</h2><span>{orders.length ? `${orders.length} 笔` : "还没有购买记录"}</span></div>
      {orders.map((order) => <article className="billing-order" key={order.id}>
        <div className="billing-order-name"><strong>{order.title}</strong><time dateTime={order.created_at}>{billingDate(order.created_at)}</time></div>
        <span className="billing-order-amount">¥{billingMoney(order.amount_cents)}</span><span className="billing-order-status" data-status={order.status}>{orderStatusLabels[order.status] || "确认中"}</span>
        <div className="billing-order-actions"><Link href={order.status === "pending" ? `/billing/checkout?order=${order.id}` : `/billing/return?order=${order.id}`}>{order.status === "pending" ? "查看订单" : "查看结果"}<ArrowRight size={14} aria-hidden="true" /></Link>{order.status === "pending" && <button disabled={!!busy} onClick={() => close(order)}>{busy === order.id ? "正在核对…" : "关闭订单"}</button>}</div>
      </article>)}
    </section>}
  </BillingShell>;
}
