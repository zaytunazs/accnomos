import LiveInvoices from "@/components/invoices/LiveInvoices";

export const metadata = { title: "Invoices · Accnomos" };

export default function InvoicesPage() {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight">Invoices</h1>
        <p className="mt-1 text-[15px] leading-7 text-muted">
          Write sales invoices, send them from your own Outlook and see who still owes you. Each one is a file in
          your OneDrive; nothing is emailed until you confirm.
        </p>
      </div>
      <LiveInvoices />
    </div>
  );
}
