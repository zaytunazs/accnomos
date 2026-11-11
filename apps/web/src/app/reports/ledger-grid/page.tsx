import PageHeader from "@/components/PageHeader";
import LedgerExplorer from "@/components/grid/LedgerExplorerLazy";

export const metadata = { title: "Ledger explorer · Accnomos", robots: { index: false, follow: false } };

/** Reporting › Ledger explorer: the Power grid add-on's view of every journal line (Settings › Business › Power grid). */
export default function LedgerGridPage() {
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        title="Ledger explorer"
        description="Your journal lines in a grid, account by account: sort and filter any column, see totals of what is shown, export CSV, or type what you want to see."
      />
      <LedgerExplorer />
    </div>
  );
}
