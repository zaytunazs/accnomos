"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import { RuntimeErrorNote } from "@/components/States";
import { money, useMsAccount } from "@/lib/invoices";
import { ukDate } from "@/lib/runtime";
import {
  billpay,
  penceFromPounds,
  poundsFromPence,
  type BpBill,
  type BpOverview,
  type BpPayout,
  type BpRule,
  type BpRunResult,
} from "@/lib/billpay";

const card = "rounded-2xl border border-border bg-white p-4";
const button = "inline-flex min-h-11 items-center rounded-xl bg-teal px-4 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-50";
const quiet = "inline-flex min-h-11 items-center rounded-xl border border-border bg-white px-4 text-[15px] font-bold hover:bg-ground disabled:opacity-50";
const input = "min-h-11 rounded-xl border border-border bg-white px-3 text-[15px]";

const STATUS: Record<BpPayout["status"], string> = {
  sending: "Sending to PayPal",
  pending: "PayPal is processing it",
  unclaimed: "Waiting for the supplier to claim it",
  paid: "Paid and posted",
  failed: "Not paid",
  unknown: "Waiting for PayPal's answer",
};

function dueLine(b: BpBill): string {
  if (b.days_overdue > 0) return `due ${ukDate(b.due_date)}, ${b.days_overdue} day${b.days_overdue === 1 ? "" : "s"} overdue`;
  if (b.days_overdue === 0) return "due today";
  return `due ${ukDate(b.due_date)}`;
}

/**
 * Pay suppliers' bills through PayPal on their due date. Opening the page follows payouts already on their way and
 * lets bill-pay Autopilot pay what its rules allow (POST /billpay/run); everything else waits here for the owner.
 */
export default function BillPay() {
  const { account } = useMsAccount();
  const [o, setO] = useState<BpOverview | null>(null);
  const [run, setRun] = useState<BpRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!account) return;
    setO(await billpay.overview(account));
  }, [account]);

  useEffect(() => {
    if (!account) return;
    queueMicrotask(async () => {
      try {
        setRun(await billpay.run(account).catch(() => null));
        await reload();
        setError(null);
      } catch (e) {
        setError((e as Error).message);
      }
    });
  }, [account, reload]);

  const act = useCallback(
    async (key: string, fn: () => Promise<unknown>) => {
      setBusy(key);
      try {
        await fn();
        await reload();
        setError(null);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(null);
      }
    },
    [reload],
  );

  if (!account) return null;
  if (!o) return error ? <RuntimeErrorNote message={error} title="Could not load bills to pay with PayPal" /> : null;

  return (
    <section aria-labelledby="billpay-h" className="space-y-4">
      <div>
        <h2 id="billpay-h" className="text-xl font-extrabold tracking-tight">Pay bills with PayPal</h2>
        <p className="mt-1 text-sm leading-6 text-muted">
          Bills you approved in Review can be paid from your PayPal account on their due date. You approve each payment, or let Autopilot pay
          suppliers you set limits for. A supplier&apos;s PayPal email is only ever the one you type here, never one read from a bill.
          {o.test_mode ? " PayPal sandbox: no real money moves." : ""}
        </p>
      </div>
      {error && <p role="alert" className="rounded-xl bg-warn-bg px-4 py-3 text-sm font-semibold text-warn-ink">{error}</p>}
      {!o.available && <p className="rounded-xl bg-ground px-4 py-3 text-sm text-muted">{o.reason}</p>}
      {o.available && !o.connected && (
        <p className="rounded-xl bg-ground px-4 py-3 text-sm text-muted">
          Connect PayPal in <Link href="/settings" className="font-bold underline">Settings › Online payments</Link> to pay bills from it.
        </p>
      )}
      <Notices o={o} run={run} account={account} onDone={reload} />
      <Flags o={o} busy={busy} onClear={(id) => act(`flag-${id}`, () => billpay.clearFlag(account, id))} />
      <DueToday o={o} busy={busy} onPay={(b, ack) => act(`pay-${b.event_id}`, () => billpay.pay(account, b.event_id, b.owed_pence, ack))} />
      <Upcoming o={o} busy={busy} account={account} act={act} />
      <Payees o={o} busy={busy} account={account} act={act} />
      <Autopilot key={`${o.payees.map((p) => p.contact_id).join(",")}:${o.autopilot.changed_at ?? ""}`} o={o} busy={busy} account={account} act={act} />
      <Payouts payouts={o.payouts} />
    </section>
  );
}

type Act = (key: string, fn: () => Promise<unknown>) => Promise<void>;

function Notices({ o, run, account, onDone }: { o: BpOverview; run: BpRunResult | null; account: AccountInfo; onDone: () => Promise<void> }) {
  if (o.notices.length === 0 && !(run && run.problems.length)) return null;
  return (
    <div role="status" className="rounded-xl bg-teal-tint px-4 py-3 text-sm text-teal-dark">
      <ul className="list-disc space-y-1 pl-5">
        {o.notices.map((n) => (
          <li key={n.id} className={n.kind === "flag" || n.kind === "problem" ? "font-bold text-warn-ink" : ""}>{n.text}</li>
        ))}
        {run?.problems.map((p) => <li key={p} className="font-semibold text-warn-ink">{p}</li>)}
      </ul>
      {o.notices.length > 0 && (
        <button type="button" className="mt-2 font-bold underline" onClick={() => billpay.noticesSeen(account, o.notices.map((n) => n.id)).then(onDone)}>
          Mark as read
        </button>
      )}
    </div>
  );
}

function Flags({ o, busy, onClear }: { o: BpOverview; busy: string | null; onClear: (id: string) => void }) {
  if (o.flags.length === 0) return null;
  return (
    <div role="alert" className="rounded-2xl border-2 border-warn-border bg-warn-bg p-4 text-sm text-warn-ink">
      <p className="font-extrabold">Payment details changed on a bill</p>
      <p className="mt-1">
        Changed bank or PayPal details on a bill are a common fraud. Accnomos keeps paying the details you saved and has stopped Autopilot for these
        suppliers. Ring the supplier on a number you already had (not one on the bill) before you change anything.
      </p>
      <ul className="mt-2 space-y-2">
        {o.flags.map((f) => (
          <li key={f.id} className="flex flex-wrap items-center justify-between gap-2">
            <span><strong>{f.supplier}:</strong> {f.reason}.</span>
            <button type="button" className={quiet} disabled={busy !== null} onClick={() => onClear(f.id)}>I checked with the supplier</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DueToday({ o, busy, onPay }: { o: BpOverview; busy: string | null; onPay: (b: BpBill, ack: boolean) => void }) {
  return (
    <div className={card}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg font-extrabold">Due today</h3>
        <p className="text-sm text-muted">1240 PayPal clearing by your books: {money(o.clearing_pence)}</p>
      </div>
      {o.due.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No bill is due for PayPal today.</p>
      ) : (
        <ul className="mt-3 space-y-3">{o.due.map((b) => <DueCard key={b.event_id} b={b} busy={busy} onPay={onPay} />)}</ul>
      )}
    </div>
  );
}

function DueCard({ b, busy, onPay }: { b: BpBill; busy: string | null; onPay: (b: BpBill, ack: boolean) => void }) {
  const [ack, setAck] = useState(false);
  const [asking, setAsking] = useState(false);
  const p = b.payout;
  return (
    <li className="rounded-xl border border-border p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-bold">
          {b.supplier}
          {b.reference ? ` · ${b.reference}` : ""}
        </p>
        <p className="text-lg font-extrabold tabular-nums">{money(b.owed_pence)}</p>
      </div>
      <p className="text-sm text-muted">
        {dueLine(b)}
        {b.payee_email ? ` · pays ${b.payee_email}` : ""}
      </p>
      {b.changed_details.length > 0 && (
        <p className="mt-2 rounded-lg bg-warn-bg px-3 py-2 text-sm font-bold text-warn-ink">{b.changed_details.join(". ")}.</p>
      )}
      {b.warnings.filter((w) => !b.changed_details.includes(w)).map((w) => (
        <p key={w} className="mt-1 text-sm font-semibold text-warn-ink">{w}.</p>
      ))}
      {b.blocks.map((w) => <p key={w} className="mt-1 text-sm text-muted">{w}.</p>)}
      {p && (
        <p className="mt-1 text-sm">
          <strong>{STATUS[p.status]}</strong>
          {p.detail ? `: ${p.detail}.` : "."}
        </p>
      )}
      {b.can_pay && !asking && (
        <button type="button" className={`${button} mt-2`} disabled={busy !== null} onClick={() => setAsking(true)}>
          {p?.status === "failed" ? "Try again" : "Approve payment"}
        </button>
      )}
      {b.can_pay && asking && (
        <div className="mt-2 rounded-xl bg-ground p-3 text-sm">
          <p>
            Pay <strong>{money(b.owed_pence)}</strong> to <strong>{b.payee_email}</strong> from your PayPal account now? When PayPal says it is paid,
            Accnomos posts it: 2100 Creditors debit, 1240 PayPal clearing credit.
          </p>
          {b.changed_details.length > 0 && (
            <label className="mt-2 flex items-start gap-2 font-semibold text-warn-ink">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-1" />
              I checked with the supplier, by phone on a number I already had, that {b.payee_email} is right.
            </label>
          )}
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              className={button}
              disabled={busy !== null || (b.changed_details.length > 0 && !ack)}
              onClick={() => onPay(b, ack)}
            >
              {busy === `pay-${b.event_id}` ? "Paying…" : `Pay ${money(b.owed_pence)}`}
            </button>
            <button type="button" className={quiet} onClick={() => setAsking(false)}>Cancel</button>
          </div>
        </div>
      )}
    </li>
  );
}

function Upcoming({ o, busy, account, act }: { o: BpOverview; busy: string | null; account: AccountInfo; act: Act }) {
  const bills = [...o.due, ...o.upcoming].sort((x, y) => x.due_date.localeCompare(y.due_date));
  if (bills.length === 0) return null;
  return (
    <div className={card}>
      <h3 className="text-lg font-extrabold">Bills to pay</h3>
      <ul className="mt-2 divide-y divide-border">
        {bills.map((b) => (
          <li key={b.event_id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
            <span className="min-w-0">
              <strong>{b.supplier}</strong>
              {b.reference ? ` · ${b.reference}` : ""} · {money(b.owed_pence)} · {dueLine(b)}
              {!b.payee_email && <span className="text-muted"> · no PayPal email saved</span>}
            </span>
            <label className="flex items-center gap-2 font-semibold">
              <input
                type="checkbox"
                checked={b.plan === "paypal" || (b.plan === null && b.payee_email !== null)}
                disabled={busy !== null}
                onChange={(e) => act(`plan-${b.event_id}`, () => billpay.setPlan(account, b.event_id, e.target.checked ? "paypal" : "not_paypal"))}
              />
              Pay with PayPal on due date
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Payees({ o, busy, account, act }: { o: BpOverview; busy: string | null; account: AccountInfo; act: Act }) {
  const suppliers = useMemo(() => {
    const m = new Map<string, string>();
    for (const b of [...o.due, ...o.upcoming]) m.set(b.contact_id, b.supplier);
    for (const p of o.payees) m.set(p.contact_id, p.name);
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [o]);
  const [cid, setCid] = useState("");
  const [email, setEmail] = useState("");
  const [bank, setBank] = useState("");
  const [sure, setSure] = useState(false);
  const chosen = cid || suppliers[0]?.[0] || "";
  return (
    <div className={card}>
      <h3 className="text-lg font-extrabold">Suppliers&apos; PayPal emails</h3>
      <p className="mt-1 text-sm text-muted">
        Type the address yourself, from details you checked with the supplier. Accnomos never copies one from a bill or an email, and changing it
        restarts Autopilot&apos;s waiting days for that supplier.
      </p>
      {o.payees.length > 0 && (
        <ul className="mt-2 divide-y divide-border text-sm">
          {o.payees.map((p) => (
            <li key={p.contact_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>
                <strong>{p.name}</strong> · {p.paypal_email}
                {p.bank ? ` · bank ${p.bank}` : ""} · confirmed {ukDate(p.confirmed_at.slice(0, 10))}
              </span>
              <button type="button" className={quiet} disabled={busy !== null} onClick={() => act(`rm-${p.contact_id}`, () => billpay.removePayee(account, p.contact_id))}>
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      {suppliers.length > 0 && (
        <form
          className="mt-3 grid gap-2 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            void act("payee", () => billpay.setPayee(account, chosen, email, bank.trim() || null)).then(() => {
              setEmail("");
              setBank("");
              setSure(false);
            });
          }}
        >
          <label className="grid gap-1 text-sm font-semibold">
            Supplier
            <select className={input} value={chosen} onChange={(e) => setCid(e.target.value)}>
              {suppliers.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
            </select>
          </label>
          <label className="grid gap-1 text-sm font-semibold">
            PayPal email
            <input className={input} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" />
          </label>
          <label className="grid gap-1 text-sm font-semibold">
            Bank details on file (optional, to compare bills against)
            <input className={input} value={bank} onChange={(e) => setBank(e.target.value)} placeholder="12-34-56 12345678" autoComplete="off" />
          </label>
          <label className="flex items-start gap-2 self-end text-sm font-semibold">
            <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} className="mt-1" />
            I typed this myself and checked it with the supplier
          </label>
          <div>
            <button type="submit" className={button} disabled={busy !== null || !sure || !email}>Save PayPal email</button>
          </div>
        </form>
      )}
    </div>
  );
}

interface RuleDraft {
  contact_id: string;
  enabled: boolean;
  max: string;
  cap: string;
  days: string;
}

function Autopilot({ o, busy, account, act }: { o: BpOverview; busy: string | null; account: AccountInfo; act: Act }) {
  const [enabled, setEnabled] = useState(o.autopilot.enabled);
  const [rules, setRules] = useState<RuleDraft[]>(() =>
    o.payees.map((p) => {
      const r = o.autopilot.rules.find((x) => x.contact_id === p.contact_id);
      return {
        contact_id: p.contact_id,
        enabled: Boolean(r?.enabled),
        max: r ? poundsFromPence(r.max_per_bill_pence) : "",
        cap: r ? poundsFromPence(r.monthly_cap_pence) : "",
        days: String(r?.min_days_unchanged ?? 7),
      };
    }),
  );
  const [problem, setProblem] = useState<string | null>(null);
  const names = new Map(o.payees.map((p) => [p.contact_id, p.name]));

  const save = (on: boolean) => {
    const out: BpRule[] = [];
    for (const r of rules) {
      if (!r.enabled) continue;
      const max = penceFromPounds(r.max);
      const cap = penceFromPounds(r.cap);
      const days = Number.parseInt(r.days, 10);
      if (!max || !cap || !(days >= 0)) {
        setProblem(`Give ${names.get(r.contact_id)} a limit per bill, a monthly cap and a number of days`);
        return;
      }
      out.push({ contact_id: r.contact_id, enabled: true, max_per_bill_pence: max, monthly_cap_pence: cap, min_days_unchanged: days, only_person_approved: true });
    }
    setProblem(null);
    void act("autopilot", () => billpay.saveAutopilot(account, on, out));
  };

  return (
    <div className={card}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-lg font-extrabold">Autopilot for bills</h3>
        <span className={`rounded-full px-3 py-1 text-sm font-bold ${o.autopilot.enabled ? "bg-teal-tint text-teal-dark" : "bg-ground text-muted"}`}>
          {o.autopilot.enabled ? "On" : o.autopilot.stopped_at ? "Stopped" : "Off"}
        </span>
      </div>
      <p className="mt-1 text-sm text-muted">{o.autopilot_note}</p>
      <p className="mt-1 text-sm text-muted">
        It pays only bills a person approved, only to a PayPal email unchanged for the days you set, within your limits, and never a supplier whose bill
        shows changed payment details. Anything else waits in Due today, with the reason. Every payment it makes is in the audit log and shown here.
      </p>
      {o.payees.length === 0 ? (
        <p className="mt-2 text-sm text-muted">Save a supplier&apos;s PayPal email first.</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-muted">
              <tr>
                <th className="py-1 pr-2">Supplier</th>
                <th className="py-1 pr-2">Pay automatically</th>
                <th className="py-1 pr-2">Most per bill (£)</th>
                <th className="py-1 pr-2">Most per month (£)</th>
                <th className="py-1 pr-2">Email unchanged for (days)</th>
              </tr>
            </thead>
            <tbody>
              {rules.map((r, i) => {
                const set = (patch: Partial<RuleDraft>) => setRules((rs) => rs.map((x, j) => (j === i ? { ...x, ...patch } : x)));
                return (
                  <tr key={r.contact_id} className="border-t border-border">
                    <td className="py-2 pr-2 font-semibold">{names.get(r.contact_id)}</td>
                    <td className="py-2 pr-2">
                      <input type="checkbox" aria-label={`Pay ${names.get(r.contact_id)} automatically`} checked={r.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
                    </td>
                    <td className="py-2 pr-2"><input className={`${input} w-28`} inputMode="decimal" value={r.max} onChange={(e) => set({ max: e.target.value })} /></td>
                    <td className="py-2 pr-2"><input className={`${input} w-28`} inputMode="decimal" value={r.cap} onChange={(e) => set({ cap: e.target.value })} /></td>
                    <td className="py-2 pr-2"><input className={`${input} w-20`} inputMode="numeric" value={r.days} onChange={(e) => set({ days: e.target.value })} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {problem && <p role="alert" className="mt-2 text-sm font-semibold text-warn-ink">{problem}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-sm font-semibold">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          Autopilot for bills is on
        </label>
        <button type="button" className={button} disabled={busy !== null || o.payees.length === 0} onClick={() => save(enabled)}>Save</button>
        {o.autopilot.enabled && (
          <button
            type="button"
            className="inline-flex min-h-11 items-center rounded-xl border-2 border-warn-ink bg-white px-4 text-[15px] font-bold text-warn-ink"
            disabled={busy !== null}
            onClick={() => {
              setEnabled(false);
              void act("stop", () => billpay.stopAutopilot(account));
            }}
          >
            Stop all automatic payments now
          </button>
        )}
      </div>
    </div>
  );
}

function Payouts({ payouts }: { payouts: BpPayout[] }) {
  if (payouts.length === 0) return null;
  return (
    <div className={card}>
      <h3 className="text-lg font-extrabold">PayPal payments to suppliers</h3>
      <ul className="mt-2 divide-y divide-border text-sm">
        {payouts.slice(0, 20).map((p) => (
          <li key={p.id} className="py-2">
            <strong>{p.supplier}</strong>
            {p.reference ? ` · ${p.reference}` : ""} · {money(p.amount_pence)} to {p.receiver} · {p.via === "autopilot" ? "by Autopilot" : "approved by you"} ·{" "}
            {ukDate(p.created_at.slice(0, 10))} · <strong>{STATUS[p.status]}</strong>
            {p.fee_pence ? ` (PayPal fee ${money(p.fee_pence)})` : ""}
            {p.detail ? `. ${p.detail}.` : ""}
            {p.problem && <span className="block font-semibold text-warn-ink">{p.problem}.</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
