"use client";

import { useCallback, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { errorText } from "@/components/jobs/useAccount";
import {
  accounting,
  money,
  toPence,
  ukDay,
  VAT_LABELS,
  type RtAccount,
  type RtFoundLine,
  type RtRecodeResult,
  type VatLetter,
} from "@/lib/accounting";
import { Field, Gate, Notes, Scroll, button, card, input, quiet, td, th, useLoad } from "./Shared";

const key = (l: RtFoundLine) => `${l.event_id}:${l.line}`;

export default function FindRecode() {
  const load = useCallback(async (a: AccountInfo) => (await accounting.chart(a)).accounts, []);
  const { account, data: accounts, error, setError, note, setNote, busy, act } = useLoad<RtAccount[]>(load);
  const [q, setQ] = useState({ account: "", contact: "", from: "", to: "", min: "", max: "", vat: "" });
  const [lines, setLines] = useState<RtFoundLine[] | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [target, setTarget] = useState({ account: "", vat: "" as VatLetter | "" });
  const [preview, setPreview] = useState<RtRecodeResult | null>(null);

  async function search() {
    if (!account) return;
    setError(null);
    setNote(null);
    setPreview(null);
    try {
      const r = await accounting.search(account, {
        account: q.account.slice(0, 4) || null,
        contact: q.contact || null,
        from: q.from || null,
        to: q.to || null,
        min_pence: q.min ? toPence(q.min) : null,
        max_pence: q.max ? toPence(q.max) : null,
        vat_code: q.vat || null,
      });
      setLines(r.lines);
      setPicked(new Set());
      if (r.truncated) setNote("Showing the newest 500 lines; narrow the search to see the rest.");
    } catch (e) {
      setError(errorText(e));
    }
  }

  const request = (confirm: boolean) => ({
    lines: (lines ?? []).filter((l) => picked.has(key(l))).map((l) => ({ event_id: l.event_id, line: l.line })),
    account: target.account || null,
    vat_code: target.vat || null,
    confirm,
  });

  const toggle = (k: string) => {
    const next = new Set(picked);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    setPicked(next);
    setPreview(null);
  };

  return (
    <Gate account={account} ready={!!accounts || !!error} what="to find posted lines and recode them to another account or VAT code.">
      <div className="flex min-w-0 flex-col gap-5">
        <p role="note" className="rounded-xl border border-border bg-ground px-4 py-2 text-sm">
          Recoding never edits an entry: it adds an adjusting entry dated like the original. Entries in a VAT period you have already
          submitted, and lines on bank, debtors, creditors and VAT control, can&apos;t be recoded.
        </p>
        <Notes note={note} error={error} />
        <section aria-labelledby="find" className={card}>
          <h2 id="find" className="text-[17px] font-extrabold">Find lines</h2>
          <form className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); void search(); }}>
            <div className="col-span-2">
              <Field label="Account">
                <select className={input} value={q.account} onChange={(e) => setQ({ ...q, account: e.target.value })}>
                  <option value="">Any account</option>
                  {(accounts ?? []).map((a) => <option key={a.code} value={a.label}>{a.label}</option>)}
                </select>
              </Field>
            </div>
            <div className="col-span-2">
              <Field label="Contact"><input className={input} maxLength={120} value={q.contact} onChange={(e) => setQ({ ...q, contact: e.target.value })} /></Field>
            </div>
            <Field label="From"><input type="date" className={input} value={q.from} onChange={(e) => setQ({ ...q, from: e.target.value })} /></Field>
            <Field label="To"><input type="date" className={input} value={q.to} onChange={(e) => setQ({ ...q, to: e.target.value })} /></Field>
            <Field label="Amount from £"><input inputMode="decimal" className={input} value={q.min} onChange={(e) => setQ({ ...q, min: e.target.value })} /></Field>
            <Field label="Amount to £"><input inputMode="decimal" className={input} value={q.max} onChange={(e) => setQ({ ...q, max: e.target.value })} /></Field>
            <Field label="VAT code">
              <select className={input} value={q.vat} onChange={(e) => setQ({ ...q, vat: e.target.value })}>
                <option value="">Any</option>
                {(Object.keys(VAT_LABELS) as VatLetter[]).map((v) => <option key={v} value={v}>{VAT_LABELS[v]}</option>)}
              </select>
            </Field>
            <div className="col-span-2 flex items-end sm:col-span-3"><button type="submit" className={button}>Search</button></div>
          </form>
        </section>

        {lines && (
          <section aria-labelledby="found" className={card}>
            <h2 id="found" className="text-[17px] font-extrabold">{lines.length} line{lines.length === 1 ? "" : "s"} found</h2>
            {lines.length > 0 && (
              <Scroll label="Lines found">
                <table className="mt-3 w-full min-w-[42rem] text-left text-[14px]">
                  <caption className="sr-only">Posted lines found</caption>
                  <thead>
                    <tr className="border-b border-border">
                      <th scope="col" className={th}><span className="sr-only">Choose</span></th>
                      <th scope="col" className={th}>Date</th>
                      <th scope="col" className={th}>Contact</th>
                      <th scope="col" className={th}>Account</th>
                      <th scope="col" className={th}>VAT</th>
                      <th scope="col" className={`${th} text-right`}>Debit</th>
                      <th scope="col" className={`${th} text-right`}>Credit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lines.map((l) => (
                      <tr key={key(l)} className="border-b border-border last:border-0">
                        <td className={td}>
                          <input type="checkbox" className="h-5 w-5" disabled={!l.recodable} checked={picked.has(key(l))}
                            aria-label={`Choose ${l.account} ${money(l.debit_pence || l.credit_pence)} on ${ukDay(l.date)}`}
                            onChange={() => toggle(key(l))} />
                        </td>
                        <td className={td}>{ukDay(l.date)}</td>
                        <td className={td}>{l.counterparty ?? "—"}</td>
                        <td className={td}>
                          {l.account}
                          {l.recoded && <span className="ml-1 rounded-full bg-teal-tint px-2 text-[12px] font-bold text-teal-dark">Recoded</span>}
                          {l.reason && <span className="block text-[12px] text-muted">{l.reason}</span>}
                        </td>
                        <td className={td}>{l.vat_code ?? ""}</td>
                        <td className={`${td} text-right tabular-nums`}>{l.debit_pence ? money(l.debit_pence) : ""}</td>
                        <td className={`${td} text-right tabular-nums`}>{l.credit_pence ? money(l.credit_pence) : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Scroll>
            )}
          </section>
        )}

        {lines && picked.size > 0 && (
          <section aria-labelledby="recode-to" className={card}>
            <h2 id="recode-to" className="text-[17px] font-extrabold">Recode {picked.size} line{picked.size === 1 ? "" : "s"}</h2>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="New account">
                <select className={input} value={target.account} onChange={(e) => { setTarget({ ...target, account: e.target.value }); setPreview(null); }}>
                  <option value="">Keep the account</option>
                  {(accounts ?? []).filter((a) => !a.archived).map((a) => <option key={a.code} value={a.label}>{a.label}</option>)}
                </select>
              </Field>
              <Field label="New VAT code" hint="The gross stays as paid; code works out the VAT again.">
                <select className={input} value={target.vat} onChange={(e) => { setTarget({ ...target, vat: e.target.value as VatLetter | "" }); setPreview(null); }}>
                  <option value="">Keep the VAT code</option>
                  {(Object.keys(VAT_LABELS) as VatLetter[]).map((v) => <option key={v} value={v}>{VAT_LABELS[v]}</option>)}
                </select>
              </Field>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" className={quiet} disabled={busy !== null || (!target.account && !target.vat)}
                onClick={() => void act("preview", (a) => accounting.recode(a, request(false)), (r) => { setPreview(r); return null; })}>
                Preview the adjusting entries
              </button>
            </div>
            {preview && (
              <div className="mt-3 flex flex-col gap-3">
                {preview.events.map((e) => (
                  <div key={e.original_event_id} className="rounded-xl border border-border p-3">
                    <h3 className="text-[15px] font-bold">Adjustment dated {ukDay(e.date)}{e.counterparty ? ` · ${e.counterparty}` : ""}</h3>
                    <Scroll label="Adjusting lines">
                      <table className="mt-2 w-full min-w-[26rem] text-left text-[14px]">
                        <caption className="sr-only">Adjusting entry lines</caption>
                        <thead>
                          <tr className="border-b border-border">
                            <th scope="col" className={th}>Account</th>
                            <th scope="col" className={`${th} text-right`}>Debit</th>
                            <th scope="col" className={`${th} text-right`}>Credit</th>
                            <th scope="col" className={th}>VAT</th>
                          </tr>
                        </thead>
                        <tbody>
                          {e.lines.map((l, i) => (
                            <tr key={i}>
                              <td className={td}>{l.account}</td>
                              <td className={`${td} text-right tabular-nums`}>{l.debit_pence ? money(l.debit_pence) : ""}</td>
                              <td className={`${td} text-right tabular-nums`}>{l.credit_pence ? money(l.credit_pence) : ""}</td>
                              <td className={td}>{l.vat_code ?? ""}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </Scroll>
                    {e.vat_box && (
                      <p className="mt-1 text-[13px] text-muted">
                        VAT return, {e.vat_box}: net {money(e.net_change_pence ?? 0)}, VAT {money(e.vat_change_pence ?? 0)}.
                      </p>
                    )}
                  </div>
                ))}
                <button type="button" className={`${button} self-start`} disabled={busy !== null}
                  onClick={() => void act("recode", (a) => accounting.recode(a, request(true)), (r) => {
                    setPreview(null);
                    setLines(null);
                    setPicked(new Set());
                    return `Recoded ${r.lines_recoded} line${r.lines_recoded === 1 ? "" : "s"} with ${r.events.length} adjusting entr${r.events.length === 1 ? "y" : "ies"}. Search again to see them.`;
                  })}>
                  Approve and post the recode
                </button>
              </div>
            )}
          </section>
        )}
      </div>
    </Gate>
  );
}
