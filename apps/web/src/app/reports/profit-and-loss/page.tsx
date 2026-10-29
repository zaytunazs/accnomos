import PageHeader from "@/components/PageHeader";
import LiveReports from "@/components/reports/LiveReports";

export const metadata = { title: "Profit and loss · Accnomos" };

/** Reporting › Profit and loss: the report on its own page (also part of /reports). */
export default function ProfitAndLossPage() {
  return (
    <div data-print-page className="flex flex-col gap-6">
      <PageHeader
        title="Profit and loss"
        description="Sales, cost of sales and overheads for the period picked on the VAT page, worked out by code from the entries you approved."
      />
      <LiveReports only="pl" />
    </div>
  );
}
