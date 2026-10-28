"use client";

import { useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { filesApi, type RtStorageOverview } from "@/lib/runtime";
import { ShowInOneDrive, bytes, card, count, primary, reason } from "@/components/files/manage";

/** Storage: files and sizes per folder and per tax year, the largest documents, and Clean up for duplicates. */
export default function StorageOverview({
  account,
  overview,
  onChanged,
  note,
  setNote,
}: {
  account: AccountInfo;
  overview: RtStorageOverview;
  onChanged: () => void;
  note: string | null; // kept by the parent: this panel is remounted when the overview is read again
  setNote: (note: string | null) => void;
}) {
  const suggested = overview.duplicates.flatMap((g) => g.files.filter((f) => !f.keep && !f.linked && !f.protected).map((f) => f.path));
  const [picked, setPicked] = useState<Set<string>>(() => new Set(suggested));
  const [busy, setBusy] = useState(false);

  function toggle(path: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  async function cleanUp() {
    setBusy(true);
    setNote(null);
    try {
      const r = await filesApi.trash(account, [...picked]);
      setNote(`Moved ${count(r.moved.length, "file")} to _Trash. Empty _Trash in OneDrive when you are sure.`);
      setPicked(new Set());
      onChanged();
    } catch (e) {
      setNote(`Nothing was moved: ${reason(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const biggest = Math.max(1, ...overview.folders.map((f) => f.bytes));
  return (
    <section aria-labelledby="storage-heading" className={card}>
      <div className="min-w-0">
        <h2 id="storage-heading" className="text-[15px] font-extrabold">
          Storage
        </h2>
        <p className="text-[13px] font-medium tabular-nums text-muted">
          {count(overview.total_files, "file")} · {bytes(overview.total_bytes)} in your books folder
          {overview.truncated && " (partial: the folder is very large)"}
        </p>
      </div>

      <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="min-w-0">
          <h3 className="text-[13px] font-extrabold">By folder</h3>
          <ul aria-label="Storage by folder" className="mt-1 flex flex-col gap-1.5">
            {overview.folders.map((f) => (
              <li key={f.folder || "(root)"} className="min-w-0 text-[13px]">
                <div className="flex min-w-0 justify-between gap-2">
                  <span className="min-w-0 truncate font-semibold">{f.folder || "Top level"}</span>
                  <span className="shrink-0 tabular-nums text-muted">
                    {count(f.files, "file")} · {bytes(f.bytes)}
                  </span>
                </div>
                <div aria-hidden="true" className="mt-0.5 h-1.5 rounded-full bg-ground">
                  <div className="h-1.5 rounded-full bg-teal" style={{ width: `${Math.max(2, (f.bytes / biggest) * 100)}%` }} />
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div className="min-w-0">
          <h3 className="text-[13px] font-extrabold">By tax year</h3>
          <ul aria-label="Storage by tax year" className="mt-1 flex flex-col gap-1.5">
            {overview.years.map((y) => (
              <li key={y.year} className="flex min-w-0 justify-between gap-2 text-[13px]">
                <span className="font-semibold">{y.year}</span>
                <span className="shrink-0 tabular-nums text-muted">
                  {count(y.files, "document")} · {bytes(y.bytes)}
                  {y.archived_files > 0 && ` · ${y.archived_files} archived`}
                </span>
              </li>
            ))}
            {overview.years.length === 0 && <li className="text-[13px] text-muted">No documents yet.</li>}
          </ul>
        </div>
      </div>

      {overview.largest.length > 0 && (
        <details className="min-w-0">
          <summary className="min-h-11 cursor-pointer py-2 text-[13px] font-extrabold">Largest documents</summary>
          <ol aria-label="Largest documents" className="flex flex-col">
            {overview.largest.map((f) => (
              <li key={f.path} className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 border-t border-border py-1.5 text-[13px]">
                <span className="min-w-0 flex-1 break-all font-semibold">{f.path}</span>
                <span className="shrink-0 tabular-nums text-muted">{bytes(f.size)}</span>
                <ShowInOneDrive url={f.web_url} name={f.name} />
              </li>
            ))}
          </ol>
        </details>
      )}

      <div className="min-w-0 border-t border-border pt-3">
        <h3 className="text-[13px] font-extrabold">Clean up</h3>
        {overview.duplicates.length === 0 ? (
          <p className="text-[13px] text-muted">No duplicate files found.</p>
        ) : (
          <>
            <p className="text-[13px] text-muted">
              {count(overview.duplicates.length, "set")} of identical files. Ticked copies move to _Trash — nothing is
              deleted, and the copy your books link to always stays.
            </p>
            <ul aria-label="Duplicate files" className="mt-2 flex flex-col gap-2">
              {overview.duplicates.map((g) => (
                <li key={g.hash} className="min-w-0 rounded-xl border border-border p-2">
                  <p className="text-[12px] font-bold text-muted">
                    {count(g.files.length, "copy", "copies")} · {bytes(g.size)} each
                  </p>
                  <ul className="flex flex-col">
                    {g.files.map((f) => {
                      const locked = f.keep || f.linked || f.protected;
                      return (
                        <li key={f.path} className="flex min-w-0 flex-wrap items-center gap-x-2 text-[13px]">
                          <label className="flex min-h-11 min-w-0 flex-1 items-center gap-2">
                            <input
                              type="checkbox"
                              className="h-5 w-5 shrink-0"
                              checked={!locked && picked.has(f.path)}
                              disabled={locked}
                              onChange={() => toggle(f.path)}
                              aria-label={`Move to _Trash: ${f.path}`}
                            />
                            <span className="min-w-0 break-all">{f.path}</span>
                          </label>
                          {locked && (
                            <span className="shrink-0 rounded-full bg-teal-tint px-2 py-0.5 text-[12px] font-bold text-teal-dark">
                              {f.linked ? "kept: in your books" : "kept"}
                            </span>
                          )}
                          <ShowInOneDrive url={f.web_url} name={f.path} />
                        </li>
                      );
                    })}
                  </ul>
                </li>
              ))}
            </ul>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <button type="button" className={primary} disabled={busy || picked.size === 0} onClick={cleanUp}>
                {busy ? "Moving…" : `Move ${count(picked.size, "copy", "copies")} to _Trash`}
              </button>
              <span className="text-[13px] tabular-nums text-muted">Frees up to {bytes(overview.duplicate_bytes)}</span>
            </div>
          </>
        )}
        {note && (
          <p role="status" className="mt-2 text-sm font-semibold text-teal-dark">
            {note}
          </p>
        )}
      </div>
    </section>
  );
}
