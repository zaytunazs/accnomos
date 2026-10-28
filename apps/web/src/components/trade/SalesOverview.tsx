"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import SignInCta from "@/components/SignInCta";
import { LoadingSkeleton, RuntimeErrorNote } from "@/components/States";
import { AgedStrip, OwedList, Tile, Tiles } from "@/components/trade/overviewParts";
import { RepeatingRunNote, runDueRepeating } from "@/components/trade/repeatingRun";
import StatementPicker from "@/components/trade/StatementPicker";
import StatementDialog from "@/components/trade/StatementDialog";
import { useMsAccount } from "@/lib/invoices";
import { runtime, ukDate, type RtRepeatingResult, type RtSalesOverview } from "@/lib/runtime";

const link = "inline-flex min-h-11 items-center rounded-xl border border-border bg-white px-4 text-[15px] font-bold hover:bg-ground";

export default function SalesOverview() {
  const { account, ready } = useMsAccount();
  const [o, setO] = useState<RtSalesOverview | null>(null);
  const [run, setRun] = useState<RtRepeatingResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [statement, setStatement] = useState<{ id: string; name: string } | null>(null);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      setRun(await runDueRepeating(account).catch(() => null)); // a failed run is not a reason to hide the figures
      setO(await runtime.salesOverview(account));
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
        <span>to see what you are owed, what is overdue and what came in; all of it is worked out from your own files.</span>
      </p>
    );
  }
  if (error) return <RuntimeErrorNote message={error} title="Could not load the sales overview" />;
  if (!o) return <LoadingSkeleton lines={4} label="Loading your sales overview…" />;

  return (
    <div className="space-y-5">
      <RepeatingRunNote result={run} />
      {note && <p role="status" className="rounded-xl bg-teal-tint px-4 py-3 text-sm font-bold text-teal-dark">{note}</p>}
      <div className="flex flex-wrap gap-2">
        <Link href="/invoices/new" className="inline-flex min-h-11 items-center rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark">New invoice</Link>
        <Link href="/invoices" className={link}>Invoices</Link>
        <Link href="/sales/quotes" className={link}>Quotes</Link>
        <Link href="/sales/items" className={link}>Products and services</Link>
        <Link href="/sales/repeating" className={link}>Repeating</Link>
      </div>
      <Tiles label="Invoices">
        <Tile label="Draft invoices" bucket={o.drafts} href="/invoices" />
        <Tile label="Awaiting payment" bucket={o.awaiting_payment} href="/invoices" />
        <Tile label="Overdue" bucket={o.overdue} tone="warn" href="/invoices" />
        <Tile label="Due in the next 7 days" bucket={o.due_soon} href="/invoices" />
      </Tiles>
      <Tiles label={`Last ${o.window_days} days`}>
        <Tile label={`Money in, last ${o.window_days} days`} pence={o.money_in_pence} hint="payments received" />
        <Tile label={`Invoiced, last ${o.window_days} days`} pence={o.invoiced_pence} hint="invoices dated in the period" />
        <Tile label="Credit held for customers" pence={o.customer_credit_pence} hint="overpayments and credit notes" />
        <Tile label="Quotes accepted, not invoiced" bucket={o.quotes_to_invoice} href="/sales/quotes" />
      </Tiles>
      <div className="grid gap-4 lg:grid-cols-2">
        <AgedStrip aged={o.aged} title="Who owes you, by how late" />
        <OwedList rows={o.owed_most} title="Biggest amounts to chase" empty="Nobody owes you anything right now." hrefFor={(r) => (r.number ? `/invoices?q=${encodeURIComponent(r.number)}` : null)} />
      </div>
      <Tiles label="Quotes">
        <Tile label="Draft quotes" bucket={o.quote_drafts} href="/sales/quotes" />
        <Tile label="Sent, waiting for an answer" bucket={o.quotes_waiting} href="/sales/quotes" />
        <Tile label="Expired" bucket={o.quotes_expired} href="/sales/quotes" />
        <div className="rounded-2xl border border-border bg-white p-4">
          <p className="text-xs font-bold text-muted">Repeating invoices</p>
          <p className="mt-1 text-2xl font-extrabold tabular-nums">{o.repeating.active}</p>
          <p className="mt-0.5 text-sm text-muted">{o.repeating.next_date ? `next run ${ukDate(o.repeating.next_date)}` : "none scheduled"}</p>
        </div>
      </Tiles>
      <StatementPicker account={account!} owed={o} onOpen={setStatement} />
      {statement && account && (
        <StatementDialog account={account} contactId={statement.id} name={statement.name} onClose={() => setStatement(null)}
          onSent={(m) => { setStatement(null); setNote(m); }} />
      )}
    </div>
  );
}

