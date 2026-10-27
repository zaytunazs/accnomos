"use client";

import { useRef, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { runtime } from "@/lib/runtime";

const MAX = 5 * 1024 * 1024; // the runtime's limit (routes_bank.py MAX_CSV)

/** Drop (or pick) bank statement CSVs. The runtime files each one as "03 Bank statements/{date}_{bank}.csv". */
export default function BankUpload({ account, onDone }: { account: AccountInfo | null; onDone: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msgs, setMsgs] = useState<string[]>([]);

  async function upload(files: FileList | null) {
    if (!account || !files || files.length === 0) return;
    setBusy(true);
    const out: string[] = [];
    for (const f of Array.from(files)) {
      if (!/\.csv$/i.test(f.name)) {
        out.push(`${f.name}: not a CSV — export the statement as CSV from your bank's website or app.`);
        continue;
      }
      if (f.size > MAX) {
        out.push(`${f.name}: over 5 MB — export a shorter date range.`);
        continue;
      }
      try {
        const r = await runtime.bank.upload(account, f);
        out.push(
          r.duplicate_file
            ? `${f.name}: already imported — nothing changed.`
            : `${f.name}: ${r.new_lines} new line${r.new_lines === 1 ? "" : "s"}` +
                (r.new_lines < r.lines ? ` (${r.lines - r.new_lines} already imported)` : "") +
                ` · saved as ${r.filed_path}`,
        );
      } catch (e) {
        out.push(`${f.name}: ${(e as Error).message}`);
      }
    }
    setMsgs(out);
    setBusy(false);
    if (input.current) input.current.value = "";
    onDone();
  }

  return (
    <section aria-labelledby="bank-upload-heading" className="flex flex-col gap-2">
      <h2 id="bank-upload-heading" className="sr-only">
        Upload a bank statement
      </h2>
      <input
        ref={input}
        type="file"
        accept=".csv,text/csv"
        multiple
        className="hidden"
        onChange={(e) => upload(e.target.files)}
      />
      <button
        type="button"
        disabled={!account || busy}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          upload(e.dataTransfer.files);
        }}
        className={`flex min-h-[96px] w-full flex-col items-center justify-center gap-1 rounded-2xl border-2 border-dashed px-4 py-5 text-center disabled:opacity-60 ${
          over ? "border-teal bg-teal-tint" : "border-border bg-white hover:bg-ground"
        }`}
      >
        <span className="text-[15px] font-bold">
          {busy ? "Reading statement…" : "Drop a bank statement CSV here, or choose a file"}
        </span>
        <span className="text-[13px] font-medium text-muted">
          Barclays, Starling, Tide, Monzo, HSBC, Lloyds and most UK bank CSV exports. The same file twice is ignored.
        </span>
      </button>
      {msgs.length > 0 && (
        <ul role="status" className="flex flex-col gap-1 text-sm font-semibold text-teal-dark">
          {msgs.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
