import CashFlow from "@/components/accounting/CashFlow";
import { ToolPage } from "@/components/accounting/Shared";

export const metadata = { title: "Short-term cash flow · Accnomos" };

export default function Page() {
  return (
    <ToolPage
      title="Short-term cash flow"
      description="The next 30, 60 and 90 days from your bank balance and the invoices and bills still open, by due date. Worked out by code."
    >
      <CashFlow />
    </ToolPage>
  );
}
