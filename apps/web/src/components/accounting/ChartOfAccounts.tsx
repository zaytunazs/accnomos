"use client";

import { useState } from "react";
import { accounting, money, VAT_LABELS, type AccountType, type RtAccount, type VatLetter } from "@/lib/accounting";
import { Field, Gate, Notes, Scroll, button, card, input, quiet, small, td, th, useLoad } from "./Shared";

const TYPES: AccountType[] = ["fixed_asset", "current_asset", "bank", "current_liability", "equity", "revenue", "direct_costs", "overhead"];

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  URL.revokeObjectURL(url);
}

export default function ChartOfAccounts() {
  const { account, data, error, note, busy, act } = useLoad(accounting.chart);
  const [type, setType] = useState<AccountType | "">("");
  const [showArchived, setShowArchived] = useState(false);
  const [form, setForm] = useState({ code: "", name: "", type: "overhead" as AccountType, vat: "S" as VatLetter | "" });
  const [editing, setEditing] = useState<RtAccount | null>(null);
  const [rename, setRename] = useState("");
  const [importErrors, setImportErrors] = useState<string[]>([]);

  const types = data?.types;
  const rows = (data?.accounts ?? []).filter((a) => (!type || a.type === type) && (showArchived || !a.archived));

  async function onImport(file: File | undefined) {
    if (!file) return;
    const text = await file.text();
    setImportErrors([]);
    await act("import", (a) => accounting.importChart(a, text), (r) => {
      setImportErrors(r.result.errors);
      return r.result.errors.length
        ? null
        : `Imported: ${r.result.added.length} added, ${r.result.updated.length} updated, ${r.result.unchanged} unchanged.`;
    });
  }

  return (
    <Gate account={account} ready={!!data || !!error} what="to see and change your chart of accounts: the accounts every entry is posted to.">
      <div className="flex min-w-0 flex-col gap-5">
        <Notes note={note} error={error} />
        {data && !data.saved && (
          <p role="note" className="rounded-xl border border-border bg-ground px-4 py-2 text-sm">
            This is the standard UK small-business chart. It is saved to your books the first time you change it.
          </p>
        )}
        {data && data.unlisted.length > 0 && (
          <p role="note" className="rounded-xl border border-warn-border bg-warn-bg px-4 py-2 text-sm text-warn-ink">
            Posted to but not in the chart: {data.unlisted.join(", ")}. Add them so they can be chosen again.
          </p>
        )}

        <section aria-labelledby="add-account" className={card}>
          <h2 id="add-account" className="text-[17px] font-extrabold">Add an account</h2>
          <form
            className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-[7rem_1fr_12rem_12rem_auto] sm:items-end"
            onSubmit={(e) => {
              e.preventDefault();
              void act(
                "add",
                (a) => accounting.addAccount(a, { code: form.code.trim(), name: form.name, type: form.type, vat_default: form.vat || null }),
                () => {
                  const label = `${form.code} ${form.name}`;
                  setForm({ ...form, code: "", name: "" });
                  return `Added ${label}.`;
                },
              );
            }}
          >
            <Field label="Code">
              <input className={input} inputMode="numeric" pattern="\d{4}" maxLength={4} required value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })} />
            </Field>
            <Field label="Name">
              <input className={input} required maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </Field>
            <Field label="Type">
              <select className={input} value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as AccountType })}>
                {TYPES.map((t) => (
                  <option key={t} value={t}>
                    {types?.[t] ?? t} ({String(data?.ranges[t][0] ?? 0).padStart(4, "0")}–{data?.ranges[t][1]})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Default VAT">
              <select className={input} value={form.vat} onChange={(e) => setForm({ ...form, vat: e.target.value as VatLetter | "" })}>
                <option value="">None</option>
                {(Object.keys(VAT_LABELS) as VatLetter[]).map((v) => (
                  <option key={v} value={v}>{VAT_LABELS[v]}</option>
                ))}
              </select>
            </Field>
            <button type="submit" className={button} disabled={busy !== null}>Add account</button>
          </form>
        </section>

        <section aria-labelledby="accounts" className={card}>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <h2 id="accounts" className="text-[17px] font-extrabold">Accounts</h2>
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Show type">
                <select className={input} value={type} onChange={(e) => setType(e.target.value as AccountType | "")}>
                  <option value="">All types</option>
                  {TYPES.map((t) => <option key={t} value={t}>{types?.[t] ?? t}</option>)}
                </select>
              </Field>
              <label className="flex min-h-11 items-center gap-2 text-[14px] font-bold">
                <input type="checkbox" className="h-5 w-5" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
                Show archived
              </label>
              <button type="button" className={quiet} disabled={busy !== null}
                onClick={() => void act("export", accounting.exportChart, (text) => { download("chart-of-accounts.csv", text); return "Chart exported as a CSV file."; })}>
                Export CSV
              </button>
              <label className={`${quiet} cursor-pointer`}>
                Import CSV
                <input type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => void onImport(e.target.files?.[0])} />
              </label>
            </div>
          </div>
          {importErrors.length > 0 && (
            <div role="alert" className="mt-3 rounded-xl border border-warn-border bg-warn-bg px-4 py-2 text-sm text-warn-ink">
              <p className="font-bold">Nothing was imported:</p>
              <ul className="list-disc pl-5">{importErrors.map((e) => <li key={e}>{e}</li>)}</ul>
            </div>
          )}
          <Scroll label="Accounts table">
            <table className="mt-3 w-full min-w-[40rem] text-left text-[15px]">
              <caption className="sr-only">Chart of accounts</caption>
              <thead>
                <tr className="border-b border-border">
                  <th scope="col" className={th}>Code</th>
                  <th scope="col" className={th}>Name</th>
                  <th scope="col" className={th}>Type</th>
                  <th scope="col" className={th}>VAT</th>
                  <th scope="col" className={`${th} text-right`}>Balance</th>
                  <th scope="col" className={th}><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.code} className="border-b border-border last:border-0">
                    <td className={`${td} font-mono`}>{a.code}</td>
                    <td className={td}>
                      {a.name}
                      {a.archived && <span className="ml-2 rounded-full bg-ground px-2 text-[12px] font-bold text-muted">Archived</span>}
                      {a.postings > 0 && <span className="block text-[12px] text-muted">{a.postings} posted line{a.postings === 1 ? "" : "s"}</span>}
                    </td>
                    <td className={td}>{types?.[a.type] ?? a.type}</td>
                    <td className={td}>{a.vat_default ? VAT_LABELS[a.vat_default] : "—"}</td>
                    <td className={`${td} text-right tabular-nums`}>{money(a.balance_pence)}</td>
                    <td className={`${td} whitespace-nowrap text-right`}>
                      <button type="button" className={small} aria-label={`Edit ${a.label}`} onClick={() => { setEditing(a); setRename(a.name); }}>
                        Edit
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
        </section>

        {editing && (
          <section key={editing.code} aria-labelledby="edit-account" className={card}>
            <h2 id="edit-account" className="text-[17px] font-extrabold">Edit {editing.label}</h2>
            {editing.postings > 0 && (
              <p className="mt-1 text-sm text-muted">
                It has posted lines, so its name stays (they keep the name they were posted with) and it can be archived but not deleted.
              </p>
            )}
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3 sm:items-end">
              <Field label="Name">
                <input className={input} value={rename} maxLength={80} onChange={(e) => setRename(e.target.value)} />
              </Field>
              <Field label="Type">
                <select className={input} defaultValue={editing.type}
                  onChange={(e) => void act("type", (a) => accounting.editAccount(a, editing.code, { type: e.target.value }), () => "Type changed.")}>
                  {TYPES.map((t) => <option key={t} value={t}>{types?.[t] ?? t}</option>)}
                </select>
              </Field>
              <Field label="Default VAT">
                <select className={input} defaultValue={editing.vat_default ?? ""}
                  onChange={(e) =>
                    void act("vat", (a) => accounting.editAccount(a, editing.code, e.target.value ? { vat_default: e.target.value } : { clear_vat_default: true }), () => "Default VAT changed.")
                  }>
                  <option value="">None</option>
                  {(Object.keys(VAT_LABELS) as VatLetter[]).map((v) => <option key={v} value={v}>{VAT_LABELS[v]}</option>)}
                </select>
              </Field>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" className={button} disabled={busy !== null || rename === editing.name}
                onClick={() => void act("rename", (a) => accounting.editAccount(a, editing.code, { name: rename }), () => { setEditing(null); return "Renamed."; })}>
                Save name
              </button>
              {!editing.system && (
                <button type="button" className={quiet} disabled={busy !== null}
                  onClick={() => void act("archive", (a) => accounting.editAccount(a, editing.code, { archived: !editing.archived }), () => {
                    setEditing(null);
                    return editing.archived ? `${editing.label} restored.` : `${editing.label} archived.`;
                  })}>
                  {editing.archived ? "Restore" : "Archive"}
                </button>
              )}
              {!editing.system && editing.postings === 0 && (
                <button type="button" className={quiet} disabled={busy !== null}
                  onClick={() => {
                    if (!window.confirm(`Delete ${editing.label}? It has no postings.`)) return;
                    void act("delete", (a) => accounting.deleteAccount(a, editing.code), () => { setEditing(null); return `${editing.label} deleted.`; });
                  }}>
                  Delete
                </button>
              )}
              <button type="button" className={quiet} onClick={() => setEditing(null)}>Close</button>
            </div>
            {editing.system && <p className="mt-2 text-sm text-muted">Accnomos posts to this account by itself, so it can&apos;t be archived or deleted.</p>}
          </section>
        )}
      </div>
    </Gate>
  );
}
