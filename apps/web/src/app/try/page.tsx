import HomeDashboard from "@/components/home/HomeDashboard";

export const metadata = { title: "Sample books · Accnomos" };

/** "Try the sample books": Home with the fictional Bramblewood books when signed out (the live dashboard if signed in). */
export default function TryPage() {
  return <HomeDashboard />;
}
