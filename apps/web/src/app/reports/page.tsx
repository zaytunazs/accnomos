import Link from "next/link";
import Explain from "@/components/Explain";
import PageHeader from "@/components/PageHeader";
import LiveReports from "@/components/reports/LiveReports";

export const metadata = { title: "Reports · Accnomos" };

export default function ReportsPage() {
  return (
    <div data-print-page className="flex flex-col gap-6">
      <PageHeader
        title="Reports"
        description="Profit and loss, who owes what, VAT by period and the last 12 months, worked out by code from the entries you approved."
        action={
          <Explain title="How the reports are worked out">
            <p>
              Every figure is calculated by code from your approved ledger entries — no model is involved, and
              looking at a report changes nothing in your books.
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li><strong>Profit and loss</strong> — as approved: an invoice counts when it was raised, a receipt when it was bought. Sales are the 4000 accounts, cost of sales the 5000s, overheads 6000 to 8999. VAT and the bank never appear.</li>
              <li><strong>Aged balances</strong> — unpaid invoices and bills by age, the same figures as on Contacts.</li>
              <li><strong>VAT by period</strong> — the 9-box calculation for each of the last four periods.</li>
              <li><strong>Last 12 months</strong> — sales, purchases (cost of sales plus overheads) and the net each month.</li>
            </ul>
            <p>
              <em>Export to OneDrive</em> saves a spreadsheet in 07 Reports; it never posts anything.
            </p>
          </Explain>
        }
      />
      <p className="text-[15px] print:hidden">
        <Link href="/reports/exports" className="font-bold text-teal-dark underline underline-offset-2 hover:text-teal">
          Reports &amp; exports
        </Link>
        <span className="text-muted"> · trial balance, ledger, balance sheet, HMRC VAT return, the Accountant pack and files for Xero, QuickBooks, Sage and FreeAgent</span>
      </p>
      <LiveReports />
    </div>
  );
}
