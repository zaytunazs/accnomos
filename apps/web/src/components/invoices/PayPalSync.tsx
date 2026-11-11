"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import type { AccountInfo } from "@azure/msal-browser";
import { fieldInput, fieldLabel, primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { RuntimeErrorNote } from "@/components/States";
import { money } from "@/lib/invoices";
import PayPalTieOut from "@/components/invoices/PayPalTieOut";
import { runtime, ukDate, type RtPaypalSyncItem, type RtPaypalSyncView } from "@/lib/runtime";
import { COST_ACCOUNTS, KIND, VAT_CODES } from "@/components/invoices/paypal-codes";
import { usePowerGridOn, useWide } from "@/lib/power-grid";

/** The Power grid add-on (Settings › Business): loaded only when it is on, so AG Grid stays out of everyone else's pages. */
const PayPalReviewGrid = dynamic(() => import("@/components/grid/PayPalReviewGrid"), {
  ssr: false,
  loading: () => <p className="text-sm text-muted">Opening the grid…</p>,
});

/** "Sync PayPal": one tap reads the PayPal history; each transaction waits here for the user's yes. */
export default function PayPalSync({ account, onPosted }: { account: AccountInfo; onPosted: () => void }) {
  const [view, setView] = useState<RtPaypalSyncView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [showDone, setShowDone] = useState(false);
  const powerGrid = usePowerGridOn();
  const wide = useWide();

  const load = useCallback(async () => {
    try {
      setView(await runtime.paypalSyncView(account));
    } catch {
      /* the invoices page works without it */
    }
  }, [account]);
  useEffect(() => {
    queueMicrotask(load);
  }, [load]);

  if (!view || (!view.available && view.items.length === 0)) return null;
  const tieKey = view.items.filter((i) => i.status === "approved").length + (view.last_synced_at ? 1 : 0);
  const waiting = view.items.filter((i) => i.status === "proposed");
  const rest = view.items.filter((i) => i.status !== "proposed");

  function update(item: RtPaypalSyncItem, message: string) {
    setView((v) => (v ? { ...v, items: v.items.map((i) => (i.transaction_id === item.transaction_id ? item : i)) } : v));
    setNote(message);
    if (item.status === "approved") onPosted();
  }

  return (
    <section id="paypal-sync" aria-label="PayPal" className="scroll-mt-20 space-y-3 rounded-2xl border border-border bg-white p-4">
      {!view.sample && <PayPalTieOut account={account} refresh={tieKey} />}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-extrabold">PayPal</h2>
          <p className="text-sm text-muted">
            {view.last_synced_at ? `Last synced ${ukDate(view.last_synced_at.slice(0, 10))}. ` : ""}
            Every transaction waits for your approval; nothing goes in your books on its own.
          </p>
          {view.sample && (
            <p className="mt-1 text-sm font-bold text-warn-ink">Sample PayPal history for this demo, not a real PayPal account.</p>
          )}
        </div>
        {view.available ? (
          <button
            type="button"
            className={primaryButton}
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              setNote(null);
              try {
                const out = await runtime.paypalSync(account, { ai: true });
                setView((v) => ({ ...(v as RtPaypalSyncView), items: out.items, last_synced_at: new Date().toISOString() }));
                const waitingNow = out.items.filter((i) => i.status === "proposed").length;
                setNote(
                  `${out.new === 0 ? "Nothing new" : `${out.new} new`} from PayPal · ${waitingNow} waiting for you` +
                    (out.pending ? ` · ${out.pending} still pending at PayPal` : ""),
                );
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Syncing PayPal…" : "Sync PayPal"}
          </button>
        ) : (
          <p className="text-sm">
            {view.reason}{" "}
            <Link href="/settings#settings-payments" className="font-bold text-teal-dark underline">Online payments</Link>
          </p>
        )}
      </div>
      {note && <p role="status" className="rounded-xl bg-teal-tint px-4 py-2 text-sm font-bold text-teal-dark">{note}</p>}
      {error && <RuntimeErrorNote message={error} title="Could not sync PayPal" />}
      {powerGrid && wide && view.items.length > 0 && (
        <PayPalReviewGrid account={account} items={view.items} onChanged={update} />
      )}
      {!(powerGrid && wide) && waiting.length > 0 && (
        <ul className="space-y-2" aria-label="PayPal transactions waiting for approval">
          {waiting.map((i) => (
            <SyncRow key={i.transaction_id} account={account} item={i} onChanged={update} />
          ))}
        </ul>
      )}
      {!(powerGrid && wide) && rest.length > 0 && (
        <div>
          <button type="button" className="text-[13px] font-bold text-teal-dark hover:underline" onClick={() => setShowDone((s) => !s)}>
            {showDone ? "Hide" : "Show"} {rest.length} other PayPal transaction{rest.length === 1 ? "" : "s"}
          </button>
          {showDone && (
            <ul className="mt-2 divide-y divide-border text-sm">
              {rest.map((i) => (
                <li key={i.transaction_id} className="flex flex-wrap items-baseline justify-between gap-2 py-2">
                  <span>
                    <span className="font-bold">{ukDate(i.date)} · {i.name}</span>{" "}
                    <span className="text-muted">· {KIND[i.kind]} · {statusText(i)}</span>
                    {i.notes[0] && <span className="block text-[13px] text-muted">{i.notes[0]}</span>}
                  </span>
                  <span className="tabular-nums font-bold">{signed(i)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

function signed(i: RtPaypalSyncItem): string {
  if (i.currency !== "GBP") return i.currency;
  return i.gross_pence < 0 ? `−${money(-i.gross_pence)}` : money(i.gross_pence);
}

function statusText(i: RtPaypalSyncItem): string {
  return { approved: "approved", rejected: "rejected", already: "already in your books", info: "not posted", proposed: "waiting" }[i.status];
}

/** Preview the journal the runtime worked out. A changed account or VAT code is sent to the runtime, which works the
 *  figures out again on approval; the preview shows the runtime's own lines. */
function SyncRow({
  account, item, onChanged,
}: { account: AccountInfo; item: RtPaypalSyncItem; onChanged: (item: RtPaypalSyncItem, message: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [acct, setAcct] = useState(item.account ?? "");
  const needsVat = item.kind === "sale" && item.status === "proposed" && item.vat_code == null;
  const [vat, setVat] = useState(item.vat_code ?? (needsVat ? "" : "N"));
  const editable = item.kind === "expense";
  const id = `pp-${item.transaction_id}`;
  const gross = Math.abs(item.gross_pence);
  return (
    <li className="rounded-xl border border-border bg-ground/40 p-3">
      <p className="flex flex-wrap items-center gap-2 text-[15px] font-bold">
        {KIND[item.kind]} · {item.name} · {item.gross_pence < 0 ? "paid" : "received"} {money(gross)} on {ukDate(item.date)}
        {item.invoice && <span className="text-teal-dark">· {item.invoice}</span>}
      </p>
      <p className="text-sm text-muted">
        {item.items.length > 0 && <>{item.items.join(", ")} · </>}
        {item.fee_pence > 0 ? <>PayPal fee {money(item.fee_pence)} · you receive {money(item.net_pence)}</> : <>No PayPal fee</>}
        {item.coded_by && <> · coded by {item.coded_by}</>}
      </p>
      {item.notes.map((n) => (
        <p key={n} className={`text-sm ${n.startsWith("No receipt") || n.includes("twice") || n.includes("not both") ? "font-bold text-warn-ink" : "text-muted"}`}>
          {n}
        </p>
      ))}
      {item.notes.some((n) => n.startsWith("No receipt")) && (
        <p className="text-sm">
          <Link href="/review" className="font-bold text-teal-dark underline">Add the receipt</Link>
        </p>
      )}
      <table className="mt-2 w-full text-[13px] tabular-nums">
        <caption className="sr-only">What approving posts</caption>
        <tbody>
          {item.journal.map((j, n) => (
            <tr key={n}>
              <td className="py-0.5">{j.account}{j.vat_code ? ` (VAT ${j.vat_code})` : ""}</td>
              <td className="text-right">{j.debit_pence ? `Dr ${money(j.debit_pence)}` : ""}</td>
              <td className="text-right">{j.credit_pence ? `Cr ${money(j.credit_pence)}` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {editable && (
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <div>
            <label className={fieldLabel} htmlFor={`${id}-acct`}>Account</label>
            <select id={`${id}-acct`} className={fieldInput} value={acct} onChange={(e) => setAcct(e.target.value)}>
              {COST_ACCOUNTS.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
          <div>
            <label className={fieldLabel} htmlFor={`${id}-vat`}>VAT</label>
            <select id={`${id}-vat`} className={fieldInput} value={vat} onChange={(e) => setVat(e.target.value)}>
              {["S", "R", "Z", "E", "N"].map((c) => <option key={c} value={c}>{VAT_CODES[c]}</option>)}
            </select>
          </div>
        </div>
      )}
      {needsVat && (
        <div className="mt-2 max-w-sm">
          <label className={fieldLabel} htmlFor={`${id}-salevat`}>VAT on this sale (choose before approving)</label>
          <select id={`${id}-salevat`} className={fieldInput} value={vat} onChange={(e) => setVat(e.target.value)}>
            <option value="">Choose…</option>
            {["S", "R", "Z", "E", "O"].map((c) => <option key={c} value={c}>{VAT_CODES[c] ?? "Outside the scope of VAT"}</option>)}
          </select>
        </div>
      )}
      <div className="mt-2 flex flex-wrap justify-end gap-2">
        <button
          type="button"
          className={secondaryButton}
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              onChanged(await runtime.paypalSyncReject(account, item.transaction_id), `Rejected: ${item.name}, ${money(gross)}.`);
            } catch (e) {
              setError((e as Error).message);
              setBusy(false);
            }
          }}
        >
          Reject
        </button>
        <button
          type="button"
          className={primaryButton}
          disabled={busy || (needsVat && !vat)}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              const changed = editable && (acct !== item.account || vat !== item.vat_code);
              const body = needsVat ? { vat_code: vat } : changed ? { account: acct, vat_code: vat } : {};
              const out = await runtime.paypalSyncApprove(account, item.transaction_id, body);
              onChanged(out, `${KIND[item.kind]} of ${money(gross)} (${item.name}) is in your books.`);
            } catch (e) {
              setError((e as Error).message);
              setBusy(false);
            }
          }}
        >
          Approve {money(gross)}
        </button>
      </div>
      {error && <RuntimeErrorNote message={error} title="Could not post it" />}
    </li>
  );
}
