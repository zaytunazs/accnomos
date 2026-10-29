"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { Restore } from "@/components/files/BackupsPanel";
import { ShowInOneDrive, bytes, card, count, primary, reason, secondary } from "@/components/files/manage";
import {
  filesApi,
  fullBackupStream,
  type RtBackupVerification,
  type RtFullBackup,
  type RtFullBackupProgress,
  type RtRestorePreview,
} from "@/lib/runtime";

const when = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Europe/London",
      })
    : "Unfinished";

/**
 * Back up now (services/runtime/app/full_backup.py): a full, dated backup in its own folder, "Accnomos Backups",
 * apart from the live books. Progress as the runtime takes each step, the list of backups with Check and Restore,
 * and how to restore. Shown on the Files page and in Settings › Files & backups.
 */
export default function FullBackupPanel({ account, onChanged }: { account: AccountInfo; onChanged?: () => void }) {
  const [list, setList] = useState<RtFullBackup[] | null>(null);
  const [folder, setFolder] = useState("Accnomos Backups");
  const [progress, setProgress] = useState<RtFullBackupProgress | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [checks, setChecks] = useState<Record<string, RtBackupVerification>>({});
  const [restoring, setRestoring] = useState<RtRestorePreview | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await filesApi.fullBackups(account);
      setList(r.backups);
      setFolder(r.folder);
    } catch (e) {
      setNote(`Could not list your backups: ${reason(e)}`);
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  async function backUpNow() {
    setBusy(true);
    setNote(null);
    setProgress(null);
    try {
      const b = await fullBackupStream(account, setProgress);
      setNote(
        `Backed up to ${b.folder}: ${count(b.ledger_files ?? 0, "file")} from the ledger and settings, ` +
          `${count(b.files.length, "file")} in the folder, and an index of ${count(b.documents ?? 0, "document")}.`,
      );
      onChanged?.();
      await load();
    } catch (e) {
      setNote(`Could not back up: ${reason(e)}`);
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  async function check(b: RtFullBackup) {
    if (!b.system_zip) return;
    setBusy(true);
    setNote(null);
    try {
      const v = await filesApi.verifyBackup(account, b.system_zip);
      setChecks((prev) => ({ ...prev, [b.folder]: v }));
    } catch (e) {
      setNote(`Could not check ${b.name}: ${reason(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function startRestore(b: RtFullBackup) {
    if (!b.system_zip) return;
    setBusy(true);
    setNote(null);
    try {
      setRestoring(await filesApi.restorePreview(account, b.system_zip));
    } catch (e) {
      setNote(`Cannot restore ${b.name}: ${reason(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const pct = progress ? Math.round((progress.done / progress.total) * 100) : 0;
  return (
    <section aria-labelledby="full-backup-heading" className={card} id="back-up-now">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 id="full-backup-heading" className="text-[15px] font-extrabold">
            Full backups
          </h2>
          <p className="text-[13px] text-muted">
            Back up now writes a dated folder in <span className="font-semibold">{folder}</span> in your OneDrive, apart from
            your live books: the ledger, audit trail and settings (_System), a copy of Books.xlsx, the index of your
            documents, checksums and RESTORE.txt.
          </p>
        </div>
        <button type="button" className={primary} disabled={busy} onClick={backUpNow}>
          {busy && progress ? "Backing up…" : "Back up now"}
        </button>
      </div>
      {progress && (
        <div className="flex min-w-0 flex-col gap-1">
          <div
            role="progressbar"
            aria-label="Backup progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct}
            aria-valuetext={progress.label}
            className="h-2 w-full overflow-hidden rounded-full bg-ground"
          >
            <div className="h-full rounded-full bg-teal transition-[width]" style={{ width: `${pct}%` }} />
          </div>
          <p className="text-[13px] text-muted">
            Step {Math.min(progress.done + 1, progress.total)} of {progress.total}: {progress.label}
          </p>
        </div>
      )}
      {note && (
        <p role="status" className="text-sm font-semibold text-teal-dark">
          {note}
        </p>
      )}
      {restoring && (
        <Restore
          account={account}
          preview={restoring}
          onClose={() => setRestoring(null)}
          onRestored={(msg) => {
            setRestoring(null);
            setNote(msg);
            onChanged?.();
            void load();
          }}
        />
      )}
      {list === null ? (
        <p className="text-[13px] text-muted">Reading {folder}…</p>
      ) : list.length === 0 ? (
        <p className="text-[13px] text-muted">No full backups yet.</p>
      ) : (
        <ul aria-label="Full backups" className="flex min-w-0 flex-col">
          {list.map((b) => {
            const v = checks[b.folder];
            const size = b.files.reduce((n, f) => n + f.size, 0);
            return (
              <li key={b.folder} className="flex min-w-0 flex-col gap-1 border-t border-border py-2 first:border-t-0">
                <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="min-w-0 flex-1 break-all text-[14px] font-semibold">{b.name}</span>
                  <span className="text-[12px] tabular-nums text-muted">
                    {b.complete
                      ? `${when(b.created_at)} · ${count(b.files.length, "file")} · ${bytes(size)}`
                      : "Unfinished: it stopped part way; make a new one"}
                  </span>
                </div>
                {b.complete && (
                  <div className="flex flex-wrap items-center gap-2">
                    <button type="button" className={secondary} disabled={busy} onClick={() => check(b)} aria-label={`Check ${b.name}`}>
                      Check
                    </button>
                    <button type="button" className={secondary} disabled={busy} onClick={() => startRestore(b)} aria-label={`Restore ${b.name}`}>
                      Restore…
                    </button>
                    <ShowInOneDrive url={b.web_url} name={b.name} />
                  </div>
                )}
                {v && (
                  <p role="status" className={`text-[13px] font-semibold ${v.ok ? "text-teal-dark" : "text-warn-ink"}`}>
                    {v.ok ? `Checksum and all ${v.files} files match.` : `Problems: ${v.problems.join("; ")}`}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <details className="border-t border-border pt-3 text-[13px] text-ink">
        <summary className="min-h-11 cursor-pointer font-bold text-teal-dark">How to restore a backup</summary>
        <ol className="mt-1 list-decimal space-y-1 pl-5">
          <li>Press Check on the backup: it is compared with its checksums.</li>
          <li>
            Press Restore and read the preview: each file is new, the same, changed or kept. Type RESTORE to go ahead.
          </li>
          <li>
            Nothing is deleted: a changed file&apos;s current copy goes to _Trash first, and ledger entries and audit files
            already in your books are never replaced. Books.xlsx is rebuilt from the restored books.
          </li>
          <li>Each backup folder also holds RESTORE.txt with the same steps, and the zip can be opened without the app.</li>
        </ol>
        <p className="mt-2 text-muted">
          Backups are never removed by the app; delete old ones yourself in OneDrive. Every backup and restore is in the
          audit trail.
        </p>
      </details>
    </section>
  );
}
