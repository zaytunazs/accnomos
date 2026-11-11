"use client";

import { useEffect, useState, type ReactNode } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "@/lib/msal";
import { savedVrn } from "@/lib/hmrc";
import { PLANNED, useHmrcStatus } from "@/lib/hmrc-status";
import { fileYourself, type FyCell, type FyFormat, type FyKind, type FySheet } from "@/lib/file-yourself";
import { usePickedPeriod } from "@/lib/vat-period";
import { FOLDER } from "@/lib/folders";

const btn = "h-10 whitespace-nowrap rounded-xl px-4 text-[14px] font-bold disabled:cursor-not-allowed disabled:opacity-50";
const primary = `${btn} bg-teal text-white hover:bg-teal-dark`;
const secondary = `${btn} border border-border bg-white hover:bg-ground`;
const card = "rounded-2xl border border-border bg-white p-5 sm:p-6";

/** The signed-in Microsoft account, or null (signed out: these panels are not shown). */
function useAccount(): AccountInfo | null {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  useEffect(() => {
    (async () => {
      try {
        if (!msalConfigured()) return;
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        setAccount(msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null);
      } catch {
        /* signed out */
      }
    })();
  }, []);
  return account;
}

const cellText = (v: FyCell) =>
  v === null || v === undefined ? "" : typeof v === "number" ? v.toLocaleString("en-GB", { maximumFractionDigits: 2 }) : String(v);

/** One "File it yourself" file: what it is for, the cells as they are in the file, and CSV / XLSX buttons. */
function FilePanel({
  account,
  kind,
  query,
  heading,
  intro,
  controls,
}: {
  account: AccountInfo;
  kind: FyKind;
  query: Record<string, string | undefined>;
  heading: string;
  intro: ReactNode;
  controls?: ReactNode;
}) {
  const [sheet, setSheet] = useState<FySheet | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const key = JSON.stringify(query);

  useEffect(() => {
    let stale = false;
    fileYourself.preview(account, kind, JSON.parse(key)).then(
      (s) => {
        if (stale) return;
        setSheet(s);
        setError(null);
        setSaved(null); // a "saved" line is for the figures it was saved with
      },
      (e: Error) => !stale && setError(e.message),
    );
    return () => {
      stale = true;
    };
  }, [account, kind, key]);

  async function act(what: string, f: () => Promise<void>) {
    setBusy(what);
    setError(null);
    try {
      await f();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const id = `fy-${kind}`;
  return (
    <section aria-labelledby={id} className={card}>
      <h3 id={id} className="text-[17px] font-extrabold">
        {heading}
      </h3>
      <div className="mt-2 text-[15px] leading-7">{intro}</div>
      {controls && <div className="mt-3 flex flex-wrap items-end gap-3">{controls}</div>}
      {error && (
        <p role="alert" className="mt-3 rounded-xl border border-warn-border bg-warn-bg p-3 text-sm text-warn-ink">
          {error}
        </p>
      )}
      {sheet && (
        <>
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm leading-6">
            {sheet.guidance.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
          {sheet.warnings.length > 0 && (
            <ul className="mt-3 flex flex-col gap-1 rounded-xl border border-warn-border bg-warn-bg p-3 text-sm text-warn-ink">
              {sheet.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {(["csv", "xlsx"] as FyFormat[]).map((f) => (
              <button key={f} type="button" disabled={!!busy} className={primary} onClick={() => act(f, () => fileYourself.download(account, kind, query, f))}>
                {busy === f ? "Making…" : `Download ${f.toUpperCase()}`}
              </button>
            ))}
            {(["csv", "xlsx"] as FyFormat[]).map((f) => (
              <button
                key={`save-${f}`}
                type="button"
                disabled={!!busy}
                className={secondary}
                onClick={() =>
                  act(`save-${f}`, async () => {
                    const s = await fileYourself.save(account, kind, query, f);
                    setSaved(s.path);
                  })
                }
              >
                {busy === `save-${f}` ? "Saving…" : `Save ${f.toUpperCase()} to ${FOLDER.reports}`}
              </button>
            ))}
          </div>
          {saved && (
            <p aria-live="polite" className="mt-2 text-sm font-semibold text-teal-dark">
              Saved to your books: {saved}
            </p>
          )}
          {sheet.quickbooks_note && <p className="mt-2 text-[13px] text-muted">{sheet.quickbooks_note}</p>}
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer font-semibold text-muted">What&apos;s in the file, cell by cell</summary>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-muted">
              {sheet.layout.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
            <div className="mt-2 overflow-x-auto">
              <table aria-label={`${heading}: the file's cells`} className="w-full text-[13px]">
                <tbody>
                  {sheet.rows.map((r, i) => (
                    <tr key={i} className="border-t border-border">
                      <th scope="row" className="w-8 py-1 pr-2 text-left font-normal text-muted">
                        {i + 1}
                      </th>
                      {r.map((v, j) => (
                        <td key={j} className={`py-1 pr-3 ${typeof v === "number" ? "text-right tabular-nums" : ""}`}>
                          {cellText(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </section>
  );
}

/** /vat: the bridging file for the picked period. Shown beside Submit; the main way to file when live filing is off. */
export function VatFileItYourself() {
  const account = useAccount();
  const picked = usePickedPeriod();
  const status = useHmrcStatus();
  const [vrn] = useState(() => (typeof window === "undefined" ? "" : savedVrn()));
  if (!account) return null;
  return (
    <FilePanel
      account={account}
      kind="vat"
      query={{ period: picked?.period ?? undefined, vrn: vrn || undefined }}
      heading="File it yourself: VAT bridging file"
      intro={
        <>
          {status?.vatLive ? (
            <p>You can submit to HMRC above, or upload this file to your own bridging software instead.</p>
          ) : (
            <p>
              <strong>{PLANNED}</strong> Until then, upload this file to HMRC-recognised bridging software, which sends
              your return to HMRC.
            </p>
          )}
          <p className="text-muted">
            You can&apos;t type a VAT return into your HMRC online VAT account: since 1 November 2022 it has to go through
            Making Tax Digital or bridging software. Upload the file rather than retyping the numbers, so they stay
            digitally linked to your records.
          </p>
        </>
      }
    />
  );
}

const thisTaxYear = (d = new Date()) => {
  const y = d.getMonth() > 3 || (d.getMonth() === 3 && d.getDate() >= 6) ? d.getFullYear() : d.getFullYear() - 1;
  return `${y}-${String((y + 1) % 100).padStart(2, "0")}`;
};
const yearsBack = (n: number) => {
  const first = Number(thisTaxYear().slice(0, 4));
  return Array.from({ length: n }, (_, i) => `${first - i}-${String((first - i + 1) % 100).padStart(2, "0")}`);
};
const quarterEnds = (ty: string) => {
  const y = Number(ty.slice(0, 4));
  return [
    { value: `${y}-07-05`, label: "6 Apr – 5 Jul (due 7 Aug)" },
    { value: `${y}-10-05`, label: "6 Apr – 5 Oct (due 7 Nov)" },
    { value: `${y + 1}-01-05`, label: "6 Apr – 5 Jan (due 7 Feb)" },
    { value: `${y + 1}-04-05`, label: "6 Apr – 5 Apr (due 7 May)" },
  ];
};

const select = "h-10 rounded-xl border border-border bg-white px-3 text-[14px]";

/** /self-employment: the quarterly figures (cumulative) and the annual SA103S / SA103F pages. */
export function ItsaFileItYourself() {
  const account = useAccount();
  const status = useHmrcStatus();
  const [taxYear, setTaxYear] = useState(thisTaxYear);
  const [periodEnd, setPeriodEnd] = useState<string>(() => {
    const today = new Date().toISOString().slice(0, 10);
    const ended = quarterEnds(thisTaxYear()).filter((q) => q.value <= today);
    return (ended[ended.length - 1] ?? quarterEnds(thisTaxYear())[0]).value;
  });
  const [saYear, setSaYear] = useState(() => yearsBack(2)[1]);
  const [form, setForm] = useState<"auto" | "short" | "full">("auto");
  if (!account) return null;
  return (
    <div className="flex flex-col gap-6">
      <section aria-labelledby="fy-itsa-heading" className="flex flex-col gap-2">
        <h2 id="fy-itsa-heading" className="text-lg font-extrabold">
          File it yourself
        </h2>
        <p className="text-[15px] leading-7">
          <strong>{PLANNED}</strong>{" "}
          {status?.itsaSubmit
            ? "The Connect to HMRC card above practises the flow on HMRC's sandbox only. To file for real, use these files."
            : "To file now, use these files."}
        </p>
      </section>
      <FilePanel
        account={account}
        kind="itsa-quarterly"
        query={{ tax_year: taxYear, period_end: periodEnd }}
        heading="Quarterly update figures (Making Tax Digital for Income Tax)"
        intro={
          <p>
            HMRC has no web form for quarterly updates and no free software for them: upload this file into any
            HMRC-recognised MTD software or bridging product. The figures run from 6 April to the end of the quarter, in
            HMRC&apos;s own field names, each with the SA103F box it ends up in.
          </p>
        }
        controls={
          <>
            <label className="flex flex-col gap-1 text-sm font-semibold">
              Tax year
              <select
                className={select}
                value={taxYear}
                onChange={(e) => {
                  setTaxYear(e.target.value);
                  setPeriodEnd(quarterEnds(e.target.value)[0].value);
                }}
              >
                {yearsBack(3).map((y) => (
                  <option key={y}>{y}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm font-semibold">
              Update for
              <select className={select} value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)}>
                {quarterEnds(taxYear).map((q) => (
                  <option key={q.value} value={q.value}>
                    {q.label}
                  </option>
                ))}
              </select>
            </label>
          </>
        }
      />
      <FilePanel
        account={account}
        kind="sa103"
        query={{ tax_year: saYear, form }}
        heading="Self Assessment self-employment pages (SA103S or SA103F)"
        intro={
          <p>
            If you&apos;re not in Making Tax Digital for Income Tax, you can type these boxes into HMRC&apos;s online Self
            Assessment. Turnover under £90,000 uses the short pages (SA103S); £90,000 or more the full pages (SA103F).
          </p>
        }
        controls={
          <>
            <label className="flex flex-col gap-1 text-sm font-semibold">
              Tax year
              <select className={select} value={saYear} onChange={(e) => setSaYear(e.target.value)}>
                {yearsBack(3).map((y) => (
                  <option key={y}>{y}</option>
                ))}
              </select>
            </label>
            <fieldset className="flex flex-col gap-1 text-sm font-semibold">
              <legend>Pages</legend>
              <div className="flex gap-3">
                {(
                  [
                    ["auto", "By turnover"],
                    ["short", "Short (SA103S)"],
                    ["full", "Full (SA103F)"],
                  ] as const
                ).map(([v, label]) => (
                  <label key={v} className="flex min-h-10 items-center gap-2 font-normal">
                    <input type="radio" name="sa103-form" value={v} checked={form === v} onChange={() => setForm(v)} className="h-4 w-4 accent-teal" />
                    {label}
                  </label>
                ))}
              </div>
            </fieldset>
          </>
        }
      />
    </div>
  );
}
