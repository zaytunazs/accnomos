import ManualJournals from "@/components/accounting/ManualJournals";
import { ToolPage } from "@/components/accounting/Shared";

export const metadata = { title: "Manual journals · Accnomos" };

export default function Page() {
  return (
    <ToolPage
      title="Manual journals"
      description="Balanced journals you write yourself, with optional VAT, a reversal date and a document. They post only when you approve them."
    >
      <ManualJournals />
    </ToolPage>
  );
}
