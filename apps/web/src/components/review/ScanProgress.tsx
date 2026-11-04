"use client";

import { useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import { runtime, type RtDocKind, type RtScanFile, type RtScanJob } from "@/lib/runtime";
import { KIND_LABEL, KINDS, trackScanJob, untrackScanJob, updateScanJob, useScanJobs } from "@/lib/scan-jobs";

/**
 * Every background scan this browser follows (lib/scan-jobs.ts): one progress bar per file (uploaded → reading →
 * confirm the type → checking → ready to review) and one for the whole job. When the AI has said what a file is,
 * its guess and how sure it is are shown with a choice of type; nothing is read in full, filed or posted until the
 * user confirms. Finished rows say where the file went (Review, Bank, Needs a look) or why it was not read.
 * A finished job folds into a quiet, compact row (its bars are full and gone; Dismiss stays); a job still reading,
 * waiting on a type, or with a file that failed keeps the full card so the progress and the errors stand out.
 */
export default function ScanProgress({ account }: { account: AccountInfo }) {
  const jobs = useScanJobs(account);
  if (jobs.length === 0) return null;
  return (
    <div className="flex flex-col gap-3">
      {[...jobs].reverse().map((j) => (
        <JobCard key={j.id} job={j} account={account} />
      ))}
    </div>
  );
}

const SOURCE: Record<RtScanJob["source"], string> = {
  upload: "Your upload",
  inbox: "00 Inbox",
  email: "From your email",
  phone: "From your phone",
};

function headline(job: RtScanJob): string {
  const n = job.files.length;
  const files = `${n} file${n === 1 ? "" : "s"}`;
  if (job.status === "working") return `Reading ${files}…`;
  if (job.status === "waiting") return `${job.counts.to_confirm} to confirm: what kind of document is it?`;
  const parts = [
    job.counts.ready ? `${job.counts.ready} ready to review` : "",
    job.counts.needs_a_look ? `${job.counts.needs_a_look} need${job.counts.needs_a_look === 1 ? "s" : ""} a look` : "",
    job.counts.failed ? `${job.counts.failed} not read` : "",
  ].filter(Boolean);
  return `Done · ${parts.join(" · ") || files}`;
}

function Bar({ value, label }: { value: number; label: string }) {
  const pct = Math.round(value * 100);
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      className="h-2 w-full overflow-hidden rounded-full bg-ground"
    >
      <div className="h-full rounded-full bg-teal transition-[width] duration-500" style={{ width: `${pct}%` }} />
    </div>
  );
}

function JobCard({ job, account }: { job: RtScanJob; account: AccountInfo }) {
  const [choice, setChoice] = useState<Record<string, RtDocKind>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const waiting = job.files.filter((f) => f.stage === "confirm");
  const kindOf = (f: RtScanFile): RtDocKind => choice[f.name] ?? f.guess?.kind ?? "other";
  // After a restart the unfinished files are still in 00 Inbox (route "inbox"): one tap reads them again.
  const stopped = job.interrupted ? job.files.filter((f) => f.stage === "failed" && f.route === "inbox") : [];

  async function scanAgain() {
    setBusy(true);
    setError(null);
    try {
      const fresh = await runtime.startScan(account, stopped.map((f) => f.name), job.source);
      trackScanJob(fresh);
      untrackScanJob(job.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirm(files: RtScanFile[]) {
    setBusy(true);
    setError(null);
    try {
      updateScanJob(await runtime.confirmScan(account, job.id, files.map((f) => ({ name: f.name, kind: kindOf(f) }))));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // Done, and nothing went wrong: the compact row. (A file that was not read keeps the full card: errors stay loud.)
  const quiet = job.status === "done" && !job.counts.failed && stopped.length === 0 && !error;

  return (
    <section
      aria-label={`Scan: ${SOURCE[job.source]}`}
      data-scan-quiet={quiet ? "" : undefined}
      className={quiet ? "rounded-2xl border border-border bg-ground px-4 py-2" : "rounded-2xl border border-border bg-white p-4"}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className={quiet ? "text-sm font-semibold text-ink" : "text-[15px] font-bold"} aria-live="polite">
          {headline(job)}
        </p>
        <div className="flex flex-wrap gap-2">
          {waiting.length > 1 && (
            <button
              type="button"
              disabled={busy}
              onClick={() => confirm(waiting)}
              className="h-11 rounded-xl bg-teal px-4 text-sm font-bold text-white disabled:opacity-60"
            >
              Confirm all {waiting.length}
            </button>
          )}
          {stopped.length > 0 && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void scanAgain()}
              data-scan-again=""
              className="h-11 rounded-xl bg-teal px-4 text-sm font-bold text-white disabled:opacity-60"
            >
              Scan {stopped.length === 1 ? "it" : `these ${stopped.length}`} again
            </button>
          )}
          {job.status === "done" && (
            <button
              type="button"
              onClick={() => untrackScanJob(job.id)}
              className={`h-11 rounded-xl px-4 text-sm font-bold ${quiet ? "text-teal-dark hover:bg-white" : "border border-border bg-white"}`}
            >
              Dismiss
            </button>
          )}
        </div>
      </div>
      <p className={`${quiet ? "" : "mt-1"} text-xs text-muted`}>
        {SOURCE[job.source]}
        {job.status === "done" ? "" : " · it carries on if you leave this page"}
        {job.interrupted ? " · the reader restarted part-way" : ""}
      </p>
      {!quiet && (
        <div className="mt-2">
          <Bar value={job.progress} label="Overall progress" />
        </div>
      )}
      {error && <p className="mt-2 text-sm font-semibold text-warn-ink">{error}</p>}
      <ul className={`${quiet ? "mt-1" : "mt-3"} flex flex-col divide-y divide-border`}>
        {job.files.map((f, i) => (
          <li
            key={f.name}
            className={`flex flex-col ${quiet ? "gap-0.5 py-1.5" : "gap-2 py-3"}`}
            data-scan-job={job.id}
            data-scan-file={f.name}
            data-stage={f.stage}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className={`min-w-0 break-all ${quiet ? "text-[13px] font-semibold text-ink" : "text-sm font-bold"}`}>{f.name}</span>
              <span className={`text-xs font-semibold ${f.stage === "failed" ? "text-warn-ink" : "text-teal-dark"}`}>{f.stage_label}</span>
            </div>
            {!quiet && <Bar value={f.progress} label={`${f.name}: ${f.stage_label}`} />}
            {f.stage === "confirm" && f.guess && (
              <div className="flex flex-wrap items-end gap-2">
                <p className="basis-full text-sm">
                  Looks like a <strong>{KIND_LABEL[f.guess.kind].toLowerCase()}</strong> ({Math.round(f.guess.confidence * 100)}% sure
                  {f.guess.by === "code" ? ", guessed by code" : ""}). <span className="text-muted">{f.guess.reason}</span>
                </p>
                <div className="flex flex-col gap-1">
                  <label htmlFor={`scan-${job.id}-${i}`} className="text-xs font-bold text-muted">
                    Type
                  </label>
                  <select
                    id={`scan-${job.id}-${i}`}
                    value={kindOf(f)}
                    onChange={(e) => setChoice((c) => ({ ...c, [f.name]: e.target.value as RtDocKind }))}
                    className="h-11 rounded-xl border border-border bg-white px-3 text-[15px] font-normal text-ink"
                  >
                    {KINDS.map((k) => (
                      <option key={k} value={k}>
                        {KIND_LABEL[k]}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => confirm([f])}
                  className="h-11 rounded-xl bg-teal px-4 text-sm font-bold text-white disabled:opacity-60"
                >
                  Confirm
                </button>
              </div>
            )}
            {f.message && (
              <p className={f.stage === "failed" ? "text-sm font-semibold text-warn-ink" : `${quiet ? "text-[13px]" : "text-sm"} text-muted`}>{f.message}</p>
            )}
            {f.stage !== "failed" && f.route === "bank" && (
              <Link href="/bank" className={`${quiet ? "text-[13px]" : "text-sm"} inline-block py-1 font-bold text-teal-dark underline underline-offset-2`}>
                Match the lines on Bank
              </Link>
            )}
            {f.stage === "ready" && f.route === "sales" && (
              <p className={`${quiet ? "text-[13px]" : "text-sm"} text-muted`}>In Review as a sale: approving it posts it to Sales.</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
