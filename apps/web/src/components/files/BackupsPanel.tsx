"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import {
  BACKUP_CHECKED_KEY,
  MONTHLY_BACKUP_KEY,
  filesApi,
  type RtBackup,
  type RtBackupVerification,
  type RtFileSettings,
  type RtRestorePreview,
} from "@/lib/runtime";
import { ShowInOneDrive, bytes, card, count, day, field, label, primary, reason, secondary } from "@/components/files/manage";

function remember(on: boolean) {
  try {
    window.localStorage.setItem(MONTHLY_BACKUP_KEY, on ? "1" : "0");
  } catch {
    /* private mode: the monthly check just does not run on this device */
  }
}

function Restore({
  account,
  preview,
  onClose,
  onRestored,
}: {
  account: AccountInfo;
  preview: RtRestorePreview;
  onClose: () => void;
  onRestored: (msg: string) => void;
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = !preview.needs_confirmation || typed.trim() === preview.confirm_word;
  const nothing = preview.counts.new + preview.counts.changed === 0;

  async function restore() {
    setBusy(true);
    setError(null);
    try {
      const r = await filesApi.restore(account, preview.path, preview.needs_confirmation ? typed.trim() : null);
      onRestored(
        `Restored ${preview.path.split("/").pop()}: ${count(r.restored, "file")} added, ${r.replaced} replaced` +
          (r.trash ? ` (the copies they replaced are in ${r.trash})` : "") +
          ".",
      );
    } catch (e) {
      setError(reason(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div role="region" aria-label="Restore preview" className="flex min-w-0 flex-col gap-2 rounded-xl border-2 border-warn-border bg-warn-bg p-3">
      <h3 className="text-[14px] font-extrabold text-warn-ink">Restore {preview.path.split("/").pop()}?</h3>
      <p className="text-[13px] text-warn-ink">
        {count(preview.counts.new, "file")} to add · {count(preview.counts.changed, "file")} to replace ·{" "}
        {preview.counts.same} the same · {preview.counts.kept} kept as they are now
      </p>
      <p className="text-[13px] text-warn-ink">{preview.note}</p>
      {preview.items.filter((i) => i.status !== "same").length > 0 && (
        <ul aria-label="What would change" className="flex max-h-56 flex-col gap-0.5 overflow-y-auto text-[12px]">
          {preview.items
            .filter((i) => i.status !== "same")
            .map((i) => (
              <li key={i.path} className="break-all">
                <span className="font-bold">
                  {{ new: "Add", changed: "Replace", kept: "Keep current", same: "Same" }[i.status]}
                </span>{" "}
                {i.path}
              </li>
            ))}
        </ul>
      )}
      {preview.needs_confirmation && !nothing && (
        <label className={label}>
          <span className="text-warn-ink">
            Your books are not empty. Type {preview.confirm_word} to restore this backup over them.
          </span>
          <input className={field} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} />
        </label>
      )}
      {error && (
        <p role="alert" className="text-sm font-semibold text-warn-ink">
          {error}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button type="button" className={primary} disabled={busy || !ready || nothing} onClick={restore}>
          {busy ? "Restoring…" : nothing ? "Nothing to restore" : "Restore"}
        </button>
        <button type="button" className={secondary} onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  );
}

/** Backups: Back up now, keep the last N, check a backup, restore one (preview first). */
export default function BackupsPanel({ account, onChanged }: { account: AccountInfo; onChanged: () => void }) {
  const [list, setList] = useState<RtBackup[] | null>(null);
  const [settings, setSettings] = useState<RtFileSettings | null>(null);
  const [keep, setKeep] = useState("12");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [checks, setChecks] = useState<Record<string, RtBackupVerification>>({});
  const [restoring, setRestoring] = useState<RtRestorePreview | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await filesApi.backups(account);
      setList(r.backups);
      setSettings(r.settings);
      setKeep(String(r.settings.backup_keep));
      remember(r.settings.monthly_backup);
    } catch (e) {
      setNote(`Could not list backups: ${reason(e)}`);
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  async function run<T>(what: () => Promise<T>, done: (r: T) => string, failed: string) {
    setBusy(true);
    setNote(null);
    try {
      setNote(done(await what()));
      await load();
    } catch (e) {
      setNote(`${failed}: ${reason(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const backUp = () =>
    run(
      () => filesApi.backUp(account),
      (r) => {
        onChanged();
        try {
          window.localStorage.setItem(BACKUP_CHECKED_KEY, new Date().toISOString().slice(0, 7));
        } catch {
          /* fine */
        }
        return (
          `Backed up ${count(r.backup.files ?? 0, "file")} to ${r.backup.path} (${bytes(r.backup.size)}).` +
          (r.retired.length ? ` ${count(r.retired.length, "older backup")} moved to _Trash.` : "")
        );
      },
      "Could not back up",
    );

  const saveSettings = (next: RtFileSettings) =>
    run(
      () => filesApi.saveBackupSettings(account, next),
      (s) => {
        remember(s.monthly_backup);
        return `Saved: keep the last ${s.backup_keep}${s.monthly_backup ? ", and back up once a month when you open the app" : ""}.`;
      },
      "Could not save",
    );

  async function verify(b: RtBackup) {
    setBusy(true);
    setNote(null);
    try {
      const v = await filesApi.verifyBackup(account, b.path);
      setChecks((prev) => ({ ...prev, [b.path]: v }));
    } catch (e) {
      setNote(`Could not check ${b.name}: ${reason(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function startRestore(b: RtBackup) {
    setBusy(true);
    setNote(null);
    try {
      setRestoring(await filesApi.restorePreview(account, b.path));
    } catch (e) {
      setNote(`Cannot restore ${b.name}: ${reason(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const keepN = Number(keep);
  const keepOk = Number.isInteger(keepN) && keepN >= 1 && keepN <= 120;
  return (
    <section aria-labelledby="backups-heading" className={card}>
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 id="backups-heading" className="text-[15px] font-extrabold">
            Backups
          </h2>
          <p className="text-[13px] text-muted">
            A dated zip of _System (ledger entries, Review cards, contacts, settings and the audit log) in Backups/, with a
            checksum beside it.
          </p>
        </div>
        <button type="button" className={primary} disabled={busy} onClick={backUp}>
          {busy ? "Working…" : "Back up now"}
        </button>
      </div>
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
            onChanged();
            void load();
          }}
        />
      )}
      {list === null ? (
        <p className="text-[13px] text-muted">Reading Backups/…</p>
      ) : list.length === 0 ? (
        <p className="text-[13px] text-muted">No backups yet.</p>
      ) : (
        <ul aria-label="Backups" className="flex min-w-0 flex-col">
          {list.map((b) => {
            const v = checks[b.path];
            return (
              <li key={b.path} className="flex min-w-0 flex-col gap-1 border-t border-border py-2 first:border-t-0">
                <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="min-w-0 flex-1 break-all text-[14px] font-semibold">{b.name}</span>
                  <span className="text-[12px] tabular-nums text-muted">
                    {day(b.day)} · {bytes(b.size)}
                    {!b.has_checksum && " · no checksum file"}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button type="button" className={secondary} disabled={busy} onClick={() => verify(b)} aria-label={`Check ${b.name}`}>
                    Check
                  </button>
                  <button type="button" className={secondary} disabled={busy} onClick={() => startRestore(b)} aria-label={`Restore ${b.name}`}>
                    Restore…
                  </button>
                  <ShowInOneDrive url={b.web_url} name={b.name} />
                </div>
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
      {settings && (
        <form
          aria-label="Backup settings"
          className="flex min-w-0 flex-wrap items-end gap-2 border-t border-border pt-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (keepOk) void saveSettings({ ...settings, backup_keep: keepN });
          }}
        >
          <label className={`${label} w-40`}>
            Keep the last
            <input type="number" min={1} max={120} className={field} value={keep} onChange={(e) => setKeep(e.target.value)} />
          </label>
          <button type="submit" className={secondary} disabled={busy || !keepOk}>
            Save
          </button>
          <label className="flex min-h-11 w-full items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="h-5 w-5"
              checked={settings.monthly_backup}
              disabled={busy}
              onChange={(e) => void saveSettings({ ...settings, monthly_backup: e.target.checked })}
            />
            Back up once a month, the first time I open the app that month
          </label>
          <p className="w-full text-[12px] text-muted">
            Older backups move to _Trash, never deleted. There is no Accnomos server running for you, so the monthly backup
            happens only when you open the app (on this device) in a new month.
          </p>
        </form>
      )}
    </section>
  );
}
