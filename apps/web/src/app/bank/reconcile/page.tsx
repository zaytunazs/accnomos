import LiveBank from "@/components/bank/LiveBank";
import PageHeader from "@/components/PageHeader";

export const metadata = { title: "Reconcile · Accnomos" };

/** Accounting › Reconcile: the reconciliation on a page of its own (the same as /bank's Reconcile tab). */
export default function BankReconcilePage() {
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Reconcile"
        description="Check your statement balance against the books, one statement at a time, and clear what is left. Matching never posts anything."
      />
      <LiveBank view="reconcile" />
    </div>
  );
}
