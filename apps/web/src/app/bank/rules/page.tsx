import LiveBank from "@/components/bank/LiveBank";
import PageHeader from "@/components/PageHeader";

export const metadata = { title: "Bank rules · Accnomos" };

/** Accounting › Bank rules: the rules on a page of their own (the same rules as /bank's Rules tab). */
export default function BankRulesPage() {
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Bank rules"
        description="How a regular payment is coded when it appears on a statement: by name, amount and direction. A rule suggests; you still confirm each match."
      />
      <LiveBank view="rules" />
    </div>
  );
}
