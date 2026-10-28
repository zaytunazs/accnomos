import ExplainMore from "@/components/ExplainMore";
import PurchasesOverview from "@/components/trade/PurchasesOverview";

export const metadata = { title: "Purchases · Accnomos" };

export default function Page() {
  return (
    <div data-print-page className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-extrabold tracking-tight">Purchases</h1>
          <p className="mt-1 text-[15px] leading-7 text-muted">What you owe, what is overdue and what went out, plus bills and orders waiting for you. Every figure is worked out by code from your own files.</p>
        </div>
        <ExplainMore title="How this page works" anchor="invoices">
          Bills count as owed once you approve them in Review. A bill is due on its supplier&apos;s payment terms (30 days if none are set). Repeating bills that have come due are made when this page opens.
        </ExplainMore>
      </div>
      <PurchasesOverview />
    </div>
  );
}
