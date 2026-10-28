import Budgets from "@/components/accounting/Budgets";
import { ToolPage } from "@/components/accounting/Shared";

export const metadata = { title: "Budgets · Accnomos" };

export default function Page() {
  return (
    <ToolPage
      title="Budgets"
      description="A monthly budget per income and cost account for a year, its summary, and the variance against what actually happened."
    >
      <Budgets />
    </ToolPage>
  );
}
