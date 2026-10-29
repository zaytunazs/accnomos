"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import { useAccount } from "@/components/jobs/useAccount";
import { bytes, card, count, day, primary, reason, secondary } from "@/components/files/manage";
import { filesApi, runtime, type RtPreviousFiles } from "@/lib/runtime";

/** Home's "Not now" for the earlier-files prompt, per account in this browser (the list stays on the Files page). */
const SNOOZE = "accnomos.previous-files.snoozed";

function snoozedCount(id: string): number | null {
  try {
    const v = (JSON.parse(window.localStorage.getItem(SNOOZE) ?? "{}") as Record<string, number>)[id];
    return typeof v === "number" ? v : null;
  } catch {
    return null;
  }
}

function snooze(id: string, n: number): void {
  try {
    const all = JSON.parse(window.localStorage.getItem(SNOOZE) ?? "{}") as Record<string, number>;
    window.localStorage.setItem(SNOOZE, JSON.stringify({ ...all, [id]: n }));
  } catch {
    /* the prompt just shows again next time */
  }
}

/** Run the usual Inbox scan until the queued files are read (10 a call, as Review's scan does). */
async function readInbox(account: AccountInfo, queued: number): Promise<{ proposals: number; errors: number }> {
  let proposals = 0;
  let errors = 0;
  for (let round = 0; round < Math.ceil(queued / 10) + 1 && proposals + errors < queued; round++) {
    const r = await runtime.scan(account);
    proposals += r.proposals.length;
    errors += r.errors.length;
    if (r.proposals.length === 0) break;
  }
  return { proposals, errors };
}

/**
 * Earlier files (services/runtime/app/previous_files.py): documents already in 00 Inbox, 01 Receipts or 02 Needs a
 * look that Accnomos never read. The list, with the ones to read ticked; nothing is read until the user presses
 * "Read the ticked files". Each becomes a Review card to approve, as usual. "Leave them" stops offering them.
 */
export default function PreviousFiles({ account, onChanged }: { account: AccountInfo; onChanged?: () => void }) {
  const [found, setFound] = useState<RtPreviousFiles | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const look = useCallback(async () => {
    try {
      const r = await filesApi.previousFiles(account);
      setFound(r);
      setTicked(new Set(r.files.map((f) => f.path)));
    } catch (e) {
      setNote(`Could not look for earlier files: ${reason(e)}`);
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(() => void look());
  }, [look]);

  async function readThem() {
    const paths = [...ticked];
    setBusy(true);
    setNote(`Reading ${count(paths.length, "file")}…`);
    try {
      const q = await filesApi.queuePrevious(account, paths);
      const r = await readInbox(account, q.queued);
      setNote(
        `${count(r.proposals, "file")} read: each is a card in Review for you to check and approve.` +
          (r.errors ? ` ${count(r.errors, "file")} could not be read and stay in 00 Inbox.` : ""),
      );
      onChanged?.();
      await look();
    } catch (e) {
      setNote(`Could not read them: ${reason(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function leaveThem() {
    const paths = [...ticked];
    setBusy(true);
    try {
      const r = await filesApi.leavePrevious(account, paths);
      setNote(`Left ${count(r.left, "file")} where ${r.left === 1 ? "it is" : "they are"}; Accnomos will not offer ${r.left === 1 ? "it" : "them"} again.`);
      await look();
    } catch (e) {
      setNote(`Could not do that: ${reason(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const all = found?.files ?? [];
  return (
    <section aria-labelledby="previous-files-heading" className={card} id="previous-files">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 id="previous-files-heading" className="text-[15px] font-extrabold">
            Earlier files not read yet
          </h2>
          <p className="text-[13px] text-muted">
            Documents already in your Inbox, Receipts or Needs a look folders that Accnomos has not read: left from an
            earlier session or put there by hand. Nothing is read until you say so; each one you choose becomes a Review
            card for you to approve.
          </p>
        </div>
        <button type="button" className={secondary} disabled={busy} onClick={() => void look()}>
          Look again
        </button>
      </div>
      {note && (
        <p role="status" className="text-sm font-semibold text-teal-dark">
          {note}
        </p>
      )}
      {found === null ? (
        <p className="text-[13px] text-muted">Looking in your OneDrive…</p>
      ) : all.length === 0 ? (
        <p className="text-[13px] text-muted">
          No earlier files waiting.{found.left_alone ? ` ${count(found.left_alone, "file")} you chose to leave alone.` : ""}
        </p>
      ) : (
        <>
          <fieldset className="min-w-0">
            <legend className="sr-only">Earlier files to read</legend>
            <ul aria-label="Earlier files" className="flex min-w-0 flex-col">
              {all.map((f) => (
                <li key={f.path} className="border-t border-border first:border-t-0">
                  <label className="flex min-h-11 min-w-0 items-center gap-3 py-1.5 text-[14px]">
                    <input
                      type="checkbox"
                      className="h-5 w-5 shrink-0"
                      checked={ticked.has(f.path)}
                      disabled={busy}
                      onChange={(e) =>
                        setTicked((prev) => {
                          const next = new Set(prev);
                          if (e.target.checked) next.add(f.path);
                          else next.delete(f.path);
                          return next;
                        })
                      }
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block break-all font-semibold">{f.name}</span>
                      <span className="block text-[12px] text-muted">
                        {f.folder} · {bytes(f.size)}
                        {f.modified ? ` · ${day(f.modified)}` : ""}
                      </span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </fieldset>
          <div className="flex flex-wrap gap-2">
            <button type="button" className={primary} disabled={busy || ticked.size === 0} onClick={readThem}>
              Read the ticked files ({ticked.size})
            </button>
            <button type="button" className={secondary} disabled={busy || ticked.size === 0} onClick={leaveThem}>
              Leave them
            </button>
          </div>
        </>
      )}
    </section>
  );
}

/**
 * Home: the count of earlier files, with the way to the list. Shown after the first connect and whenever there are
 * new ones; "Not now" hides it until the count changes.
 */
export function PreviousFilesNotice() {
  const account = useAccount();
  const [n, setN] = useState<number | null>(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    if (!account) return;
    let stale = false;
    filesApi.previousFiles(account).then(
      (r) => {
        if (stale) return;
        setN(r.count);
        setHidden(snoozedCount(account.homeAccountId) === r.count);
      },
      () => undefined, // the Files page says why; Home stays calm
    );
    return () => {
      stale = true;
    };
  }, [account]);

  if (!account || !n || hidden) return null;
  return (
    <section
      aria-labelledby="previous-files-notice"
      className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-white px-4 py-3"
    >
      <div className="min-w-0 flex-1">
        <h2 id="previous-files-notice" className="text-[15px] font-extrabold text-ink">
          {count(n, "earlier file")} in your OneDrive not read yet
        </h2>
        <p className="text-sm text-muted">Accnomos found documents it has not read. Choose which to read; nothing happens until you do.</p>
      </div>
      <span className="flex shrink-0 flex-wrap items-center gap-2">
        <Link href="/files#previous-files" className={`${primary} inline-flex items-center`}>
          See the list
        </Link>
        <button
          type="button"
          className="min-h-11 rounded-xl px-3 text-sm font-bold text-teal-dark hover:bg-ground"
          onClick={() => {
            snooze(account.homeAccountId, n);
            setHidden(true);
          }}
        >
          Not now
        </button>
      </span>
    </section>
  );
}
