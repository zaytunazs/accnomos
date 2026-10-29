import PageHeader from "@/components/PageHeader";
import SettingsSection from "@/components/settings/SettingsSection";

export const metadata = { title: "Sales settings · Accnomos" };

export default function SalessettingsPage() {
  return (
    <div className="flex flex-col">
      <PageHeader title="Sales settings" description="What your invoices and quotes say about you, and how customers can pay online." />
      <SettingsSection part="sales" />
    </div>
  );
}
