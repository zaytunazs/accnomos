"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import { errorText } from "@/components/invoices/InvoiceDialogs";
import Modal, { fieldInput, fieldLabel, primaryButton, secondaryButton } from "@/components/invoices/Modal";
import SignInCta from "@/components/SignInCta";
import { EmptyState, LoadingSkeleton, RuntimeErrorNote } from "@/components/States";
import PurchaseOrderFormDialog from "@/components/trade/PurchaseOrderFormDialog";
import SendDialog from "@/components/trade/SendDialog";
import { money, useMsAccount } from "@/lib/invoices";
import { runtime, ukDate, type RtBillCandidate, type RtPurchaseOrder, type RtPurchaseOrderStatus } from "@/lib/runtime";

type Filter = "all" | RtPurchaseOrderStatus;
const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "draft", label: "Drafts" },
  { value: "approved", label: "Approved" },
  { value: "sent", label: "Sent" },
  { value: "billed", label: "Billed" },
  { value: "cancelled", label: "Cancelled" },
];
const LABEL: Record<RtPurchaseOrderStatus, string> = { draft: "Draft", approved: "Approved", sent: "Sent", billed: "Billed", cancelled: "Cancelled" };
const TONE: Record<RtPurchaseOrderStatus, string> = {
  draft: "bg-ground text-muted",
  approved: "bg-teal-tint text-teal-dark",
  sent: "bg-teal-tint text-teal-dark",
  billed: "bg-teal text-white",
  cancelled: "bg-ground text-muted line-through",
};
const action = "text-[13px] font-bold text-teal-dark hover:underline";

type Dialog =
  | { kind: "form"; order: RtPurchaseOrder | null }
  | { kind: "pdf"; order: RtPurchaseOrder }
  | { kind: "match"; order: RtPurchaseOrder }
  | { kind: "cancel"; order: RtPurchaseOrder }
  | null;

function MatchDialog({ account, order, onClose, onDone }: { account: AccountInfo; order: RtPurchaseOrder; onClose: () => void; onDone: (o: RtPurchaseOrder) => void }) {
  const [list, setList] = useState<RtBillCandidate[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    runtime.poBillCandidates(account, order.number).then(setList).catch((e) => { setList([]); setNote(errorText(e)); });
  }, [account, order.number]);

  async function match(id: string) {
    setBusy(true);
    setNote(null);
    try {
      onDone(await runtime.matchPurchaseOrderBill(account, order.number, id));
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal id="po-match-title" title={`Match a bill to ${order.number}`} onClose={onClose}>
      <p className="mt-2 text-sm text-muted">
        Bills from {order.supplier.name} that are waiting in Review or already approved. Matching only links them; it posts nothing and changes no figures.
      </p>
      {!list && <p className="mt-3 text-sm text-muted">Looking for bills…</p>}
      {list && list.length === 0 && <p className="mt-3 text-sm">No bills from this supplier yet. Scan or upload one and it will appear here.</p>}
      {list && list.length > 0 && (
        <ul aria-label="Bills from this supplier" className="mt-3 divide-y divide-border rounded-xl border border-border">
          {list.map((c) => (
            <li key={c.proposal_id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2">
              <div className="min-w-0">
                <p className="text-[15px] font-bold">{c.invoice_number ?? "No bill number"} · {money(c.gross_pence)}</p>
                <p className="text-sm text-muted">
                  {ukDate(c.date)} · {c.status === "posted" ? "approved" : "in Review"}
                  {c.exact ? " · same total as the order" : ` · ${money(Math.abs(c.variance_pence))} ${c.variance_pence > 0 ? "more" : "less"} than the order`}
                  {c.linked_to && ` · already matched to ${c.linked_to}`}
                </p>
              </div>
              <button type="button" className={action} disabled={busy || c.linked_to !== null} onClick={() => match(c.proposal_id)}>Match</button>
            </li>
          ))}
        </ul>
      )}
      {note && <p role="alert" className="mt-3 text-sm font-bold text-warn-ink">{note}</p>}
      <div className="mt-4"><button type="button" onClick={onClose} className={secondaryButton}>Close</button></div>
    </Modal>
  );
}

function CancelDialog({ account, order, onClose, onDone }: { account: AccountInfo; order: RtPurchaseOrder; onClose: () => void; onDone: (o: RtPurchaseOrder) => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  async function go() {
    setBusy(true);
    try {
      onDone(await runtime.cancelPurchaseOrder(account, order.number, reason));
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal id="po-cancel-title" title={`Cancel ${order.number}`} onClose={onClose}>
      <p className="mt-2 text-[15px] leading-7">The order stays in your folder, marked cancelled, so the number is not used again. Tell the supplier separately if you have already sent it.</p>
      <div className="mt-3">
        <label className={fieldLabel} htmlFor="po-cancel-reason">Why?</label>
        <input id="po-cancel-reason" className={fieldInput} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. ordered elsewhere" />
      </div>
      <div className="mt-4 flex flex-wrap gap-3">
        <button type="button" onClick={go} disabled={busy || !reason.trim()} className={primaryButton}>{busy ? "Cancelling…" : "Cancel order"}</button>
        <button type="button" onClick={onClose} className={secondaryButton}>Keep it</button>
      </div>
      {note && <p role="alert" className="mt-3 text-sm font-bold text-warn-ink">{note}</p>}
    </Modal>
  );
}

export default function LivePurchaseOrders() {
  const { account, ready } = useMsAccount();
  const [orders, setOrders] = useState<RtPurchaseOrder[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [dialog, setDialog] = useState<Dialog>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      setOrders(await runtime.purchaseOrders(account));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [account]);
  useEffect(() => {
    queueMicrotask(load);
  }, [load]);

  const replace = (o: RtPurchaseOrder) => setOrders((l) => l?.map((x) => (x.number === o.number ? o : x)) ?? null);

  async function act(o: RtPurchaseOrder, run: (a: AccountInfo) => Promise<RtPurchaseOrder>, message: string) {
    if (!account) return;
    setBusy(o.number);
    setNote(null);
    setError(null);
    try {
      replace(await run(account));
      setNote(message);
    } catch (e) {
      setError(errorText(e) ?? "Something went wrong.");
    } finally {
      setBusy(null);
    }
  }

  async function toBill(o: RtPurchaseOrder) {
    if (!account) return;
    setBusy(o.number);
    setNote(null);
    setError(null);
    try {
      const r = await runtime.convertPurchaseOrder(account, o.number);
      replace(r.order);
      // The bill goes through the same checks as a scanned one (app/checks.py): say when it needs a look, and why.
      const why = r.proposal.reasons.map((x) => x.replace(/^[A-Z_]+: /, "")).join("; ");
      setNote(
        r.proposal.status === "needs_a_look"
          ? `A bill for ${o.number} is waiting in Review and needs a look: ${why}. Nothing is posted until you approve it there.`
          : `A bill for ${o.number} is waiting in Review with the same lines and totals. Nothing is posted until you approve it there.`,
      );
    } catch (e) {
      setError(errorText(e) ?? "Something went wrong.");
    } finally {
      setBusy(null);
    }
  }

  if (ready && !account) {
    return (
      <p className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl bg-ground p-4 text-sm text-muted">
        <SignInCta />
        <span>to write purchase orders; each one is saved in your OneDrive under _System/PurchaseOrders.</span>
      </p>
    );
  }

  const needle = query.trim().toLowerCase();
  const shown = (orders ?? [])
    .filter((o) => filter === "all" || o.status === filter)
    .filter((o) => !needle || o.number.toLowerCase().includes(needle) || o.supplier.name.toLowerCase().includes(needle));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Show purchase orders">
          {FILTERS.map((f) => (
            <button key={f.value} type="button" role="tab" aria-selected={filter === f.value} onClick={() => setFilter(f.value)}
              className={`h-9 rounded-full px-3 text-[13px] font-bold ${filter === f.value ? "bg-teal text-white" : "border border-border bg-white text-ink"}`}>
              {f.label}
            </button>
          ))}
        </div>
        <button type="button" className={primaryButton} onClick={() => setDialog({ kind: "form", order: null })}>New purchase order</button>
      </div>
      <div>
        <label className="text-xs font-bold text-muted" htmlFor="po-search">Search purchase orders</label>
        <input id="po-search" className="mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px] text-ink" placeholder="Number or supplier…" autoComplete="off" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      {note && <p role="status" className="rounded-xl bg-teal-tint px-4 py-3 text-sm font-bold text-teal-dark">{note}</p>}
      {error && <RuntimeErrorNote message={error} title="Could not complete that" />}
      {!orders && !error && <LoadingSkeleton lines={3} label="Loading your purchase orders…" />}
      {orders && orders.length === 0 && (
        <EmptyState title="No purchase orders yet" body="Order from a supplier, send it from your Outlook, and turn it into a bill for Review when the delivery arrives." />
      )}
      {orders && orders.length > 0 && shown.length === 0 && <p className="rounded-2xl border border-border bg-white p-4 text-sm text-muted">Nothing here.</p>}
      {shown.length > 0 && account && (
        <ul className="divide-y divide-border rounded-2xl border border-border bg-white">
          {shown.map((o) => (
            <li key={o.number} className="px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-[15px] font-bold">{o.number} · {o.supplier.name}</p>
                  <p className="text-sm text-muted">
                    {ukDate(o.issue_date)}
                    {o.delivery_date && ` · delivery by ${ukDate(o.delivery_date)}`}
                    {o.overdue_days != null && o.overdue_days > 0 && <> · <span className="font-bold text-warn-ink">{o.overdue_days} day{o.overdue_days === 1 ? "" : "s"} late</span></>}
                    {o.bill_now && (
                      <> · bill {o.bill_now.status === "posted" ? "approved" : "waiting in Review"}
                        {o.bill_now.variance_pence ? ` (${money(Math.abs(o.bill_now.variance_pence))} ${o.bill_now.variance_pence > 0 ? "more" : "less"} than the order)` : ""}
                        {o.bill_now.status !== "posted" && <> · <Link href="/review" className="font-bold text-teal-dark">Open Review</Link></>}
                      </>
                    )}
                    {o.status === "cancelled" && o.cancel_reason && ` · ${o.cancel_reason}`}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`rounded-full px-2 py-0.5 text-[12px] font-extrabold ${TONE[o.status]}`}>{LABEL[o.status]}</span>
                  <span className="text-[15px] font-extrabold tabular-nums">{money(o.total_pence)}</span>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-4">
                {o.status === "draft" && (
                  <>
                    <button type="button" className={action} onClick={() => setDialog({ kind: "form", order: o })}>Edit</button>
                    <button type="button" className={action} disabled={busy === o.number} onClick={() => act(o, (a) => runtime.approvePurchaseOrder(a, o.number), `${o.number} is approved. You can send it to the supplier now.`)}>Approve</button>
                  </>
                )}
                {o.status === "approved" && (
                  <>
                    <button type="button" className={action} onClick={() => setDialog({ kind: "pdf", order: o })}>Preview and send</button>
                    <button type="button" className={action} disabled={busy === o.number} onClick={() => act(o, (a) => runtime.markPurchaseOrderSent(a, o.number), `${o.number} is marked as sent.`)}>Mark as sent</button>
                  </>
                )}
                {o.status !== "draft" && o.status !== "approved" && <button type="button" className={action} onClick={() => setDialog({ kind: "pdf", order: o })}>View PDF</button>}
                {(o.status === "approved" || o.status === "sent") && (
                  <>
                    <button type="button" className={action} disabled={busy === o.number} onClick={() => toBill(o)}>Convert to bill</button>
                    <button type="button" className={action} onClick={() => setDialog({ kind: "match", order: o })}>Match a received bill</button>
                  </>
                )}
                {o.status === "billed" && o.bill_now && o.bill_now.status !== "posted" && (
                  <button type="button" className={action} disabled={busy === o.number} onClick={() => act(o, (a) => runtime.unlinkPurchaseOrderBill(a, o.number), `The bill is no longer linked to ${o.number}.`)}>Unlink bill</button>
                )}
                {(o.status === "draft" || o.status === "approved" || o.status === "sent") && (
                  <button type="button" className="text-[13px] font-bold text-muted hover:underline" onClick={() => setDialog({ kind: "cancel", order: o })}>Cancel</button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {dialog?.kind === "form" && account && (
        <PurchaseOrderFormDialog account={account} order={dialog.order} onClose={() => setDialog(null)}
          onSaved={(o) => { setDialog(null); setNote(`Draft ${o.number} saved in your OneDrive (_System/PurchaseOrders).`); void load(); }} />
      )}
      {dialog?.kind === "pdf" && account && (
        <SendDialog
          id="po-send-title"
          title={`${dialog.order.status === "approved" ? "Preview and send" : "Purchase order"} ${dialog.order.number}`}
          summary={`${dialog.order.supplier.name} · ${money(dialog.order.total_pence)}${dialog.order.delivery_date ? ` · delivery by ${ukDate(dialog.order.delivery_date)}` : ""}`}
          attachName={`${dialog.order.number}.pdf`}
          canSend={dialog.order.status === "approved"}
          load={() => runtime.purchaseOrderPdf(account, dialog.order.number)}
          send={async (email) => { replace(await runtime.sendPurchaseOrder(account, dialog.order.number, email)); }}
          confirmText={(to) => `I have checked this order. Email it to ${to} from my Outlook.`}
          onClose={() => setDialog(null)}
          onDone={() => { setDialog(null); setNote(`${dialog.order.number} sent to the supplier.`); void load(); }}
        />
      )}
      {dialog?.kind === "match" && account && (
        <MatchDialog account={account} order={dialog.order} onClose={() => setDialog(null)}
          onDone={(o) => { setDialog(null); replace(o); setNote(`The bill is matched to ${o.number}.`); void load(); }} />
      )}
      {dialog?.kind === "cancel" && account && (
        <CancelDialog account={account} order={dialog.order} onClose={() => setDialog(null)}
          onDone={(o) => { setDialog(null); replace(o); setNote(`${o.number} is cancelled.`); }} />
      )}
    </div>
  );
}
