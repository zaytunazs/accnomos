"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import StatusBadge from "@/components/StatusBadge";
import { runtime, ukDate, type RtEbayStatus, type RtEbaySync } from "@/lib/runtime";

/** Between "Connect eBay" and eBay sending the browser back: a secret only this tab knows (its hash is in the signed
 *  state), so an eBay sign-in started in another browser cannot attach to these books. */
const PENDING_KEY = "accnomos.ebay.pending";

const button = "h-10 whitespace-nowrap rounded-xl border border-border bg-white px-4 text-sm font-bold text-ink hover:bg-ground disabled:opacity-60";
const primary = "h-10 whitespace-nowrap rounded-xl bg-teal px-4 text-sm font-bold text-white hover:bg-teal-dark disabled:opacity-60";

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const pounds = (p: number) => `£${(p / 100).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function hex(bytes: ArrayBuffer | Uint8Array): string {
  return Array.from(new Uint8Array(bytes), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function sha256(text: string): Promise<string> {
  return hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)));
}

const typeName = (t: string) => t.toLowerCase().replace(/_/g, " ");

/** "Proposed from eBay: 2 sales, 1 refund, 3 selling fees, 2 ad fees, 1 postage label, 1 payout; 5 already imported;
 *  not imported (book by hand): 1 adjustment." */
export function ebaySentence(
  r: Pick<RtEbaySync, "sales" | "refunds" | "fees" | "ad_fees" | "postage" | "payouts" | "already_imported" | "skipped" | "skipped_types">,
): string {
  const parts = [
    plural(r.sales, "sale"),
    plural(r.refunds, "refund"),
    plural(r.fees, "selling fee"),
    plural(r.ad_fees ?? 0, "ad fee"),
    plural(r.postage, "postage label"),
    plural(r.payouts, "payout"),
  ];
  const types = Object.entries(r.skipped_types ?? {});
  const extra = [
    ...(r.already_imported ? [`${r.already_imported} already imported`] : []),
    ...(types.length
      ? [`not imported (book by hand): ${types.map(([t, n]) => `${n} ${typeName(t)}`).join(", ")}`]
      : r.skipped
        ? [`${r.skipped} not imported (book by hand)`]
        : []),
  ];
  return `Proposed from eBay: ${parts.join(", ")}${extra.length ? `; ${extra.join(", ")}` : ""}.`;
}

/** Bank › eBay: connect the seller's eBay account; its sales, fees and payouts become proposals on Review. */
export default function EbayConnect({ account, onSynced }: { account: AccountInfo | null; onSynced: () => void }) {
  const [status, setStatus] = useState<RtEbayStatus | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [vrn, setVrn] = useState("");
  const handled = useRef(false);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      const got = await runtime.ebay.status(account);
      setStatus(got);
      setVrn(got.fee_vat_number ?? "");
    } catch {
      setStatus(null); // an older runtime without /books/ebay: no card
    }
  }, [account]);

  const sync = useCallback(
    async (acct: AccountInfo) => {
      setBusy("sync");
      try {
        const got = await runtime.ebay.sync(acct);
        setNote(`${ebaySentence(got)}${got.warning ? ` ${got.warning}` : ""}`);
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

  // Back from eBay: /bank#feed=ebay&code=…&state=… (the runtime's callback put them there).
  useEffect(() => {
    if (!account || handled.current) return;
    const p = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    if (p.get("feed") !== "ebay") {
      queueMicrotask(load);
      return;
    }
    handled.current = true;
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
        if (p.get("error")) throw new Error(p.get("error_description") || `eBay did not connect (${p.get("error")}).`);
        if (!binding) throw new Error("This eBay sign-in was not started here. Connect again.");
        setStatus(await runtime.ebay.complete(account, { code: p.get("code") ?? "", state: p.get("state") ?? "", binding }));
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
      const { url } = await runtime.ebay.connect(account, { redirect_to: `${window.location.origin}/bank`, binding_hash: await sha256(binding) });
      window.sessionStorage.setItem(PENDING_KEY, binding);
      window.location.assign(url);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  async function disconnect() {
    if (!account) return;
    setBusy("disconnect");
    try {
      const got = await runtime.ebay.disconnect(account);
      setStatus(got.status);
      setConfirming(false);
      setNote(got.message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function saveVrn() {
    if (!account) return;
    setBusy("vrn");
    try {
      const got = await runtime.ebay.settings(account, vrn.trim() || null);
      setStatus(got);
      setNote(got.fee_vat_number ? "eBay's VAT number saved: VAT on fees imported from now on is reclaimed." : "eBay's VAT number removed.");
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (!status || !status.configured) return null; // no eBay keyset on this server: nothing to show
  const waiting = status.payouts.filter((p) => !p.matched);
  return (
    <section id="ebay" aria-label="eBay" className="scroll-mt-4 rounded-2xl border border-border bg-white p-5">
      <h2 className="flex flex-wrap items-center gap-2 text-lg font-extrabold">
        eBay{" "}
        {status.sandbox && (
          <StatusBadge tone="warning" className="uppercase tracking-wide">
            Sandbox
          </StatusBadge>
        )}
      </h2>
      {!status.connected ? (
        <div className="mt-1 flex flex-wrap items-center justify-between gap-3">
          <p className="min-w-0 text-sm text-muted">
            Sign in with your eBay seller account and Accnomos fetches your sales, refunds, fees, postage labels and
            payouts (read only). Each one waits on Review for you to approve; nothing is posted on its own.
          </p>
          <button type="button" className={primary} disabled={busy !== null} onClick={connect}>
            {busy === "connect" ? "Opening…" : "Connect eBay"}
          </button>
        </div>
      ) : (
        <div className="mt-1">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 text-sm text-muted">
              {status.message && <p className="font-semibold text-warn-ink">{status.message}</p>}
              <p>
                {status.last_synced_at ? `Last synced ${ukDate(status.last_synced_at.slice(0, 10))}.` : "Not synced yet."}
                {status.connected_at ? ` Connected ${ukDate(status.connected_at.slice(0, 10))}.` : ""}
              </p>
              {status.last_summary && <p data-testid="ebay-summary">{ebaySentence(status.last_summary)}</p>}
            </div>
            <div className="flex flex-wrap gap-2">
              {status.state === "ok" ? (
                <button type="button" className={button} disabled={busy !== null} onClick={() => account && sync(account)}>
                  {busy === "sync" ? "Syncing…" : "Sync now"}
                </button>
              ) : (
                <button type="button" className={primary} disabled={busy !== null} onClick={connect}>
                  Reconnect eBay
                </button>
              )}
              {!confirming && (
                <button type="button" className={button} disabled={busy !== null} onClick={() => setConfirming(true)}>
                  Disconnect
                </button>
              )}
            </div>
          </div>
          {confirming && (
            <div className="mt-2 flex flex-wrap items-center gap-2 rounded-xl bg-ground p-3 text-sm">
              <span>Disconnect eBay? Proposals and postings already made stay; nothing new is fetched.</span>
              <button type="button" className={primary} disabled={busy !== null} onClick={disconnect}>
                Yes, disconnect eBay
              </button>
              <button type="button" className={button} onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </div>
          )}
          <p className="mt-2 text-sm text-muted">
            Sync reads the last 90 days. Approve the proposals on{" "}
            <Link href="/review" className="font-bold text-teal-dark underline underline-offset-2">
              Review
            </Link>
            ; when a payout reaches your bank, choose “Payout from eBay” on that bank line.
          </p>
          {waiting.length > 0 && (
            <p className="mt-1 text-sm text-muted">
              eBay payouts waiting for their bank line:{" "}
              {waiting.map((p) => `${pounds(p.amount_pence)} on ${ukDate(p.date)}${p.last4 ? ` to ····${p.last4}` : ""}`).join("; ")}.
            </p>
          )}
          <form
            className="mt-3 flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void saveVrn();
            }}
          >
            <label className="flex min-w-0 flex-col text-sm">
              <span className="font-semibold text-ink">eBay&apos;s VAT number (from eBay&apos;s VAT invoice for your fees)</span>
              <input
                value={vrn}
                onChange={(e) => setVrn(e.target.value)}
                placeholder="GB 123 4567 89"
                maxLength={20}
                className="mt-1 h-10 rounded-xl border border-border px-3"
              />
            </label>
            <button type="submit" className={button} disabled={busy !== null}>
              {busy === "vrn" ? "Saving…" : "Save"}
            </button>
          </form>
          <p className="mt-1 text-xs text-muted">
            Without it, VAT on eBay&apos;s fees stays in the cost. With it, fees are proposed with 20% VAT to reclaim;
            check them against eBay&apos;s monthly VAT invoice.
          </p>
        </div>
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
    </section>
  );
}
