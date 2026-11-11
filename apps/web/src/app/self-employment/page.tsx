import PageHeader from "@/components/PageHeader";
import SelfEmployment from "@/components/itsa/SelfEmployment";
import SelfEmployedHint from "@/components/itsa/SelfEmployedHint";
import { ItsaFileItYourself } from "@/components/filing/FileItYourself";

export const metadata = { title: "Self-employment (MTD Income Tax) · Accnomos", robots: { index: false, follow: false } };

export default function SelfEmploymentPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Self-employment (MTD Income Tax)"
        description="Quarterly update figures for Making Tax Digital for Income Tax and your Self Assessment pages, worked out by code from the entries you approved."
      />
      <SelfEmployedHint />
      <SelfEmployment />
      <ItsaFileItYourself />
    </div>
  );
}
