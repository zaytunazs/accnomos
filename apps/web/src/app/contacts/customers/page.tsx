import LiveContacts from "@/components/contacts/LiveContacts";
import PageHeader from "@/components/PageHeader";

export const metadata = { title: "Customers · Accnomos" };

/** Contacts › Customers: the contact list opened on customers (the filter can still show everyone). */
export default function CustomersPage() {
  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Customers" description="The people and businesses you sell to, with what each owes you. Worked out from your ledger; only names and details are saved, in your OneDrive." />
      <LiveContacts kind="customer" />
    </div>
  );
}
