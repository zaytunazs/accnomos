"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getMsal, msalConfigured } from "@/lib/msal";
import { BANK_FEED_KEY, BANK_FEED_SYNCED, runtime, type RtFeedConnection } from "@/lib/runtime";

/** sessionStorage: when this tab last fetched the feed (ms). At most once an hour per tab. */
export const SYNCED_AT_KEY = "accnomos.bankFeed.syncedAt";
const EVERY_MS = 60 * 60 * 1000;

/**
 * Bank feeds (services/runtime/app/bank_feeds.py) are fetched when the app is opened: there is no server running per
 * user and a webhook would arrive without the user's Graph token. Only on a device where the Bank page saw a feed
 * (BANK_FEED_KEY). Shows a strip when a consent needs reconfirming or has ended; otherwise renders nothing. A failed
 * fetch is silent here (the Bank page shows its errors) and tried again next time.
 */
export default function BankFeedOnOpen() {
  const [due, setDue] = useState<RtFeedConnection[]>([]);

  useEffect(() => {
    try {
      if (window.localStorage.getItem(BANK_FEED_KEY) !== "1") return;
    } catch {
      return;
    }
    void (async () => {
      try {
        if (!msalConfigured()) return;
        const msal = await getMsal();
        const account = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
        if (!account) return;
        const status = await runtime.bankFeeds.status(account);
        if (status.connections.length === 0) {
          window.localStorage.removeItem(BANK_FEED_KEY);
          return;
        }
        setDue(status.connections.filter((c) => c.state !== "ok"));
        const last = Number(window.sessionStorage.getItem(SYNCED_AT_KEY) ?? "0");
        if (!status.available || Date.now() - last < EVERY_MS) return;
        if (!status.connections.some((c) => c.state === "ok" || c.state === "reconfirm")) return;
        window.sessionStorage.setItem(SYNCED_AT_KEY, String(Date.now()));
        const got = await runtime.bankFeeds.sync(account);
        window.dispatchEvent(new CustomEvent(BANK_FEED_SYNCED, { detail: got }));
      } catch {
        /* next app open tries again */
      }
    })();
  }, []);

  if (due.length === 0) return null;
  const first = due[0];
  return (
    <div role="note" aria-label="Bank feed" className="border-b border-warn-border bg-warn-bg px-4 py-2 text-sm font-semibold text-warn-ink print:hidden">
      {first.bank}: {first.message}{" "}
      <Link href="/bank#bank-feed" className="underline underline-offset-2">
        {first.state === "reconfirm" ? "Reconfirm on Bank" : "Connect again on Bank"}
      </Link>
    </div>
  );
}
