import ExplainMore from "@/components/ExplainMore";
import LiveContacts from "@/components/contacts/LiveContacts";

export default function ContactsPage() {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-extrabold tracking-tight">Contacts</h1>
          <p className="mt-1 text-[15px] leading-7 text-muted">
            Your customers and suppliers, taken from your books. Balances and statements are worked out from the
            ledger each time; only names and details are saved, in your OneDrive.
          </p>
        </div>
        <ExplainMore title="How contacts work" anchor="contacts">
          Contacts are rebuilt from your ledger by code, so a rename to another contact’s name is refused and two tabs editing at once means last write wins. Import from Outlook only fills blank details unless you also add new contacts.
        </ExplainMore>
      </div>
      <LiveContacts />
    </div>
  );
}
