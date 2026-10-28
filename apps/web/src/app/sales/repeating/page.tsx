import ExplainMore from "@/components/ExplainMore";
import LiveRepeating from "@/components/trade/LiveRepeating";

export const metadata = { title: "Repeating · Accnomos" };

export default function Page() {
  return (
    <div data-print-page className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-extrabold tracking-tight">Repeating</h1>
          <p className="mt-1 text-[15px] leading-7 text-muted">Invoices you send and bills you receive on a schedule. Each one is made as a draft, or approved automatically if you tick that.</p>
        </div>
        <ExplainMore title="How this page works" anchor="invoices">
          Nothing of ours runs for you between visits, so a schedule is worked through when you open Sales, Purchases or this page. It makes everything that has come due since last time, dated on its scheduled day. Approve automatically is your standing approval; everything it does is in the audit log.
        </ExplainMore>
      </div>
      <LiveRepeating />
    </div>
  );
}
