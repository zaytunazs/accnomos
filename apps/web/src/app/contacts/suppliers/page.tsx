import LiveContacts from "@/components/contacts/LiveContacts";
import PageHeader from "@/components/PageHeader";

export const metadata = { title: "Suppliers · Accnomos" };

/** Contacts › Suppliers: the contact list opened on suppliers (the filter can still show everyone). */
export default function SuppliersPage() {
  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Suppliers" description="The businesses you buy from, with what you owe each. Worked out from your ledger; only names and details are saved, in your OneDrive." />
      <LiveContacts kind="supplier" />
    </div>
  );
}
