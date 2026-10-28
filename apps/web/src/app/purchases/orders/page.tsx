import ExplainMore from "@/components/ExplainMore";
import LivePurchaseOrders from "@/components/trade/LivePurchaseOrders";

export const metadata = { title: "Purchase orders · Accnomos" };

export default function Page() {
  return (
    <div data-print-page className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-extrabold tracking-tight">Purchase orders</h1>
          <p className="mt-1 text-[15px] leading-7 text-muted">Order from a supplier, send it from your own Outlook, and turn it into a bill for Review when the delivery arrives.</p>
        </div>
        <ExplainMore title="How this page works" anchor="invoices">
          An order is approved, then sent. Convert to bill writes a bill in Review with the same lines and totals for you to approve; nothing is posted until you do. You can also match a bill you have already received to an open order.
        </ExplainMore>
      </div>
      <LivePurchaseOrders />
    </div>
  );
}
