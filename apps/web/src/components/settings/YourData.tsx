"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "@/lib/msal";
import { getRoot } from "@/lib/graph";
import { runtime, type RtDataExport } from "@/lib/runtime";

/** Settings › Your data: export everything, what is stored where, and leaving. */
export default function YourData({ card, heading }: { card: string; heading: string }) {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [exporting, setExporting] = useState(false);
  const [saved, setSaved] = useState<{ text: string; url: string | null } | null>(null);
  const [folderUrl, setFolderUrl] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        if (!msalConfigured()) return;
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct = msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
        if (!acct) return;
        setAccount(acct);
        try {
          setFolderUrl((await getRoot(acct)).webUrl ?? null);
        } catch {
          /* the folder link is a convenience; the export and the words below do not need it */
        }
      } catch {
        /* signed out: the sections below still explain where things live */
      }
    })();
  }, []);

  async function exportData() {
    if (!account) return;
    setExporting(true);
    setSaved(null);
    try {
      const r: RtDataExport = await runtime.booksExport(account);
      setSaved({ text: `Saved ${r.name} (${r.files} files) in your OneDrive, under 07 Reports/Exports.`, url: r.web_url });
    } catch (e) {
      setSaved({ text: `Could not save the export: ${(e as Error).message}`, url: null });
    } finally {
      setExporting(false);
    }
  }

  return (
    <>
      <section aria-labelledby="settings-data-export" className={card}>
        <h2 id="settings-data-export" className={heading}>
          Export your data
        </h2>
        <p className="mt-1 text-sm text-muted">
          Everything as one zip, saved to <span className="font-semibold">07 Reports/Exports</span> in your OneDrive: ledger
          events, proposals, contacts, invoices (with an index of the invoice PDFs), payments, bank lines, rules, the audit
          trail and the saved VAT returns — plus a README explaining each file and one CSV per main table so it opens in
          Excel. A second export the same day is kept beside the first, never overwritten.
        </p>
        {account ? (
          <div className="mt-3">
            <button
              type="button"
              onClick={exportData}
              disabled={exporting}
              className="h-12 rounded-xl border-2 border-teal bg-white px-5 text-[15px] font-extrabold text-teal-dark disabled:opacity-60"
            >
              {exporting ? "Saving…" : "Export your data"}
            </button>
            {saved && (
              <p role="status" className="mt-2 text-sm text-ink">
                {saved.text}{" "}
                {saved.url && (
                  <a href={saved.url} target="_blank" rel="noreferrer" className="font-bold text-teal-dark underline">
                    Open
                  </a>
                )}
              </p>
            )}
          </div>
        ) : (
          <p className="mt-3 text-sm text-muted">Sign in to export your books.</p>
        )}
      </section>

      <section aria-labelledby="settings-data-where" className={card}>
        <h2 id="settings-data-where" className={heading}>
          What is stored where
        </h2>
        <ul className="mt-2 list-disc space-y-2 pl-5 text-sm text-ink">
          <li>
            <strong>Your books</strong> live in your OneDrive, in the Accnomos app folder (personal accounts) or
            <span className="font-semibold"> /Accnomos</span> (work accounts): inbox, receipts, sales, bank statements,
            VAT returns, reports, Books.xlsx and <span className="font-semibold">_System</span> (the ledger events, audit
            trail and working data).
          </li>
          <li>
            <strong>This browser</strong> keeps your sign-in, your AI choice and key, VAT settings and display choices in
            its own localStorage (HMRC tokens live only in the tab). Disconnect removes them from this browser.
          </li>
          <li>
            <strong>The runtime keeps nothing.</strong> It reads and writes your OneDrive with the token each request
            carries, answers, and discards everything. There is no Accnomos user database.
          </li>
        </ul>
      </section>

      <section aria-labelledby="settings-leave" className={card}>
        <h2 id="settings-leave" className={heading}>
          Leave Accnomos
        </h2>
        <div className="mt-2 space-y-2 text-sm text-ink">
          <p>
            <strong>Disconnect</strong> clears this browser&apos;s sign-in and settings; your files stay in your OneDrive.{" "}
            <a href="#settings-disconnect" className="font-bold text-teal-dark underline">
              Disconnect Accnomos
            </a>
          </p>
          <p>
            <strong>To delete the books</strong>, delete the Accnomos folder in your OneDrive
            {folderUrl ? (
              <>
                {" "}
                (<a href={folderUrl} target="_blank" rel="noreferrer" className="font-bold text-teal-dark underline">
                  open your OneDrive folder
                </a>)
              </>
            ) : (
              ""
            )}
            . Because the runtime keeps no copy, that removes everything.
          </p>
          <p>
            <strong>To revoke the app&apos;s Microsoft permission</strong>, remove Accnomos at{" "}
            <a href="https://account.live.com/myapps" target="_blank" rel="noreferrer" className="font-bold text-teal-dark underline">
              account.live.com/myapps
            </a>
            .
          </p>
          <p>No server-side delete is needed, because nothing is stored server-side.</p>
        </div>
      </section>
    </>
  );
}
