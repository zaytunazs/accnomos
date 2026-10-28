import ExplainMore from "@/components/ExplainMore";
import LiveQuotes from "@/components/trade/LiveQuotes";

export const metadata = { title: "Quotes · Accnomos" };

export default function Page() {
  return (
    <div data-print-page className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-extrabold tracking-tight">Quotes</h1>
          <p className="mt-1 text-[15px] leading-7 text-muted">Write a quote, send it from your own Outlook, and turn it into an invoice when the customer says yes. Nothing is emailed until you confirm.</p>
        </div>
        <ExplainMore title="How this page works" anchor="invoices">
          Totals and VAT are worked out by code per line. A sent quote that passes its valid-until date shows as expired. Convert to invoice makes a draft invoice with exactly the quote's lines and totals; you still check and send it on the Invoices page.
        </ExplainMore>
      </div>
      <LiveQuotes />
    </div>
  );
}
