import ExplainMore from "@/components/ExplainMore";
import SalesOverview from "@/components/trade/SalesOverview";

export const metadata = { title: "Sales · Accnomos" };

export default function Page() {
  return (
    <div data-print-page className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-extrabold tracking-tight">Sales</h1>
          <p className="mt-1 text-[15px] leading-7 text-muted">What you are owed, what is overdue and what came in, with customer statements. Every figure is worked out by code from your own files.</p>
        </div>
        <ExplainMore title="How this page works" anchor="invoices">
          Nothing here is estimated by an AI. Awaiting payment is what is left on sent invoices after payments and credit notes; overdue means past the due date. Repeating invoices that have come due are made when this page opens.
        </ExplainMore>
      </div>
      <SalesOverview />
    </div>
  );
}
