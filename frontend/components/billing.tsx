import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import { Header } from "@/components/shared";
import { billingDate, type BillingOrder } from "@/lib/billing";

export function BillingShell({ children, compact = false }: { children: ReactNode; compact?: boolean }) {
  return <div className="billing-shell">
    <a className="skip-link" href="#billing-content">跳到主要内容</a>
    <Header><Link className="billing-back" href="/"><ArrowLeft size={16} />回到书房</Link></Header>
    <main id="billing-content" className={`billing-main${compact ? " billing-main-compact" : ""}`}>{children}</main>
  </div>;
}

export function BillingWindow({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  return <section className={`billing-window ${className}`} aria-label={title}>
    <div className="billing-window-bar"><span className="billing-pixels" aria-hidden="true"><i /><i /><i /></span><span>{title}</span><span className="billing-window-square" aria-hidden="true" /></div>
    <div className="billing-window-body">{children}</div>
  </section>;
}

export function BillingBook({ className = "" }: { className?: string }) {
  return <span className={`billing-book ${className}`} aria-hidden="true"><svg viewBox="0 0 32 32" fill="none" shapeRendering="crispEdges"><path d="M5 6h9v2h4V6h9v19H18v2h-4v-2H5V6Z" stroke="currentColor" strokeWidth="2" /><path d="M16 8v17M8 11h4M8 15h4M20 11h4M20 15h4" stroke="currentColor" strokeWidth="2" /></svg></span>;
}

export function BillingSandboxNotice() {
  return <p className="billing-sandbox" role="note"><span aria-hidden="true" />沙箱预览 · 不收取真实资金</p>;
}

export function BillingLoading() {
  return <div className="billing-loading" role="status" aria-label="正在读取商品与订单"><span /><span /><span /><span className="billing-loading-button" /></div>;
}

export function BillingOrderDetails({ order }: { order: BillingOrder }) {
  return <dl className="billing-order-details">
    <div><dt>订单编号</dt><dd className="billing-order-id">{order.id}</dd></div>
    <div><dt>创建时间</dt><dd>{billingDate(order.created_at)}</dd></div>
    {order.kind === "membership" && <div><dt>会员有效期</dt><dd>{order.member_days} 天</dd></div>}
    {order.credits > 0 && <div><dt>{order.kind === "membership" ? "随单额度" : "学习额度"}</dt><dd>{order.credits} 额度</dd></div>}
  </dl>;
}

export function BillingEmpty({ title, children }: { title: string; children: ReactNode }) {
  return <div className="billing-empty"><BillingBook /><h2>{title}</h2><p>{children}</p><Link className="billing-secondary" href="/">继续阅读<ArrowUpRight size={16} /></Link></div>;
}
