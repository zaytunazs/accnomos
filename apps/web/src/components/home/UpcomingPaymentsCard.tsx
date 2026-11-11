"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import ByWhom from "@/components/ByWhom";
import { useAccount } from "@/components/jobs/useAccount";
import { ShortfallWarning, StatusPill, useUpcoming } from "@/components/trade/UpcomingPayments";
import { billpay } from "@/lib/billpay";
import { money } from "@/lib/invoices";
import { ukDate } from "@/lib/runtime";

const SHOWN = 5;

/**
 * Home › Upcoming PayPal payments: the next five bill payments through PayPal (approved in advance or planned), what
 * leaves PayPal in the next 30 days and the shortfall warning against the books' 1240 PayPal clearing. Opening Home is
 * "opening the app", so it first calls POST /billpay/run (follow payouts, pay approvals whose date has come, Autopilot),
 * exactly as the Purchases panel does. Hidden when there is nothing planned.
 */
export default function UpcomingPaymentsCard() {
  const account = useAccount();
  const [ran, setRan] = useState(0);
  useEffect(() => {
    if (!account) return;
    billpay
      .run(account)
      .catch(() => null) // a demo or no PayPal: the schedule still shows
      .finally(() => setRan((n) => n + 1));
  }, [account]);
  const { data: u } = useUpcoming(ran > 0 ? account ?? null : null, ran);

  if (!u || u.items.length === 0) return null;
  const next = u.items.filter((i) => i.status !== "paid").slice(0, SHOWN);
  const warn = !!u.warning || next.some((i) => i.status === "needs_you");

  return (
    <section
      aria-labelledby="home-paypal-upcoming"
      className={`flex flex-col rounded-2xl border bg-white p-4 sm:p-5 ${warn ? "border-warn-border" : "border-border"}`}
    >
      <h2 id="home-paypal-upcoming" className="text-lg font-bold tracking-tight">Upcoming PayPal payments</h2>
      <p className="mt-1 text-3xl font-bold tracking-tight tabular-nums text-ink">{money(u.next_30_pence)}</p>
      <p className="text-[13px] text-muted">leaving PayPal in the next 30 days · {money(u.next_7_pence)} in the next 7</p>
      <div className="mt-2"><ShortfallWarning u={u} /></div>
      <ul className="mt-3 space-y-1.5">
        {next.map((i) => (
          <li key={i.event_id} className="flex items-start justify-between gap-2 text-sm">
            <span className="min-w-0">
              <span className="font-semibold">{i.supplier}</span> <span className="text-muted">· {ukDate(i.date)}</span>
              <span className="ml-2"><StatusPill s={i.status} /></span>
            </span>
            <span className="shrink-0 font-bold tabular-nums">{money(i.amount_pence)}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[12px] text-muted">{u.note}</p>
      <ByWhom className="mt-2" code="Dates and totals by code; clearing is a books figure" ai="the AI pays nothing" />
      <div className="mt-auto pt-4">
        <Link href="/purchases" className="inline-flex shrink-0 whitespace-nowrap rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark">
          Open bill pay
        </Link>
      </div>
    </section>
  );
}
