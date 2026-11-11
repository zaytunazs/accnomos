import PageHeader from "@/components/PageHeader";
import SupportDesk from "@/components/support/SupportDesk";

export const metadata = { title: "Support · Accnomos", robots: { index: false, follow: false } };

export default function Page() {
  return (
    <div className="flex flex-col">
      <PageHeader title="Support" description="Ask the support assistant, follow your tickets, or raise a new one." />
      <SupportDesk />
    </div>
  );
}
