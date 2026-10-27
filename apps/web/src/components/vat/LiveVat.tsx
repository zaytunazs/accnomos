"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "@/lib/msal";
import { fetchLiveVat, type RtVatBox as Box, type RtVatView as VatView } from "@/lib/runtime";
import { usePickedPeriod } from "@/lib/vat-period";
import VatPeriodPicker from "./VatPeriodPicker";

const fmt = (b: Box) => (b.box <= 5 ? `£${Number(b.amount).toLocaleString("en-GB", { minimumFractionDigits: 2 })}` : `£${Number(b.amount).toLocaleString("en-GB")}`);
const uk = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

/** Live 9-box return computed by code from the user's posted ledger events. Hidden unless signed in and the runtime answers. */
export default function LiveVat() {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [view, setView] = useState<VatView | null>(null);
  const [state, setState] = useState<"idle" | "live" | "off">("idle");
  const picked = usePickedPeriod();

  useEffect(() => {
    (async () => {
      try {
        if (!msalConfigured()) return setState("off");
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct: AccountInfo | undefined = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
        if (!acct) return setState("off");
        setAccount(acct);
      } catch {
        setState("off");
      }
    })();
  }, []);

  useEffect(() => {
    if (!account) return;
    let stale = false;
    fetchLiveVat(account, picked?.period ?? null).then(
      (v) => {
        if (stale) return;
        setView(v);
        setState("live");
      },
      () => !stale && setState("off"),
    );
    return () => {
      stale = true;
    };
  }, [account, picked?.period]);

  if (state !== "live" || !view || !account) return null;
  const net = view.boxes.find((b) => b.box === 5)!;
  return (
    <section aria-labelledby="live-vat" className="rounded-2xl border border-teal bg-white p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <VatPeriodPicker account={account} />
        <Link href="/ask" className="text-[15px] font-bold text-teal underline underline-offset-2 hover:text-teal-dark">
          Ask about {view.label}
        </Link>
      </div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="live-vat" className="text-lg font-extrabold">
          Your return · {view.label}
          {view.current ? " (current period)" : ""} · {uk(view.start)} – {uk(view.end)}
        </h2>
        <span className="text-sm text-muted">{view.events_in_period} approved entries · calculated by code</span>
      </div>
      {/* Phone: one card per box. Wider screens: the 9-box table. */}
      <ul className="mt-3 flex flex-col gap-2 sm:hidden">
        {view.boxes.map((b) => (
          <li
            key={b.box}
            className={`rounded-xl border p-3 ${
              b.box === 3 || b.box === 5 ? "border-border bg-ground" : "border-border bg-white"
            }`}
          >
            <div className="flex items-baseline justify-between gap-2">
              <p className="text-[14px] font-extrabold">
                Box {b.box} · {b.label}
              </p>
              <p className={`shrink-0 font-bold tabular-nums ${b.box === 5 ? "text-[17px]" : "text-[14px]"}`}>
                {fmt(b)}
              </p>
            </div>
            {b.entries ? (
              <p className="mt-0.5 text-[13px] text-muted">{b.entries} entries</p>
            ) : null}
          </li>
        ))}
      </ul>
      <div className="mt-3 hidden overflow-x-auto sm:block">
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
        Net VAT to pay: <strong className="text-ink">{fmt(net)}</strong>.{" "}
        {view.can_submit
          ? "Connect to HMRC below to submit it to the sandbox."
          : view.submitted
            ? "This return has already been submitted; its receipt is in 05 VAT returns."
            : "Only the current or previous period can be submitted from here."}
      </p>
    </section>
  );
}
