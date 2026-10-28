"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "@/lib/msal";
import { itsaBooks } from "@/lib/itsa";
import type { RtBasis } from "@/lib/runtime";

const OPTIONS: { value: RtBasis; label: string; hint: string }[] = [
  { value: "cash", label: "Cash basis", hint: "Income when you're paid, costs when you pay. HMRC's default for sole traders." },
  { value: "traditional", label: "Traditional (accruals)", hint: "Income when you invoice, costs when you're billed." },
];

/**
 * Settings › Business › Accounting basis, under "I am self-employed". Kept in the books (_System/itsa/settings.json), so
 * every device and every update uses the same basis. Changing it changes how the figures are worked out, never the ledger.
 */
export default function AccountingBasisSetting() {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [basis, setBasis] = useState<RtBasis | null>(null);
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");

  useEffect(() => {
    let stale = false;
    (async () => {
      try {
        if (!msalConfigured()) return;
        const msal = await getMsal();
        const acct = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
        if (!acct || stale) return;
        setAccount(acct);
        const s = await itsaBooks.settings(acct);
        if (!stale) setBasis(s.accounting_basis);
      } catch {
        if (!stale) setState("error");
      }
    })();
    return () => {
      stale = true;
    };
  }, []);

  async function choose(next: RtBasis) {
    if (!account || next === basis) return;
    const before = basis;
    setBasis(next);
    setState("saving");
    try {
      await itsaBooks.saveSettings(account, next);
      setState("saved");
    } catch {
      setBasis(before);
      setState("error");
    }
  }

  if (!account) return null; // signed out: the figures come from the books, so there is nothing to choose for yet

  return (
    <div className="mt-4 border-t border-border pt-4">
      <h4 id="settings-accounting-basis" className="text-[15px] font-bold">Accounting basis</h4>
      <p className="mt-1 text-sm text-muted">
        How your self-employment figures and quarterly updates are worked out. Changing it doesn&apos;t change any entry. Tell
        HMRC the same method at the end of the tax year.
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2" role="radiogroup" aria-labelledby="settings-accounting-basis">
        {OPTIONS.map((o) => {
          const active = basis === o.value;
          return (
            <button
              key={o.value}
              type="button"
              role="radio"
              aria-checked={active}
              disabled={basis === null || state === "saving"}
              onClick={() => choose(o.value)}
              className={`rounded-xl border p-3 text-left disabled:opacity-60 ${
                active ? "border-2 border-teal bg-teal-tint text-teal-dark" : "border-border text-ink"
              }`}
            >
              <span className="block text-[15px] font-bold">
                {o.label}
                {o.value === "cash" ? " (default)" : ""}
              </span>
              <span className="mt-0.5 block text-[13px] text-muted">{o.hint}</span>
            </button>
          );
        })}
      </div>
      <p role="status" className="mt-2 text-[13px] text-muted">
        {state === "saved" && "Saved. Your self-employment figures now use this basis."}
        {state === "error" && "Couldn't reach your books to read or save the accounting basis. Try again."}
      </p>
    </div>
  );
}
