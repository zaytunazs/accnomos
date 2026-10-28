import Explain from "@/components/Explain";
import PageHeader from "@/components/PageHeader";
import ImportWizard from "@/components/import/ImportWizard";

export const metadata = { title: "Import history · Accnomos" };

export default function ImportPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Import history"
        description="Switching from Xero, QuickBooks Online, Sage, FreeAgent or a spreadsheet: bring your opening balances, contacts and unpaid invoices and bills over, checked to the penny."
        action={
          <Explain title="How the import works">
            <p>
              Upload the old system&apos;s exports. The trial balance at your conversion date is required; the chart of
              accounts, contacts, open invoices and bills, and bank balances make the result better.
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li><strong>Map accounts</strong> — every account gets a suggested Accnomos account, which you can change. An account we cannot place is flagged and must be mapped before anything is posted.</li>
              <li><strong>One opening entry</strong> — after you approve it, code posts one balanced entry dated the day before your conversion date. It carries no VAT, so no VAT return counts it.</li>
              <li><strong>Unpaid invoices and bills</strong> — kept as open items, so aged debtors and creditors, statements and Record payment work from day one.</li>
              <li><strong>Reconciliation</strong> — the Accnomos trial balance is worked out again from the ledger and compared, account by account, with the one you uploaded. A copy is saved in 07 Reports.</li>
            </ul>
            <p>Undo reverses the opening entry. The files you uploaded are kept in _System/Import as they came.</p>
          </Explain>
        }
      />
      <ImportWizard />
    </div>
  );
}
