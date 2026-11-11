"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { money } from "@/lib/invoices";
import { ukDate } from "@/lib/runtime";
import { isDemo } from "@/lib/demo";
import { accountKind } from "@/lib/msal";
import {
  billpay,
  calendarName,
  downloadText,
  paysLine,
  UPCOMING_STATUS,
  type BpUpcoming,
  type BpUpcomingItem,
} from "@/lib/billpay";

const quiet = "inline-flex min-h-9 items-center rounded-lg border border-border bg-white px-3 text-[13px] font-bold hover:bg-ground disabled:opacity-50";

const TONE: Record<BpUpcomingItem["status"], string> = {
  scheduled: "bg-teal-tint text-teal-dark",
  planned: "bg-ground text-muted",
  due_today: "bg-teal-tint text-teal-dark",
  paying: "bg-ground text-ink",
  paid: "bg-ground text-muted",
  needs_you: "bg-warn-bg text-warn-ink",
};

export function StatusPill({ s }: { s: BpUpcomingItem["status"] }) {
  return <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[12px] font-bold ${TONE[s]}`}>{UPCOMING_STATUS[s]}</span>;
}

/** GET /billpay/upcoming, reloaded when `refreshKey` changes. */
export function useUpcoming(account: AccountInfo | null, refreshKey: unknown) {
  const [data, setData] = useState<BpUpcoming | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    if (!account) return;
    try {
      setData(await billpay.upcoming(account));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [account]);
  useEffect(() => {
    queueMicrotask(() => void reload());
  }, [reload, refreshKey]);
  return { data, error, reload };
}

export function ShortfallWarning({ u }: { u: BpUpcoming }) {
  if (!u.warning) return null;
  return <p role="alert" className="rounded-xl bg-warn-bg px-3 py-2 text-sm font-semibold text-warn-ink">{u.warning}</p>;
}

/**
 * The Purchases bill pay panel's schedule: every approved-in-advance and planned PayPal payment with its status, the
 * books' 1240 PayPal clearing balance, what leaves PayPal in the next 7 and 30 days, and the calendar: an .ics file per
 * payment or for all, or (on a tap) events in the calendar the user signed in with, which Accnomos can update and remove.
 */
export function UpcomingTable({ account, refreshKey, onChanged }: { account: AccountInfo; refreshKey: unknown; onChanged: () => Promise<void> }) {
  const { data: u, error, reload } = useUpcoming(account, refreshKey);
  const [busy, setBusy] = useState<string | null>(null);
  const [said, setSaid] = useState<string | null>(null);
  const cal = isDemo() ? "the demo calendar" : calendarName(accountKind(account));

  const act = async (key: string, fn: () => Promise<string | null>) => {
    setBusy(key);
    try {
      setSaid(await fn());
      await reload();
    } catch (e) {
      setSaid((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  if (!u) return error ? <p className="text-sm text-warn-ink">Could not load upcoming PayPal payments: {error}</p> : null;
  const open = u.items.filter((i) => i.status !== "paid" && i.status !== "paying");

  const download = (i?: BpUpcomingItem) =>
    act(`ics-${i?.event_id ?? "all"}`, async () => {
      downloadText(await billpay.ics(account, i?.event_id), i ? `paypal-payment-${i.event_id.slice(0, 12)}.ics` : "paypal-payments.ics");
      return "Calendar file downloaded. Open it to add the event; opening a newer file updates the same event. Accnomos cannot change or remove an event added from a file: delete it yourself if the payment is cancelled.";
    });
  const addLive = (i?: BpUpcomingItem) =>
    act(`cal-${i?.event_id ?? "all"}`, async () => {
      const r = await billpay.addToCalendar(account, i ? [i.event_id] : undefined);
      const parts = [r.added && `${r.added} added`, r.updated && `${r.updated} updated`, r.unchanged && `${r.unchanged} already there`].filter(Boolean);
      return `${cal}: ${parts.join(", ") || "nothing to add"}.`;
    });

  return (
    <div className="rounded-2xl border border-border bg-white p-4" aria-labelledby="bp-upcoming-h">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="bp-upcoming-h" className="text-lg font-extrabold">Upcoming PayPal payments</h3>
        <p className="text-sm text-muted">{u.clearing_label}: {money(u.clearing_pence)}</p>
      </div>
      <p className="mt-1 text-sm text-muted">{u.note}</p>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-sm sm:max-w-md">
        <div className="rounded-xl bg-ground px-3 py-2">
          <dt className="text-muted">Leaving PayPal, next 7 days</dt>
          <dd className="text-lg font-extrabold tabular-nums">{money(u.next_7_pence)}</dd>
        </div>
        <div className="rounded-xl bg-ground px-3 py-2">
          <dt className="text-muted">Next 30 days</dt>
          <dd className="text-lg font-extrabold tabular-nums">{money(u.next_30_pence)}</dd>
        </div>
      </dl>
      <div className="mt-2"><ShortfallWarning u={u} /></div>
      {u.items.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No PayPal bill payments are planned. Tick &quot;Pay with PayPal on due date&quot; on a bill below, or approve one in advance.</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-muted">
              <tr>
                <th className="py-1 pr-2">Date</th>
                <th className="py-1 pr-2">Supplier</th>
                <th className="py-1 pr-2 text-right">Amount</th>
                <th className="py-1 pr-2">Status</th>
                <th className="py-1 pr-2">Calendar</th>
              </tr>
            </thead>
            <tbody>
              {u.items.map((i) => (
                <tr key={i.event_id} className="border-t border-border align-top">
                  <td className="py-2 pr-2 whitespace-nowrap">{ukDate(i.date)}</td>
                  <td className="py-2 pr-2">
                    <strong>{i.supplier}</strong>
                    {i.reference ? ` · ${i.reference}` : ""}
                    {i.payee_email && <span className="block text-[12px] text-muted">to {i.payee_email}</span>}
                    {i.approved && i.status === "scheduled" && <span className="block text-[12px] text-muted">{paysLine(i.date)}</span>}
                    {i.reason && <span className={`block text-[12px] ${i.status === "needs_you" ? "font-semibold text-warn-ink" : "text-muted"}`}>{i.reason}.</span>}
                  </td>
                  <td className="py-2 pr-2 text-right font-bold tabular-nums">{money(i.amount_pence)}</td>
                  <td className="py-2 pr-2">
                    <StatusPill s={i.status} />
                    {i.approved && (i.status === "scheduled" || i.status === "due_today" || i.status === "needs_you") && (
                      <button
                        type="button"
                        className="mt-1 block text-[12px] font-bold text-warn-ink underline disabled:opacity-50"
                        disabled={busy !== null}
                        onClick={() =>
                          act(`cancel-${i.event_id}`, async () => {
                            await billpay.cancelSchedule(account, i.event_id);
                            await onChanged();
                            return i.in_calendar
                              ? `Cancelled. Its event is still in ${cal}: remove it with the button above the table.`
                              : "Cancelled. Nothing will be sent for it.";
                          })
                        }
                      >
                        Cancel approval
                      </button>
                    )}
                  </td>
                  <td className="py-2 pr-2">
                    {i.status === "paid" || i.status === "paying" ? (
                      <span className="text-[12px] text-muted">{i.in_calendar ? `In ${cal}` : "—"}</span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        <button type="button" className={quiet} disabled={busy !== null} onClick={() => download(i)} title="Download an .ics file">
                          .ics
                        </button>
                        <button type="button" className={quiet} disabled={busy !== null} onClick={() => addLive(i)}>
                          {i.in_calendar ? (i.calendar_outdated ? `Update in ${cal}` : `In ${cal} ✓`) : `Add to ${cal}`}
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {u.calendar_stale.length > 0 && (
        <p className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-ground px-3 py-2 text-sm">
          {u.calendar_stale.length} event{u.calendar_stale.length === 1 ? " is" : "s are"} in {cal} for a payment that was cancelled, paid or is no longer planned.
          <button type="button" className={quiet} disabled={busy !== null} onClick={() => act("stale", async () => {
            const r = await billpay.removeFromCalendar(account);
            return `Removed ${r.removed} from ${cal}${r.not_found ? ` (${r.not_found} had already gone)` : ""}.`;
          })}>
            Remove from {cal}
          </button>
        </p>
      )}
      {open.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" className={quiet} disabled={busy !== null} onClick={() => download()}>Download all (.ics)</button>
          <button type="button" className={quiet} disabled={busy !== null} onClick={() => addLive()}>Add all to {cal}</button>
        </div>
      )}
      <p className="mt-2 text-[12px] text-muted">
        Calendar events are all-day on the due date. Added to {cal} by Accnomos, they are updated when you add them again and can be removed here; a
        downloaded file is yours to change.
      </p>
      {said && <p role="status" className="mt-2 text-sm font-semibold">{said}</p>}
    </div>
  );
}
