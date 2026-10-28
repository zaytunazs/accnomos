"use client";

import { useCallback, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { todayIso } from "@/components/jobs/useAccount";
import {
  accounting,
  money,
  toPence,
  ukDay,
  VAT_LABELS,
  type RtAccount,
  type RtJournal,
  type RtTracking,
  type VatLetter,
} from "@/lib/accounting";
import { Field, Gate, Notes, Scroll, button, card, input, quiet, small, td, th, useLoad } from "./Shared";

type Row = { account: string; debit: string; credit: string; vat: VatLetter | ""; description: string; tags: Record<string, string> };
const blank = (): Row => ({ account: "", debit: "", credit: "", vat: "", description: "", tags: {} });

type Filters = { status: string; source: string; from: string; to: string; account: string; q: string };

interface Data {
  journals: RtJournal[];
  accounts: RtAccount[];
  tracking: RtTracking;
}

const STATUS_LABEL: Record<RtJournal["status"], string> = { draft: "Draft", posted: "Posted", voided: "Voided", discarded: "Discarded" };
const SOURCE_LABEL: Record<RtJournal["source"], string> = { manual: "Manual", depreciation: "Depreciation", disposal: "Asset disposal" };

export default function ManualJournals() {
  const [filters, setFilters] = useState<Filters>({ status: "", source: "", from: "", to: "", account: "", q: "" });
  const load = useCallback(
    async (a: AccountInfo): Promise<Data> => {
      const [j, c, t] = await Promise.all([accounting.journals(a, filters), accounting.chart(a), accounting.tracking(a)]);
      return { journals: j.journals, accounts: c.accounts, tracking: t };
    },
    [filters],
  );
  const { account, data, error, note, busy, act } = useLoad(load);
  const [rows, setRows] = useState<Row[]>([blank(), blank()]);
  const [head, setHead] = useState({ date: todayIso(), narration: "", vatBox: "" as "" | "sales" | "purchases", reverseOn: "", doc: "" });

  const active = (data?.accounts ?? []).filter((a) => !a.archived);
  const cats = data?.tracking.categories ?? [];
  const debit = rows.reduce((n, r) => n + (toPence(r.debit) ?? 0), 0);
  const credit = rows.reduce((n, r) => n + (toPence(r.credit) ?? 0), 0);
  const set = (i: number, patch: Partial<Row>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  function save() {
    const lines = rows
      .filter((r) => r.account || r.debit || r.credit)
      .map((r) => ({
        account: r.account,
        debit_pence: toPence(r.debit) ?? 0,
        credit_pence: toPence(r.credit) ?? 0,
        vat_code: r.vat || null,
        description: r.description || null,
        tracking: Object.keys(r.tags).length ? r.tags : null,
      }));
    void act(
      "save",
      (a) =>
        accounting.createJournal(a, {
          date: head.date,
          narration: head.narration,
          lines,
          vat_box: head.vatBox || null,
          auto_reverse_on: head.reverseOn || null,
          document_path: head.doc || null,
        }),
      (j) => {
        setRows([blank(), blank()]);
        setHead({ ...head, narration: "", reverseOn: "", doc: "" });
        return `Saved ${j.number} as a draft. Nothing is posted until you approve it.${j.warnings.length ? ` ${j.warnings.join(" ")}` : ""}`;
      },
    );
  }

  return (
    <Gate account={account} ready={!!data || !!error} what="to write manual journals: balanced entries that post only when you approve them.">
      <div className="flex min-w-0 flex-col gap-5">
        <Notes note={note} error={error} />

        <section aria-labelledby="new-journal" className={card}>
          <h2 id="new-journal" className="text-[17px] font-extrabold">New journal</h2>
          <form
            className="mt-3 flex min-w-0 flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              save();
            }}
          >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-[11rem_1fr]">
              <Field label="Date">
                <input type="date" required className={input} value={head.date} onChange={(e) => setHead({ ...head, date: e.target.value })} />
              </Field>
              <Field label="Narration">
                <input required maxLength={300} className={input} value={head.narration} onChange={(e) => setHead({ ...head, narration: e.target.value })} />
              </Field>
            </div>
            <fieldset className="flex min-w-0 flex-col gap-3">
              <legend className="text-[13px] font-bold text-muted">Lines</legend>
              {rows.map((r, i) => (
                <div key={i} className="grid min-w-0 grid-cols-2 gap-2 rounded-xl border border-border p-3 sm:grid-cols-[1fr_8rem_8rem_10rem]">
                  <div className="col-span-2 sm:col-span-1">
                    <Field label={`Line ${i + 1} account`}>
                      <select className={input} value={r.account} onChange={(e) => {
                        const acc = active.find((a) => a.label === e.target.value);
                        set(i, { account: e.target.value, vat: r.vat || (acc?.vat_default && acc.label !== "2200 VAT control" && head.vatBox ? acc.vat_default : r.vat) });
                      }}>
                        <option value="">Choose…</option>
                        {active.map((a) => <option key={a.code} value={a.label}>{a.label}</option>)}
                      </select>
                    </Field>
                  </div>
                  <Field label="Debit £">
                    <input inputMode="decimal" className={input} value={r.debit} onChange={(e) => set(i, { debit: e.target.value })} />
                  </Field>
                  <Field label="Credit £">
                    <input inputMode="decimal" className={input} value={r.credit} onChange={(e) => set(i, { credit: e.target.value })} />
                  </Field>
                  <div className="col-span-2 sm:col-span-1">
                    <Field label="VAT code">
                      <select className={input} value={r.vat} onChange={(e) => set(i, { vat: e.target.value as VatLetter | "" })}>
                        <option value="">None</option>
                        {(Object.keys(VAT_LABELS) as VatLetter[]).map((v) => <option key={v} value={v}>{VAT_LABELS[v]}</option>)}
                      </select>
                    </Field>
                  </div>
                  <div className="col-span-2 sm:col-span-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
                    <Field label="Description">
                      <input maxLength={200} className={input} value={r.description} onChange={(e) => set(i, { description: e.target.value })} />
                    </Field>
                    {cats.map((c) => (
                      <Field key={c.id} label={c.name}>
                        <select className={input} value={r.tags[c.id] ?? ""} onChange={(e) => {
                          const tags = { ...r.tags };
                          if (e.target.value) tags[c.id] = e.target.value;
                          else delete tags[c.id];
                          set(i, { tags });
                        }}>
                          <option value="">None</option>
                          {c.options.filter((o) => !o.archived).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                        </select>
                      </Field>
                    ))}
                  </div>
                  {rows.length > 2 && (
                    <button type="button" className={`${small} col-span-2 justify-self-start`} onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                      Remove line {i + 1}
                    </button>
                  )}
                </div>
              ))}
              <button type="button" className={`${quiet} self-start`} onClick={() => setRows([...rows, blank()])}>Add a line</button>
            </fieldset>
            <p aria-live="polite" className={`text-[15px] font-bold ${debit === credit && debit > 0 ? "text-teal-dark" : "text-warn-ink"}`}>
              Debits {money(debit)} · Credits {money(credit)}
              {debit !== credit ? ` · ${money(Math.abs(debit - credit))} apart: they must be equal` : debit > 0 ? " · balanced" : ""}
            </p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Field label="VAT on this journal" hint="Only when a line is on 2200 VAT control.">
                <select className={input} value={head.vatBox} onChange={(e) => setHead({ ...head, vatBox: e.target.value as "" | "sales" | "purchases" })}>
                  <option value="">No VAT</option>
                  <option value="purchases">VAT on purchases (box 4 and 7)</option>
                  <option value="sales">VAT on sales (box 1 and 6)</option>
                </select>
              </Field>
              <Field label="Reverse on (optional)" hint="Approving also posts the reversal dated this day.">
                <input type="date" className={input} value={head.reverseOn} min={head.date} onChange={(e) => setHead({ ...head, reverseOn: e.target.value })} />
              </Field>
              <Field label="Attach a file from your books (optional)" hint="Its path in OneDrive, e.g. 01 Receipts/2026-10/note.pdf">
                <input maxLength={400} className={input} value={head.doc} onChange={(e) => setHead({ ...head, doc: e.target.value })} />
              </Field>
            </div>
            <button type="submit" className={`${button} self-start`} disabled={busy !== null}>Save draft</button>
          </form>
        </section>

        <section aria-labelledby="journal-list" className={card}>
          <h2 id="journal-list" className="text-[17px] font-extrabold">Journals</h2>
          <form className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-6" onSubmit={(e) => e.preventDefault()} aria-label="Filter journals">
            <Field label="Status">
              <select className={input} value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
                <option value="">Any</option>
                {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </Field>
            <Field label="Source">
              <select className={input} value={filters.source} onChange={(e) => setFilters({ ...filters, source: e.target.value })}>
                <option value="">Any</option>
                {Object.entries(SOURCE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </Field>
            <Field label="From">
              <input type="date" className={input} value={filters.from} onChange={(e) => setFilters({ ...filters, from: e.target.value })} />
            </Field>
            <Field label="To">
              <input type="date" className={input} value={filters.to} onChange={(e) => setFilters({ ...filters, to: e.target.value })} />
            </Field>
            <Field label="Account code">
              <input className={input} inputMode="numeric" maxLength={4} value={filters.account} onChange={(e) => setFilters({ ...filters, account: e.target.value })} />
            </Field>
            <Field label="Text">
              <input className={input} maxLength={100} value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
            </Field>
          </form>
          {data && data.journals.length === 0 && <p className="mt-3 text-[15px] text-muted">No journals match.</p>}
          <ul className="mt-3 flex flex-col gap-3">
            {data?.journals.map((j) => (
              <li key={j.id} className="rounded-xl border border-border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-[15px] font-extrabold">
                    {j.number} · {ukDay(j.date)} · {j.narration}
                  </h3>
                  <span className={`rounded-full px-2.5 py-0.5 text-[12px] font-bold ${j.status === "posted" ? "bg-teal-tint text-teal-dark" : "bg-ground text-muted"}`}>
                    {STATUS_LABEL[j.status]}
                    {j.source !== "manual" ? ` · ${SOURCE_LABEL[j.source]}` : ""}
                  </span>
                </div>
                <Scroll label={`Lines of ${j.number}`}>
                  <table className="mt-2 w-full min-w-[30rem] text-left text-[14px]">
                    <caption className="sr-only">Lines of journal {j.number}</caption>
                    <thead>
                      <tr className="border-b border-border">
                        <th scope="col" className={th}>Account</th>
                        <th scope="col" className={`${th} text-right`}>Debit</th>
                        <th scope="col" className={`${th} text-right`}>Credit</th>
                        <th scope="col" className={th}>VAT</th>
                      </tr>
                    </thead>
                    <tbody>
                      {j.lines.map((l, i) => (
                        <tr key={i}>
                          <td className={td}>{l.account}{l.description ? <span className="block text-[12px] text-muted">{l.description}</span> : null}</td>
                          <td className={`${td} text-right tabular-nums`}>{l.debit_pence ? money(l.debit_pence) : ""}</td>
                          <td className={`${td} text-right tabular-nums`}>{l.credit_pence ? money(l.credit_pence) : ""}</td>
                          <td className={td}>{l.vat_code ?? ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Scroll>
                {j.vat_box && (
                  <p className="mt-1 text-[13px] text-muted">
                    VAT on {j.vat_box}: net {money(j.net_pence ?? 0)}, VAT {money(j.vat_pence ?? 0)}.
                  </p>
                )}
                {j.auto_reverse_on && <p className="mt-1 text-[13px] text-muted">Reverses on {ukDay(j.auto_reverse_on)}.</p>}
                {j.document_path && <p className="mt-1 text-[13px] text-muted">Document: {j.document_path}</p>}
                {j.warnings.map((w) => <p key={w} className="mt-1 text-[13px] font-semibold text-warn-ink">{w}</p>)}
                <div className="mt-2 flex flex-wrap gap-2">
                  {j.status === "draft" && (
                    <>
                      <button type="button" className={button} disabled={busy !== null}
                        onClick={() => void act(`a${j.id}`, (a) => accounting.approveJournal(a, j.id), (r) => `${r.number} approved and posted${r.reversal_event_id ? `, with its reversal on ${ukDay(r.auto_reverse_on ?? "")}` : ""}.`)}>
                        Approve {j.number}
                      </button>
                      <button type="button" className={quiet} disabled={busy !== null}
                        onClick={() => void act(`d${j.id}`, (a) => accounting.discardJournal(a, j.id), (r) => `${r.number} discarded. Nothing was posted.`)}>
                        Discard
                      </button>
                    </>
                  )}
                  {j.status === "posted" && (
                    <button type="button" className={quiet} disabled={busy !== null}
                      onClick={() => {
                        if (!window.confirm(`Void ${j.number}? A mirror entry is added; nothing is deleted.`)) return;
                        void act(`v${j.id}`, (a) => accounting.voidJournal(a, j.id), (r) => `${r.number} voided: a mirror entry cancels it.`);
                      }}>
                      Void {j.number}
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </Gate>
  );
}
