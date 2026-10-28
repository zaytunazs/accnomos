"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import SignInCta from "@/components/SignInCta";
import { LoadingSkeleton, RuntimeErrorNote } from "@/components/States";
import { AgedStrip, OwedList, Tile, Tiles } from "@/components/trade/overviewParts";
import { RepeatingRunNote, runDueRepeating } from "@/components/trade/repeatingRun";
import { useMsAccount } from "@/lib/invoices";
import { runtime, ukDate, type RtPurchasesOverview, type RtRepeatingResult } from "@/lib/runtime";

const link = "inline-flex min-h-11 items-center rounded-xl border border-border bg-white px-4 text-[15px] font-bold hover:bg-ground";

export default function PurchasesOverview() {
  const { account, ready } = useMsAccount();
  const [o, setO] = useState<RtPurchasesOverview | null>(null);
  const [run, setRun] = useState<RtRepeatingResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      setRun(await runDueRepeating(account).catch(() => null));
      setO(await runtime.purchasesOverview(account));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [account]);
  useEffect(() => {
    queueMicrotask(load);
  }, [load]);

  if (ready && !account) {
    return (
      <p className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl bg-ground p-4 text-sm text-muted">
        <SignInCta />
        <span>to see what you owe, what is overdue and what went out; all of it is worked out from your own files.</span>
      </p>
    );
  }
  if (error) return <RuntimeErrorNote message={error} title="Could not load the purchases overview" />;
  if (!o) return <LoadingSkeleton lines={4} label="Loading your purchases overview…" />;

  return (
    <div className="space-y-5">
      <RepeatingRunNote result={run} />
      <div className="flex flex-wrap gap-2">
        <Link href="/purchases/orders" className="inline-flex min-h-11 items-center rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark">Purchase orders</Link>
        <Link href="/review" className={link}>Review bills</Link>
        <Link href="/sales/repeating" className={link}>Repeating bills</Link>
        <Link href="/sales/items" className={link}>Products and services</Link>
      </div>
      <Tiles label="Bills">
        <Tile label="Bills and receipts in Review" bucket={o.in_review} href="/review" hint={`${o.in_review.count} waiting${o.needs_a_look ? `, ${o.needs_a_look} need a look` : ""}`} />
        <Tile label="Awaiting payment" bucket={o.awaiting_payment} href="/contacts" />
        <Tile label="Overdue" bucket={o.overdue} tone="warn" href="/contacts" />
        <Tile label="Due in the next 7 days" bucket={o.due_soon} href="/contacts" />
      </Tiles>
      <Tiles label={`Last ${o.window_days} days`}>
        <Tile label={`Money out, last ${o.window_days} days`} pence={o.money_out_pence} hint="payments to suppliers" />
        <Tile label="Credit held by suppliers" pence={o.supplier_credit_pence} hint="overpayments and credit notes" />
        <Tile label="Orders waiting for delivery" bucket={o.orders_open} href="/purchases/orders" />
        <Tile label="Orders past their delivery date" bucket={o.orders_late} tone="warn" href="/purchases/orders" />
      </Tiles>
      <div className="grid gap-4 lg:grid-cols-2">
        <AgedStrip aged={o.aged} title="What you owe, by how late" />
        <OwedList rows={o.owed_most} title="Biggest bills to pay" empty="You do not owe anyone anything right now." />
      </div>
      <Tiles label="Orders and repeating">
        <Tile label="Draft orders" bucket={o.order_drafts} href="/purchases/orders" />
        <Tile label="Billed, bill still in Review" bucket={o.orders_billed_in_review} href="/review" />
        <div className="rounded-2xl border border-border bg-white p-4">
          <p className="text-xs font-bold text-muted">Repeating bills</p>
          <p className="mt-1 text-2xl font-extrabold tabular-nums">{o.repeating.active}</p>
          <p className="mt-0.5 text-sm text-muted">{o.repeating.next_date ? `next run ${ukDate(o.repeating.next_date)}` : "none scheduled"}</p>
        </div>
      </Tiles>
    </div>
  );
}
