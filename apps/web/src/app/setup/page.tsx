import type { Metadata } from "next";
import SetupWizard from "@/components/setup/SetupWizard";
import PageHeader from "@/components/PageHeader";

export const metadata: Metadata = {
  title: "Set up your business · Accnomos",
};

/** First-run set-up wizard, also reached from Settings › Business. One question per step, saved as you go. */
export default function SetupPage() {
  return (
    <div className="mx-auto max-w-xl">
      <PageHeader
        title="Set up your business"
        description="One question at a time. Saved as you go into your own books — nothing is filed."
      />
      <SetupWizard />
    </div>
  );
}
