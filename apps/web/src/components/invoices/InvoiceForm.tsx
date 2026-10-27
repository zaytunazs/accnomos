"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { PreviewSendDialog } from "@/components/invoices/InvoiceDialogs";
import { fieldArea, fieldInput, fieldLabel, primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { linePence, liveTotals, money, parsePounds, poundsInput, thousandths, todayIso, useMsAccount, VAT_CODES, type LiveTotals } from "@/lib/invoices";
import { RuntimeErrorNote } from "@/components/States";
import {
  INVOICE_DRAFT_KEY,
  runtime,
  type JobInvoiceDraft,
  type RtInvoice,
  type RtInvoiceCustomer,
  type RtInvoiceDraft,
  type RtSalesVatCode,
} from "@/lib/runtime";

interface LineForm {
  key: number;
  description: string;
  quantity: string;
  unit: string;
  price: string; // pounds as typed
  vat_code: RtSalesVatCode;
  entry_ids: string[]; // job hours this line bills; marked invoiced when the invoice is sent
}

const EMPTY_CUSTOMER: RtInvoiceCustomer = { contact_id: null, name: "", email: null, address: null, vrn: null };
let nextKey = 1;
const blankLine = (): LineForm => ({ key: nextKey++, description: "", quantity: "1", unit: "", price: "", vat_code: "S", entry_ids: [] });

/** The lines and customer a job's "Invoice these hours" left in sessionStorage, or null. */
function readJobDraft(): JobInvoiceDraft | null {
  try {
    const d = JSON.parse(window.sessionStorage.getItem(INVOICE_DRAFT_KEY) ?? "null") as JobInvoiceDraft | null;
    return d?.proposal?.lines?.length ? d : null;
  } catch {
    return null;
  }
}

/**
 * /invoices/new, /invoices/new?id=INV-0001 to change a draft, and /invoices/new?from=job for a job's unbilled hours
 * (prefilled from INVOICE_DRAFT_KEY, all editable). Sums are previews; the runtime prices it on save.
 */
export default function InvoiceForm() {
  const router = useRouter();
  const params = useSearchParams();
  const editId = params.get("id");
  const fromJob = !editId && params.get("from") === "job";
  const { account, ready } = useMsAccount();
  const [customers, setCustomers] = useState<RtInvoiceCustomer[]>([]);
  const [customer, setCustomer] = useState<RtInvoiceCustomer>(EMPTY_CUSTOMER);
  const [issueDate, setIssueDate] = useState(todayIso());
  const [dueDate, setDueDate] = useState("");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<LineForm[]>(() => [blankLine()]);
  const [terms, setTerms] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<RtInvoice | null>(null);
  const [preview, setPreview] = useState(false);
  const [locked, setLocked] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobNote, setJobNote] = useState<{ name: string; warnings: string[] } | null>(null);
  const [query, setQuery] = useState("");
  const [dirty, setDirty] = useState(false);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfNote, setPdfNote] = useState<string | null>(null);

  useEffect(() => {
    if (!fromJob) return;
    const d = readJobDraft();
    // Deferred to avoid a synchronous setState in the effect body.
    queueMicrotask(() => {
      if (!d) return setError("No job hours to invoice here. Open the job and press Invoice these hours again.");
      setJobId(d.proposal.job_id);
      setJobNote({ name: d.job_name, warnings: d.proposal.warnings });
      setCustomer({ ...EMPTY_CUSTOMER, contact_id: d.proposal.customer_id, name: d.customer_name ?? "" });
      setLines(d.proposal.lines.map((l) => ({
        key: nextKey++, description: l.description, quantity: String(l.qty), unit: l.unit === "hour" ? "hours" : l.unit,
        price: poundsInput(l.unit_price_pence), vat_code: l.vat_code as RtSalesVatCode, entry_ids: l.entry_ids,
      })));
    });
  }, [fromJob]);

  useEffect(() => {
    if (!account) return;
    runtime.invoiceCustomers(account).then((cs) => {
      setCustomers(cs);
      // A job's customer arrives as a contact id and name: fill in the rest from the contact book.
      setCustomer((c) => {
        const known = c.contact_id && !c.email && !c.address ? cs.find((x) => x.contact_id === c.contact_id) : undefined;
        return known ? { ...known } : c;
      });
    }).catch(() => setCustomers([]));
    runtime.invoiceProfile(account).then((p) => setTerms(p.terms_days)).catch(() => setTerms(null));
    if (!editId) return;
    runtime.invoice(account, editId).then((inv) => {
      if (inv.status !== "draft") return setLocked(`${inv.number} is ${inv.status}; only drafts can be changed.`);
      setSaved(inv);
      setCustomer(inv.customer);
      setIssueDate(inv.issue_date);
      setDueDate(inv.due_date);
      setReference(inv.reference ?? "");
      setNotes(inv.notes ?? "");
      setJobId(inv.job_id);
      setLines(inv.lines.map((l) => ({
        key: nextKey++, description: l.description, quantity: String(l.quantity), unit: l.unit ?? "",
        price: poundsInput(l.unit_price_pence), vat_code: l.vat_code, entry_ids: l.timesheet_entry_ids ?? [],
      })));
      setDirty(false);
    }).catch((e) => setError((e as Error).message));
  }, [account, editId]);

  // Every edit below goes through these so the totals know when they no longer match the last save.
  function touchLines(next: LineForm[] | ((ls: LineForm[]) => LineForm[])) {
    setLines((ls) => (typeof next === "function" ? (next as (ls: LineForm[]) => LineForm[])(ls) : next));
    setDirty(true);
  }

  function touchCustomer(patch: Partial<RtInvoiceCustomer>) {
    setCustomer((c) => ({ ...c, ...patch }));
    setDirty(true);
  }

  function touch(set: () => void) {
    set();
    setDirty(true);
  }

  function setLine(key: number, patch: Partial<LineForm>) {
    touchLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  }

  /** Enter on a line adds the next one and moves into its description; Tab moves across as usual. */
  function addLine(focus = false) {
    const nl = blankLine();
    touchLines((ls) => [...ls, nl]);
    if (focus) requestAnimationFrame(() => document.getElementById(`ln-desc-${nl.key}`)?.focus());
  }

  function moveLine(key: number, dir: -1 | 1) {
    touchLines((ls) => {
      const i = ls.findIndex((l) => l.key === key);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= ls.length) return ls;
      const next = [...ls];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  }

  function pick(contactId: string) {
    const c = customers.find((x) => x.contact_id === contactId);
    setCustomer(c ? { ...c } : EMPTY_CUSTOMER);
    setDirty(true);
    setQuery("");
  }

  function pickNew() {
    // New customer inline: keep what was typed below, forget the contact link.
    setCustomer((c) => (c.contact_id ? { ...EMPTY_CUSTOMER, name: "", email: "" } : c));
    setDirty(true);
    setQuery("");
  }

  const q = query.trim().toLowerCase();
  const matches = q
    ? customers.filter((c) => `${c.name} ${c.email ?? ""}`.toLowerCase().includes(q)).slice(0, 6)
    : [];

  // The preview pane beside the form; re-rendered from the invoice after every save.
  useEffect(() => {
    if (!saved || !account) return;
    let blobUrl: string | null = null;
    let cancelled = false;
    // Deferred to avoid a synchronous setState in the effect body.
    queueMicrotask(() => {
      if (cancelled) return;
      setPdfUrl(null);
      setPdfNote(null);
    });
    runtime.invoicePdf(account, saved.number).then(async (r) => {
      const blob = await (await fetch(r.data_url)).blob();
      if (cancelled) return;
      blobUrl = URL.createObjectURL(blob);
      setPdfUrl(blobUrl);
    }).catch((e) => {
      if (!cancelled) setPdfNote((e as Error).message);
    });
    return () => {
      cancelled = true;
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [account, saved]);

  const priced = lines.map((l) => ({ quantity: l.quantity, unit_price_pence: parsePounds(l.price) ?? 0, vat_code: l.vat_code }));
  const totals = liveTotals(lines.filter((l) => parsePounds(l.price) !== null).map((l) => ({
    quantity: l.quantity, unit_price_pence: parsePounds(l.price)!, vat_code: l.vat_code,
  })));

  // Totals are the runtime's figures once saved; while typing they are a greyed preview.
  const showSaved = saved !== null && !dirty;
  const shownTotals: LiveTotals = showSaved
    ? {
      byCode: saved!.vat_summary.map((g) => ({ code: g.vat_code, rate: g.vat_rate, net: g.net_pence, vat: g.vat_pence })),
      net: saved!.net_pence, vat: saved!.vat_pence, total: saved!.total_pence,
    }
    : totals;

  function toDraft(): RtInvoiceDraft | string {
    if (!customer.name.trim()) return "Add the customer's name.";
    const out: RtInvoiceDraft["lines"] = [];
    for (const [n, l] of lines.entries()) {
      if (!l.description.trim() && !l.price.trim()) continue;
      if (!l.description.trim()) return `Line ${n + 1}: add a description.`;
      if (thousandths(l.quantity) === null || thousandths(l.quantity) === 0) return `Line ${n + 1}: quantity must be a number above 0 (up to 3 decimals).`;
      const p = parsePounds(l.price);
      if (p === null) return `Line ${n + 1}: unit price must be pounds and pence, e.g. 45.00.`;
      out.push({
        description: l.description.trim(), quantity: l.quantity.trim(), unit: l.unit.trim() || null, unit_price_pence: p, vat_code: l.vat_code,
        timesheet_entry_ids: l.entry_ids,
      });
    }
    if (!out.length) return "Add at least one line.";
    const clean = (s: string | null) => (s && s.trim()) || null;
    return {
      customer: { ...customer, name: customer.name.trim(), email: clean(customer.email), address: clean(customer.address), vrn: clean(customer.vrn) },
      issue_date: issueDate || null, due_date: dueDate || null, lines: out, reference: clean(reference), notes: clean(notes),
      job_id: jobId,
    };
  }

  async function save(thenPreview: boolean, e?: FormEvent) {
    e?.preventDefault();
    if (!account) return;
    const draft = toDraft();
    if (typeof draft === "string") return setError(draft);
    setBusy(true);
    setError(null);
    try {
      const inv = saved ? await runtime.updateInvoice(account, saved.number, draft) : await runtime.createInvoice(account, draft);
      if (fromJob && !saved) {
        try {
          window.sessionStorage.removeItem(INVOICE_DRAFT_KEY); // the draft now holds the hours
        } catch {
          /* storage unavailable: nothing to clear */
        }
      }
      setSaved(inv);
      setDueDate(inv.due_date);
      setDirty(false);
      if (thenPreview) setPreview(true);
      else router.push("/invoices");
    } catch (err) {
      const msg = (err as Error).message;
      setError(/"(?:detail|msg)":"([^"]+)"/.exec(msg)?.[1] ?? msg);
    } finally {
      setBusy(false);
    }
  }

  if (ready && !account) {
    return <p className="rounded-2xl bg-ground p-4 text-sm text-muted">Sign in with Microsoft to write invoices.</p>;
  }
  if (locked) {
    return (
      <p className="rounded-2xl bg-ground p-4 text-sm text-muted">
        {locked} <Link href="/invoices" className="font-bold text-teal-dark">Back to invoices</Link>
      </p>
    );
  }

  const card = "rounded-2xl border border-border bg-white p-4";
  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
    <form onSubmit={(e) => save(false, e)} noValidate className="min-w-0 space-y-4">
      <section className={card} aria-labelledby="inv-customer">
        <h2 id="inv-customer" className="text-[17px] font-extrabold">Customer</h2>
        <div className="mt-3">
          <label className={fieldLabel} htmlFor="inv-search">Search your contacts</label>
          <input
            id="inv-search"
            className={fieldInput}
            role="combobox"
            aria-expanded={q ? true : undefined}
            aria-controls="inv-search-results"
            autoComplete="off"
            placeholder="Type a name or email…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {q && (
            <ul id="inv-search-results" role="listbox" aria-label="Matching contacts" className="mt-2 divide-y divide-border overflow-hidden rounded-xl border border-border">
              {matches.map((c) => (
                <li key={c.contact_id ?? c.name}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={customer.contact_id === c.contact_id}
                    onClick={() => c.contact_id && pick(c.contact_id)}
                    className="block w-full px-3 py-2 text-left hover:bg-ground"
                  >
                    <span className="text-[15px] font-bold">{c.name}</span>
                    {c.email && <span className="block text-sm text-muted">{c.email}</span>}
                    {c.address && <span className="block text-sm text-muted">{c.address}</span>}
                    {c.vrn && <span className="block text-sm text-muted">VAT number {c.vrn}</span>}
                  </button>
                </li>
              ))}
              {matches.length === 0 && (
                <li className="px-3 py-2 text-sm text-muted">No match — fill in the name and email below as a new customer.</li>
              )}
              <li>
                <button type="button" onClick={pickNew} className="block w-full px-3 py-2 text-left text-sm font-bold text-teal-dark hover:bg-ground">
                  New customer…
                </button>
              </li>
            </ul>
          )}
          <p className="mt-1 text-xs text-muted">
            Full details live on the <Link href="/contacts" className="font-bold text-teal-dark">contacts page</Link>.
          </p>
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <label className={fieldLabel} htmlFor="inv-name">Name</label>
            <input id="inv-name" className={fieldInput} value={customer.name} onChange={(e) => touchCustomer({ name: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="inv-email">Email (the invoice is sent here)</label>
            <input id="inv-email" type="email" className={fieldInput} value={customer.email ?? ""} onChange={(e) => touchCustomer({ email: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="inv-address">Address</label>
            <textarea id="inv-address" rows={3} className={fieldArea} value={customer.address ?? ""} onChange={(e) => touchCustomer({ address: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="inv-vrn">Their VAT number (optional)</label>
            <input id="inv-vrn" className={fieldInput} value={customer.vrn ?? ""} onChange={(e) => touchCustomer({ vrn: e.target.value })} />
          </div>
        </div>
      </section>

      <section className={card} aria-labelledby="inv-dates">
        <h2 id="inv-dates" className="text-[17px] font-extrabold">Dates</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <div>
            <label className={fieldLabel} htmlFor="inv-issue">Invoice date</label>
            <input id="inv-issue" type="date" className={fieldInput} value={issueDate} onChange={(e) => touch(() => setIssueDate(e.target.value))} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="inv-due">Due date</label>
            <input id="inv-due" type="date" className={fieldInput} value={dueDate} onChange={(e) => touch(() => setDueDate(e.target.value))} />
            {!dueDate && <p className="mt-1 text-xs text-muted">Blank: {terms ?? 30} days after the invoice date</p>}
          </div>
          <div>
            <label className={fieldLabel} htmlFor="inv-ref">Their PO or job number</label>
            <input id="inv-ref" className={fieldInput} value={reference} onChange={(e) => touch(() => setReference(e.target.value))} />
          </div>
        </div>
      </section>

      <section className={card} aria-labelledby="inv-lines">
        <h2 id="inv-lines" className="text-[17px] font-extrabold">Lines</h2>
        {jobId && lines.some((l) => l.entry_ids.length > 0) && (
          <div className="mt-2 rounded-xl bg-teal-tint p-3 text-sm" role="status">
            <p>
              Lines from job {jobNote ? <strong>{jobNote.name}</strong> : "a job"}. When this invoice is sent, the hours on these
              lines are marked invoiced with its number. Removing a line leaves its hours unbilled.
            </p>
            {jobNote?.warnings.map((w) => (
              <p key={w} className="mt-1 font-semibold text-warn-ink">{w}</p>
            ))}
          </div>
        )}
        <div className="mt-3 space-y-3">
          {lines.map((l, n) => {
            const p = linePence(priced[n]);
            const priceOk = l.price.trim() === "" || parsePounds(l.price) !== null;
            return (
              <div
                key={l.key}
                className="rounded-xl border border-border p-3"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.target as HTMLElement).tagName === "INPUT") {
                    e.preventDefault();
                    addLine(true);
                  }
                }}
              >
                <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
                  <div>
                    <label className={fieldLabel} htmlFor={`ln-desc-${l.key}`}>Description</label>
                    <input id={`ln-desc-${l.key}`} className={fieldInput} value={l.description} onChange={(e) => setLine(l.key, { description: e.target.value })} />
                  </div>
                  <p className="self-end pb-2 text-right text-[15px] font-extrabold tabular-nums">
                    {p && parsePounds(l.price) !== null ? money(p.net) : "—"}
                  </p>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <div>
                    <label className={fieldLabel} htmlFor={`ln-qty-${l.key}`}>Qty</label>
                    <input id={`ln-qty-${l.key}`} inputMode="decimal" className={fieldInput} value={l.quantity} onChange={(e) => setLine(l.key, { quantity: e.target.value })} />
                  </div>
                  <div>
                    <label className={fieldLabel} htmlFor={`ln-unit-${l.key}`}>Unit</label>
                    <input id={`ln-unit-${l.key}`} className={fieldInput} placeholder="hours, days, each" value={l.unit} onChange={(e) => setLine(l.key, { unit: e.target.value })} />
                  </div>
                  <div>
                    <label className={fieldLabel} htmlFor={`ln-price-${l.key}`}>Unit price (£, ex VAT)</label>
                    <input id={`ln-price-${l.key}`} inputMode="decimal" className={`${fieldInput} ${priceOk ? "" : "border-warn-border"}`} placeholder="45.00" value={l.price} onChange={(e) => setLine(l.key, { price: e.target.value })} />
                  </div>
                  <div>
                    <label className={fieldLabel} htmlFor={`ln-vat-${l.key}`}>VAT</label>
                    <select id={`ln-vat-${l.key}`} className={fieldInput} value={l.vat_code} onChange={(e) => setLine(l.key, { vat_code: e.target.value as RtSalesVatCode })}>
                      {VAT_CODES.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
                    </select>
                  </div>
                </div>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                  {n > 0 && (
                    <button type="button" onClick={() => moveLine(l.key, -1)} aria-label={`Move line ${n + 1} up`} className="text-[13px] font-bold text-muted hover:underline">
                      Move up
                    </button>
                  )}
                  {n < lines.length - 1 && (
                    <button type="button" onClick={() => moveLine(l.key, 1)} aria-label={`Move line ${n + 1} down`} className="text-[13px] font-bold text-muted hover:underline">
                      Move down
                    </button>
                  )}
                  {lines.length > 1 && (
                    <button type="button" onClick={() => touchLines((ls) => ls.filter((x) => x.key !== l.key))} className="text-[13px] font-bold text-muted hover:underline">
                      Remove line
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
        <button type="button" onClick={() => addLine(true)} className="mt-3 text-sm font-bold text-teal-dark hover:underline">
          + Add a line
        </button>

        <dl className={`mt-4 space-y-1 border-t border-border pt-3 text-sm ${showSaved ? "" : "opacity-60"}`} aria-live="polite">
          {shownTotals.byCode.map((g) => (
            <div key={g.code} className="flex justify-between text-muted">
              <dt>{VAT_CODES.find((c) => c.code === g.code)!.label}: net {money(g.net)}</dt>
              <dd className="tabular-nums">VAT {money(g.vat)}</dd>
            </div>
          ))}
          <div className="flex justify-between pt-1"><dt className="font-bold">Net</dt><dd className="tabular-nums">{money(shownTotals.net)}</dd></div>
          <div className="flex justify-between"><dt className="font-bold">VAT</dt><dd className="tabular-nums">{money(shownTotals.vat)}</dd></div>
          <div className="flex justify-between text-[17px]"><dt className="font-extrabold">Total</dt><dd className="font-extrabold tabular-nums">{money(shownTotals.total)}</dd></div>
        </dl>
        {showSaved ? (
          <p className="mt-2 text-xs text-muted">Totals from your last save. Edit the lines to re-price them.</p>
        ) : (
          <p className="mt-2 text-xs text-muted">A preview while you type; Accnomos works out the sums again when you save.</p>
        )}
      </section>

      <section className={card}>
        <label className={fieldLabel} htmlFor="inv-notes">Note on the invoice (optional)</label>
        <textarea id="inv-notes" rows={2} className={fieldArea} value={notes} onChange={(e) => touch(() => setNotes(e.target.value))} />
      </section>

      {error && <RuntimeErrorNote message={error} />}
      <div className="flex flex-wrap gap-3">
        <Link href="/invoices" className={`${secondaryButton} inline-flex items-center`}>Cancel</Link>
        <button type="submit" disabled={busy || !account} className={secondaryButton}>{busy ? "Saving…" : "Save draft"}</button>
        <button type="button" onClick={() => save(true)} disabled={busy || !account} className={`${primaryButton} flex-1`}>
          Save and preview
        </button>
      </div>
      {saved && <p className="text-xs text-muted">Draft {saved.number} saved in your OneDrive (03 Sales/invoices).</p>}

      {preview && saved && account && (
        <PreviewSendDialog account={account} invoice={saved} onClose={() => setPreview(false)} onDone={() => router.push("/invoices")} />
      )}
    </form>
    {saved && (
      <aside aria-label="Invoice preview" className={`${card} min-w-0 lg:sticky lg:top-4`}>
        <h2 className="text-[17px] font-extrabold">Preview {saved.number}</h2>
        <p className="mt-1 text-sm font-bold">{saved.customer.name}</p>
        {saved.customer.address && <p className="whitespace-pre-line text-sm text-muted">{saved.customer.address}</p>}
        {(saved.customer.email || saved.customer.vrn) && (
          <p className="text-sm text-muted">
            {[saved.customer.email, saved.customer.vrn && `VAT ${saved.customer.vrn}`].filter(Boolean).join(" · ")}
          </p>
        )}
        <p className="mt-1 text-sm text-muted">
          Net {money(saved.net_pence)} · VAT {money(saved.vat_pence)} · <strong className="text-ink">Total {money(saved.total_pence)}</strong>
        </p>
        <div className="mt-3 h-[70vh] min-h-96 overflow-hidden rounded-xl border border-border bg-ground lg:h-[60vh]">
          {pdfUrl ? (
            <iframe title={`PDF of ${saved.number}`} src={pdfUrl} className="h-full w-full" />
          ) : (
            <p className="p-4 text-sm text-muted">{pdfNote ? "Could not make the PDF." : "Making the PDF…"}</p>
          )}
        </div>
        {pdfUrl && (
          <a href={pdfUrl} download={`${saved.number}.pdf`} className="mt-2 inline-block text-sm font-bold text-teal-dark hover:underline">
            Download PDF
          </a>
        )}
      </aside>
    )}
    </div>
  );
}
