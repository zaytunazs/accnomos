"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "@/lib/msal";
import SignInCta from "@/components/SignInCta";
import { LoadingSkeleton, RuntimeErrorNote, SamplePill, parseRuntimeError } from "@/components/States";
import {
  runtime,
  type RtCellKind,
  type RtExportCatalogue,
  type RtExportPreview,
  type RtExportQuery,
  type RtExportReport,
  type RtMappingView,
  type RtReportSection,
} from "@/lib/runtime";
import { sampleCatalogue, sampleTrialBalance } from "@/lib/sample-exports";

const card = "rounded-2xl border border-border bg-white p-4 sm:p-5";
const th = "px-3 py-2 text-left text-[13px] font-bold text-muted";
const td = "px-3 py-1.5 text-[14px] align-top";
const button = "h-11 rounded-xl border border-border bg-white px-3 text-[14px] font-bold hover:bg-ground disabled:opacity-60";
const primary = "h-11 rounded-xl bg-teal px-4 text-[14px] font-bold text-white hover:bg-teal-dark disabled:opacity-60";
const FORMAT_LABEL: Record<string, string> = { csv: "CSV", xlsx: "Excel", pdf: "PDF", zip: "ZIP", json: "JSON" };

const money = (pence: number) => (pence / 100).toLocaleString("en-GB", { style: "currency", currency: "GBP" });
const ukDay = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
};

function cell(kind: RtCellKind, v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "";
  if (kind === "money" && typeof v === "number") return money(v);
  if (kind === "pounds" && typeof v === "number") return `£${v.toLocaleString("en-GB")}`;
  if (kind === "date" && typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v)) return ukDay(v);
  return String(v);
}

/** One table of a report, as the runtime laid it out: heading, subtotal and total rows bold. Scrolls sideways on a phone.
 *  With no rows the column headings still show: an import file has its header row (the package's template) even then. */
function SectionTable({ section, label, total }: { section: RtReportSection; label: string; total: number }) {
  const numeric = (k: RtCellKind) => k === "money" || k === "pounds" || k === "int";
  return (
    <div className="mt-4">
      <h3 className="text-[15px] font-extrabold">{section.title}</h3>
      {section.columns.length === 0 ? (
        <p className="mt-1 text-sm text-muted">Nothing in this period.</p>
      ) : (
        // relative: the sr-only caption is absolutely positioned and must not widen the page (docs/reviews/ci).
        <div role="region" aria-label={`${label}: ${section.title}`} tabIndex={0} className="relative mt-2 max-w-full overflow-x-auto">
          <table className="w-full border-collapse tabular-nums">
            <caption className="sr-only">{`${label}: ${section.title}`}</caption>
            <thead className="border-b border-border">
              <tr>
                {section.columns.map((c) => (
                  <th key={c.key} scope="col" className={`${th} whitespace-nowrap ${numeric(c.kind) ? "text-right" : ""}`}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {section.rows.length === 0 && (
                <tr>
                  <td colSpan={section.columns.length} className={`${td} text-muted`}>
                    Nothing in this period.
                  </td>
                </tr>
              )}
              {section.rows.map((r, i) => (
                <tr
                  key={i}
                  className={`border-b border-border ${r.style === "total" ? "bg-ground font-extrabold" : r.style === "subtotal" ? "font-bold" : r.style === "heading" ? "bg-teal-tint/40 font-bold" : ""}`}
                >
                  {section.columns.map((c) => (
                    <td key={c.key} className={`${td} ${numeric(c.kind) ? "whitespace-nowrap text-right" : ""}`}>
                      {cell(c.kind, r.cells[c.key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {total > section.rows.length && (
        <p className="mt-1 text-[13px] text-muted">
          Showing the first {section.rows.length} of {total} rows. The files have them all.
        </p>
      )}
      {section.note && <p className="mt-1 text-[13px] text-muted">{section.note}</p>}
    </div>
  );
}

function Star({ report, on, disabled, onToggle }: { report: RtExportReport; on: boolean; disabled: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={`Star ${report.title}`}
      title={on ? "Starred" : "Star this report"}
      disabled={disabled}
      onClick={onToggle}
      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-xl hover:bg-ground disabled:opacity-50"
    >
      <span aria-hidden="true" className={on ? "text-warn-ink" : "text-muted"}>
        {on ? "★" : "☆"}
      </span>
    </button>
  );
}

function ReportList({
  catalogue,
  favourites,
  selected,
  filter,
  live,
  onSelect,
  onStar,
}: {
  catalogue: RtExportCatalogue;
  favourites: string[];
  selected: string | null;
  filter: string;
  live: boolean;
  onSelect: (id: string) => void;
  onStar: (id: string) => void;
}) {
  const f = filter.trim().toLowerCase();
  const match = (r: RtExportReport) => !f || r.title.toLowerCase().includes(f) || r.description.toLowerCase().includes(f);
  const groups = [
    ...(favourites.length ? [{ id: "starred", title: "Starred" }] : []),
    ...catalogue.groups,
  ];
  return (
    <div className="flex min-w-0 flex-col gap-4">
      {groups.map((g) => {
        const reports =
          g.id === "starred"
            ? favourites.map((id) => catalogue.reports.find((r) => r.id === id)).filter((r): r is RtExportReport => !!r)
            : catalogue.reports.filter((r) => r.group === g.id);
        const shown = reports.filter(match);
        if (!shown.length) return null;
        return (
          <section key={g.id} aria-labelledby={`group-${g.id}`} className={card}>
            <h2 id={`group-${g.id}`} className="text-[17px] font-extrabold">
              {g.title}
            </h2>
            <ul className="mt-2 flex flex-col">
              {shown.map((r) => (
                <li key={`${g.id}-${r.id}`} className="flex min-w-0 items-start gap-1 border-t border-border py-1 first:border-t-0">
                  <button
                    type="button"
                    onClick={() => onSelect(r.id)}
                    aria-current={selected === r.id ? "true" : undefined}
                    aria-controls="report-preview"
                    className={`min-h-11 min-w-0 flex-1 rounded-xl px-2 py-1.5 text-left hover:bg-ground ${selected === r.id ? "bg-teal-tint" : ""}`}
                  >
                    <span className="block text-[15px] font-bold">{r.title}</span>
                    <span className="block text-[13px] text-muted">{r.description}</span>
                  </button>
                  <Star report={r} on={favourites.includes(r.id)} disabled={!live} onToggle={() => onStar(r.id)} />
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** The account mapping for one package: each account in the books, what it maps to, and how sure that is. */
function MappingPanel({ account, packages }: { account: AccountInfo; packages: Record<string, string> }) {
  const [pkg, setPkg] = useState("xero");
  const [loaded, setLoaded] = useState<{ pkg: string; view: RtMappingView } | null>(null);
  const view = loaded && loaded.pkg === pkg ? loaded.view : null;
  const [edits, setEdits] = useState<Record<string, { code: string; name: string }>>({});
  const [note, setNote] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let stale = false;
    runtime.exports.mapping(account, pkg).then(
      (v) => !stale && setLoaded({ pkg, view: v }),
      (e: Error) => !stale && setNote(`Could not load the mapping: ${parseRuntimeError(e.message).detail || e.message}`),
    );
    return () => {
      stale = true;
    };
  }, [account, pkg]);

  async function save() {
    setSaving(true);
    setNote(null);
    try {
      const v = await runtime.exports.putMapping(account, pkg, edits);
      setLoaded({ pkg, view: v });
      setEdits({});
      setNote(`Mapping saved in _System/exports/mappings.json. ${v.unmapped ? `${v.unmapped} account(s) still unmapped.` : "Every account is mapped."}`);
    } catch (e) {
      setNote(`Could not save the mapping: ${parseRuntimeError((e as Error).message).detail || "try again."}`);
    } finally {
      setSaving(false);
    }
  }

  const QUALITY: Record<string, string> = {
    user: "Your choice",
    default: "Standard",
    suggested: "Suggested",
    check: "Check",
    own: "Your own",
    unmapped: "Unmapped",
  };
  return (
    <section aria-labelledby="mapping-heading" className={card}>
      <h2 id="mapping-heading" className="text-[17px] font-extrabold">
        Account mapping
      </h2>
      <p className="text-[13px] text-muted">
        How each account in your books lands in the other package. Standard and suggested ones are filled in; change any, and
        check the ones marked Check or Unmapped before importing.
      </p>
      <label className="mt-3 flex flex-col gap-1 text-[13px] font-bold">
        Package
        <select value={pkg} onChange={(e) => { setEdits({}); setPkg(e.target.value); }} className="h-11 rounded-xl border border-border bg-white px-3 text-[15px] font-normal">
          {Object.entries(packages).map(([id, title]) => (
            <option key={id} value={id}>
              {title}
            </option>
          ))}
        </select>
      </label>
      {!view ? (
        <LoadingSkeleton lines={3} label="Loading the mapping…" />
      ) : (
        <>
          <div role="region" aria-label={`${view.title} account mapping`} tabIndex={0} className="mt-3 max-w-full overflow-x-auto">
            <table className="w-full border-collapse">
              <caption className="sr-only">{view.title} account mapping</caption>
              <thead className="border-b border-border">
                <tr>
                  <th scope="col" className={th}>Your account</th>
                  <th scope="col" className={th}>{view.title} code</th>
                  <th scope="col" className={th}>{view.title} name</th>
                  <th scope="col" className={th}>Status</th>
                </tr>
              </thead>
              <tbody>
                {view.accounts.map((m) => {
                  const value = edits[m.account] ?? { code: m.code, name: m.name };
                  const set = (k: "code" | "name", v: string) => setEdits((all) => ({ ...all, [m.account]: { ...value, [k]: v } }));
                  return (
                    <tr key={m.account} className="border-b border-border">
                      <th scope="row" className={`${td} text-left font-semibold`}>{m.account}</th>
                      <td className={td}>
                        <input aria-label={`${view.title} code for ${m.account}`} value={value.code} onChange={(e) => set("code", e.target.value)}
                          className="h-10 w-20 rounded-lg border border-border px-2" maxLength={40} />
                      </td>
                      <td className={td}>
                        <input aria-label={`${view.title} name for ${m.account}`} value={value.name} onChange={(e) => set("name", e.target.value)}
                          className="h-10 w-48 rounded-lg border border-border px-2" maxLength={200} />
                      </td>
                      <td className={`${td} text-[13px] ${m.quality === "unmapped" || m.quality === "check" ? "font-bold text-warn-ink" : "text-muted"}`} title={m.note}>
                        {QUALITY[m.quality] ?? m.quality}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[13px] text-muted">
            VAT codes become: {Object.entries(view.vat.sales ?? {}).map(([k, v]) => `${k} → ${v}`).join(", ")} (sales).
          </p>
          <button type="button" onClick={save} disabled={saving || !Object.keys(edits).length} className={`${primary} mt-3`}>
            {saving ? "Saving…" : "Save mapping"}
          </button>
        </>
      )}
      <p role="status" className="mt-2 text-[13px] text-muted">{note}</p>
    </section>
  );
}

function Preview({
  report,
  preview,
  loading,
  live,
  query,
  onMode,
  onDownload,
  onSave,
  busy,
  status,
}: {
  report: RtExportReport;
  preview: RtExportPreview | null;
  loading: boolean;
  live: boolean;
  query: RtExportQuery;
  onMode: (mode: string) => void;
  onDownload: (format: string) => void;
  onSave: (format: string) => void;
  busy: string | null;
  status: { text: string; url: string | null } | null;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const [saveFormat, setSaveFormat] = useState(report.formats[0]); // the parent keys Preview by report: fresh per report
  useEffect(() => {
    heading.current?.focus();
  }, [report.id]);
  const doc = preview?.doc;
  return (
    <section id="report-preview" aria-labelledby="preview-heading" className={`${card} min-w-0`}>
      <h2 id="preview-heading" ref={heading} tabIndex={-1} className="text-lg font-extrabold outline-none">
        {report.title}
      </h2>
      <p className="text-[13px] text-muted">{doc ? doc.period : report.description}</p>
      {report.modes.length > 0 && (
        <label className="mt-3 flex max-w-sm flex-col gap-1 text-[13px] font-bold">
          What to include
          <select
            value={query.mode ?? report.modes[0].value}
            onChange={(e) => onMode(e.target.value)}
            className="h-11 rounded-xl border border-border bg-white px-3 text-[15px] font-normal"
          >
            {report.modes.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2" role="group" aria-label="Download">
        {report.formats.map((f) => (
          <button key={f} type="button" disabled={!live || !!busy} onClick={() => onDownload(f)} className={button} aria-label={`Download ${FORMAT_LABEL[f] ?? f}`}>
            {busy === `download-${f}` ? "Preparing…" : FORMAT_LABEL[f] ?? f}
          </button>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        {report.formats.length > 1 && (
          <label className="flex flex-col gap-1 text-[13px] font-bold">
            Save as
            <select value={saveFormat} onChange={(e) => setSaveFormat(e.target.value)} className="h-11 rounded-xl border border-border bg-white px-3 text-[15px] font-normal">
              {report.formats.map((f) => (
                <option key={f} value={f}>
                  {FORMAT_LABEL[f] ?? f}
                </option>
              ))}
            </select>
          </label>
        )}
        <button type="button" disabled={!live || !!busy} onClick={() => onSave(saveFormat)} className={primary}>
          {busy === "save" ? "Saving…" : "Save to 07 Reports"}
        </button>
      </div>
      {!live && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-[13px] text-muted">
          Sign in to download or save reports from your own books. <SignInCta />
        </p>
      )}
      <p role="status" className="mt-2 text-[13px] text-muted">
        {status?.text}
        {status?.url && (
          <>
            {" "}
            <a href={status.url} target="_blank" rel="noreferrer" className="font-bold text-teal-dark underline underline-offset-2">
              Open
            </a>
          </>
        )}
      </p>
      {loading && <LoadingSkeleton lines={5} label={`Working out ${report.title.toLowerCase()}…`} />}
      {!loading && !doc && <p className="mt-3 text-sm text-muted">Sign in to preview this report with your books.</p>}
      {!loading && doc && (
        <>
          {doc.sample && <p className="mt-3 text-sm font-bold text-warn-ink">SAMPLE — FICTIONAL COMPANY</p>}
          {doc.import_file && (
            <p className="mt-3 rounded-xl bg-ground p-3 text-[13px]">
              <strong>{doc.import_file.package}</strong> · {doc.import_file.template}. {doc.import_file.instructions}{" "}
              <span className="text-muted">Checked against: {doc.import_file.source}</span>
            </p>
          )}
          {doc.warnings.length > 0 && (
            <ul aria-label="Check before using" className="mt-3 list-disc space-y-1 rounded-xl border border-warn-ink/30 p-3 pl-6 text-[13px] text-warn-ink">
              {doc.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
          {doc.sections.map((s, i) => (
            <SectionTable key={i} section={s} label={doc.title} total={preview?.total_rows[i] ?? s.rows.length} />
          ))}
          {doc.basis.map((b, i) => (
            <p key={i} className="mt-3 text-[13px] text-muted">
              {b}
            </p>
          ))}
          <p className="mt-1 text-[13px] text-muted">Worked out by code from your approved entries. Downloading or saving posts nothing.</p>
        </>
      )}
    </section>
  );
}

/** Reports & exports: every report the runtime offers, grouped as Xero groups them, each with a preview, format
 *  buttons and Save to 07 Reports. Signed out: a labelled sample. */
export default function ReportsExports() {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [state, setState] = useState<"checking" | "demo" | "live" | "error">("checking");
  const [error, setError] = useState<string | null>(null);
  const [catalogue, setCatalogue] = useState<RtExportCatalogue | null>(null);
  const [favourites, setFavourites] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState<RtExportQuery>({});
  const [result, setResult] = useState<{ key: string; preview: RtExportPreview | null } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [status, setStatus] = useState<{ text: string; url: string | null } | null>(null);
  const [filter, setFilter] = useState("");
  const live = state === "live" && !!account;

  useEffect(() => {
    (async () => {
      try {
        if (!msalConfigured()) {
          setCatalogue(sampleCatalogue);
          return setState("demo");
        }
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct = msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
        if (!acct) {
          setCatalogue(sampleCatalogue);
          return setState("demo");
        }
        setAccount(acct);
        const c = await runtime.exports.catalogue(acct);
        setCatalogue(c);
        setFavourites(c.favourites);
        setState("live");
      } catch (e) {
        setError((e as Error).message);
        setState("error");
      }
    })();
  }, []);

  const report = useMemo(() => catalogue?.reports.find((r) => r.id === selected) ?? null, [catalogue, selected]);

  const requestKey = selected ? JSON.stringify([selected, query.from, query.to, query.as_of, query.mode]) : null;
  const preview = !account ? (selected === "trial-balance" ? sampleTrialBalance : null) : result && result.key === requestKey ? result.preview : null;
  const loading = !!account && !!requestKey && result?.key !== requestKey;

  useEffect(() => {
    if (!account || !selected || !requestKey) return;
    let stale = false;
    runtime.exports.preview(account, selected, query).then(
      (p) => {
        if (stale) return;
        setResult({ key: requestKey, preview: p });
        setQuery((old) => (old.from && old.to ? old : { ...old, from: p.from, to: p.to }));
      },
      (e: Error) => {
        if (stale) return;
        setResult({ key: requestKey, preview: null });
        setStatus({ text: `Could not work out the report: ${parseRuntimeError(e.message).detail || "try again."}`, url: null });
      },
    );
    return () => {
      stale = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, requestKey]);

  function select(id: string) {
    setStatus(null);
    setSelected(id);
    setQuery((q) => ({ ...q, mode: undefined }));
  }

  async function star(id: string) {
    if (!account) return;
    const next = favourites.includes(id) ? favourites.filter((f) => f !== id) : [...favourites, id];
    setFavourites(next);
    try {
      setFavourites((await runtime.exports.putFavourites(account, next)).ids);
    } catch (e) {
      setFavourites(favourites);
      setStatus({ text: `Could not save your starred reports: ${parseRuntimeError((e as Error).message).detail || "try again."}`, url: null });
    }
  }

  async function onDownload(format: string) {
    if (!account || !report) return;
    setBusy(`download-${format}`);
    setStatus(null);
    try {
      const { blob, name: fromHeader } = await runtime.exports.file(account, report.id, format, query);
      // The runtime's Content-Disposition is not exposed to a cross-origin page; the preview carries the same name.
      const name = preview?.filenames[format] ?? fromHeader;
      download(blob, name);
      setStatus({ text: `Downloaded ${name}.`, url: null });
    } catch (e) {
      setStatus({ text: `Could not download: ${parseRuntimeError((e as Error).message).detail || "try again."}`, url: null });
    } finally {
      setBusy(null);
    }
  }

  async function onSave(format: string) {
    if (!account || !report) return;
    setBusy("save");
    setStatus(null);
    try {
      const r = await runtime.exports.save(account, report.id, format, query);
      setStatus({ text: `Saved to ${r.path} in your OneDrive.`, url: r.web_url });
    } catch (e) {
      setStatus({ text: `Could not save: ${parseRuntimeError((e as Error).message).detail || "try again."}`, url: null });
    } finally {
      setBusy(null);
    }
  }

  if (state === "checking") return <LoadingSkeleton lines={4} label="Loading reports…" />;
  if (state === "error" && error) return <RuntimeErrorNote message={error} title="Couldn't load the reports" />;
  if (!catalogue) return null;

  const usesPeriod = !report || report.params.includes("period");
  const usesAsOf = !!report?.params.includes("as_of");
  const periodWhy = !live
    ? "The period is fixed for the sample: sign in to choose dates from your own books."
    : !usesPeriod
      ? `${report?.title ?? "This report"} is worked out as at one date, not for a period.`
      : null;
  return (
    <div className="flex min-w-0 flex-col gap-4">
      {state === "demo" && (
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] font-medium text-muted">
          <SamplePill />
          <span>Some of the reports and exports on offer, with fictional figures.</span>
          <SignInCta />
        </p>
      )}
      <form className={`${card} flex flex-wrap items-end gap-3`} aria-label="Report period" onSubmit={(e) => e.preventDefault()}>
        <label className="flex flex-col gap-1 text-[13px] font-bold">
          From
          <input type="date" value={query.from ?? ""} disabled={!live || !usesPeriod} aria-describedby={periodWhy ? "period-why" : undefined}
            onChange={(e) => e.target.value && setQuery((q) => ({ ...q, from: e.target.value }))}
            className="h-11 rounded-xl border border-border px-3 text-[15px] font-normal" />
        </label>
        <label className="flex flex-col gap-1 text-[13px] font-bold">
          To
          <input type="date" value={query.to ?? ""} disabled={!live || !usesPeriod} aria-describedby={periodWhy ? "period-why" : undefined}
            onChange={(e) => e.target.value && setQuery((q) => ({ ...q, to: e.target.value }))}
            className="h-11 rounded-xl border border-border px-3 text-[15px] font-normal" />
        </label>
        {usesAsOf && (
          <label className="flex flex-col gap-1 text-[13px] font-bold">
            As at
            <input type="date" value={query.as_of ?? preview?.as_of ?? ""} disabled={!live}
              onChange={(e) => e.target.value && setQuery((q) => ({ ...q, as_of: e.target.value }))}
              className="h-11 rounded-xl border border-border px-3 text-[15px] font-normal" />
          </label>
        )}
        <button type="button" className={button} disabled={!live || !usesPeriod} aria-describedby={periodWhy ? "period-why" : undefined}
          onClick={() => setQuery((q) => ({ mode: q.mode }))}>
          This VAT period
        </button>
        <label className="flex min-w-0 flex-1 flex-col gap-1 text-[13px] font-bold sm:min-w-56">
          Find a report
          <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="e.g. VAT, aged, Xero"
            className="h-11 rounded-xl border border-border px-3 text-[15px] font-normal" />
        </label>
        {/* A disabled control says why (the period controls are off for the sample, or for an as-at report). */}
        {periodWhy && (
          <p id="period-why" className="basis-full text-[13px] text-muted">
            {periodWhy}
          </p>
        )}
      </form>
      <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
        <div className="min-w-0">
          <ReportList catalogue={catalogue} favourites={favourites} selected={selected} filter={filter} live={live} onSelect={select} onStar={star} />
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          {report ? (
            <Preview
              key={report.id}
              report={report}
              preview={preview}
              loading={loading}
              live={live}
              query={query}
              onMode={(mode) => setQuery((q) => ({ ...q, mode }))}
              onDownload={onDownload}
              onSave={onSave}
              busy={busy}
              status={status}
            />
          ) : (
            // The report buttons' aria-controls names this id, so it exists before a report is chosen too.
            <section id="report-preview" className={card} aria-label="Preview">
              <p className="text-sm text-muted">Choose a report to preview it, download it or save it to 07 Reports.</p>
            </section>
          )}
          {live && account && <MappingPanel account={account} packages={catalogue.packages} />}
        </div>
      </div>
    </div>
  );
}
