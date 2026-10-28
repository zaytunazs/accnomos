"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "@/lib/msal";
import SignInCta from "@/components/SignInCta";
import { LoadingSkeleton, RuntimeErrorNote, parseRuntimeError } from "@/components/States";
import {
  IMPORT_KINDS,
  IMPORT_VENDORS,
  importApi,
  ukDate,
  type RtImportCheck,
  type RtImportDraftView,
  type RtImportKind,
  type RtImportMappingRow,
  type RtImportReconciliation,
  type RtImportRecord,
  type RtImportVendor,
} from "@/lib/runtime";

const card = "rounded-2xl border border-border bg-white p-5 sm:p-6";
const heading = "text-lg font-extrabold tracking-tight";
const th = "px-3 py-2 text-left text-[13px] font-bold text-muted";
const td = "px-3 py-2 text-[15px]";
const field = "h-11 rounded-xl border border-border bg-white px-3 text-[15px]";
const primary = "h-11 rounded-xl bg-teal px-4 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60";
const secondary = "h-11 rounded-xl border border-border px-4 text-[15px] font-bold text-teal-dark hover:bg-ground disabled:opacity-60";
const money = (pence: number) => (pence / 100).toLocaleString("en-GB", { style: "currency", currency: "GBP" });
const drCr = (pence: number) => (pence === 0 ? "—" : `${money(Math.abs(pence))} ${pence > 0 ? "Dr" : "Cr"}`);
const kindLabel = (k: RtImportKind) => IMPORT_KINDS.find((x) => x.id === k)?.label ?? k;
const HOW: Record<string, string> = { code: "same code", name: "by name", type: "new account", user: "your choice" };

function Scroll({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="region" aria-label={label} tabIndex={0} className="mt-3 overflow-x-auto">
      {children}
    </div>
  );
}

function Step({ n, id, title, children }: { n: number; id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className={card}>
      <h2 id={id} className={heading}>
        <span className="mr-2 inline-flex h-7 w-7 items-center justify-center rounded-full bg-teal-tint text-[14px] text-teal-dark">{n}</span>
        {title}
      </h2>
      {children}
    </section>
  );
}

function CheckList({ checks }: { checks: RtImportCheck[] }) {
  return (
    <ul className="mt-3 flex flex-col gap-2" aria-label="Checks">
      {checks.map((c) => (
        <li key={c.id} data-check={c.id} data-ok={c.ok ? "yes" : "no"} className="flex items-start gap-2 text-[15px]">
          <span
            aria-hidden="true"
            className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[12px] font-extrabold ${
              c.ok ? "bg-teal-tint text-teal-dark" : c.severity === "error" ? "bg-warn-ink text-white" : "bg-warn-bg text-warn-ink"
            }`}
          >
            {c.ok ? "✓" : "!"}
          </span>
          <span>
            <span className="sr-only">{c.ok ? "Passed: " : c.severity === "error" ? "Must fix: " : c.severity === "warning" ? "Warning: " : "Note: "}</span>
            {c.message}
          </span>
        </li>
      ))}
    </ul>
  );
}

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** One account's Accnomos account: type a code and name, or pick from the list; saved when it changes. */
function TargetInput({
  row,
  chartId,
  onSave,
  busy,
}: {
  row: RtImportMappingRow;
  chartId: string;
  onSave: (key: string, target: string | null) => void;
  busy: boolean;
}) {
  const [value, setValue] = useState(row.target ?? "");
  const label = `Accnomos account for ${row.code ? `${row.code} ` : ""}${row.name}`;
  function commit() {
    const v = value.trim();
    if (v === (row.target ?? "")) return;
    onSave(row.key, v || null);
  }
  return (
    <input
      aria-label={label}
      list={chartId}
      value={value}
      disabled={busy}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
      }}
      placeholder="e.g. 0010 Motor vehicles"
      className={`${field} w-64 ${row.target ? "" : "border-warn-border bg-warn-bg"}`}
    />
  );
}

function Posted({
  record,
  rec,
  account,
  onUndone,
}: {
  record: RtImportRecord;
  rec: RtImportReconciliation;
  account: AccountInfo;
  onUndone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [sure, setSure] = useState(false);
  const vendor = IMPORT_VENDORS.find((v) => v.id === record.vendor)?.label ?? "the old system";
  async function undo() {
    setBusy(true);
    setNote(null);
    try {
      await importApi.undo(account);
      onUndone();
    } catch (e) {
      setNote(parseRuntimeError((e as Error).message).detail || "Could not undo the import.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-labelledby="import-posted" className={card}>
      <h2 id="import-posted" className={heading}>
        {rec.undone ? "Opening balances undone" : "Opening balances posted"}
      </h2>
      <p className="mt-1 text-[15px] text-muted">
        From {vendor}, as at {ukDate(record.balance_date)} (conversion date {ukDate(record.conversion_date)}):{" "}
        {record.items.length} open invoice{record.items.length === 1 ? "" : "s"} and bill{record.items.length === 1 ? "" : "s"},{" "}
        {record.contacts_added.length} new contact{record.contacts_added.length === 1 ? "" : "s"}.
        {record.report_path ? ` A copy of this reconciliation is in ${record.report_path}.` : ""}
      </p>
      <p
        role="status"
        data-testid="import-proved"
        className={`mt-3 text-[15px] font-extrabold ${rec.proved ? "text-teal-dark" : "text-warn-ink"}`}
      >
        {rec.undone
          ? "The opening entry was reversed; the open items are gone."
          : rec.proved
            ? "Reconciled: the Accnomos trial balance equals the one you uploaded, to the penny."
            : "The reconciliation needs a look: see the checks below."}
      </p>
      <CheckList checks={rec.checks} />
      <Scroll label="Reconciliation by account">
        <table className="w-full min-w-[560px] border-collapse">
          <caption className="sr-only">Source trial balance against Accnomos, by account</caption>
          <thead>
            <tr>
              <th scope="col" className={th}>Accnomos account</th>
              <th scope="col" className={th}>From</th>
              <th scope="col" className={`${th} text-right`}>Source</th>
              <th scope="col" className={`${th} text-right`}>Accnomos</th>
              <th scope="col" className={th}>Agrees</th>
            </tr>
          </thead>
          <tbody>
            {rec.rows.map((r) => (
              <tr key={r.account} className="border-t border-border">
                <th scope="row" className={`${td} text-left font-normal`}>{r.account}</th>
                <td className={`${td} text-[13px] text-muted`}>{r.sources.join(", ")}</td>
                <td className={`${td} text-right tabular-nums`}>{drCr(r.source_pence)}</td>
                <td className={`${td} text-right tabular-nums`}>{drCr(r.accnomos_pence)}</td>
                <td className={td}>{r.ok ? "Yes" : <strong className="text-warn-ink">No</strong>}</td>
              </tr>
            ))}
            <tr className="border-t-2 border-ink font-bold">
              <th scope="row" className={`${td} text-left`}>Totals (debits)</th>
              <td className={td} />
              <td className={`${td} text-right tabular-nums`}>{money(rec.source_debits_pence)}</td>
              <td className={`${td} text-right tabular-nums`}>{money(rec.accnomos_debits_pence)}</td>
              <td className={td}>{rec.source_debits_pence === rec.accnomos_debits_pence ? "Yes" : "No"}</td>
            </tr>
          </tbody>
        </table>
      </Scroll>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          className={secondary}
          onClick={async () => {
            try {
              download(await importApi.reportCsv(account), `opening-balances-${record.balance_date}.csv`);
            } catch (e) {
              setNote(parseRuntimeError((e as Error).message).detail || "Could not download the report.");
            }
          }}
        >
          Download reconciliation (CSV)
        </button>
        <Link href="/reports" className="text-[15px] font-bold text-teal-dark underline underline-offset-2">
          See aged debtors and creditors
        </Link>
      </div>
      {!rec.undone && (
        <div className="mt-5 border-t border-border pt-4">
          <label className="flex items-start gap-2 text-[15px]">
            <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} className="mt-1 h-5 w-5" />
            <span>Undo the import: post the reversal of the opening entry and take the open items away. Contacts stay.</span>
          </label>
          <button type="button" className={`${secondary} mt-3`} disabled={!sure || busy} onClick={undo}>
            {busy ? "Undoing…" : "Undo import"}
          </button>
        </div>
      )}
      {note && (
        <p role="alert" className="mt-3 text-[15px] font-bold text-warn-ink">
          {note}
        </p>
      )}
    </section>
  );
}

export default function ImportWizard() {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [state, setState] = useState<"checking" | "signed-out" | "live" | "error">("checking");
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<RtImportDraftView | null>(null);
  const [opening, setOpening] = useState<{ record: RtImportRecord | null; reconciliation: RtImportReconciliation | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [kind, setKind] = useState<RtImportKind | "">("");
  const [side, setSide] = useState<"" | "sale" | "purchase">("");
  const [approved, setApproved] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [startAgain, setStartAgain] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function load(acct: AccountInfo) {
    const [v, o] = await Promise.all([importApi.draft(acct), importApi.opening(acct)]);
    setView(v);
    setOpening(o);
  }

  useEffect(() => {
    (async () => {
      try {
        if (!msalConfigured()) return setState("signed-out");
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct = msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
        if (!acct) return setState("signed-out");
        setAccount(acct);
        await load(acct);
        setState("live");
      } catch (e) {
        setError((e as Error).message);
        setState("error");
      }
    })();
  }, []);

  async function act(f: () => Promise<RtImportDraftView | void>, done?: string) {
    setBusy(true);
    setNote(null);
    try {
      const v = await f();
      if (v) setView(v);
      if (done) setNote(done);
    } catch (e) {
      setNote(parseRuntimeError((e as Error).message).detail || "That did not work; try again.");
    } finally {
      setBusy(false);
    }
  }

  if (state === "checking") return <LoadingSkeleton lines={4} label="Loading the import…" />;
  if (state === "signed-out")
    return (
      <div className={card}>
        <p className="text-[15px] leading-7 text-muted">
          Sign in to import your history. The files you upload and the opening entry go into your own OneDrive; nothing is
          posted until you have checked it.
        </p>
        <div className="mt-3">
          <SignInCta />
        </div>
      </div>
    );
  if (state === "error" && error) return <RuntimeErrorNote message={error} title="Couldn't open the import" />;
  if (!account || !view) return null;

  const live = opening?.record && !opening.record.undone_at;
  if (opening?.record && opening.reconciliation && (live || !startAgain)) {
    return (
      <div className="flex flex-col gap-6">
        <Posted
          record={opening.record}
          rec={opening.reconciliation}
          account={account}
          onUndone={() => void load(account)}
        />
        {!live && (
          <button type="button" className={`${primary} self-start`} onClick={() => setStartAgain(true)}>
            Start a new import
          </button>
        )}
      </div>
    );
  }

  const d = view.draft;
  const unmapped = view.accounts.filter((a) => !a.target).length;
  const errors = view.checks.filter((c) => c.severity === "error" && !c.ok);
  const files = d.files;
  const tbLoaded = files.some((f) => f.kind === "trial_balance");

  return (
    <div className="flex flex-col gap-6">
      <Step n={1} id="import-from" title="Where are you coming from?">
        <div className="mt-3 flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1 text-[14px] font-bold">
            Old system
            <select
              className={field}
              value={d.vendor ?? ""}
              disabled={busy}
              onChange={(e) => act(() => importApi.edit(account, { vendor: e.target.value as RtImportVendor }))}
            >
              <option value="" disabled>
                Choose…
              </option>
              {IMPORT_VENDORS.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[14px] font-bold">
            Conversion date (your first day in Accnomos)
            <input
              type="date"
              className={field}
              value={d.conversion_date ?? ""}
              disabled={busy}
              onChange={(e) => e.target.value && act(() => importApi.edit(account, { conversion_date: e.target.value }))}
            />
          </label>
        </div>
        <p className="mt-2 text-[14px] text-muted">
          {view.balance_date
            ? `Export everything as at ${ukDate(view.balance_date)}, the day before. The opening entry is dated then.`
            : "Usually the first day of a VAT quarter or of your financial year. Export the old system's figures as at the day before."}
        </p>
      </Step>

      <Step n={2} id="import-files" title="Upload the exports">
        <p className="mt-1 text-[15px] text-muted">
          The trial balance is required. Add the chart of accounts, contacts, open (unpaid) invoices and bills, and bank
          balances if you have them: CSV, or Excel .xlsx. We work out what each file is; pick it yourself if we cannot.
        </p>
        <form
          className="mt-3 flex flex-wrap items-end gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            const file = fileRef.current?.files?.[0];
            if (!file) return setNote("Choose a file first.");
            void act(async () => {
              const v = await importApi.upload(account, file, {
                kind: kind || undefined,
                vendor: d.vendor ?? undefined,
                side: side || undefined,
              });
              if (fileRef.current) fileRef.current.value = "";
              return v;
            }, `Read ${file.name}.`);
          }}
        >
          <label className="flex flex-col gap-1 text-[14px] font-bold">
            File
            <input ref={fileRef} type="file" accept=".csv,.xlsx,text/csv" className="text-[15px]" disabled={busy} />
          </label>
          <label className="flex flex-col gap-1 text-[14px] font-bold">
            What it is
            <select className={field} value={kind} onChange={(e) => setKind(e.target.value as RtImportKind | "")}>
              <option value="">Work it out</option>
              {IMPORT_KINDS.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
          {(kind === "" || kind === "open_items") && (
            <label className="flex flex-col gap-1 text-[14px] font-bold">
              Open items are
              <select className={field} value={side} onChange={(e) => setSide(e.target.value as "" | "sale" | "purchase")}>
                <option value="">As the file says</option>
                <option value="sale">Sales invoices (customers owe you)</option>
                <option value="purchase">Bills (you owe suppliers)</option>
              </select>
            </label>
          )}
          <button type="submit" className={primary} disabled={busy}>
            {busy ? "Reading…" : "Upload"}
          </button>
        </form>
        {d.vendor === "spreadsheet" && (
          <p className="mt-3 text-[14px] text-muted">
            Templates:{" "}
            {IMPORT_KINDS.map((k, i) => (
              <span key={k.id}>
                {i ? " · " : ""}
                <button
                  type="button"
                  className="font-bold text-teal-dark underline underline-offset-2"
                  onClick={async () => download(await importApi.template(account, k.id), `accnomos-${k.id}.csv`)}
                >
                  {k.label}
                </button>
              </span>
            ))}
          </p>
        )}
        {files.length > 0 && (
          <ul className="mt-4 flex flex-col gap-2" aria-label="Uploaded files">
            {files.map((f) => (
              <li key={f.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border px-3 py-2">
                <span className="min-w-0 text-[15px]">
                  <strong>{kindLabel(f.kind)}</strong> · {f.name} · {f.rows} row{f.rows === 1 ? "" : "s"}
                  {f.skipped.length > 0 && (
                    <span className="block text-[13px] text-warn-ink">
                      Left out: {f.skipped.slice(0, 3).join("; ")}
                      {f.skipped.length > 3 ? ` and ${f.skipped.length - 3} more` : ""}
                    </span>
                  )}
                </span>
                <button
                  type="button"
                  className="text-[14px] font-bold text-teal-dark underline underline-offset-2"
                  disabled={busy}
                  onClick={() => act(() => importApi.removeFile(account, f.id))}
                  aria-label={`Remove ${f.name}`}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </Step>

      {tbLoaded && (
        <Step n={3} id="import-map" title="Map the accounts">
          <p className="mt-1 text-[15px] text-muted">
            {unmapped
              ? `${unmapped} account${unmapped === 1 ? "" : "s"} need${unmapped === 1 ? "s" : ""} an Accnomos account (highlighted). `
              : "Every account has an Accnomos account. "}
            Change any you disagree with: type a four-digit code and a name, or pick one from the list.
          </p>
          <datalist id="import-chart">
            {view.chart.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
          <Scroll label="Account mapping">
            <table className="w-full min-w-[640px] border-collapse">
              <caption className="sr-only">Old accounts and the Accnomos account each goes to</caption>
              <thead>
                <tr>
                  <th scope="col" className={th}>Old account</th>
                  <th scope="col" className={th}>Type</th>
                  <th scope="col" className={`${th} text-right`}>Balance</th>
                  <th scope="col" className={th}>Accnomos account</th>
                </tr>
              </thead>
              <tbody>
                {view.accounts.map((r) => (
                  <tr key={r.key} data-account={r.key} className="border-t border-border">
                    <th scope="row" className={`${td} text-left font-normal`}>
                      {r.code ? <span className="text-muted">{r.code} </span> : null}
                      {r.name}
                    </th>
                    <td className={`${td} text-[13px] text-muted`}>{r.type ?? "—"}</td>
                    <td className={`${td} text-right tabular-nums`}>{drCr(r.balance_pence)}</td>
                    <td className={td}>
                      <TargetInput
                        key={`${r.key}:${r.target ?? ""}`}
                        row={r}
                        chartId="import-chart"
                        busy={busy}
                        onSave={(key, target) => act(() => importApi.edit(account, { mapping: { [key]: target } }))}
                      />
                      <span className="ml-2 text-[13px] text-muted">
                        {r.target ? `${HOW[r.how ?? ""] ?? ""}${r.new && r.how !== "type" ? ", new account" : ""}` : "needs an account"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
          <fieldset className="mt-4">
            <legend className="text-[15px] font-bold">Income and costs so far this year</legend>
            <label className="mt-2 flex items-start gap-2 text-[15px]">
              <input
                type="radio"
                name="pl"
                className="mt-1 h-5 w-5"
                checked={d.pl_treatment === "keep"}
                onChange={() => act(() => importApi.edit(account, { pl_treatment: "keep" }))}
              />
              <span>Keep them on their accounts (converting part way through a year), so this year&apos;s profit and loss is complete.</span>
            </label>
            <label className="mt-2 flex items-start gap-2 text-[15px]">
              <input
                type="radio"
                name="pl"
                className="mt-1 h-5 w-5"
                checked={d.pl_treatment === "retained"}
                onChange={() => act(() => importApi.edit(account, { pl_treatment: "retained" }))}
              />
              <span>Fold them into 3200 Retained profit (converting at a year end).</span>
            </label>
          </fieldset>
        </Step>
      )}

      {tbLoaded && (
        <Step n={4} id="import-check" title="Check the opening entry">
          <CheckList checks={view.checks} />
          {view.journal.length > 0 && (
            <Scroll label="Opening entry">
              <table className="w-full min-w-[480px] border-collapse">
                <caption className="sr-only">The opening entry, by Accnomos account</caption>
                <thead>
                  <tr>
                    <th scope="col" className={th}>Account</th>
                    <th scope="col" className={`${th} text-right`}>Debit</th>
                    <th scope="col" className={`${th} text-right`}>Credit</th>
                  </tr>
                </thead>
                <tbody>
                  {view.journal.map((j) => (
                    <tr key={j.account} className="border-t border-border">
                      <th scope="row" className={`${td} text-left font-normal`}>{j.account}</th>
                      <td className={`${td} text-right tabular-nums`}>{j.debit_pence ? money(j.debit_pence) : ""}</td>
                      <td className={`${td} text-right tabular-nums`}>{j.credit_pence ? money(j.credit_pence) : ""}</td>
                    </tr>
                  ))}
                  <tr className="border-t-2 border-ink font-bold">
                    <th scope="row" className={`${td} text-left`}>Total</th>
                    <td className={`${td} text-right tabular-nums`} data-testid="import-debits">{money(view.debits_pence)}</td>
                    <td className={`${td} text-right tabular-nums`}>{money(view.credits_pence)}</td>
                  </tr>
                </tbody>
              </table>
            </Scroll>
          )}
          <p className="mt-3 text-[15px] text-muted">
            Also carried over: {view.items.filter((i) => i.side === "sale").length} unpaid sales invoice(s),{" "}
            {view.items.filter((i) => i.side === "purchase").length} unpaid bill(s), {view.contacts} contact(s) from the
            contacts file plus everyone on an open item.
          </p>
        </Step>
      )}

      {tbLoaded && (
        <Step n={5} id="import-post" title="Approve and post">
          {errors.length > 0 ? (
            <p className="mt-2 text-[15px] font-bold text-warn-ink">Fix the checks marked ! above before posting.</p>
          ) : (
            <>
              <label className="mt-3 flex items-start gap-2 text-[15px]">
                <input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} className="mt-1 h-5 w-5" />
                <span>
                  I have checked the mapping and the opening entry. Post it to my books, dated{" "}
                  {view.balance_date ? ukDate(view.balance_date) : "the day before the conversion date"}.
                </span>
              </label>
              {view.needs_accept && (
                <label className="mt-2 flex items-start gap-2 text-[15px]">
                  <input type="checkbox" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} className="mt-1 h-5 w-5" />
                  <span>Post it anyway: I understand the warnings above (the reconciliation will show them).</span>
                </label>
              )}
              <button
                type="button"
                className={`${primary} mt-3`}
                disabled={busy || !approved || (view.needs_accept && !accepted)}
                onClick={() =>
                  act(async () => {
                    await importApi.post(account, accepted);
                    setStartAgain(false);
                    await load(account);
                  })
                }
              >
                {busy ? "Posting…" : "Post opening balances"}
              </button>
            </>
          )}
        </Step>
      )}

      <div className="flex flex-wrap items-center gap-3">
        {files.length > 0 && (
          <button type="button" className={secondary} disabled={busy} onClick={() => act(() => importApi.discard(account), "Started again.")}>
            Start again
          </button>
        )}
        <p role="status" aria-live="polite" className="text-[15px] font-bold text-teal-dark">
          {note}
        </p>
      </div>
    </div>
  );
}
