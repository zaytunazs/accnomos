"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "@/lib/msal";
import { loadBusiness } from "@/lib/business";
import PrintButton from "@/components/PrintButton";
import { fetchLiveVat, type RtVatBox as Box, type RtVatAdjustment, type RtVatPeriod, type RtVatView as VatView } from "@/lib/runtime";
import { usePickedPeriod } from "@/lib/vat-period";
import BoxExplain from "./BoxExplain";
import SchemeNote from "./SchemeNote";
import VatPeriodPicker from "./VatPeriodPicker";

const fmt = (b: Box) => (b.box <= 5 ? `£${Number(b.amount).toLocaleString("en-GB", { minimumFractionDigits: 2 })}` : `£${Number(b.amount).toLocaleString("en-GB")}`);
const uk = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
const shortUk = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
};

const DAY_MS = 86_400_000;

const signedPounds = (pence: number) =>
  `${pence < 0 ? "−" : ""}£${(Math.abs(pence) / 100).toLocaleString("en-GB", { minimumFractionDigits: 2 })}`;

/** Journals and recodes with VAT in this return: which boxes each one moved, and by how much (signed). */
function Adjustments({ rows }: { rows: RtVatAdjustment[] }) {
  return (
    <section aria-labelledby="vat-adjustments" className="mt-4 rounded-xl border border-border p-3">
      <h3 id="vat-adjustments" className="text-[15px] font-extrabold">
        Journals and adjustments in this return
      </h3>
      <ul className="mt-2 flex flex-col gap-2">
        {rows.map((a) => (
          <li key={a.event_id} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-[14px]">
            <span className="min-w-0 [overflow-wrap:anywhere]">
              <strong>{a.name}</strong> · {shortUk(a.date)}
              {a.note ? ` · ${a.note}` : ""}
            </span>
            <span className="shrink-0 tabular-nums text-muted">
              {a.side === "sales"
                ? `Box 1 ${signedPounds(a.vat_pence)} · Box 6 ${signedPounds(a.net_pence)}`
                : `Box 4 ${signedPounds(a.vat_pence)} · Box 7 ${signedPounds(a.net_pence)}`}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[13px] text-muted">
        <Link href="/accounting/journals" className="font-bold text-teal underline underline-offset-2">
          Manual journals
        </Link>{" "}
        lists each one in full; a void or an automatic reversal shows here with the opposite sign.
      </p>
    </section>
  );
}

/** Whole days from today (UTC) to an ISO date: positive = left, zero = today, negative = late. */
function daysUntil(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  const now = new Date();
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((Date.UTC(y, m - 1, d) - today) / DAY_MS);
}

function daysText(n: number): string {
  if (n === 0) return "due today";
  if (n < 0) return `${-n} day${n === -1 ? "" : "s"} late`;
  return `${n} day${n === 1 ? "" : "s"} left`;
}

/** Live 9-box return computed by code from the user's posted ledger events. Hidden unless signed in and the runtime answers. */
export default function LiveVat() {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [view, setView] = useState<VatView | null>(null);
  const [periods, setPeriods] = useState<RtVatPeriod[] | null>(null);
  const [state, setState] = useState<"idle" | "live" | "off">("idle");
  // Print-only: who the return is for. Read once (loadBusiness is localStorage-only and null-safe).
  const [business] = useState<{ name: string; vatNumber: string } | null>(() => {
    const b = loadBusiness();
    return b && (b.name || b.vatNumber) ? { name: b.name, vatNumber: b.vatNumber } : null;
  });
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
  // Box 5's direction the way the runtime works it out (total VAT due minus reclaimed):
  // positive = pay, negative = reclaim, zero = nil.
  const diff = Math.round((Number(view.hmrc_body.totalVatDue ?? 0) - Number(view.hmrc_body.vatReclaimedCurrPeriod ?? 0)) * 100) / 100;
  const period = periods?.find((p) => p.period === (picked?.period ?? periods.find((q) => q.current)?.period));
  const box5Note = period
    ? diff > 0
      ? `${fmt(net)} to pay · due ${shortUk(period.deadline)} · ${daysText(daysUntil(period.deadline))}`
      : diff < 0
        ? `${fmt(net)} to reclaim · due ${shortUk(period.deadline)} · ${daysText(daysUntil(period.deadline))}`
        : `Nothing to pay · return due ${shortUk(period.deadline)} · ${daysText(daysUntil(period.deadline))}`
    : null;
  return (
    <section aria-labelledby="live-vat" className="rounded-2xl border border-teal bg-white p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3 print:hidden">
        <VatPeriodPicker account={account} onPeriods={setPeriods} />
        <span className="flex flex-wrap items-center gap-3">
          <Link href="/ask" className="text-[15px] font-bold text-teal underline underline-offset-2 hover:text-teal-dark">
            Ask about {view.label}
          </Link>
          <PrintButton />
        </span>
      </div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="live-vat" className="min-w-0 text-lg font-extrabold [overflow-wrap:anywhere]">
          Your return · {view.label}
          {view.current ? " (current period)" : ""} · {uk(view.start)} – {uk(view.end)}
        </h2>
        <span className="text-sm text-muted">
          {view.undone_in_period > 0
            ? `${view.events_in_period} entries, ${view.undone_in_period} undone`
            : `${view.events_in_period} approved entries`}{" "}
          · calculated by code
        </span>
      </div>
      {/* Paper only: who the return is for and whether it is still an estimate. */}
      <div className="hidden print:block">
        {business && (
          <p className="mt-1 text-sm font-bold">
            {business.name}
            {business.name && business.vatNumber ? " · " : ""}
            {business.vatNumber ? `VRN ${business.vatNumber}` : ""}
          </p>
        )}
        <p className="text-sm text-muted">
          {view.submitted ? "Submitted." : "Estimate until submitted."}
        </p>
      </div>
      {/* The values animate to the new period (key) and announce politely. */}
      <div key={view.period} aria-live="polite" aria-label="VAT box values" className="vat-update">
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
                <p className="flex min-w-0 items-center gap-1 text-[14px] font-extrabold">
                  <span>
                    Box {b.box} · {b.label}
                  </span>
                  <BoxExplain box={b.box} label={b.label} entries={b.entries} extra={b.box === 5 ? box5Note : undefined} />
                </p>
                <p className={`shrink-0 font-bold tabular-nums ${b.box === 5 ? "text-[17px]" : "text-[14px]"}`}>
                  {fmt(b)}
                </p>
              </div>
              {b.entries ? (
                <p className="mt-0.5 text-[13px] text-muted">
                  <Link href="/review" aria-label={`View ${b.entries} entries for Box ${b.box}`} className="font-bold text-teal underline underline-offset-2">
                    {b.entries} {b.entries === 1 ? "entry" : "entries"}
                  </Link>
                </p>
              ) : null}
            </li>
          ))}
        </ul>
        <div className="relative mt-3 hidden overflow-x-auto sm:block">
          <table className="w-full text-[15px]">
            <thead>
              <tr className="border-b border-border text-left text-[13px] font-bold text-muted">
                <th scope="col" className="w-12 py-2 pr-2">Box</th>
                <th scope="col" className="py-2 pr-2">What it is</th>
                <th scope="col" className="py-2 pr-2 text-right">Amount</th>
                <th scope="col" className="w-20 py-2 text-right">Entries</th>
                <th scope="col" className="w-10 py-2"><span className="sr-only">Explain</span></th>
              </tr>
            </thead>
            <tbody>
              {view.boxes.map((b) => (
                <tr key={b.box} className={`border-t border-border ${b.box === 3 || b.box === 5 ? "bg-ground" : ""}`}>
                  <td className="w-12 py-2 pr-2 font-extrabold">{b.box}</td>
                  <td className="py-2 pr-2">{b.label}</td>
                  <td className={`py-2 pr-2 text-right font-bold tabular-nums ${b.box === 5 ? "text-[17px]" : ""}`}>{fmt(b)}</td>
                  <td className="w-20 py-2 text-right text-sm text-muted">
                    {b.entries ? (
                      <Link href="/review" aria-label={`View ${b.entries} entries for Box ${b.box}`} className="font-bold text-teal underline underline-offset-2">
                        {b.entries}
                      </Link>
                    ) : (
                      ""
                    )}
                  </td>
                  <td className="w-10 py-2 text-right">
                    <BoxExplain box={b.box} label={b.label} entries={b.entries} extra={b.box === 5 ? box5Note : undefined} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {view.adjustments && view.adjustments.length > 0 && <Adjustments rows={view.adjustments} />}
      {view.scheme && <SchemeNote scheme={view.scheme} />}
      {view.warnings.length > 0 && (
        <p className="mt-3 rounded-xl border border-warn-border bg-warn-bg p-3 text-sm text-warn-ink">{view.warnings.join(" · ")}</p>
      )}
      <p className="mt-3 text-sm text-muted">
        {box5Note ?? <>Net VAT to pay: <strong className="text-ink">{fmt(net)}</strong>.</>}{" "}
        {view.can_submit
          ? "Connect to HMRC below to submit it to the sandbox."
          : view.submitted
            ? view.submitted_source === "hmrc" && view.received
              ? `Filed with HMRC on ${uk(view.received)}.`
              : "This return has already been submitted; its receipt is in 06 VAT returns."
            : "Only the current or previous period can be submitted from here."}
      </p>
    </section>
  );
}
