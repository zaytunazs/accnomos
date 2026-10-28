import PageHeader from "@/components/PageHeader";
import LivePersonal from "@/components/personal/LivePersonal";

export const metadata = { title: "Personal · Accnomos" };

export default function PersonalPage() {
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Personal"
        description="Monthly budgets, regular bills and savings goals from the bank statements you import. Figures are worked out by code; anything estimated says so. This is not financial advice."
      />
      <LivePersonal />
    </div>
  );
}
