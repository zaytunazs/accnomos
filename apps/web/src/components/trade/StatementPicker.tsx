"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { fieldInput, fieldLabel } from "@/components/invoices/Modal";
import { runtime, type RtContact, type RtSalesOverview } from "@/lib/runtime";

/** Choose a customer to open their statement. The list is the contact book as the Contacts page shows it (saved
 * contacts plus everyone the ledger names), so a customer known only from an invoice can still be chosen. */
export default function StatementPicker({ account, onOpen }: { account: AccountInfo; owed: RtSalesOverview; onOpen: (c: { id: string; name: string }) => void }) {
  const [customers, setCustomers] = useState<RtContact[]>([]);
  const [pick, setPick] = useState("");
  useEffect(() => {
    runtime.contacts(account)
      .then((l) => setCustomers(l.contacts.filter((c) => c.kind !== "supplier").sort((a, b) => a.name.localeCompare(b.name))))
      .catch(() => setCustomers([]));
  }, [account]);
  if (customers.length === 0) return null;
  return (
    <section aria-labelledby="statements-h" className="rounded-2xl border border-border bg-white p-4">
      <h2 id="statements-h" className="text-[17px] font-extrabold">Customer statements</h2>
      <p className="mt-1 text-sm text-muted">What a customer was charged and paid, and what they still owe. Download it or email it from your Outlook.</p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <label className={fieldLabel} htmlFor="st-customer">Customer</label>
          <select id="st-customer" className={fieldInput} value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">Choose a customer</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <button type="button" disabled={!pick} onClick={() => { const c = customers.find((x) => x.id === pick)!; onOpen({ id: pick, name: c.name }); }}
          className="h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60">Open statement</button>
      </div>
    </section>
  );
}
