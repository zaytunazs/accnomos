"use client";

import { useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getFileBlob, type DriveItem } from "@/lib/graph";
import { runtime } from "@/lib/runtime";
import { modified, size } from "@/components/files/FilesTree";

/** The workbook sheets, as built by the runtime (services/runtime/app/projection.py SHEETS). */
export const BOOKS_SHEETS = [
  "README",
  "Summary",
  "Ledger",
  "Accounts",
  "VAT",
  "Customers",
  "Suppliers",
  "Bank",
  "Proposals",
  "Jobs",
  "Vehicles",
  "Payroll",
] as const;

/** Books.xlsx: when it was last rebuilt, rebuild it now, and download it through Graph. */
export default function BooksCard({
  account,
  books,
  onRebuilt,
}: {
  account: AccountInfo;
  books: DriveItem | null;
  onRebuilt: () => void;
}) {
  const [rebuilding, setRebuilding] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function rebuild() {
    setRebuilding(true);
    setNote(null);
    try {
      const r = await runtime.rebuild(account);
      setNote(`Books.xlsx rebuilt from your ledger events · ${size(r.size)}`);
      onRebuilt();
    } catch (e) {
      setNote(`Could not rebuild Books.xlsx: ${(e as Error).message}`);
    } finally {
      setRebuilding(false);
    }
  }

  async function download() {
    setDownloading(true);
    setNote(null);
    try {
      const blob = await getFileBlob(account, "Books.xlsx");
      const url = URL.createObjectURL(blob);
      try {
        const a = document.createElement("a");
        a.href = url;
        a.download = "Books.xlsx";
        document.body.appendChild(a);
        a.click();
        a.remove();
      } finally {
        URL.revokeObjectURL(url);
      }
    } catch (e) {
      setNote(`Could not download Books.xlsx: ${(e as Error).message}`);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <section aria-label="Books.xlsx" className="flex min-w-0 flex-col gap-3 rounded-2xl border border-border bg-white p-4 sm:p-5">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-[15px] font-extrabold">Books.xlsx</h2>
          <p className="text-[13px] font-medium text-muted">
            {books ? (
              <>Last rebuilt {modified(books.lastModifiedDateTime) || "just now"} · {size(books.size)}</>
            ) : (
              "Not built yet — press Rebuild now."
            )}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <button
            type="button"
            onClick={rebuild}
            disabled={rebuilding}
            title="Regenerate Books.xlsx from the ledger event files"
            className="whitespace-nowrap rounded-xl border-2 border-teal bg-white px-4 py-2 text-sm font-bold text-teal-dark disabled:border-border disabled:text-muted"
          >
            {rebuilding ? "Rebuilding…" : "Rebuild now"}
          </button>
          <button
            type="button"
            onClick={download}
            disabled={!books || downloading}
            title={books ? "Download Books.xlsx from your OneDrive" : "Rebuild Books.xlsx first"}
            className="whitespace-nowrap rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark disabled:bg-border disabled:text-muted"
          >
            {downloading ? "Downloading…" : "Download"}
          </button>
        </div>
      </div>
      {note && (
        <p role="status" className="text-sm font-semibold text-teal-dark">
          {note}
        </p>
      )}
      <div className="flex min-w-0 flex-wrap gap-1.5" aria-label="Workbook sheets">
        {BOOKS_SHEETS.map((s) => (
          <span key={s} className="whitespace-nowrap rounded-full bg-ground px-2.5 py-0.5 text-[12px] font-bold text-muted">
            {s}
          </span>
        ))}
      </div>
      <p className="text-[13px] font-medium text-muted">
        A read-only spreadsheet of your books. Do not edit it — the next rebuild overwrites your changes.
      </p>
    </section>
  );
}
