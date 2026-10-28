import Portal from "@/components/accountant/Portal";
import PageHeader from "@/components/PageHeader";

export const metadata = { title: "Accountant portal · Accnomos" };

export default function AccountantPage() {
  return (
    <div className="flex flex-col">
      <PageHeader
        title="Accountant portal"
        description="Your clients' Accnomos books, as they shared them with your Microsoft account. Open one to use the usual pages on their books, view only or with edit access if they gave it; every change is recorded under your name in their audit trail."
      />
      <Portal />
    </div>
  );
}
