import PageHeader from "@/components/PageHeader";
import SelfEmployment from "@/components/itsa/SelfEmployment";
import SelfEmployedHint from "@/components/itsa/SelfEmployedHint";

export const metadata = { title: "Self-employment (MTD Income Tax) · Accnomos" };

export default function SelfEmploymentPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Self-employment (MTD Income Tax)"
        description="Quarterly updates for Making Tax Digital for Income Tax, worked out by code from the entries you approved."
      />
      <SelfEmployedHint />
      <SelfEmployment />
    </div>
  );
}
