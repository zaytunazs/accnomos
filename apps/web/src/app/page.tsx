import type { Metadata } from "next";
import HomeDashboard from "@/components/home/HomeDashboard";
import HomeSwitch from "@/components/marketing/HomeSwitch";
import Landing from "@/components/marketing/Landing";

export const metadata: Metadata = {
  title: "Accnomos · AI bookkeeping and MTD VAT for UK small businesses",
  // docs/marketing/COPY.md, "Meta description".
  description:
    "Bookkeeping for UK small firms: AI reads the paperwork, you approve, code does the VAT. Books kept in your OneDrive.",
};

/** Signed out: the public landing page. Signed in: Home, the owner's dashboard. */
export default function HomePage() {
  return <HomeSwitch landing={<Landing />} home={<HomeDashboard />} />;
}
