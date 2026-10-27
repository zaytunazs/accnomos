import SettingsPanels from "@/components/settings/SettingsPanels";
import PageHeader from "@/components/PageHeader";

export const metadata = { title: "Settings · Accnomos" };

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-xl">
      <PageHeader
        title="Settings"
        description="Connections, autopilot and housekeeping. Everything here stays on this device."
      />
      <SettingsPanels />
    </div>
  );
}
