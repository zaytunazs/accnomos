"use client";

import { useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { BULK_TYPES, type RtBulkJob } from "@/lib/bulk";
import { FOLDER } from "@/lib/folders";
import { runtime } from "@/lib/runtime";
import UploadMany from "@/components/review/UploadMany";

/**
 * The bulk batch: upload into 01 Bulk upload, process it (zips unpacked, every
 * file classified two at a time), check the one-line summary row by row, then
 * Confirm all files everything to its normal folder.
 */
export default function BulkSection({ account, onDone }: { account: AccountInfo; onDone: () => void }) {
  const [job, setJob] = useState<RtBulkJob | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<"process" | "confirm" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function process() {
    setBusy("process");
    setError(null);
    try {
      setJob(await runtime.bulkStart(account));
      setEdits({});
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function confirm() {
    if (!job) return;
    setBusy("confirm");
    setError(null);
    try {
      setJob(await runtime.bulkConfirm(account, job.id, edits));
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const routed = job?.rows.filter((r) => r.status === "routed").length ?? 0;

  return (
    <section aria-labelledby="bulk-upload" className="flex min-w-0 flex-col gap-3">
      <UploadMany account={account} onDone={() => undefined} />
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={process}
          disabled={busy !== null}
          className="h-11 whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white disabled:opacity-60"
        >
          {busy === "process" ? "Reading the bulk folder…" : "Process the bulk folder"}
        </button>
        <span className="text-sm text-muted">Only {FOLDER.bulk} is ever read in bulk.</span>
      </div>
      {error && (
        <p role="alert" className="rounded-xl bg-warn-bg px-4 py-2 text-sm font-semibold text-warn-ink">
          {error}
        </p>
      )}
      {job && (
        <div className="rounded-2xl border border-border bg-white p-4">
          <p className="text-[15px] font-extrabold">{job.summary || "Nothing to file"}</p>
          {job.errors.length > 0 && (
            <ul className="mt-2 flex flex-col gap-1">
              {job.errors.map((e) => (
                <li key={e.path} className="text-sm font-semibold text-warn-ink">
                  {e.path.split("/").pop()}: {e.error}
                </li>
              ))}
            </ul>
          )}
          {job.rows.length > 0 && (
            <ul className="mt-3 divide-y divide-border">
              {job.rows.map((r) => (
                <li key={r.path} className="flex flex-wrap items-center justify-between gap-3 py-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-bold">{r.name}</p>
                    <p className="text-sm text-muted">
                      {r.status === "failed"
                        ? (r.reason ?? "could not be read")
                        : [r.doc_type, r.supplier, r.gross != null ? `£${r.gross.toFixed(2)}` : null, r.source_note]
                            .filter(Boolean)
                            .join(" · ")}
                    </p>
                  </div>
                  {r.status === "ready" && job.status === "classified" && (
                    <label className="flex items-center gap-2 text-sm font-bold">
                      Type
                      <select
                        value={edits[r.path] ?? r.doc_type}
                        onChange={(e) =>
                          setEdits((prev) => {
                            const next = { ...prev };
                            if (e.target.value === r.doc_type) delete next[r.path];
                            else next[r.path] = e.target.value;
                            return next;
                          })
                        }
                        className="h-11 rounded-xl border border-border bg-white px-3 font-normal"
                      >
                        {BULK_TYPES.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {r.status === "routed" && <span className="text-sm font-bold text-teal-dark">Filed</span>}
                </li>
              ))}
            </ul>
          )}
          {job.status === "classified" && (
            <button
              type="button"
              onClick={confirm}
              disabled={busy !== null}
              className="mt-3 h-11 whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white disabled:opacity-60"
            >
              {busy === "confirm" ? "Filing…" : "Confirm all"}
            </button>
          )}
          {job.status === "confirmed" && (
            <p role="status" className="mt-3 text-sm font-semibold text-teal-dark">
              {routed} file{routed === 1 ? "" : "s"} filed. Anything left behind keeps its reason above.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
