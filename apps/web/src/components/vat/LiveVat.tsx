"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "@/lib/msal";
import { fetchLiveVat, type RtVatBox as Box, type RtVatView as VatView } from "@/lib/runtime";

const fmt = (b: Box) => (b.box <= 5 ? `£${Number(b.amount).toLocaleString("en-GB", { minimumFractionDigits: 2 })}` : `£${Number(b.amount).toLocaleString("en-GB")}`);
const uk = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

/** Live 9-box return computed by code from the user's posted ledger events. Hidden unless signed in and the runtime answers. */
export default function LiveVat() {
  const [view, setView] = useState<VatView | null>(null);
  const [state, setState] = useState<"idle" | "live" | "off">("idle");

  useEffect(() => {
    (async () => {
      try {
        if (!msalConfigured()) return setState("off");
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct: AccountInfo | undefined = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
        if (!acct) return setState("off");
        setView(await fetchLiveVat(acct));
        setState("live");
      } catch {
        setState("off");
      }
    })();
  }, []);

  if (state !== "live" || !view) return null;
  const net = view.boxes.find((b) => b.box === 5)!;
  return (
    <section aria-labelledby="live-vat" className="rounded-2xl border border-teal bg-white p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="live-vat" className="text-lg font-extrabold">
          Your return · {uk(view.start)} – {uk(view.end)} · key {view.period_key}
        </h2>
        <span className="text-sm text-muted">{view.events_in_period} approved entries · calculated by code</span>
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-[15px]">
          <tbody>
            {view.boxes.map((b) => (
              <tr key={b.box} className={`border-t border-border ${b.box === 3 || b.box === 5 ? "bg-ground" : ""}`}>
                <td className="w-12 py-2 pr-2 font-extrabold">{b.box}</td>
                <td className="py-2 pr-2">{b.label}</td>
                <td className={`py-2 text-right font-bold ${b.box === 5 ? "text-[17px]" : ""}`}>{fmt(b)}</td>
                <td className="w-20 py-2 text-right text-sm text-muted">{b.entries || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {view.warnings.length > 0 && (
        <p className="mt-3 rounded-xl border border-warn-border bg-warn-bg p-3 text-sm text-warn-ink">{view.warnings.join(" · ")}</p>
      )}
      <p className="mt-3 text-sm text-muted">
        Net VAT to pay: <strong className="text-ink">{fmt(net)}</strong>. Connect to HMRC below to submit it to the sandbox.
      </p>
    </section>
  );
}
