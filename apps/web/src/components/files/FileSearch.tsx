"use client";

import { useMemo, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { filesApi, type RtFileIndex, type RtFileKind, type RtIndexedFile } from "@/lib/runtime";
import { ShowInOneDrive, bytes, card, count, day, field, label, pounds, primary, reason, secondary } from "@/components/files/manage";

const KINDS: { value: RtFileKind | ""; label: string }[] = [
  { value: "", label: "Any type" },
  { value: "pdf", label: "PDF" },
  { value: "image", label: "Photo or image" },
  { value: "csv", label: "CSV" },
  { value: "spreadsheet", label: "Spreadsheet" },
  { value: "json", label: "JSON" },
  { value: "text", label: "Text" },
  { value: "zip", label: "Zip" },
  { value: "other", label: "Other" },
];
const SHOWN = 100;

export interface Filters {
  q: string;
  kind: RtFileKind | "";
  from: string;
  to: string;
  min: string; // pounds, as typed
  max: string;
  folder: string;
  archived: "all" | "current" | "archived";
}

export const NO_FILTERS: Filters = { q: "", kind: "", from: "", to: "", min: "", max: "", folder: "", archived: "all" };

const toPence = (s: string) => {
  const n = Number(s.replace(/[£,\s]/g, ""));
  return s.trim() && Number.isFinite(n) ? Math.round(n * 100) : null;
};

/** The documents matching every filter. An amount filter keeps only documents linked to a ledger entry. */
export function matches(f: RtIndexedFile, filters: Filters): boolean {
  const words = filters.q.toLowerCase().split(/\s+/).filter(Boolean);
  const hay = `${f.path} ${f.linked?.counterparty ?? ""}`.toLowerCase();
  if (words.some((w) => !hay.includes(w))) return false;
  if (filters.kind && f.kind !== filters.kind) return false;
  if (filters.from && f.date < filters.from) return false;
  if (filters.to && f.date > filters.to) return false;
  if (filters.folder && f.folder !== filters.folder) return false;
  if (filters.archived === "current" && f.archived) return false;
  if (filters.archived === "archived" && !f.archived) return false;
  const min = toPence(filters.min);
  const max = toPence(filters.max);
  if (min !== null || max !== null) {
    const amount = f.linked?.amount_pence;
    if (amount === null || amount === undefined) return false;
    if (min !== null && amount < min) return false;
    if (max !== null && amount > max) return false;
  }
  return true;
}

function Rename({ account, file, onDone }: { account: AccountInfo; file: RtIndexedFile; onDone: (msg: string) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(file.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (file.protected) return null;
  if (!open)
    return (
      <button type="button" className="min-h-11 shrink-0 text-[13px] font-bold text-teal-dark hover:underline" onClick={() => setOpen(true)} aria-label={`Rename ${file.name}`}>
        Rename
      </button>
    );
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await filesApi.rename(account, file.path, name);
      onDone(`Renamed to ${r.new.split("/").pop()}`);
    } catch (err) {
      setError(reason(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={save} className="flex w-full min-w-0 flex-wrap items-end gap-2">
      <label className={`${label} flex-1`}>
        New name for {file.name}
        <input className={field} value={name} onChange={(e) => setName(e.target.value)} maxLength={200} autoFocus />
      </label>
      <button type="submit" className={primary} disabled={busy || !name.trim()}>
        {busy ? "Saving…" : "Save name"}
      </button>
      <button type="button" className={secondary} onClick={() => setOpen(false)}>
        Cancel
      </button>
      <p className="w-full text-[12px] text-muted">Characters OneDrive does not allow (\ / : * ? &quot; &lt; &gt; |) become spaces; the extension stays.</p>
      {error && (
        <p role="alert" className="w-full text-sm font-semibold text-warn-ink">
          {error}
        </p>
      )}
    </form>
  );
}

/** Find files: search and filter every document, select several to move, rename one, open it in OneDrive. */
export default function FileSearch({ account, index, onChanged }: { account: AccountInfo; index: RtFileIndex; onChanged: () => void }) {
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const folders = useMemo(() => [...new Set(index.files.map((f) => f.folder).filter(Boolean))].sort(), [index]);
  const hits = useMemo(() => index.files.filter((f) => matches(f, filters)), [index, filters]);
  const shown = hits.slice(0, SHOWN);
  const movable = shown.filter((f) => !f.protected);
  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => {
    setFilters((prev) => ({ ...prev, [k]: v }));
    setSelected(new Set());
  };
  const allPicked = movable.length > 0 && movable.every((f) => selected.has(f.path));

  function toggle(path: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  async function move() {
    setBusy(true);
    setNote(null);
    try {
      const r = await filesApi.move(account, [...selected], to);
      setNote(`Moved ${count(r.moved.length, "file")} to ${to}. Links from your books still work.`);
      setSelected(new Set());
      onChanged();
    } catch (e) {
      setNote(`Nothing was moved: ${reason(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="find-heading" className={card}>
      <div>
        <h2 id="find-heading" className="text-[15px] font-extrabold">
          Find files
        </h2>
        <p className="text-[13px] text-muted">Search every document, archived ones too. Amounts come from the ledger entry a document is linked to.</p>
      </div>
      <form role="search" aria-label="Search files" onSubmit={(e) => e.preventDefault()} className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2">
        <label className={`${label} sm:col-span-2`}>
          Name, folder or supplier
          <input type="search" className={field} value={filters.q} onChange={(e) => set("q", e.target.value)} placeholder="e.g. Screwfix 2025" />
        </label>
        <label className={label}>
          Type
          <select className={field} value={filters.kind} onChange={(e) => set("kind", e.target.value as RtFileKind | "")}>
            {KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <label className={label}>
          Folder
          <select className={field} value={filters.folder} onChange={(e) => set("folder", e.target.value)}>
            <option value="">Any folder</option>
            {folders.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </label>
        <label className={label}>
          Dated from
          <input type="date" className={field} value={filters.from} onChange={(e) => set("from", e.target.value)} />
        </label>
        <label className={label}>
          Dated to
          <input type="date" className={field} value={filters.to} onChange={(e) => set("to", e.target.value)} />
        </label>
        <label className={label}>
          Amount from (£)
          <input inputMode="decimal" className={field} value={filters.min} onChange={(e) => set("min", e.target.value)} />
        </label>
        <label className={label}>
          Amount to (£)
          <input inputMode="decimal" className={field} value={filters.max} onChange={(e) => set("max", e.target.value)} />
        </label>
        <label className={label}>
          Archive
          <select className={field} value={filters.archived} onChange={(e) => set("archived", e.target.value as Filters["archived"])}>
            <option value="all">Archived and current</option>
            <option value="current">Not archived</option>
            <option value="archived">Archived only</option>
          </select>
        </label>
        <div className="flex items-end">
          <button type="button" className={secondary} onClick={() => { setFilters(NO_FILTERS); setSelected(new Set()); }}>
            Clear filters
          </button>
        </div>
      </form>

      <p aria-live="polite" className="text-[13px] font-semibold tabular-nums text-muted">
        {count(hits.length, "file")} found{hits.length > SHOWN ? ` · showing the first ${SHOWN}` : ""}
        {index.truncated && " · the folder is very large, so the list may be partial"}
      </p>

      {shown.length > 0 && (
        <div className="flex min-w-0 flex-col gap-2 rounded-xl bg-ground p-2">
          <label className="flex min-h-11 items-center gap-2 text-[13px] font-bold">
            <input
              type="checkbox"
              className="h-5 w-5"
              checked={allPicked}
              onChange={() => setSelected(allPicked ? new Set() : new Set(movable.map((f) => f.path)))}
            />
            Select all shown ({movable.length})
          </label>
          <div className="flex min-w-0 flex-wrap items-end gap-2">
            <label className={`${label} min-w-[12rem] flex-1`}>
              Move selected to
              <select className={field} value={to} onChange={(e) => setTo(e.target.value)}>
                <option value="">Choose a folder…</option>
                {index.folders.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className={primary} disabled={busy || selected.size === 0 || !to} onClick={move}>
              {busy ? "Moving…" : `Move ${count(selected.size, "file")}`}
            </button>
          </div>
        </div>
      )}
      {note && (
        <p role="status" className="text-sm font-semibold text-teal-dark">
          {note}
        </p>
      )}

      <ul aria-label="Matching files" className="flex min-w-0 flex-col">
        {shown.map((f) => (
          <li key={f.path} className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 border-t border-border py-2">
            {f.protected ? (
              <span className="h-5 w-5 shrink-0" aria-hidden="true" />
            ) : (
              <input
                type="checkbox"
                className="h-5 w-5 shrink-0"
                checked={selected.has(f.path)}
                onChange={() => toggle(f.path)}
                aria-label={`Select ${f.path}`}
              />
            )}
            <div className="min-w-0 flex-1">
              <p className="break-all text-[14px] font-semibold">{f.name}</p>
              <p className="break-all text-[12px] text-muted">{f.path}</p>
              <p className="text-[12px] tabular-nums text-muted">
                {[
                  day(f.date),
                  bytes(f.size),
                  f.linked?.amount_pence != null ? pounds(f.linked.amount_pence) : null,
                  f.linked?.counterparty,
                  f.archived ? "archived" : null,
                  f.protected ? "kept in place by the app" : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
            <ShowInOneDrive url={f.web_url} name={f.name} />
            <Rename
              account={account}
              file={f}
              onDone={(msg) => {
                setNote(msg);
                onChanged();
              }}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
