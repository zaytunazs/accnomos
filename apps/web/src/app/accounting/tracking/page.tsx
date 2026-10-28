import Tracking from "@/components/accounting/Tracking";
import { ToolPage } from "@/components/accounting/Shared";

export const metadata = { title: "Tracking · Accnomos" };

export default function Page() {
  return (
    <ToolPage
      title="Tracking"
      description="Up to two tracking categories, such as Department or Project, and the Tracking Summary: profit and loss by option."
    >
      <Tracking />
    </ToolPage>
  );
}
