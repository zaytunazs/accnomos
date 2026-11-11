"use client";

import { useRef, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { FOLDER } from "@/lib/folders";
import { listChildren, putSmallFile } from "@/lib/graph";
import {
  candidatesFromDrop,
  candidatesFromFiles,
  chunk,
  expandAll,
  mapLimit,
  planUploads,
  SCAN_BATCH,
  skipSummary,
  type Candidate,
  type Skipped,
} from "@/lib/bulk-intake";
import { runtime } from "@/lib/runtime";
import { trackScanJob } from "@/lib/scan-jobs";

interface FileResult {
  name: string;
  ok: boolean;
  error?: string;
}

const CONCURRENCY = 4;

/**
 * F3 intake (web): put photos, PDFs, bank CSVs, zips and whole folders into the user's own "00 Inbox" folder (straight
 * to their OneDrive or Google Drive), then start reading them at once: background jobs on the runtime
 * (lib/scan-jobs.ts, 50 files each), whose progress ScanProgress shows. Zips are opened and folders walked in the
 * browser (lib/bulk-intake.ts); everything lands flat in 00 Inbox. No request waits on the AI.
 */
export default function UploadToInbox({ account, onDone }: { account: AccountInfo; onDone: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [bar, setBar] = useState<{ done: number; total: number } | null>(null);
  const [results, setResults] = useState<FileResult[]>([]);
  const [skipped, setSkipped] = useState<Skipped[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [reading, setReading] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  async function onItems(gather: () => Promise<Candidate[]>) {
    if (busy) return;
    setBusy(true);
    setProgress("Looking through what you added…");
    setBar(null);
    setResults([]);
    setSkipped([]);
    setProblem(null);
    setReading(null);
    const done: FileResult[] = [];
    const names: string[] = [];
    try {
      let plan: ReturnType<typeof planUploads>;
      try {
        const expanded = await expandAll(await gather());
        let taken: string[] = [];
        try {
          taken = (await listChildren(account, FOLDER.inbox)).map((c) => c.name);
        } catch {
          /* no Inbox listing: names are still made unique within this drop */
        }
        plan = planUploads(expanded.files, taken);
        plan.skipped.push(...expanded.skipped);
      } catch (e) {
        setProblem((e as Error).message);
        setProgress(null);
        return;
      }
      setSkipped(plan.skipped);
      const { uploads } = plan;
      let finished = 0;
      setBar({ done: 0, total: uploads.length });
      await mapLimit(uploads, CONCURRENCY, async (u) => {
        try {
          const item = await putSmallFile(account, `${FOLDER.inbox}/${u.name}`, u.blob, u.type);
          names.push(item?.name || u.name);
          done.push({ name: u.name, ok: true });
        } catch (e) {
          done.push({ name: u.name, ok: false, error: (e as Error).message });
        }
        finished++;
        setBar({ done: finished, total: uploads.length });
        setProgress(`Uploading ${finished} of ${uploads.length}`);
        setResults([...done]);
      });
      if (names.length > 0) {
        setProgress("Starting to read…");
        try {
          for (const batch of chunk(names, SCAN_BATCH)) trackScanJob(await runtime.startScan(account, batch, "upload"));
          setReading("Reading now: see the progress below. It carries on if you leave this page.");
        } catch (e) {
          setReading(`Uploaded, but reading could not start: ${(e as Error).message} Press “Scan 00 Inbox now” to try again.`);
        }
        onDone();
      }
      setProgress(null);
      setBar(null);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
      if (folderInput.current) folderInput.current.value = "";
    }
  }

  const okCount = results.filter((r) => r.ok).length;
  const errors = results.filter((r) => !r.ok);

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const dt = e.dataTransfer;
        void onItems(() => candidatesFromDrop(dt));
      }}
      className={`flex flex-wrap items-center gap-3 rounded-2xl border-2 border-dashed p-3 ${
        dragging ? "border-teal bg-teal-tint" : "border-border"
      }`}
    >
      <input
        ref={input}
        type="file"
        accept="image/*,.pdf,.csv,.zip,application/zip"
        multiple
        aria-label="Choose receipt photos, PDFs, bank CSVs or zips"
        className="hidden"
        onChange={(e) => {
          const files = e.target.files ? Array.from(e.target.files) : [];
          if (files.length) void onItems(async () => candidatesFromFiles(files));
        }}
      />
      <input
        ref={folderInput}
        type="file"
        multiple
        aria-label="Choose a folder of documents"
        className="hidden"
        {...({ webkitdirectory: "" } as Record<string, string>)}
        onChange={(e) => {
          const files = e.target.files ? Array.from(e.target.files) : [];
          if (files.length) void onItems(async () => candidatesFromFiles(files));
        }}
      />
      <button
        type="button"
        disabled={busy}
        onClick={() => input.current?.click()}
        className="h-11 whitespace-nowrap rounded-xl border border-border bg-white px-5 text-[15px] font-bold disabled:opacity-60"
      >
        {busy ? "Uploading…" : "Add a receipt"}
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => folderInput.current?.click()}
        className="h-11 whitespace-nowrap rounded-xl border border-border bg-white px-5 text-[15px] font-bold disabled:opacity-60"
      >
        Choose a folder
      </button>
      <span className="text-sm text-muted">or drop photos, PDFs, bank CSVs, zips or whole folders here — they are read straight away</span>
      <div className="w-full" aria-live="polite">
        {progress && (
          <p role="status" className="text-sm font-semibold text-teal-dark">
            {progress}
          </p>
        )}
        {bar && bar.total > 0 && (
          <div
            role="progressbar"
            aria-label="Upload progress"
            aria-valuemin={0}
            aria-valuemax={bar.total}
            aria-valuenow={bar.done}
            className="my-1 h-2 w-full overflow-hidden rounded-full bg-border"
          >
            <div className="h-full bg-teal" style={{ width: `${Math.round((bar.done / bar.total) * 100)}%` }} />
          </div>
        )}
        {problem && (
          <p role="alert" className="text-sm font-semibold text-warn-ink">
            {problem}
          </p>
        )}
        {skipped.length > 0 && (
          <details className="text-sm text-muted">
            <summary>
              {skipped.length} skipped: {skipSummary(skipped)}
            </summary>
            <ul className="ml-4 list-disc">
              {skipped.slice(0, 20).map((s, i) => (
                <li key={`${s.name}-${i}`}>
                  {s.name}: {s.reason}
                </li>
              ))}
              {skipped.length > 20 && <li>and {skipped.length - 20} more</li>}
            </ul>
          </details>
        )}
        {results.length > 0 && (
          <div role="status" className="flex flex-col gap-1">
            {okCount > 0 && (
              <p className="text-sm text-muted">
                {okCount} file{okCount === 1 ? "" : "s"} added to 00 Inbox. {reading}
              </p>
            )}
            {errors.length > 0 && (
              <ul className="flex flex-col gap-1">
                {errors.map((r) => (
                  <li key={r.name} className="text-sm font-semibold text-warn-ink">
                    {r.name}: {r.error}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
