import type { Metadata } from "next";
import HomeDashboard from "@/components/home/HomeDashboard";
import HomeSwitch from "@/components/marketing/HomeSwitch";
import Landing from "@/components/marketing/Landing";

export const metadata: Metadata = {
  title: "Accnomos · AI bookkeeping and MTD VAT for UK small businesses",
  description:
    "AI proposes, you approve, code calculates. Meta models read your receipts, you approve every entry, code works out the nine VAT boxes, and your books stay in your own OneDrive.",
};

/** Signed out: the public landing page. Signed in: Home, the owner's dashboard. */
export default function HomePage() {
  return <HomeSwitch landing={<Landing />} home={<HomeDashboard />} />;
}
