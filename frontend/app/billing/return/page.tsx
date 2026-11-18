"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { BookOpen, ArrowLeft } from "lucide-react";
import { Header } from "@/components/shared";
import { api, post, errorText } from "@/lib/api";
import "../billing.css";

type Order = {id: string; title: string; amount_cents: number; status: string};
const headings: Record<string, string> = { paid: "付款已确认", closed: "订单已关闭", refund_pending: "退款正在确认", refunded: "退款已确认", review_required: "订单待人工核对" };
export default function PaymentReturn() {
  const [orderId, setOrderId] = useState(""), [order, setOrder] = useState<Order | null>(null);
  const [loaded, setLoaded] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    let id = params.get("order");
    // Deliberately ignore trade_status, total_amount, out_trade_no and other redirect claims.
    if (!id) try { id = sessionStorage.getItem("narcissus:pending-payment"); } catch { /* neutral state */ }
    if (id && /^[0-9a-f-]{36}$/i.test(id)) setOrderId(id);
    setLoaded(true);
  }, []);
  useEffect(() => {
    if (!orderId) return;
    let active = true, timer: ReturnType<typeof setTimeout>, attempts = 0;
    async function poll() {
      try {
        const value = await api<Order>(`/billing/orders/${orderId}/refresh`, post());
        if (!active) return;
        setOrder(value); setError(""); attempts++;
        if (value.status === "pending" && attempts < 12) timer = setTimeout(poll, 5000);
      } catch (e) { if (active) setError(errorText(e)); }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [orderId]);
  async function refresh() {
    if (!orderId || busy) return;
    setBusy(true); setError("");
    try { setOrder(await api<Order>(`/billing/orders/${orderId}/refresh`, post())); }
    catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  const heading = !loaded ? "正在读取订单" : !orderId ? "尚无待确认的付款" : order ? headings[order.status] || "正在确认付款结果" : "正在确认付款结果";
  return <div className="billing-shell"><Header><Link className="billing-back" href="/"><ArrowLeft size={16} />回到书房</Link></Header>
    <main className="billing-result" aria-live="polite"><BookOpen size={40} strokeWidth={1} aria-hidden="true" /><h1>{heading}</h1>
      {order && <p>{order.title} · ¥{(order.amount_cents / 100).toFixed(2)}</p>}
      {order?.status === "paid" ? <p>会员或额度已记入当前账号，可回到账户页面查看。</p> : order?.status === "refunded" ? <p>退款结果已核验，对应权益已调整。</p> : order?.status === "closed" ? <p>本订单已关闭，需要时可以重新选择商品。</p> : orderId ? <p>请稍候。如果确认需要更长时间，可以关闭此页，后台会继续查询。</p> : <p>从会员与额度页面选择商品后，再查看你的订单结果。</p>}
      {error && <p className="billing-error" role="alert">{error}</p>}
      <div className="billing-result-actions"><Link href="/billing">查看会员与额度</Link>{orderId && order?.status !== "paid" && order?.status !== "closed" && <button disabled={busy} onClick={refresh}>{busy ? "正在核对…" : "刷新结果"}</button>}</div>
    </main></div>;
}
