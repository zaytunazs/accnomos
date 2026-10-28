"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { fieldInput, fieldLabel } from "@/components/invoices/Modal";
import { runtime, type RtSalesOverview } from "@/lib/runtime";

/** Choose a customer to open their statement. The list is the contact book's customers (GET /contacts), which
 *  includes customers known only from the ledger: the statement route takes those ids, and an invoice's customer
 *  often has no saved contact id (the picker used to list only those that did, so it never showed). */
export default function StatementPicker({ account, onOpen }: { account: AccountInfo; owed: RtSalesOverview; onOpen: (c: { id: string; name: string }) => void }) {
  const [customers, setCustomers] = useState<{ id: string; name: string }[]>([]);
  const [pick, setPick] = useState("");
  useEffect(() => {
    runtime
      .contacts(account)
      .then((list) =>
        setCustomers(
          list.contacts
            .filter((c) => c.kind !== "supplier")
            .map((c) => ({ id: c.id, name: c.name }))
            .sort((a, b) => a.name.localeCompare(b.name)),
        ),
      )
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
