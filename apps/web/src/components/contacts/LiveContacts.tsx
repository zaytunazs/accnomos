"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "@/lib/msal";
import {
  runtime,
  ukDate,
  type RtAged,
  type RtAgedBucket,
  type RtAgedTable,
  type RtContactField,
  type RtContactRow,
  type RtStatement,
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
const BUCKETS: RtAgedBucket[] = ["0-30", "31-60", "61-90", "90+"];
const KIND_LABEL = { customer: "Customer", supplier: "Supplier", both: "Both" } as const;

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

const card = "rounded-2xl border border-border bg-white";
const th = "px-4 py-2.5 text-left text-[13px] font-bold text-muted";
const td = "px-4 py-2.5 text-[15px]";
const input = "h-10 w-full rounded-xl border border-border bg-white px-3 text-[15px] focus:border-teal focus:outline-none";
const secondary =
  "shrink-0 rounded-xl border-2 border-teal bg-white px-4 py-2 text-sm font-bold text-teal-dark disabled:border-border disabled:text-muted";

function ContactTable({ rows, selected, onSelect }: { rows: RtContactRow[]; selected: string | null; onSelect: (id: string) => void }) {
  if (!rows.length) {
    return <p className={`${card} p-4 text-sm font-semibold text-muted`}>No contacts match.</p>;
  }
  return (
    <div className={`${card} overflow-x-auto`}>
      <table className="w-full min-w-[560px] border-collapse">
        <thead className="border-b border-border">
          <tr>
            <th className={th}>Name</th>
            <th className={th}>Kind</th>
            <th className={`${th} text-right`}>Open balance</th>
            <th className={`${th} text-right`}>Net this tax year</th>
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
                <button type="button" className="text-left font-semibold" onClick={() => onSelect(c.id)} aria-pressed={selected === c.id}>
                  {c.name}
                </button>
                {c.vrn && <span className="ml-2 text-[13px] font-medium text-muted">{c.vrn}</span>}
              </td>
              <td className={`${td} text-muted`}>{KIND_LABEL[c.kind]}</td>
              <td className={`${td} text-right tabular-nums`}>
                <Balance pence={c.totals.balance_pence} />
              </td>
              <td className={`${td} text-right tabular-nums text-muted`}>{ytd(c)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Form = Record<RtContactField, string>;

function toForm(c: RtContactRow): Form {
  return {
    name: c.name, kind: c.kind, vrn: c.vrn ?? "", email: c.email ?? "", phone: c.phone ?? "", address: c.address ?? "",
    default_category: c.default_category ?? "", default_vat_code: c.default_vat_code ?? "",
  };
}

function EditForm({ contact, onSave, onCancel }: {
  contact: RtContactRow;
  onSave: (edits: Partial<Record<RtContactField, string | null>>) => Promise<void>;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<Form>(() => toForm(contact));
  const [saving, setSaving] = useState(false);
  const set = (k: RtContactField) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    const before = toForm(contact);
    const edits = Object.fromEntries(
      (Object.keys(form) as RtContactField[]).filter((k) => form[k].trim() !== before[k]).map((k) => [k, form[k].trim() || null]),
    );
    if (!Object.keys(edits).length) return onCancel();
    setSaving(true);
    try {
      await onSave(edits);
    } finally {
      setSaving(false);
    }
  }

  const field = (k: RtContactField, label: string, type = "text") => (
    <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
      {label}
      <input className={input} type={type} value={form[k]} onChange={set(k)} />
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
      {field("vrn", "VAT number")}
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

function StatementTable({ st }: { st: RtStatement }) {
  if (!st.lines.length) return <p className="text-sm text-muted">Nothing in the books for this contact yet.</p>;
  return (
    <div className="overflow-x-auto">
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
            <tr key={`${ln.event_id}-${i}`} className="border-b border-border last:border-b-0">
              <td className="whitespace-nowrap py-1.5 pr-2">{ukDate(ln.date)}</td>
              <td className="py-1.5 pr-2">
                {ln.details}
                {ln.reference && <span className="text-muted"> · {ln.reference}</span>}
              </td>
              <td className="py-1.5 pr-2 text-right">{ln.amount_pence ? money(ln.amount_pence) : ""}</td>
              <td className="py-1.5 pr-2 text-right">{ln.paid_pence ? money(ln.paid_pence) : ""}</td>
              <td className="py-1.5 text-right font-semibold">{money(ln.balance_pence)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[13px] text-muted">
        Plus means they owe you, minus means you owe them. Receipts paid by card or cash at the time are settled on the
        same line.
      </p>
    </div>
  );
}

function SidePanel({ contact, account, onSaved, onClose }: {
  contact: RtContactRow;
  account: AccountInfo | null;
  onSaved: () => Promise<void>;
  onClose: () => void;
}) {
  const [st, setSt] = useState<RtStatement | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    let live = true; // the panel is keyed by contact, so a new contact starts from a fresh state
    if (account) {
      runtime.statement(account, contact.id).then(
        (s) => live && setSt(s),
        (e: Error) => live && setErr(e.message),
      );
    }
    return () => {
      live = false;
    };
  }, [account, contact.id]);

  async function save(edits: Partial<Record<RtContactField, string | null>>) {
    if (!account) return;
    try {
      await runtime.editContact(account, contact.id, edits);
      setEditing(false);
      setErr(null);
      await onSaved();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  const details: [string, string | null][] = [
    ["VAT number", contact.vrn], ["Email", contact.email], ["Phone", contact.phone], ["Address", contact.address],
    ["Usual category", contact.default_category],
  ];
  return (
    <aside aria-label={`${contact.name}: statement`} className={`${card} flex flex-col gap-4 p-4 lg:sticky lg:top-4 lg:self-start`}>
      <div className="flex items-start justify-between gap-3">
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

      {editing ? (
        <EditForm contact={contact} onSave={save} onCancel={() => setEditing(false)} />
      ) : (
        <>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px]">
            {details.map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="font-bold text-muted">{label}</dt>
                <dd className="whitespace-pre-line">{value || "—"}</dd>
              </div>
            ))}
          </dl>
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-[15px] tabular-nums">
              <Balance pence={contact.totals.balance_pence} />
            </p>
            <button type="button" onClick={() => setEditing(true)} disabled={!account} className={secondary}>
              Edit
            </button>
          </div>
        </>
      )}

      {err && <p role="alert" className="text-sm font-semibold text-warn-ink">{err}</p>}

      <div>
        <h3 className="mb-2 text-[15px] font-extrabold">Statement</h3>
        {!account ? (
          <p className="text-sm text-muted">Connect your OneDrive to see statements.</p>
        ) : st ? (
          <StatementTable st={st} />
        ) : !err ? (
          <p className="text-sm text-muted">Working it out from your ledger…</p>
        ) : null}
      </div>
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
                {BUCKETS.map((b) => <th key={b} className={`${th} text-right`}>{b} days</th>)}
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

/** Contacts: from the runtime when signed in; the sample otherwise. */
export default function LiveContacts() {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [state, setState] = useState<"checking" | "demo" | "loading" | "live" | "error">("checking");
  const [rows, setRows] = useState<RtContactRow[]>([]);
  const [aged, setAged] = useState<RtAged | null>(null);
  const [tab, setTab] = useState<"contacts" | "aged">("contacts");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState<"refresh" | "import" | null>(null);
  const [addNew, setAddNew] = useState(false);

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
      setNote(
        `Read ${r.read} Outlook contacts: ${r.matched} already here (${r.updated} gained an email or phone)` +
          (addNew ? `, ${r.added} added` : "") + `, ${r.skipped} left out.`,
      );
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
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q
      ? shown.filter((c) => [c.name, c.vrn, c.email, c.phone].some((v) => v?.toLowerCase().includes(q)))
      : shown;
  }, [shown, query]);
  const current = shown.find((c) => c.id === selected) ?? null;
  const select = (id: string) => {
    setSelected(id);
    setTab("contacts");
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
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
          <button type="button" onClick={importOutlook} disabled={!account || busy !== null}
            title={account ? "Asks Microsoft for read-only access to your Outlook contacts" : "Connect your OneDrive first"}
            className="shrink-0 rounded-xl bg-teal px-4 py-2.5 text-sm font-bold text-white hover:bg-teal-dark disabled:opacity-60">
            {busy === "import" ? "Importing…" : "Import from Outlook"}
          </button>
        </div>
      </div>
      {account && (
        <label className="flex items-center justify-end gap-2 text-[13px] font-semibold text-muted">
          <input type="checkbox" checked={addNew} onChange={(e) => setAddNew(e.target.checked)} />
          When importing, also add Outlook contacts that are not in your books (as customers)
        </label>
      )}

      {note && <p role="status" className="text-sm font-semibold text-teal-dark">{note}</p>}
      {state === "demo" || state === "error" ? (
        <p className="text-[13px] font-medium text-muted">
          {state === "error" ? "Could not read your contacts; showing the sample instead. " : (
            <>Sample contacts. <Link href="/connect" className="font-bold text-teal-dark underline">Connect your OneDrive</Link> to see yours. </>
          )}
          SAMPLE — FICTIONAL COMPANY
        </p>
      ) : null}

      {state === "checking" || state === "loading" ? (
        <p className={`${card} p-4 text-sm font-semibold text-muted`}>
          {state === "loading" ? "Reading your books…" : "Checking sign-in…"}
        </p>
      ) : tab === "aged" ? (
        agedShown && (
          <div className="flex flex-col gap-6">
            <AgedTable title="Debtors" hint="Customers who owe you: sales invoices with no bank payment matched, by age from the invoice date."
              table={agedShown.debtors} onSelect={select} />
            <AgedTable title="Creditors" hint="Suppliers you owe: bills on account with no bank payment matched. Card and cash receipts are already paid."
              table={agedShown.creditors} onSelect={select} />
            <p className="text-[13px] text-muted">As of {ukDate(agedShown.as_of)}. An entry drops off once a bank statement line is matched to it.</p>
          </div>
        )
      ) : (
        <div className={`grid gap-4 ${current ? "lg:grid-cols-[minmax(0,1fr)_400px]" : ""}`}>
          <div className="flex flex-col gap-3">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name, VAT number, email or phone"
              aria-label="Search contacts"
              className={input}
            />
            {shown.length === 0 ? (
              <p className={`${card} p-4 text-sm font-semibold text-muted`}>
                No customers or suppliers yet. They appear here once you approve receipts and invoices.
              </p>
            ) : (
              <ContactTable rows={filtered} selected={selected} onSelect={setSelected} />
            )}
          </div>
          {current && (
            <SidePanel
              key={current.id}
              contact={current}
              account={live ? account : null}
              onSaved={async () => {
                if (account) await load(account);
              }}
              onClose={() => setSelected(null)}
            />
          )}
        </div>
      )}
    </div>
  );
}
