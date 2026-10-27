import SettingsPanels from "@/components/settings/SettingsPanels";

export const metadata = { title: "Settings · Accnomos" };

export default function SettingsPage() {
  return (
    <main className="mx-auto max-w-xl px-4 py-10">
      <h1 className="text-3xl font-extrabold tracking-tight text-ink">Settings</h1>
      <p className="mt-2 text-[15px] leading-relaxed text-muted">
        Connections, autopilot and housekeeping. Everything here stays on this device.
      </p>
      <SettingsPanels />
    </main>
  );
}
