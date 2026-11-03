"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import {
  runtime,
  type RtImportCandidate,
  type RtContactImportKind,
  type RtImportPreview,
  type RtImportSummary,
} from "@/lib/runtime";
import { parseRuntimeError } from "@/components/States";

/**
 * Import contacts, all or a chosen few, from Outlook or from the people who email you (the Android app adds the
 * phone's address book). Every row shows whether it is already in the books (same name, email or phone); those start
 * unticked. Each row picks Customer, Supplier or Both. Nothing is written to Outlook or the mailbox.
 */

type WebSource = "outlook" | "email";
const SOURCES: { id: WebSource; label: string }[] = [
  { id: "outlook", label: "Outlook contacts" },
  { id: "email", label: "People who email you" },
];
const KINDS: { id: RtContactImportKind; label: string }[] = [
  { id: "customer", label: "Customer" },
  { id: "supplier", label: "Supplier" },
  { id: "both", label: "Both" },
];
const card = "rounded-2xl border border-border bg-white";
const control = "h-11 rounded-xl border border-border bg-white px-3 text-[15px] focus:border-teal focus:outline-none";

export default function ImportContacts({
  account,
  onDone,
  onClose,
}: {
  account: AccountInfo;
  onDone: (summary: RtImportSummary) => void;
  onClose: () => void;
}) {
  const [source, setSource] = useState<WebSource>("outlook");
  const [preview, setPreview] = useState<RtImportPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [kinds, setKinds] = useState<Record<string, RtContactImportKind>>({});
  const [query, setQuery] = useState("");

  const load = useCallback(
    async (s: WebSource) => {
      setLoading(true);
      setError(null);
      setPreview(null);
      try {
        const p = await runtime.importPreview(account, s);
        setPreview(p);
        setPicked(new Set(p.candidates.filter((c) => !c.existing_id).map((c) => c.ref)));
        setKinds(Object.fromEntries(p.candidates.map((c) => [c.ref, c.kind])));
      } catch (e) {
        const msg = (e as Error).message;
        if (!/redirecting for consent/.test(msg)) setError(parseRuntimeError(msg).detail || "Could not read that list; try again.");
      } finally {
        setLoading(false);
      }
    },
    [account],
  );

  useEffect(() => {
    queueMicrotask(() => void load(source));
  }, [load, source]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const all = preview?.candidates ?? [];
    return q ? all.filter((c) => [c.name, c.person, c.email, c.phone].some((v) => v?.toLowerCase().includes(q))) : all;
  }, [preview, query]);
  const chosen = (preview?.candidates ?? []).filter((c) => picked.has(c.ref));

  const toggle = (ref: string) =>
    setPicked((old) => {
      const next = new Set(old);
      if (next.has(ref)) next.delete(ref);
      else next.add(ref);
      return next;
    });
  const selectAll = () => setPicked(new Set(rows.map((c) => c.ref)));
  const clear = () => setPicked(new Set());
  const setAllKinds = (k: RtContactImportKind) =>
    setKinds((old) => ({ ...old, ...Object.fromEntries(chosen.map((c) => [c.ref, k])) }));

  async function save() {
    if (!preview || chosen.length === 0) return;
    setSaving(true);
    setError(null);
    try {
      const summary = await runtime.importContacts(
        account,
        preview.source,
        chosen.map((c) => ({ name: c.name, person: c.person, email: c.email, phone: c.phone, kind: kinds[c.ref] ?? c.kind })),
      );
      onDone(summary);
    } catch (e) {
      setError(parseRuntimeError((e as Error).message).detail || "Could not import; try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-label="Import contacts" aria-busy={loading || saving} className={`${card} flex flex-col gap-3 p-4`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-[17px] font-bold">Import contacts</h2>
          <p className="mt-1 text-[13px] leading-6 text-muted">
            Tick the ones you want, choose Customer, Supplier or Both, then import. Ones already in your books start
            unticked; importing them again only fills in a missing email or phone. On the Android app you can also
            import from your phone&rsquo;s contacts.
          </p>
        </div>
        <button type="button" onClick={onClose} className="h-11 rounded-xl px-3 text-sm font-bold text-teal-dark hover:bg-teal-tint">
          Close
        </button>
      </div>

      <div role="tablist" aria-label="Import from" className="flex w-fit gap-1 rounded-xl border border-border bg-white p-1">
        {SOURCES.map((s) => (
          <button
            key={s.id}
            type="button"
            role="tab"
            aria-selected={source === s.id}
            onClick={() => setSource(s.id)}
            className={`min-h-10 rounded-lg px-4 text-sm font-bold ${source === s.id ? "bg-teal-tint text-teal-dark" : "text-muted hover:text-ink"}`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {preview && <p className="text-[13px] text-muted">{preview.note}</p>}
      {error && (
        <p role="alert" className="text-[13px] font-semibold text-[#A12626]">
          {error}
        </p>
      )}
      {loading && <p className="text-[13px] text-muted">Reading the list…</p>}

      {preview && preview.candidates.length === 0 && !loading && (
        <p className="text-[15px]">
          {source === "outlook" ? "No Outlook contacts were found." : "No one has emailed you in the last 180 days, apart from newsletters."}
        </p>
      )}

      {preview && preview.candidates.length > 0 && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <label className="sr-only" htmlFor="import-search">
              Search the list
            </label>
            <input
              id="import-search"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search name, email or phone"
              className={`${control} min-w-0 flex-1`}
            />
            <button type="button" onClick={selectAll} className="h-11 rounded-xl border border-border px-3 text-sm font-bold text-teal-dark">
              Select all
            </button>
            <button type="button" onClick={clear} className="h-11 rounded-xl border border-border px-3 text-sm font-bold text-teal-dark">
              Clear
            </button>
            <label className="flex items-center gap-2 text-[13px] font-semibold text-muted">
              Set ticked to
              <select
                aria-label="Set the kind of every ticked row"
                defaultValue=""
                onChange={(e) => {
                  if (e.target.value) setAllKinds(e.target.value as RtContactImportKind);
                  e.target.value = "";
                }}
                className={control}
              >
                <option value="">Choose…</option>
                {KINDS.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="text-[13px] text-muted">
            {preview.new} new · {preview.existing} already in your books · {chosen.length} ticked
          </p>
          <ul aria-label="Contacts to import" className="flex max-h-[28rem] flex-col divide-y divide-border overflow-y-auto rounded-xl border border-border">
            {rows.map((c) => (
              <ImportRow
                key={c.ref}
                c={c}
                checked={picked.has(c.ref)}
                kind={kinds[c.ref] ?? c.kind}
                onToggle={() => toggle(c.ref)}
                onKind={(k) => setKinds((old) => ({ ...old, [c.ref]: k }))}
              />
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={save}
              disabled={saving || chosen.length === 0}
              className="h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60"
            >
              {saving ? "Importing…" : `Import ${chosen.length}`}
            </button>
          </div>
        </>
      )}
    </section>
  );
}

function ImportRow({
  c,
  checked,
  kind,
  onToggle,
  onKind,
}: {
  c: RtImportCandidate;
  checked: boolean;
  kind: RtContactImportKind;
  onToggle: () => void;
  onKind: (k: RtContactImportKind) => void;
}) {
  const id = `imp-${c.ref}`;
  const details = [c.person, c.email, c.phone, c.messages ? `${c.messages} email${c.messages === 1 ? "" : "s"}` : null]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className="flex flex-wrap items-center gap-3 px-3 py-2.5">
      <input id={id} type="checkbox" checked={checked} onChange={onToggle} className="h-5 w-5 shrink-0 accent-[#0F6E63]" />
      <label htmlFor={id} className="min-w-0 flex-1">
        <span className="block font-bold">{c.name}</span>
        {details && <span className="block truncate text-[13px] text-muted">{details}</span>}
        {c.existing_id && (
          <span className="mt-0.5 inline-block rounded-md bg-[#EDF6FF] px-2 py-0.5 text-[12px] font-semibold text-[#175C86]">
            Already in your books{c.existing_name && c.existing_name !== c.name ? ` as ${c.existing_name}` : ""} ({c.match})
          </span>
        )}
      </label>
      <select
        aria-label={`Kind for ${c.name}`}
        value={kind}
        onChange={(e) => onKind(e.target.value as RtContactImportKind)}
        className={control}
      >
        {KINDS.map((k) => (
          <option key={k.id} value={k.id}>
            {k.label}
          </option>
        ))}
      </select>
    </li>
  );
}
