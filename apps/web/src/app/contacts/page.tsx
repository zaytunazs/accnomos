import LiveContacts from "@/components/contacts/LiveContacts";

export default function ContactsPage() {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight">Contacts</h1>
        <p className="mt-1 text-[15px] leading-7 text-muted">
          Your customers and suppliers, taken from your books. Balances and statements are worked out from the
          ledger each time; only names and details are saved, in your OneDrive.
        </p>
      </div>
      <LiveContacts />
    </div>
  );
}
