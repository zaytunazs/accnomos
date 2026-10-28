"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import {
  BANK_FEED_KEY,
  BANK_FEED_SYNCED,
  runtime,
  ukDate,
  type RtFeedConnection,
  type RtFeedStatus,
  type RtFeedSync,
} from "@/lib/runtime";
import { SYNCED_AT_KEY } from "@/components/bank/BankFeedOnOpen";

/** Between "Connect" and TrueLayer sending the browser back: a secret only this tab knows (its hash is in the signed
 *  state), so a bank sign-in started in another browser cannot attach a feed to these books. */
const PENDING_KEY = "accnomos.bankFeed.pending";

const button = "h-10 whitespace-nowrap rounded-xl border border-border bg-white px-4 text-sm font-bold text-ink hover:bg-ground disabled:opacity-60";
const primary = "h-10 whitespace-nowrap rounded-xl bg-teal px-4 text-sm font-bold text-white hover:bg-teal-dark disabled:opacity-60";

function hex(bytes: ArrayBuffer | Uint8Array): string {
  return Array.from(new Uint8Array(bytes), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function sha256(text: string): Promise<string> {
  return hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)));
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

/** "Fetched from your bank feed: 3 new lines (3 already in a statement)." */
export function syncSentence(r: RtFeedSync): string {
  const extra = r.already_imported > 0 ? ` (${plural(r.already_imported, "line")} already in a statement, left out)` : "";
  const errors = r.connections.filter((c) => c.error).map((c) => c.error);
  return `Fetched from your bank feed: ${plural(r.new_lines, "new line")}${extra}.${errors.length ? ` ${errors.join(" ")}` : ""}`;
}

function remember(status: RtFeedStatus) {
  try {
    if (status.connections.length > 0) window.localStorage.setItem(BANK_FEED_KEY, "1");
    else window.localStorage.removeItem(BANK_FEED_KEY);
  } catch {
    /* storage unavailable: the feed is still fetched from this page */
  }
}

function SandboxBadge() {
  return (
    <span className="rounded-full bg-warn-bg px-2 py-0.5 text-[11px] font-extrabold uppercase tracking-wide text-warn-ink">
      Sandbox
    </span>
  );
}

/** Bank › Bank feed: connect a bank through TrueLayer (Open Banking, read only), reconfirm the 90-day consent, fetch. */
export default function BankFeeds({ account, onSynced }: { account: AccountInfo | null; onSynced: () => void }) {
  const [status, setStatus] = useState<RtFeedStatus | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const handled = useRef(false);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      const got = await runtime.bankFeeds.status(account);
      setStatus(got);
      remember(got);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [account]);

  const sync = useCallback(
    async (acct: AccountInfo) => {
      setBusy("sync");
      try {
        window.sessionStorage.setItem(SYNCED_AT_KEY, String(Date.now())); // the app-open fetch need not repeat it
        setNote(syncSentence(await runtime.bankFeeds.sync(acct)));
        setError(null);
        onSynced();
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(null);
        await load();
      }
    },
    [load, onSynced],
  );

  // The app's own fetch on open (BankFeedOnOpen) finished: show what it found and reload the lines.
  useEffect(() => {
    const on = (e: Event) => {
      setNote(syncSentence((e as CustomEvent<RtFeedSync>).detail));
      onSynced();
      void load();
    };
    window.addEventListener(BANK_FEED_SYNCED, on);
    return () => window.removeEventListener(BANK_FEED_SYNCED, on);
  }, [load, onSynced]);

  // Back from the bank: /bank#feed=truelayer&code=…&state=… (the runtime's callback put them there).
  useEffect(() => {
    if (!account || handled.current) return;
    const p = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    if (p.get("feed") !== "truelayer") {
      queueMicrotask(load);
      return;
    }
    handled.current = true;
    // Off the address bar at once, so a reload or a bookmark never replays it.
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    let binding: string | null = null;
    try {
      binding = window.sessionStorage.getItem(PENDING_KEY);
      window.sessionStorage.removeItem(PENDING_KEY);
    } catch {
      /* storage unavailable */
    }
    (async () => {
      try {
        if (p.get("error")) throw new Error(p.get("error_description") || `Your bank did not connect (${p.get("error")}).`);
        if (!binding) throw new Error("This bank sign-in was not started here. Connect again.");
        const got = await runtime.bankFeeds.connect(account, { code: p.get("code") ?? "", state: p.get("state") ?? "", binding });
        setStatus(got);
        remember(got);
        setError(null);
        await sync(account);
      } catch (e) {
        setError((e as Error).message);
        await load();
      }
    })();
  }, [account, load, sync]);

  async function connect() {
    if (!account) return;
    setBusy("connect");
    setError(null);
    try {
      const binding = hex(crypto.getRandomValues(new Uint8Array(32)));
      const { url } = await runtime.bankFeeds.start(account, {
        redirect_to: `${window.location.origin}/bank`,
        binding_hash: await sha256(binding),
      });
      window.sessionStorage.setItem(PENDING_KEY, binding);
      window.location.assign(url);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  async function reconfirm(c: RtFeedConnection) {
    if (!account) return;
    setBusy(c.id);
    try {
      const got = await runtime.bankFeeds.reconfirm(account, c.id);
      setNote(got.message);
      setError(null);
      if (got.reauthorise) await connect();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
      await load();
    }
  }

  async function disconnect(c: RtFeedConnection) {
    if (!account) return;
    setBusy(c.id);
    try {
      const got = await runtime.bankFeeds.disconnect(account, c.id);
      setStatus(got.status);
      remember(got.status);
      setConfirming(null);
      setNote(got.warning ?? `${c.bank} disconnected. Lines already fetched stay in your books.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (!status) return null;
  const sandbox = status.sandbox ? " (sandbox)" : "";
  return (
    <section id="bank-feed" aria-label="Bank feed" className="scroll-mt-4 rounded-2xl border border-border bg-white p-5">
      <h2 className="flex flex-wrap items-center gap-2 text-lg font-extrabold">
        Bank feed {status.available && status.sandbox && <SandboxBadge />}
      </h2>
      {!status.available ? (
        <p className="mt-1 text-sm text-muted">{status.reason}</p>
      ) : status.connections.length === 0 ? (
        <div className="mt-1 flex flex-wrap items-center justify-between gap-3">
          <p className="min-w-0 text-sm text-muted">
            Connect your bank through {status.provider} (Open Banking, read only: it cannot move money). Transactions
            are fetched when you open the app. Your OneDrive keeps only the consent dates and a key sealed by our
            server; consent lasts 90 days and you reconfirm it here.
          </p>
          <button type="button" className={primary} disabled={busy !== null} onClick={connect}>
            {busy === "connect" ? "Opening…" : `Connect a bank${sandbox}`}
          </button>
        </div>
      ) : (
        <ul className="mt-2 divide-y divide-border">
          {status.connections.map((c) => (
            <li key={c.id} className="py-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[15px] font-bold text-ink">{c.bank}</p>
                  <p className="text-sm text-muted">
                    {c.accounts.map((a) => `${a.name}${a.last4 ? ` ····${a.last4}` : ""}`).join(", ") || "No accounts shared"}
                  </p>
                  <p className={`text-sm ${c.state === "ok" ? "text-muted" : "font-semibold text-warn-ink"}`}>{c.message}</p>
                  <p className="text-sm text-muted">
                    {c.last_synced_at ? `Last fetched ${ukDate(c.last_synced_at.slice(0, 10))}.` : "Not fetched yet."}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {(c.state === "ok" || c.state === "reconfirm") && (
                    <button type="button" className={button} disabled={busy !== null} onClick={() => account && sync(account)}>
                      {busy === "sync" ? "Fetching…" : "Fetch now"}
                    </button>
                  )}
                  {(c.state === "expired" || c.state === "key_changed") && (
                    <button type="button" className={primary} disabled={busy !== null} onClick={connect}>
                      Connect again
                    </button>
                  )}
                  {confirming !== c.id && (
                    <button type="button" className={button} disabled={busy !== null} onClick={() => setConfirming(c.id)}>
                      Disconnect
                    </button>
                  )}
                </div>
              </div>
              {c.state === "reconfirm" && (
                <div role="group" aria-label={`Reconfirm ${c.bank}`} className="mt-2 flex flex-wrap items-center gap-2 rounded-xl border border-warn-border bg-warn-bg p-3 text-sm text-warn-ink">
                  <span className="min-w-0 flex-1">
                    Keep sharing {c.bank} with Accnomos for another 90 days? Accnomos reads balances and transactions
                    only. You can stop at any time here or in your bank&apos;s app.
                  </span>
                  <button type="button" className={primary} disabled={busy !== null} onClick={() => reconfirm(c)}>
                    Reconfirm for 90 days
                  </button>
                </div>
              )}
              {confirming === c.id && (
                <div className="mt-2 flex flex-wrap items-center gap-2 rounded-xl bg-ground p-3 text-sm">
                  <span>Disconnect {c.bank}? Lines already fetched stay; nothing new is read.</span>
                  <button type="button" className={primary} disabled={busy !== null} onClick={() => disconnect(c)}>
                    Yes, disconnect {c.bank}
                  </button>
                  <button type="button" className={button} onClick={() => setConfirming(null)}>
                    Cancel
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {note && (
        <p role="status" className="mt-2 text-sm font-semibold text-teal-dark">
          {note}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm font-semibold text-red-700">
          {error}
        </p>
      )}
      <p className="mt-2 text-xs text-muted">No feed, or your bank isn&apos;t listed? Upload a statement CSV below; lines already fetched are left out.</p>
    </section>
  );
}
