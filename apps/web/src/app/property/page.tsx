import PageHeader from "@/components/PageHeader";
import LiveProperty from "@/components/property/LiveProperty";

export const metadata = { title: "Property · Accnomos" };

export default function PropertyPage() {
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Property"
        description="Rent and costs for the homes or rooms you let, split between owners, in HMRC's UK property categories. Figures are worked out by code; the tax reduction on mortgage interest is an estimate."
      />
      <LiveProperty />
    </div>
  );
}
