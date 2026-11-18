"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Check, Clock3, RotateCcw } from "lucide-react";
import { api, post, errorText } from "@/lib/api";
import { billingMoney, validBillingOrderId, type BillingOrder } from "@/lib/billing";
import { BillingBook, BillingOrderDetails, BillingSandboxNotice, BillingShell, BillingWindow } from "@/components/billing";
import "../billing.css";

const headings: Record<string, string> = { paid: "付款已确认", closed: "订单已关闭", refund_pending: "退款正在确认", refunded: "退款已确认", review_required: "订单待人工核对" };

export default function PaymentReturn() {
  const [orderId, setOrderId] = useState(""), [order, setOrder] = useState<BillingOrder | null>(null);
  const [loaded, setLoaded] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    let id = params.get("order");
    if (!id) try { id = sessionStorage.getItem("narcissus:pending-payment"); } catch { /* The URL works without browser storage. */ }
    // Redirect claims never determine an order's payment status or price.
    if (validBillingOrderId(id)) setOrderId(id);
    setLoaded(true);
  }, []);
  useEffect(() => {
    if (!orderId) return;
    let active = true, timer: ReturnType<typeof setTimeout>, attempts = 0;
    async function poll() {
      try {
        const value = await api<BillingOrder>(`/billing/orders/${orderId}/refresh`, post());
        if (!active) return;
        setOrder((current) => current && current.status !== "pending" && value.status === "pending" ? current : value);
        setError(""); attempts++;
        if (value.status === "pending" && attempts < 12) timer = setTimeout(poll, 5000);
      } catch (e) { if (active) setError(errorText(e)); }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [orderId]);
  async function refresh() {
    if (!orderId || busy) return;
    setBusy(true); setError("");
    try {
      const value = await api<BillingOrder>(`/billing/orders/${orderId}/refresh`, post());
      setOrder((current) => current && current.status !== "pending" && value.status === "pending" ? current : value);
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }

  const heading = !loaded ? "正在读取订单" : !orderId ? "尚无待确认的付款" : order ? headings[order.status] || "付款结果待确认" : "正在确认付款结果";
  const pending = !!orderId && (!order || order.status === "pending");
  const paid = order?.status === "paid";
  const description = paid ? "会员或额度已记入当前账号，可以继续下一次学习。" : order?.status === "refunded" ? "退款结果已核验，对应权益已调整。" : order?.status === "closed" ? "本订单已关闭，需要时可以重新选择商品。" : order?.status === "refund_pending" ? "退款结果正在核对，确认后会更新订单与对应权益。" : order?.status === "review_required" ? "这笔订单需要人工核对，请联系收款管理人员。" : orderId ? "我们正在核对支付宝付款状态。关闭页面后，后台仍会继续查询。" : "选择会员或额度后，就可以在这里查看订单结果。";
  return <BillingShell compact>
    <Link className="billing-text-link billing-page-back" href="/billing"><ArrowLeft size={16} />返回会员与额度</Link>
    <BillingWindow title="Narcissus · 付款结果" className="billing-result-window">
      <header className="billing-result-heading"><div className="billing-result-symbol" data-paid={paid} aria-hidden="true">{paid ? <Check size={32} /> : pending ? <Clock3 size={32} /> : <BillingBook />}</div><p className="billing-kicker">{paid ? "下一页，已经准备好了。" : "每一笔订单，都有回音。"}</p><h1 aria-live="polite">{heading}</h1><p>{description}</p></header>
      {order?.environment === "sandbox" && <BillingSandboxNotice />}
      {order && <section className="billing-result-receipt" aria-label="订单摘要"><div className="billing-receipt-product"><strong>{order.title}</strong><span>¥{billingMoney(order.amount_cents)}</span></div><BillingOrderDetails order={order} /></section>}
      {error && <p className="billing-error" role="alert">{error}</p>}
      <div className="billing-result-actions">
        {pending ? <><button className="billing-primary" disabled={busy} onClick={refresh}><span>{busy ? "正在核对…" : "刷新付款状态"}</span><RotateCcw size={16} aria-hidden="true" /></button>{order?.status === "pending" && <Link className="billing-secondary" href={`/billing/checkout?order=${order.id}`}>查看付款订单<ArrowRight size={16} /></Link>}</> : <Link className="billing-primary" href={paid ? "/" : "/billing"}>{paid ? "回到书房" : "查看会员与额度"}<ArrowRight size={16} /></Link>}
      </div>
      {pending && <p className="billing-policy">尚未付款，可返回订单继续；如果已经付款，请等待核验结果，避免重复支付。</p>}
    </BillingWindow>
  </BillingShell>;
}
