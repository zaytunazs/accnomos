import PageHeader from "@/components/PageHeader";
import LiveReports from "@/components/reports/LiveReports";

export const metadata = { title: "Aged receivables and payables · Accnomos" };

/** Reporting › Aged receivables and payables: who owes what and for how long (also part of /reports). */
export default function AgedPage() {
  return (
    <div data-print-page className="flex flex-col gap-6">
      <PageHeader
        title="Aged receivables and payables"
        description="Unpaid sales invoices and bills by days past their due date, the same figures as on Contacts."
      />
      <LiveReports only="aged" />
    </div>
  );
}
