import FindRecode from "@/components/accounting/FindRecode";
import { ToolPage } from "@/components/accounting/Shared";

export const metadata = { title: "Find and recode · Accnomos" };

export default function Page() {
  return (
    <ToolPage
      title="Find and recode"
      description="Search posted lines and move them to another account or VAT code. History is never edited: code adds adjusting entries."
    >
      <FindRecode />
    </ToolPage>
  );
}
