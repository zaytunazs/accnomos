import ChartOfAccounts from "@/components/accounting/ChartOfAccounts";
import { ToolPage } from "@/components/accounting/Shared";

export const metadata = { title: "Chart of accounts · Accnomos" };

export default function Page() {
  return (
    <ToolPage
      title="Chart of accounts"
      description="The accounts your entries are posted to: codes, names, types and default VAT. Accounts with postings are archived, never deleted."
    >
      <ChartOfAccounts />
    </ToolPage>
  );
}
