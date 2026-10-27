"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "@/lib/msal";
import { csvFilename, downloadCsv, type CsvValue } from "@/lib/csv";
import { markContactsImported } from "@/components/home/SetupChecklist";
import SignInCta from "@/components/SignInCta";
import { EmptyState, RuntimeErrorNote, isAuthError, isServerError } from "@/components/States";
import { ApplyCreditDialog, BillPaymentDialog, RefundDialog, errorText } from "@/components/invoices/CreditDialogs";
import {
  AGED_BUCKETS,
  agedBucketLabel,
  runtime,
  ukDate,
  type RtAged,
  type RtAgedBucket,
  type RtAgedRow,
  type RtAgedTable,
  type RtContactEdits,
  type RtContactField,
  type RtContactRow,
  type RtOpenItem,
  type RtStatement,
  type RtVatStatus,
} from "@/lib/runtime";
import { sampleAged, sampleContacts } from "@/lib/sample-contacts";

/** services/runtime/app/schemas.py CATEGORIES, minus Sales (a supplier default). */
const CATEGORIES = [
  "Tools & small equipment", "Materials", "Office supplies", "Motor expenses", "Travel", "Subsistence",
  "Software & subscriptions", "Telephone & internet", "Rent", "Utilities", "Insurance", "Professional fees",
  "Advertising", "Postage", "Bank charges", "Sundry",
];
const VAT_CODES: [string, string][] = [
  ["S", "Standard 20%"], ["R", "Reduced 5%"], ["Z", "Zero"], ["E", "Exempt"], ["O", "Outside scope"], ["N", "No VAT invoice"],
];
const BUCKETS: RtAgedBucket[] = AGED_BUCKETS;
const KIND_LABEL = { customer: "Customer", supplier: "Supplier", both: "Both" } as const;
type KindFilter = "customer" | "supplier" | "all";
type SortKey = "name" | "balance";

/** UK VAT number: GB then 9 or 12 digits; spaces are allowed and ignored. */
export function isVrnValid(vrn: string): boolean {
  return /^GB\d{9}(\d{3})?$/.test(vrn.replace(/\s+/g, "").toUpperCase());
}

const money = (pence: number) =>
  (pence / 100).toLocaleString("en-GB", { style: "currency", currency: "GBP" });

function Balance({ pence }: { pence: number }) {
  if (pence === 0) return <span className="text-muted">—</span>;
  return pence > 0 ? (
    <span className="font-bold text-teal-dark">owes you {money(pence)}</span>
  ) : (
    <span className="font-bold text-warn-ink">you owe {money(-pence)}</span>
  );
}

function ytd(c: RtContactRow): string {
  const sales = c.totals.ytd_sales_net_pence;
  const purchases = c.totals.ytd_purchases_net_pence;
  if (c.kind === "both" || (sales && purchases)) return `${money(sales)} sales · ${money(purchases)} bought`;
  return money(c.kind === "customer" ? sales : purchases);
}

function lastActivity(c: RtContactRow): string {
  return c.totals.last_activity ? `Last active ${ukDate(c.totals.last_activity)}` : "No activity yet";
}

/** Contacts with their balances, money exactly as the runtime gave it (signed pence). */
function contactRows(list: RtContactRow[]): CsvValue[][] {
  return [
    ["name", "kind", "email", "phone", "vrn", "balance_pence", "ytd_sales_net_pence", "ytd_purchases_net_pence"],
    ...list.map((c) => [c.name, c.kind, c.email, c.phone, c.vrn, c.totals.balance_pence, c.totals.ytd_sales_net_pence, c.totals.ytd_purchases_net_pence]),
  ];
}

const card = "rounded-2xl border border-border bg-white";
const th = "px-4 py-2.5 text-left text-[13px] font-bold text-muted";
const td = "px-4 py-2.5 text-[15px]";
const input = "h-10 w-full rounded-xl border border-border bg-white px-3 text-[15px] focus:border-teal focus:outline-none";
const secondary =
  "shrink-0 rounded-xl border-2 border-teal bg-white px-4 py-2 text-sm font-bold text-teal-dark disabled:border-border disabled:text-muted";
const quietAction = "shrink-0 rounded-lg px-2 py-1 text-[13px] font-bold text-teal-dark hover:bg-teal-tint";

/** Small stacked bars of the unpaid aged buckets for one contact. */
function AgedBars({ row }: { row: RtAgedRow | undefined }) {
  if (!row || row.total_pence === 0) return <span className="text-muted">—</span>;
  const segs = BUCKETS.map((b) => ({ b, v: row.buckets[b] })).filter((s) => s.v > 0);
  const label = `Unpaid ${money(row.total_pence)}: ` + segs.map((s) => `${money(s.v)} ${agedBucketLabel(s.b).toLowerCase()}`).join(", ");
  const shade = (b: RtAgedBucket) =>
    b === "90+" ? "bg-amber" : b === "61-90" ? "bg-teal" : b === "31-60" ? "bg-teal/60" : b === "0-30" ? "bg-teal/35" : "bg-teal/15";
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className="inline-flex h-2 w-28 overflow-hidden rounded-full bg-ground"
    >
      {segs.map((s) => (
        <span key={s.b} className={shade(s.b)} style={{ width: `${(s.v / row.total_pence) * 100}%` }} />
      ))}
    </span>
  );
}

function QuickActions({ contact, onStatement, onEdit, canEdit }: {
  contact: RtContactRow;
  onStatement: () => void;
  onEdit: () => void;
  canEdit: boolean;
}) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1 print:hidden">
      <button type="button" onClick={onStatement} className={quietAction}>
        Statement
      </button>
      {(contact.kind === "customer" || contact.kind === "both") && (
        <Link href={`/invoices/new?customer=${contact.id}`} className={quietAction}>
          New invoice
        </Link>
      )}
      <button
        type="button"
        onClick={onEdit}
        disabled={!canEdit}
        title={canEdit ? "Edit this contact" : "Sign in to edit contacts"}
        className={`${quietAction} disabled:opacity-60`}
      >
        Edit
      </button>
    </span>
  );
}

/** Contact.vat_status (services/runtime/app/contacts.py): what the VAT number check decides on for this supplier. */
export const VAT_STATUS_LABEL: Record<RtVatStatus, string> = {
  registered: "VAT-registered",
  not_registered: "Not VAT-registered",
  unknown: "VAT status not known yet",
};
const buysFrom = (c: RtContactRow) => c.kind !== "customer";

function ContactSubline({ contact, showKind }: { contact: RtContactRow; showKind: boolean }) {
  return (
    <span className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[13px] font-medium text-muted">
      {showKind && <span>{KIND_LABEL[contact.kind]}</span>}
      {contact.vrn && <span>VAT {contact.vrn}</span>}
      {buysFrom(contact) && contact.vat_status === "not_registered" && <span>{VAT_STATUS_LABEL.not_registered}</span>}
      {contact.email && <span className="break-all">{contact.email}</span>}
      <span>{lastActivity(contact)}</span>
    </span>
  );
}

function ContactList({ rows, agedById, showKind, selected, onSelect, onEdit, canEdit }: {
  rows: RtContactRow[];
  agedById: Map<string, RtAgedRow>;
  showKind: boolean;
  selected: string | null;
  onSelect: (id: string) => void;
  onEdit: (id: string) => void;
  canEdit: boolean;
}) {
  if (!rows.length) {
    return <p className={`${card} p-4 text-sm font-semibold text-muted`}>No contacts match.</p>;
  }
  return (
    <>
      {/* Phone: one card per contact. */}
      <ul className="flex flex-col gap-2 md:hidden">
        {rows.map((c) => (
          <li
            key={c.id}
            className={`${card} flex flex-col gap-1.5 p-4 ${selected === c.id ? "border-teal" : ""}`}
          >
            <span className="flex items-start justify-between gap-2">
              <button
                type="button"
                className="text-left text-[15px] font-bold"
                onClick={() => onSelect(c.id)}
                aria-pressed={selected === c.id}
              >
                {c.name}
              </button>
              <span className="shrink-0 text-[15px] tabular-nums">
                <Balance pence={c.totals.balance_pence} />
              </span>
            </span>
            <ContactSubline contact={c} showKind={showKind} />
            <span className="flex items-center justify-between gap-2">
              <AgedBars row={agedById.get(c.id)} />
              <span className="text-[13px] tabular-nums text-muted">{ytd(c)}</span>
            </span>
            <QuickActions contact={c} onStatement={() => onSelect(c.id)} onEdit={() => onEdit(c.id)} canEdit={canEdit} />
          </li>
        ))}
      </ul>
      {/* Wider screens: the table. */}
      <div className={`${card} hidden overflow-x-auto md:block`}>
        <table className="w-full min-w-[720px] border-collapse">
          <thead className="border-b border-border">
            <tr>
              <th className={th}>Name</th>
              <th className={th}>Unpaid age</th>
              <th className={`${th} text-right`}>Open balance</th>
              <th className={`${th} text-right`}>Net this tax year</th>
              <th className={th}>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr
                key={c.id}
                className={`cursor-pointer border-b border-border last:border-b-0 ${selected === c.id ? "bg-teal-tint" : "hover:bg-ground"}`}
                onClick={() => onSelect(c.id)}
              >
                <td className={td}>
                  <button type="button" className="block text-left font-semibold" onClick={() => onSelect(c.id)} aria-pressed={selected === c.id}>
                    {c.name}
                  </button>
                  <ContactSubline contact={c} showKind={showKind} />
                </td>
                <td className={td}>
                  <AgedBars row={agedById.get(c.id)} />
                </td>
                <td className={`${td} text-right tabular-nums`}>
                  <Balance pence={c.totals.balance_pence} />
                </td>
                <td className={`${td} text-right tabular-nums text-muted`}>{ytd(c)}</td>
                <td className={`${td} whitespace-nowrap text-right`}>
                  <QuickActions contact={c} onStatement={() => onSelect(c.id)} onEdit={() => onEdit(c.id)} canEdit={canEdit} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function AliasChips({ aliases }: { aliases: string[] }) {
  if (!aliases.length) return null;
  return (
    <span className="flex flex-col gap-1">
      <span className="text-[13px] font-bold text-muted">Also spelt in your books</span>
      <span className="flex flex-wrap gap-1.5">
        {aliases.map((a) => (
          <span key={a} className="rounded-full bg-ground px-2.5 py-1 text-[13px] font-semibold text-muted">
            {a}
          </span>
        ))}
      </span>
      <span className="text-[13px] font-medium text-muted">Spellings merge here when you refresh from your books.</span>
    </span>
  );
}

type Form = Record<RtContactField | "terms_days", string>;

function toForm(c: RtContactRow): Form {
  return {
    name: c.name, kind: c.kind, vrn: c.vrn ?? "", email: c.email ?? "", phone: c.phone ?? "", address: c.address ?? "",
    default_category: c.default_category ?? "", default_vat_code: c.default_vat_code ?? "", vat_status: c.vat_status ?? "unknown",
    terms_days: c.terms_days === null || c.terms_days === undefined ? "" : String(c.terms_days),
  };
}

/** Payment terms as typed: blank is the 30-day default (null); otherwise whole days, 0 to 365. */
export function parseTerms(raw: string): number | null | "bad" {
  const t = raw.trim();
  if (!t) return null;
  if (!/^\d{1,3}$/.test(t)) return "bad";
  const n = Number(t);
  return n <= 365 ? n : "bad";
}

function EditForm({ contact, onSave, onCancel }: {
  contact: RtContactRow;
  onSave: (edits: RtContactEdits) => Promise<void>;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<Form>(() => toForm(contact));
  const [saving, setSaving] = useState(false);
  const [vrnError, setVrnError] = useState<string | null>(null);
  const [termsError, setTermsError] = useState<string | null>(null);
  const set = (k: RtContactField | "terms_days") => (e: { target: { value: string } }) => {
    setForm((f) => ({ ...f, [k]: e.target.value }));
    if (k === "vrn") setVrnError(null);
    if (k === "terms_days") setTermsError(null);
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    const vrn = form.vrn.trim();
    if (vrn && !isVrnValid(vrn)) {
      setVrnError("Check the VAT number: GB followed by 9 or 12 digits (spaces are fine).");
      return;
    }
    const terms = parseTerms(form.terms_days);
    if (terms === "bad") {
      setTermsError("Payment terms are a whole number of days, 0 to 365 (blank for the usual 30).");
      return;
    }
    const before = toForm(contact);
    const edits: RtContactEdits = Object.fromEntries(
      (Object.keys(form) as RtContactField[]).filter((k) => k !== ("terms_days" as string) && form[k].trim() !== before[k]).map((k) => [k, form[k].trim() || null]),
    );
    if (form.terms_days.trim() !== before.terms_days) edits.terms_days = terms;
    if (!Object.keys(edits).length) return onCancel();
    setSaving(true);
    try {
      await onSave(edits);
    } finally {
      setSaving(false);
    }
  }

  const field = (k: RtContactField, label: string, type = "text", extra?: { describedBy?: string }) => (
    <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
      {label}
      <input className={input} type={type} value={form[k]} onChange={set(k)} aria-describedby={extra?.describedBy} aria-invalid={k === "vrn" && vrnError ? true : undefined} />
    </label>
  );

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      {field("name", "Name")}
      <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
        Kind
        <select className={input} value={form.kind} onChange={set("kind")}>
          <option value="customer">Customer</option>
          <option value="supplier">Supplier</option>
          <option value="both">Both</option>
        </select>
      </label>
      {field("vrn", "VAT number", "text", { describedBy: "vrn-hint" })}
      <span id="vrn-hint" className="text-[13px] font-medium text-muted">
        GB followed by 9 or 12 digits; spaces are fine. Leave blank if they have none.
      </span>
      {vrnError && <p role="alert" className="text-sm font-semibold text-warn-ink">{vrnError}</p>}
      {buysFrom(contact) && (
        <>
          <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
            VAT status
            <select className={input} value={form.vat_status} onChange={set("vat_status")} aria-describedby="vat-status-hint">
              <option value="registered">{VAT_STATUS_LABEL.registered}</option>
              <option value="not_registered">{VAT_STATUS_LABEL.not_registered}</option>
              <option value="unknown">Not known: ask me over £250</option>
            </select>
          </label>
          <span id="vat-status-hint" className="text-[13px] font-medium text-muted">
            A receipt over £250 with no VAT and no VAT number is only questioned while this is not known. Learnt when you approve.
          </span>
        </>
      )}
      <AliasChips aliases={contact.aliases} />
      {field("email", "Email", "email")}
      {field("phone", "Phone", "tel")}
      <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
        Address
        <textarea className={`${input} h-20 py-2`} value={form.address} onChange={set("address")} />
      </label>
      <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
        Usual category
        <select className={input} value={form.default_category} onChange={set("default_category")}>
          <option value="">—</option>
          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
        Usual VAT treatment
        <select className={input} value={form.default_vat_code} onChange={set("default_vat_code")}>
          <option value="">—</option>
          {VAT_CODES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
        Payment terms (days)
        <input
          className={input}
          inputMode="numeric"
          value={form.terms_days}
          onChange={set("terms_days")}
          placeholder="30"
          aria-describedby="terms-hint"
          aria-invalid={termsError ? true : undefined}
        />
      </label>
      <span id="terms-hint" className="text-[13px] font-medium text-muted">
        Days after the document date that payment is due. Aged balances count lateness from it; a sales invoice&apos;s own due date wins. Blank: 30 days.
      </span>
      {termsError && <p role="alert" className="text-sm font-semibold text-warn-ink">{termsError}</p>}
      <p className="text-[13px] text-muted">What you change here is kept when you refresh from your books.</p>
      <div className="flex gap-2">
        <button type="submit" disabled={saving} className="h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60">
          {saving ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={onCancel} className="text-sm font-bold text-teal-dark hover:underline">
          Cancel
        </button>
      </div>
    </form>
  );
}

function StatementTable({ st, onRemove, busy }: {
  st: RtStatement;
  onRemove?: (line: RtStatement["lines"][number]) => void;
  busy?: string | null;
}) {
  if (!st.lines.length) return <p className="text-sm text-muted">Nothing in the books for this contact yet.</p>;
  return (
    <div>
      <table className="w-full border-collapse text-[13px]">
        <thead className="border-b border-border">
          <tr className="text-left font-bold text-muted">
            <th className="py-1.5 pr-2">Date</th>
            <th className="py-1.5 pr-2">Details</th>
            <th className="py-1.5 pr-2 text-right">Amount</th>
            <th className="py-1.5 pr-2 text-right">Paid</th>
            <th className="py-1.5 text-right">Balance</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {st.opening_balance_pence !== 0 && (
            <tr className="border-b border-border">
              <td className="py-1.5 pr-2" />
              <td className="py-1.5 pr-2 font-semibold">Brought forward</td>
              <td />
              <td />
              <td className="py-1.5 text-right">{money(st.opening_balance_pence)}</td>
            </tr>
          )}
          {st.lines.map((ln, i) => (
            <tr key={`${ln.event_id}-${i}`} data-kind={ln.kind ?? "invoice"} className="border-b border-border last:border-b-0">
              <td className="whitespace-nowrap py-1.5 pr-2">{ukDate(ln.date)}</td>
              <td className={`py-1.5 pr-2 ${ln.kind === "payment" || ln.kind === "credit_note" || ln.kind === "refund" ? "text-teal-dark" : ""}`}>
                {ln.details}
                {ln.reference && <span className="text-muted"> · {ln.reference}</span>}
              </td>
              <td className="py-1.5 pr-2 text-right">{ln.amount_pence ? money(ln.amount_pence) : ""}</td>
              <td className="py-1.5 pr-2 text-right">
                {ln.paid_pence ? money(ln.paid_pence) : ""}
                {onRemove && ln.payment_id && (ln.kind === "payment" || ln.kind === "refund") && (
                  <button
                    type="button"
                    onClick={() => onRemove(ln)}
                    disabled={!!busy}
                    className="ml-2 text-[12px] font-bold text-muted hover:underline print:hidden"
                    aria-label={`Remove ${ln.details.toLowerCase()} of ${money(Math.abs(ln.paid_pence))} on ${ukDate(ln.date)}`}
                  >
                    {busy === ln.payment_id ? "…" : "Remove"}
                  </button>
                )}
              </td>
              <td className="py-1.5 text-right font-semibold">{money(ln.balance_pence)}</td>
            </tr>
          ))}
          <tr>
            <td className="py-1.5 pr-2" />
            <td className="py-1.5 pr-2 font-bold">Balance carried down</td>
            <td />
            <td />
            <td className="py-1.5 text-right font-bold">{money(st.closing_balance_pence)}</td>
          </tr>
        </tbody>
      </table>
      {(st.credit_pence ?? 0) > 0 && (
        <p className="mt-2 rounded-lg bg-teal-tint px-3 py-2 text-[13px] font-semibold text-teal-dark">
          {money(st.credit_pence ?? 0)} on account: an overpayment or a credit note bigger than what was owed.
        </p>
      )}
      <p className="mt-2 text-[13px] text-muted">
        Plus means they owe you, minus means you owe them. Payments, part payments, credit notes and refunds have their own lines.
        Receipts paid by card or cash at the time are settled on the
        same line.
      </p>
    </div>
  );
}

type MoneyDialog =
  | { kind: "apply" }
  | { kind: "refund" }
  | { kind: "bill"; bill: RtOpenItem }
  | null;

/**
 * What can be done with the contact's money from here: record a payment on a bill, apply a credit on account to
 * another document, refund it, and take any of those back. Sales invoices are paid from Invoices.
 */
function MoneyActions({ account, contact, st, onChanged }: {
  account: AccountInfo;
  contact: RtContactRow;
  st: RtStatement;
  onChanged: (message: string) => Promise<void>;
}) {
  const [dialog, setDialog] = useState<MoneyDialog>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const credits = st.credits ?? [];
  const open = st.open_documents ?? [];
  const bills = open.filter((d) => d.side === "purchase");
  const uses = (st.credit_uses ?? []).filter((u) => (u.applied_pence ?? u.amount_pence) > 0 || u.kind === "refund");
  const canApply = credits.some((c) => open.some((d) => d.side === c.side));
  if (!credits.length && !bills.length && !uses.length) return null;

  async function removeUse(id: string, what: string) {
    setBusy(id);
    setNote(null);
    try {
      await runtime.removeCreditUse(account, id);
      await onChanged(`${what} taken back.`);
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  const done = async (message: string) => {
    setDialog(null);
    await onChanged(message);
  };

  return (
    <section data-contact-money aria-label={`Money with ${contact.name}`} className="flex flex-col gap-3 print:hidden">
      {credits.length > 0 && (
        <div className="rounded-xl bg-teal-tint p-3 text-[13px]">
          <h3 className="text-[15px] font-extrabold text-teal-dark">Credit on account</h3>
          <ul className="mt-1">
            {credits.map((c) => (
              <li key={c.id} className="tabular-nums">
                <strong>{money(c.amount_pence)}</strong> · {c.source === "payment" ? "overpaid" : "credit note"} on {ukDate(c.date)} ·{" "}
                {c.side === "sale" ? `you owe ${contact.name}` : `${contact.name} owes you`}
              </li>
            ))}
          </ul>
          <div className="mt-2 flex flex-wrap gap-3">
            {canApply && (
              <button type="button" className={secondary} onClick={() => setDialog({ kind: "apply" })}>Apply credit</button>
            )}
            <button type="button" className={secondary} onClick={() => setDialog({ kind: "refund" })}>Refund</button>
          </div>
        </div>
      )}
      {bills.length > 0 && (
        <div className="text-[13px]">
          <h3 className="text-[15px] font-extrabold">Bills to pay</h3>
          <ul className="mt-1 divide-y divide-border">
            {bills.map((b) => (
              <li key={b.event_id} data-bill={b.reference ?? b.event_id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                <span className="tabular-nums">
                  <span className="font-semibold">{b.reference ?? "Bill"}</span> · {ukDate(b.date)} · due {ukDate(b.due_date)} ·{" "}
                  {b.outstanding_pence < b.gross_pence && <>paid {money(b.gross_pence - b.outstanding_pence)} · </>}
                  balance <strong>{money(b.outstanding_pence)}</strong>
                  {b.outstanding_pence < b.gross_pence && <> of {money(b.gross_pence)}</>}
                </span>
                <button
                  type="button"
                  className="text-[13px] font-bold text-teal-dark hover:underline"
                  onClick={() => setDialog({ kind: "bill", bill: b })}
                  aria-label={`Record payment on ${b.reference ?? "the bill"}`}
                >
                  Record payment
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {uses.length > 0 && (
        <div className="text-[13px]">
          <h3 className="text-[15px] font-extrabold">Credit used</h3>
          <ul className="mt-1 divide-y divide-border">
            {uses.map((u) => {
              const what = u.kind === "refund" ? "Refund" : `Credit applied to ${u.reference ?? "a document"}`;
              return (
                <li key={u.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                  <span className="tabular-nums">{ukDate(u.date)} · {what} · {money(u.applied_pence ?? u.amount_pence)}</span>
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void removeUse(u.id, what)}
                    className="text-[13px] font-bold text-muted hover:underline"
                    aria-label={`Remove: ${what}`}
                  >
                    {busy === u.id ? "Removing…" : "Remove"}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {note && <p role="alert" className="text-sm font-semibold text-warn-ink">{note}</p>}
      {dialog?.kind === "apply" && (
        <ApplyCreditDialog account={account} name={contact.name} credits={credits} documents={open} onClose={() => setDialog(null)} onDone={done} />
      )}
      {dialog?.kind === "refund" && (
        <RefundDialog account={account} name={contact.name} credits={credits} onClose={() => setDialog(null)} onDone={done} />
      )}
      {dialog?.kind === "bill" && (
        <BillPaymentDialog account={account} name={contact.name} bill={dialog.bill} onClose={() => setDialog(null)} onDone={done} />
      )}
    </section>
  );
}

function SidePanel({ contact, account, editing, onEditingChange, onSaved, onClose }: {
  contact: RtContactRow;
  account: AccountInfo | null;
  editing: boolean;
  onEditingChange: (editing: boolean) => void;
  onSaved: () => Promise<void>;
  onClose: () => void;
}) {
  const [st, setSt] = useState<RtStatement | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loadingSt, setLoadingSt] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);

  async function removeLine(ln: RtStatement["lines"][number]) {
    if (!account || !ln.payment_id) return;
    setRemoving(ln.payment_id);
    setErr(null);
    try {
      if (ln.kind === "refund") await runtime.removeCreditUse(account, ln.payment_id);
      else await runtime.removePayment(account, ln.payment_id);
      setDone(`${ln.details} of ${money(Math.abs(ln.paid_pence))} taken back.`);
      await loadStatement();
      await onSaved();
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setRemoving(null);
    }
  }
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const rangeError = from && to && from > to ? "The from date is after the to date." : null;

  const loadStatement = useCallback(async () => {
    if (!account || rangeError) return;
    setErr(null);
    setLoadingSt(true);
    try {
      setSt(await runtime.statement(account, contact.id, from || undefined, to || undefined));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoadingSt(false);
    }
  }, [account, contact.id, from, to, rangeError]);

  useEffect(() => {
    queueMicrotask(() => void loadStatement());
  }, [loadStatement]);

  async function save(edits: RtContactEdits) {
    if (!account) return;
    try {
      await runtime.editContact(account, contact.id, edits);
      onEditingChange(false);
      setErr(null);
      await onSaved();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  const details: [string, string | null][] = [
    ["VAT number", contact.vrn],
    ["VAT status", buysFrom(contact) ? VAT_STATUS_LABEL[contact.vat_status ?? "unknown"] : null],
    ["Email", contact.email], ["Phone", contact.phone], ["Address", contact.address],
    ["Usual category", contact.default_category],
    ["Payment terms", contact.terms_days === null || contact.terms_days === undefined ? "30 days (the usual)" : `${contact.terms_days} days`],
  ];
  return (
    <aside aria-label={`${contact.name}: statement`} className={`${card} flex flex-col gap-4 p-4 lg:sticky lg:top-4 lg:self-start`}>
      <div className="flex items-start justify-between gap-3 print:hidden">
        <div>
          <h2 className="text-lg font-extrabold">{contact.name}</h2>
          <p className="text-[13px] font-medium text-muted">
            {KIND_LABEL[contact.kind]} · {contact.source === "outlook" ? "from Outlook" : contact.source === "manual" ? "added by you" : "from your books"}
          </p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="text-xl font-bold leading-none text-muted hover:text-ink">
          ×
        </button>
      </div>
      <div className="hidden print:block">
        <h2 className="text-lg font-extrabold">{contact.name}</h2>
        <p className="text-[13px] text-muted">
          Statement{from || to ? ` from ${from || "the start"} to ${to || "today"}` : ""} · {KIND_LABEL[contact.kind]}
          {contact.vrn ? ` · VAT ${contact.vrn}` : ""}
        </p>
      </div>

      {editing ? (
        <div className="print:hidden">
          <EditForm contact={contact} onSave={save} onCancel={() => onEditingChange(false)} />
        </div>
      ) : (
        <div className="print:hidden">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px]">
            {details.map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="font-bold text-muted">{label}</dt>
                <dd className="whitespace-pre-line">{value || "—"}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-1">
            <AliasChips aliases={contact.aliases} />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <p className="text-[15px] tabular-nums">
              <Balance pence={contact.totals.balance_pence} />
            </p>
            <button
              type="button"
              onClick={() => onEditingChange(true)}
              disabled={!account}
              title={account ? "Edit this contact" : "Sign in to edit contacts"}
              className={`${secondary} disabled:opacity-60`}
            >
              Edit
            </button>
          </div>
        </div>
      )}

      {account && st && !editing && (
        <MoneyActions
          account={account}
          contact={contact}
          st={st}
          onChanged={async (message) => {
            setDone(message);
            await loadStatement();
            await onSaved();
          }}
        />
      )}
      {done && <p role="status" className="text-sm font-semibold text-teal-dark print:hidden">{done}</p>}

      {rangeError
        ? <p role="alert" className="text-sm font-semibold text-warn-ink">{rangeError}</p>
        : err && (isAuthError(err) || isServerError(err)
          ? <RuntimeErrorNote message={err} />
          : <p role="alert" className="text-sm font-semibold text-warn-ink">{err}</p>)}

      <section data-contacts-statement aria-label={`Statement for ${contact.name}`} className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-[15px] font-extrabold">Statement</h3>
          {account && st && (
            <button type="button" onClick={() => window.print()} className={`${secondary} print:hidden`}>
              Print
            </button>
          )}
        </div>
        {!account ? (
          <p className="text-sm text-muted">Connect your OneDrive to see statements.</p>
        ) : (
          <>
            <div className="flex flex-wrap gap-2 print:hidden">
              <label className="flex flex-1 flex-col gap-1 text-[13px] font-bold text-muted">
                From
                <input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} className={input} />
              </label>
              <label className="flex flex-1 flex-col gap-1 text-[13px] font-bold text-muted">
                To
                <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} className={input} />
              </label>
            </div>
            {st ? (
              <div className="max-h-[50vh] overflow-y-auto pr-1 print:max-h-none print:overflow-visible print:pr-0">
                <StatementTable st={st} onRemove={account ? (ln) => void removeLine(ln) : undefined} busy={removing} />
              </div>
            ) : !err ? (
              <p className="text-sm text-muted">Working it out from your ledger…</p>
            ) : null}
            {loadingSt && st && <p className="text-[13px] text-muted print:hidden">Updating…</p>}
            <p className="text-[13px] text-muted print:hidden">
              Statements cannot be sent by email yet — print this page or save it as a PDF instead.
            </p>
          </>
        )}
      </section>
    </aside>
  );
}

function AgedTable({ title, hint, table, onSelect }: { title: string; hint: string; table: RtAgedTable; onSelect: (id: string) => void }) {
  return (
    <section className="flex flex-col gap-2">
      <div>
        <h2 className="text-lg font-extrabold">{title}</h2>
        <p className="text-[13px] text-muted">{hint}</p>
      </div>
      {table.rows.length === 0 ? (
        <p className={`${card} p-4 text-sm font-semibold text-muted`}>Nothing unpaid.</p>
      ) : (
        <div className={`${card} overflow-x-auto`}>
          <table className="w-full min-w-[560px] border-collapse tabular-nums">
            <thead className="border-b border-border">
              <tr>
                <th className={th}>Name</th>
                {BUCKETS.map((b) => <th key={b} className={`${th} text-right`}>{agedBucketLabel(b)}</th>)}
                <th className={`${th} text-right`}>Total</th>
              </tr>
            </thead>
            <tbody>
              {table.rows.map((r) => (
                <tr key={r.contact_id} className="border-b border-border">
                  <td className={td}>
                    <button type="button" className="text-left font-semibold hover:underline" onClick={() => onSelect(r.contact_id)}>
                      {r.name}
                    </button>
                  </td>
                  {BUCKETS.map((b) => (
                    <td key={b} className={`${td} text-right ${b === "90+" && r.buckets[b] ? "font-bold text-warn-ink" : ""}`}>
                      {r.buckets[b] ? money(r.buckets[b]) : "—"}
                    </td>
                  ))}
                  <td className={`${td} text-right font-bold`}>{money(r.total_pence)}</td>
                </tr>
              ))}
              <tr className="bg-ground">
                <td className={`${td} font-bold`}>Total</td>
                {BUCKETS.map((b) => <td key={b} className={`${td} text-right font-bold`}>{money(table.buckets[b])}</td>)}
                <td className={`${td} text-right font-extrabold`}>{money(table.total_pence)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/**
 * Review before importing: Outlook entries are matched by company name, then display name, and only fill in
 * a blank email or phone — nothing already set is overwritten. The runtime answers with counts only
 * (RtContactImport), so the names below are the local contacts that could gain details, not Outlook's list.
 */
function OutlookReview({ rows, addNew, onAddNewChange, busy, onConfirm, onCancel }: {
  rows: RtContactRow[];
  addNew: boolean;
  onAddNewChange: (v: boolean) => void;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const matchable = useMemo(() => rows.filter((c) => !c.email || !c.phone), [rows]);
  const shownNames = matchable.slice(0, 8).map((c) => c.name);
  const rest = matchable.length - shownNames.length;
  return (
    <section aria-label="Review Outlook import" aria-busy={busy} className={`${card} flex flex-col gap-3 p-4`}>
      <div>
        <h2 className="text-[15px] font-extrabold">Review the Outlook import</h2>
        <p className="mt-1 text-[13px] leading-6 text-muted">
          Outlook contacts are matched by company name. A match only fills in a blank email or phone — nothing you
          already have is overwritten. Entries that match nobody are left out unless you tick the box below.
        </p>
      </div>
      <div className="flex flex-col gap-1 text-[13px]">
        <p className="font-bold">
          Could gain an email or phone ({matchable.length})
        </p>
        {matchable.length === 0 ? (
          <p className="text-muted">Every contact already has an email and a phone.</p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {shownNames.map((n) => (
              <li key={n} className="font-medium">{n}</li>
            ))}
          </ul>
        )}
        {rest > 0 && <p className="text-muted">…and {rest} more.</p>}
      </div>
      <label className="flex items-start gap-2 text-[13px] font-semibold text-muted">
        <input type="checkbox" checked={addNew} onChange={(e) => onAddNewChange(e.target.checked)} className="mt-1" />
        <span>Also add Outlook entries that are not in your books (as customers)</span>
      </label>
      {addNew && (
        <p className="text-[13px] text-muted">Anything new arrives as a customer with whatever email and phone Outlook has.</p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onConfirm}
          disabled={busy}
          className="h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60"
        >
          {busy ? "Importing…" : "Confirm import"}
        </button>
        <button type="button" onClick={onCancel} disabled={busy} className="text-sm font-bold text-teal-dark hover:underline disabled:opacity-60">
          Cancel
        </button>
      </div>
    </section>
  );
}

/** Contacts: from the runtime when signed in; the sample otherwise. */
export default function LiveContacts() {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [state, setState] = useState<"checking" | "demo" | "loading" | "live" | "error">("checking");
  const [rows, setRows] = useState<RtContactRow[]>([]);
  const [aged, setAged] = useState<RtAged | null>(null);
  const [tab, setTab] = useState<"contacts" | "aged">("contacts");
  const [kind, setKind] = useState<KindFilter>("all");
  const [sort, setSort] = useState<SortKey>("name");
  const [query, setQuery] = useState("");
  // A deep link from Reports (?id=): open that contact's statement on arrival.
  const [selected, setSelected] = useState<string | null>(() =>
    typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("id"),
  );
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState<"refresh" | "import" | null>(null);
  const [addNew, setAddNew] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  const load = useCallback(async (acct: AccountInfo) => {
    try {
      const [list, agedNow] = await Promise.all([runtime.contacts(acct), runtime.aged(acct)]);
      setRows(list.contacts);
      setAged(agedNow);
      setState("live");
    } catch (e) {
      setState("error");
      setNote((e as Error).message);
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        if (!msalConfigured()) return setState("demo");
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct = msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
        if (!acct) return setState("demo");
        setAccount(acct);
        setState("loading");
        await load(acct);
      } catch {
        setState("demo");
      }
    })();
  }, [load]);

  async function refresh() {
    if (!account) return;
    setBusy("refresh");
    setNote(null);
    try {
      const list = await runtime.refreshContacts(account);
      setRows(list.contacts);
      setAged(await runtime.aged(account));
      setState("live");
      setNote(`${list.contacts.length} contacts saved to _System/Contacts/contacts.json in your OneDrive.`);
    } catch (e) {
      setNote(`Could not refresh: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function importOutlook() {
    if (!account) return;
    setBusy("import");
    setNote(null);
    try {
      const r = await runtime.importOutlookContacts(account, addNew);
      markContactsImported(); // the setup checklist's optional step stays ticked
      setNote(
        `Read ${r.read} Outlook contacts: ${r.matched} already here (${r.updated} gained an email or phone)` +
          (addNew ? `, ${r.added} added` : "") + `, ${r.skipped} left out.`,
      );
      setImportOpen(false);
      await load(account);
    } catch (e) {
      const msg = (e as Error).message;
      if (!/redirecting for consent/.test(msg)) setNote(`Could not import from Outlook: ${msg}`);
    } finally {
      setBusy(null);
    }
  }

  const live = state === "live";
  const shown = useMemo(
    () => (live ? rows : state === "demo" || state === "error" ? sampleContacts : []),
    [live, rows, state],
  );
  const agedShown = live ? aged : state === "demo" || state === "error" ? sampleAged : null;
  const agedById = useMemo(() => {
    const m = new Map<string, RtAgedRow>();
    for (const t of [agedShown?.debtors, agedShown?.creditors]) {
      for (const r of t?.rows ?? []) m.set(r.contact_id, r);
    }
    return m;
  }, [agedShown]);
  const counts = useMemo(() => ({
    customer: shown.filter((c) => c.kind === "customer" || c.kind === "both").length,
    supplier: shown.filter((c) => c.kind === "supplier" || c.kind === "both").length,
    all: shown.length,
  }), [shown]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const byKind = kind === "all" ? shown : shown.filter((c) => c.kind === kind || c.kind === "both");
    const byQuery = q
      ? byKind.filter((c) => [c.name, c.vrn, c.email, c.phone, ...(c.aliases ?? [])].some((v) => v?.toLowerCase().includes(q)))
      : byKind;
    return [...byQuery].sort((a, b) =>
      sort === "balance"
        ? Math.abs(b.totals.balance_pence) - Math.abs(a.totals.balance_pence) || a.name.localeCompare(b.name)
        : a.name.localeCompare(b.name),
    );
  }, [shown, kind, query, sort]);
  const kindName = kind === "all" ? "contacts" : kind === "customer" ? "customers" : "suppliers";
  const current = shown.find((c) => c.id === selected) ?? null;
  const select = (id: string) => {
    setSelected(id);
    setEditing(false);
    setTab("contacts");
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("id", id);
      window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    } catch {
      /* the address bar is unavailable — the selection still shows */
    }
  };

  const edit = (id: string) => {
    setSelected(id);
    setEditing(true);
    setTab("contacts");
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2 print:hidden">
        <div role="tablist" aria-label="Contacts views" className="flex gap-1 rounded-xl bg-white p-1 border border-border">
          {(["contacts", "aged"] as const).map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={`rounded-lg px-4 py-1.5 text-sm font-bold ${tab === t ? "bg-teal-tint text-teal-dark" : "text-muted hover:text-ink"}`}
            >
              {t === "contacts" ? "Contacts" : "Aged balances"}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={refresh} disabled={!account || busy !== null} className={secondary}
            title={account ? "Add everyone in your ledger and save contacts.json" : "Connect your OneDrive first"}>
            {busy === "refresh" ? "Refreshing…" : "Refresh from books"}
          </button>
          <button type="button" onClick={() => { setNote(null); setImportOpen(true); }} disabled={!account || busy !== null}
            title={account ? "Asks Microsoft for read-only access to your Outlook contacts" : "Connect your OneDrive first"}
            className="shrink-0 rounded-xl bg-teal px-4 py-2.5 text-sm font-bold text-white hover:bg-teal-dark disabled:opacity-60">
            Import from Outlook
          </button>
          {filtered.length > 0 && (
            <button
              type="button"
              onClick={() => downloadCsv(csvFilename("contacts"), contactRows(filtered), { sample: !live })}
              className="shrink-0 rounded-xl border border-border bg-white px-4 py-2.5 text-sm font-bold print:hidden"
            >
              Export CSV
            </button>
          )}
        </div>
      </div>

      {note && <p role="status" className="text-sm font-semibold text-teal-dark">{note}</p>}
      {state === "error" && note && (isAuthError(note) || isServerError(note)) && (
        <RuntimeErrorNote message={note} title="Could not read your contacts" />
      )}
      {state === "demo" || state === "error" ? (
        <p className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[13px] font-medium text-muted">
          <span>{state === "error" ? "Could not read your contacts; showing the sample instead." : "Sample contacts from fictional companies."}</span>
          {state === "demo" && <SignInCta />}
        </p>
      ) : null}

      {importOpen && (
        <OutlookReview
          rows={shown}
          addNew={addNew}
          onAddNewChange={setAddNew}
          busy={busy === "import"}
          onConfirm={importOutlook}
          onCancel={() => setImportOpen(false)}
        />
      )}

      {state === "checking" || state === "loading" ? (
        <p className={`${card} p-4 text-sm font-semibold text-muted`}>
          {state === "loading" ? "Reading your books…" : "Checking sign-in…"}
        </p>
      ) : tab === "aged" ? (
        agedShown && (
          <div className="flex flex-col gap-6">
            <AgedTable title="Debtors" hint="Customers who owe you: what is still owed on each sales invoice after part payments and credit notes, by days past its due date."
              table={agedShown.debtors} onSelect={select} />
            <AgedTable title="Creditors" hint="Suppliers you owe: what is left on bills on account, by days past due. Card and cash receipts are already paid."
              table={agedShown.creditors} onSelect={select} />
            <p className="text-[13px] text-muted">
              As of {ukDate(agedShown.as_of)}. Due dates come from the invoice, else the contact&apos;s payment terms, else 30 days
              from the document date. An entry drops off once payments and credit notes cover it.
            </p>
          </div>
        )
      ) : (
        <div className={`grid gap-4 ${current ? "lg:grid-cols-[minmax(0,1fr)_400px]" : ""}`}>
          <div className="flex flex-col gap-3 print:hidden">
            <div role="tablist" aria-label="Customer or supplier" className="flex gap-1 self-start rounded-xl bg-white p-1 border border-border">
              {(["customer", "supplier", "all"] as const).map((k) => (
                <button
                  key={k}
                  type="button"
                  role="tab"
                  aria-selected={kind === k}
                  onClick={() => setKind(k)}
                  className={`rounded-lg px-4 py-1.5 text-sm font-bold ${kind === k ? "bg-teal-tint text-teal-dark" : "text-muted hover:text-ink"}`}
                >
                  {k === "all" ? `Both (${counts.all})` : k === "customer" ? `Customers (${counts.customer})` : `Suppliers (${counts.supplier})`}
                </button>
              ))}
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by name, VAT number, email or phone"
                aria-label="Search contacts"
                className={input}
              />
              <label className="flex items-center gap-2 text-[13px] font-bold text-muted sm:shrink-0">
                Sort
                <select
                  aria-label="Sort contacts"
                  value={sort}
                  onChange={(e) => setSort(e.target.value as SortKey)}
                  className="h-10 rounded-xl border border-border bg-white px-2 text-[15px] font-medium text-ink focus:border-teal focus:outline-none"
                >
                  <option value="name">Name A to Z</option>
                  <option value="balance">Open balance, largest first</option>
                </select>
              </label>
            </div>
            <p aria-live="polite" className="text-[13px] font-medium text-muted">
              {filtered.length === 0
                ? `No ${kindName} match your search.`
                : `Showing ${filtered.length} of ${shown.length} ${kindName}.`}
            </p>
            {live && rows.length === 0 ? (
              <EmptyState
                title="No contacts yet"
                body="Customers and suppliers appear here once you approve receipts and invoices — or import them from Outlook."
                action={
                  <button
                    type="button"
                    onClick={() => setImportOpen(true)}
                    disabled={busy !== null}
                    className="h-11 whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60"
                  >
                    Import from Outlook
                  </button>
                }
              />
            ) : shown.length === 0 ? (
              <p className={`${card} p-4 text-sm font-semibold text-muted`}>
                No customers or suppliers yet. They appear here once you approve receipts and invoices.
              </p>
            ) : (
              <ContactList rows={filtered} agedById={agedById} showKind={kind === "all"} selected={selected} onSelect={select} onEdit={edit} canEdit={account !== null} />
            )}
          </div>
          {current && (
            <SidePanel
              key={current.id}
              contact={current}
              account={live ? account : null}
              editing={live ? editing : false}
              onEditingChange={setEditing}
              onSaved={async () => {
                if (account) await load(account);
              }}
              onClose={() => { setSelected(null); setEditing(false); }}
            />
          )}
        </div>
      )}
    </div>
  );
}
