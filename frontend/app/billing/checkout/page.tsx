"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowUpRight, Check, WalletCards } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { billingMoney, orderStatusLabels, validBillingOrderId, type BillingOrder } from "@/lib/billing";
import { BillingBook, BillingLoading, BillingOrderDetails, BillingSandboxNotice, BillingShell, BillingWindow } from "@/components/billing";
import "../billing.css";

export default function Checkout() {
  const [order, setOrder] = useState<BillingOrder | null>(null), [loading, setLoading] = useState(true);
  const [error, setError] = useState(""), [leaving, setLeaving] = useState(false), [reload, setReload] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    let active = true;
    const id = new URLSearchParams(window.location.search).get("order");
    setLoading(true); setError(""); setOrder(null);
    if (!validBillingOrderId(id)) { setError("没有找到有效订单，请返回商品页重新选择。"); setLoading(false); return; }
    api<BillingOrder>(`/billing/orders/${id}`).then((value) => { if (active) setOrder(value); })
      .catch((e) => { if (active) setError(errorText(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reload]);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(timer);
  }, []);
  // The server already limits payment entry to 15 minutes and remains authoritative.
  const expired = !!order && now - Date.parse(order.created_at) > 15 * 60 * 1000;
  const payable = order?.status === "pending" && !expired;

  function pay() {
    if (!order || !payable || leaving) return;
    setLeaving(true);
    // No prefetch or automatic payment navigation: the user must explicitly click.
    window.location.assign(`/api/billing/orders/${order.id}/pay`);
  }

  return <BillingShell compact>
    <Link className="billing-text-link billing-page-back" href="/billing"><ArrowLeft size={16} />返回会员与额度</Link>
    <BillingWindow title="Narcissus · 确认订单" className="billing-checkout-window">
      <header className="billing-page-heading"><div><p className="billing-kicker">下一次发现，从这里继续。</p><h1>确认订单</h1></div><BillingBook /></header>
      {loading && <BillingLoading />}
      {error && <div className="billing-load-error"><p className="billing-error" role="alert">{error}</p><button className="billing-secondary" onClick={() => setReload((value) => value + 1)}>重新读取订单</button></div>}
      {order && <>
        {order.environment === "sandbox" && <BillingSandboxNotice />}
        <div className="billing-checkout-product"><span className="billing-product-kind">{order.kind === "membership" ? "会员套餐 · 单次购买" : "学习额度"}</span><h2>{order.title}</h2></div>
        <BillingOrderDetails order={order} />
        {payable ? <>
          <fieldset className="billing-payment-method"><legend>付款方式</legend><label><input type="radio" name="payment-method" value="alipay" defaultChecked aria-label="支付宝" /><span className="billing-payment-symbol" aria-hidden="true"><WalletCards size={24} /></span><span className="billing-payment-copy"><strong>支付宝</strong><small>将在支付宝页面核对并完成付款</small></span><Check className="billing-payment-check" size={18} aria-hidden="true" /></label></fieldset>
          <div className="billing-total"><span>应付金额</span><strong><small>¥</small>{billingMoney(order.amount_cents)}</strong></div>
          <button className="billing-primary billing-pay-action" disabled={leaving} onClick={pay}><span>{leaving ? "正在前往支付宝…" : "前往支付宝付款"}</span><ArrowUpRight size={18} aria-hidden="true" /></button>
          <p className="billing-policy">{order.kind === "membership" ? "本次为单次购买，到期不会自动续费。" : "额度将在付款确认后记入当前账号。"}</p>
          <Link className="billing-text-link billing-already-paid" href={`/billing/return?order=${order.id}`}>已经付款？查看付款结果<ArrowUpRight size={14} /></Link>
        </> : <div className="billing-checkout-unavailable" role="status"><h2>{expired && order.status === "pending" ? "付款入口已过期" : orderStatusLabels[order.status] || "请先核对订单状态"}</h2><p>{expired && order.status === "pending" ? "本订单创建已超过 15 分钟。请先查看付款结果，再决定是否重新选择商品。" : "当前订单不能再次付款，可以查看最新的处理结果。"}</p><Link className="billing-secondary" href={`/billing/return?order=${order.id}`}>查看订单结果<ArrowUpRight size={16} /></Link></div>}
      </>}
    </BillingWindow>
  </BillingShell>;
}
