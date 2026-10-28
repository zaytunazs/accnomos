import FixedAssets from "@/components/accounting/FixedAssets";
import { ToolPage } from "@/components/accounting/Shared";

export const metadata = { title: "Fixed assets · Accnomos" };

export default function Page() {
  return (
    <ToolPage
      title="Fixed assets"
      description="Your asset register, depreciation runs and disposals. Each run or disposal is a journal for you to approve."
    >
      <FixedAssets />
    </ToolPage>
  );
}
