import PageHeader from "@/components/PageHeader";
import SettingsSection from "@/components/settings/SettingsSection";

export const metadata = { title: "Employees · Accnomos" };

export default function EmployeesPage() {
  return (
    <div className="flex flex-col">
      <PageHeader title="Employees" description="The people you pay or whose hours you log: pay rates, charge-out rates and payroll details." />
      <SettingsSection part="employees" />
    </div>
  );
}
