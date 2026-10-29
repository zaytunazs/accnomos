import PageHeader from "@/components/PageHeader";
import SettingsSection from "@/components/settings/SettingsSection";

export const metadata = { title: "Tax settings · Accnomos" };

export default function TaxsettingsPage() {
  return (
    <div className="flex flex-col">
      <PageHeader title="Tax settings" description="Your VAT periods and VAT scheme, used for the VAT return, its deadlines and the reports." />
      <SettingsSection part="tax" />
    </div>
  );
}
