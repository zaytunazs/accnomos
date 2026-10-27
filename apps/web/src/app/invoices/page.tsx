import ExplainMore from "@/components/ExplainMore";
import LiveInvoices from "@/components/invoices/LiveInvoices";

export const metadata = { title: "Invoices · Accnomos" };

export default function InvoicesPage() {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-extrabold tracking-tight">Invoices</h1>
          <p className="mt-1 text-[15px] leading-7 text-muted">
            Write sales invoices, send them from your own Outlook and see who still owes you. Each one is a file in
            your OneDrive; nothing is emailed until you confirm.
          </p>
        </div>
        <ExplainMore title="How invoicing works" anchor="invoices">
          Totals and VAT are worked out by code per line, never by the AI. Sending needs your ticked confirmation, and the sale is posted once. There are no credit notes yet, and Mark paid posts nothing to the bank.
        </ExplainMore>
      </div>
      <LiveInvoices />
    </div>
  );
}
