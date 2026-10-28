"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { filesApi, type RtArchivePreview, type RtArchiveRequest, type RtArchiveRun, type RtYearKind } from "@/lib/runtime";
import { bytes, card, count, day, field, label, primary, reason, secondary } from "@/components/files/manage";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** Archive older years into Archive/<year>/, optionally zipped too; every run can be undone. */
export default function ArchiveYears({ account, onChanged }: { account: AccountInfo; onChanged: () => void }) {
  const [kind, setKind] = useState<RtYearKind>("tax");
  const [endMonth, setEndMonth] = useState(3);
  const [years, setYears] = useState<RtArchivePreview["years"]>([]);
  const [upTo, setUpTo] = useState("");
  const [zip, setZip] = useState(false);
  const [plan, setPlan] = useState<RtArchivePreview | null>(null);
  const [runs, setRuns] = useState<RtArchiveRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const req = useCallback(
    (up_to: string | null): RtArchiveRequest => ({
      up_to,
      kind,
      ...(kind === "financial" ? { end_month: endMonth, end_day: 31 } : {}),
    }),
    [kind, endMonth],
  );

  const load = useCallback(async () => {
    try {
      const [p, r] = await Promise.all([filesApi.archivePreview(account, req(null)), filesApi.archiveRuns(account)]);
      setYears(p.years);
      setRuns(r);
    } catch (e) {
      setNote(`Could not read the years: ${reason(e)}`);
    }
  }, [account, req]);

  useEffect(() => {
    queueMicrotask(() => {
      setPlan(null);
      setUpTo("");
      void load();
    });
  }, [load]);

  async function preview() {
    setBusy(true);
    setNote(null);
    try {
      setPlan(await filesApi.archivePreview(account, req(upTo)));
    } catch (e) {
      setNote(reason(e));
    } finally {
      setBusy(false);
    }
  }

  async function archive() {
    setBusy(true);
    setNote(null);
    try {
      const r = await filesApi.archive(account, { ...req(upTo), zip });
      const zips = r.zips.filter((z) => z.path).map((z) => z.path);
      setNote(`Archived ${count(r.moves.length, "file")}${zips.length ? ` and saved ${zips.join(", ")}` : ""}. You can undo this below.`);
      setPlan(null);
      onChanged();
      await load();
    } catch (e) {
      setNote(`Nothing was archived: ${reason(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function undo(id: string) {
    setBusy(true);
    setNote(null);
    try {
      const r = await filesApi.undoArchive(account, id);
      setNote(
        `Moved ${count(r.moves.length - r.undo_skipped.length, "file")} back.` +
          (r.undo_skipped.length ? ` ${count(r.undo_skipped.length, "file")} had been moved since and stayed where it is.` : ""),
      );
      onChanged();
      await load();
    } catch (e) {
      setNote(`Could not undo: ${reason(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const choices = years.filter((y) => !y.current);
  return (
    <section aria-labelledby="archive-heading" className={card}>
      <div>
        <h2 id="archive-heading" className="text-[15px] font-extrabold">
          Archive older years
        </h2>
        <p className="text-[13px] text-muted">
          Moves receipts, sales documents, bank statements, payroll exports and reports into Archive/&lt;year&gt;/, in the
          same folders. Ledger entries never move, and Review, Bank and search still find every document. Invoices and
          VAT returns stay where they are.
        </p>
      </div>
      <fieldset className="flex min-w-0 flex-wrap gap-x-4 gap-y-1">
        <legend className="text-[13px] font-bold text-muted">Years run</legend>
        {(["tax", "financial"] as const).map((k) => (
          <label key={k} className="flex min-h-11 items-center gap-2 text-sm">
            <input type="radio" name="year-kind" className="h-5 w-5" checked={kind === k} onChange={() => setKind(k)} />
            {k === "tax" ? "Tax year (6 April to 5 April)" : "Financial year"}
          </label>
        ))}
      </fieldset>
      <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2">
        {kind === "financial" && (
          <label className={label}>
            Year ends on the last day of
            <select className={field} value={endMonth} onChange={(e) => setEndMonth(Number(e.target.value))}>
              {MONTHS.map((m, i) => (
                <option key={m} value={i + 1}>
                  {m}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className={label}>
          Archive up to and including
          <select
            className={field}
            value={upTo}
            onChange={(e) => {
              setUpTo(e.target.value);
              setPlan(null);
            }}
          >
            <option value="">Choose a year…</option>
            {choices.map((y) => (
              <option key={y.label} value={y.label}>
                {y.label} ({count(y.files, "file")}, {bytes(y.bytes)})
              </option>
            ))}
          </select>
        </label>
      </div>
      {choices.length === 0 && <p className="text-[13px] text-muted">Nothing older than this year to archive.</p>}
      <label className="flex min-h-11 items-center gap-2 text-sm">
        <input type="checkbox" className="h-5 w-5" checked={zip} onChange={(e) => setZip(e.target.checked)} />
        Also save each year as one zip (Archive/&lt;year&gt;.zip, with a list of files and their checksums)
      </label>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={secondary} disabled={busy || !upTo} onClick={preview}>
          Preview
        </button>
        {plan && plan.moves.length > 0 && (
          <button type="button" className={primary} disabled={busy} onClick={archive}>
            {busy ? "Archiving…" : `Archive ${count(plan.moves.length, "file")}`}
          </button>
        )}
      </div>
      {plan && (
        <div aria-label="Archive preview" role="region" className="min-w-0 rounded-xl bg-ground p-3">
          <p className="text-[13px] font-bold">
            {count(plan.moves.length, "file")} ({bytes(plan.bytes)}) would move into Archive/:
          </p>
          <ul className="mt-1 flex max-h-64 flex-col gap-1 overflow-y-auto text-[12px]">
            {plan.moves.slice(0, 50).map((m) => (
              <li key={m.old} className="break-all">
                {m.old} → <span className="font-semibold">{m.new}</span>
              </li>
            ))}
            {plan.moves.length > 50 && <li className="text-muted">…and {plan.moves.length - 50} more</li>}
          </ul>
        </div>
      )}
      {note && (
        <p role="status" className="text-sm font-semibold text-teal-dark">
          {note}
        </p>
      )}
      {runs.length > 0 && (
        <div className="min-w-0 border-t border-border pt-3">
          <h3 className="text-[13px] font-extrabold">Archive runs</h3>
          <ul aria-label="Archive runs" className="flex flex-col">
            {runs.map((r) => (
              <li key={r.id} className="flex min-w-0 flex-wrap items-center justify-between gap-2 border-t border-border py-2 text-[13px] first:border-t-0">
                <span className="min-w-0">
                  {day(r.created_at)}: up to {r.up_to}, {count(r.moves.length, "file")}
                  {r.undone_at && ` · undone ${day(r.undone_at)}`}
                </span>
                {!r.undone_at && (
                  <button type="button" className={secondary} disabled={busy} onClick={() => undo(r.id)} aria-label={`Undo the archive up to ${r.up_to}`}>
                    Undo
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
