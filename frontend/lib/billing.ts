export type BillingProduct = {
  id: string;
  title: string;
  kind: "membership" | "credits";
  amount_cents: number;
  credits: number;
  member_days: number;
};

export type BillingOrder = BillingProduct & {
  status: string;
  created_at: string;
  environment: string;
  confirmation_pending?: boolean;
};

export const orderStatusLabels: Record<string, string> = {
  pending: "待付款或待确认", paid: "已到账", closed: "已关闭",
  refund_pending: "退款确认中", refunded: "已退款", review_required: "待人工核对",
};
export const billingMoney = (cents: number) => (cents / 100).toFixed(2);

export function validBillingOrderId(value: string | null): value is string {
  return !!value && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}

export function billingDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  });
}
