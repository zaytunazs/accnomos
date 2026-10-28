import ExplainMore from "@/components/ExplainMore";
import LiveItems from "@/components/trade/LiveItems";

export const metadata = { title: "Products and services · Accnomos" };

export default function Page() {
  return (
    <div data-print-page className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-extrabold tracking-tight">Products and services</h1>
          <p className="mt-1 text-[15px] leading-7 text-muted">What you sell and buy, once. Pick an item on an invoice, quote or purchase order to fill the line.</p>
        </div>
        <ExplainMore title="How this page works" anchor="invoices">
          Prices are in pounds and pence ex VAT. Invoices still post sales to 4000 Sales whatever an item's income account says. Archiving hides an item from the pickers; documents already written keep their lines.
        </ExplainMore>
      </div>
      <LiveItems />
    </div>
  );
}
