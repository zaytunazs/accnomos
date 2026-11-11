"use client";

import { useEffect, useState } from "react";
import { money } from "@/lib/invoices";
import type { AccountInfo } from "@azure/msal-browser";
import { runtime, type RtPaypalTieOut } from "@/lib/runtime";

function signed(p: number): string {
  return p < 0 ? `−${money(-p)}` : money(p);
}

function londonTime(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", { timeZone: "Europe/London", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** "Is my PayPal money in my books?": PayPal's own balance against 1240 PayPal clearing, with the difference explained
 *  by what is waiting for approval and what Accnomos never posts. Read-only. */
export default function PayPalTieOut({ account, refresh }: { account: AccountInfo; refresh: number }) {
  const [t, setT] = useState<RtPaypalTieOut | null>(null);
  useEffect(() => {
    let live = true;
    runtime
      .paypalTieOut(account)
      .then((x) => live && setT(x))
      .catch(() => live && setT(null));
    return () => {
      live = false;
    };
  }, [account, refresh]);
  if (!t || !t.available || t.paypal_pence == null) return null;
  const ok = t.unexplained_pence === 0;
  return (
    <div className={`rounded-xl border p-3 text-sm ${ok ? "border-border bg-ground/40" : "border-warn-ink/40 bg-warn-bg/40"}`} aria-label="PayPal and your books">
      <p className="font-bold">
        PayPal says {money(t.paypal_pence)}
        {t.paypal_as_of ? ` (as of ${londonTime(t.paypal_as_of)})` : ""} · your books (1240 PayPal clearing) {signed(t.books_pence)}
      </p>
      <p className="text-muted">
        Difference {signed(t.difference_pence ?? 0)} = waiting for your approval {signed(t.waiting_pence)} + not posted (withdrawals, refunds,
        opening balance and the like) {signed(t.not_posted_pence)}
        {t.unexplained_pence ? <> + <span className="font-bold text-warn-ink">unexplained {signed(t.unexplained_pence)}</span></> : null}.
      </p>
      {t.notes.map((n) => (
        <p key={n} className="text-muted">{n}</p>
      ))}
    </div>
  );
}
