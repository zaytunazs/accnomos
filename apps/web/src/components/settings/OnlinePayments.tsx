"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useMsAccount } from "@/lib/invoices";
import { runtime, type RtPayProvider, type RtProviderStatus } from "@/lib/runtime";
import { RuntimeErrorNote } from "@/components/States";

/** Between "Connect" and the provider sending the browser back: a secret only this tab knows (its hash is in the
 *  signed state), so a sign-in started in another browser cannot link an account to these books. */
const PENDING_KEY = "accnomos.pay.pending";

const input = "mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px] text-ink";
const button = "h-10 whitespace-nowrap rounded-xl border border-border bg-white px-4 text-sm font-bold text-ink hover:bg-ground disabled:opacity-60";
const primary = "h-10 whitespace-nowrap rounded-xl bg-teal px-4 text-sm font-bold text-white hover:bg-teal-dark disabled:opacity-60";

function hex(bytes: ArrayBuffer | Uint8Array): string {
  return Array.from(new Uint8Array(bytes), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function sha256(text: string): Promise<string> {
  return hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)));
}

function readPending(): { provider: string; binding: string } | null {
  try {
    const raw = window.sessionStorage.getItem(PENDING_KEY);
    return raw ? (JSON.parse(raw) as { provider: string; binding: string }) : null;
  } catch {
    return null;
  }
}

export function TestModeBadge() {
  return (
    <span className="rounded-full bg-warn-bg px-2 py-0.5 text-[11px] font-extrabold uppercase tracking-wide text-warn-ink">
      Test mode
    </span>
  );
}

/** Settings › Business › Online payments: link the user's own Stripe or PayPal, or a PayPal.me name. */
export default function OnlinePayments({ card, heading }: { card: string; heading: string }) {
  const { account, ready } = useMsAccount();
  const [rows, setRows] = useState<RtProviderStatus[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState<RtPayProvider | null>(null);
  const [confirming, setConfirming] = useState<RtPayProvider | null>(null);
  const [username, setUsername] = useState("");
  const handled = useRef(false);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      const got = await runtime.payProviders(account);
      setRows(got);
      setUsername((u) => u || (got.find((r) => r.provider === "paypalme")?.account ?? ""));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [account]);

  // Back from Stripe or PayPal: /settings#pay=stripe&code=…&state=… (the runtime's callback put them there).
  useEffect(() => {
    if (!account || handled.current) return;
    const p = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const provider = p.get("pay");
    if (provider !== "stripe" && provider !== "paypal") {
      queueMicrotask(load);
      return;
    }
    handled.current = true;
    // Off the address bar at once, so a reload or a bookmark never replays it.
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    const pending = readPending();
    try {
      window.sessionStorage.removeItem(PENDING_KEY);
    } catch {
      /* storage unavailable */
    }
    (async () => {
      const label = provider === "stripe" ? "Stripe" : "PayPal";
      try {
        if (p.get("error")) throw new Error(p.get("error_description") || `${label} did not connect (${p.get("error")}).`);
        if (!pending || pending.provider !== provider) throw new Error(`This ${label} sign-in was not started here. Connect again.`);
        const state = p.get("state") ?? "";
        const next =
          provider === "stripe"
            ? await runtime.payConnectStripe(account, { code: p.get("code") ?? "", state, binding: pending.binding })
            : await runtime.payConnectPaypal(account, { merchant_id: p.get("merchant_id") ?? "", state, binding: pending.binding });
        setRows(next);
        setNote(`${label} connected. You can add a payment link to an invoice now.`);
        setError(null);
      } catch (e) {
        setError((e as Error).message);
        await load();
      }
    })();
  }, [account, load]);

  async function connect(provider: "stripe" | "paypal") {
    if (!account) return;
    setBusy(provider);
    setError(null);
    try {
      const binding = hex(crypto.getRandomValues(new Uint8Array(32)));
      const { url } = await runtime.payStart(account, provider, {
        redirect_to: `${window.location.origin}/settings`,
        binding_hash: await sha256(binding),
      });
      window.sessionStorage.setItem(PENDING_KEY, JSON.stringify({ provider, binding }));
      window.location.assign(url);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  async function disconnect(provider: RtPayProvider) {
    if (!account) return;
    setBusy(provider);
    try {
      const out = await runtime.payDisconnect(account, provider);
      setRows(out.providers);
      setNote(out.warning ?? "Disconnected.");
      setConfirming(null);
      if (provider === "paypalme") setUsername("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function savePaypalMe() {
    if (!account) return;
    setBusy("paypalme");
    try {
      setRows(await runtime.paySetPaypalMe(account, username));
      setNote("PayPal.me name saved.");
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const row = (p: RtPayProvider) => rows?.find((r) => r.provider === p);

  function providerRow(p: "stripe" | "paypal") {
    const r = row(p);
    if (!r) return null;
    return (
      <div key={p} className="py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="flex flex-wrap items-center gap-2 text-[15px] font-bold text-ink">
              {r.label} {r.available && r.test_mode && <TestModeBadge />}
            </p>
            <p className="text-sm text-muted">
              {!r.available
                ? r.reason
                : r.connected
                  ? `Connected: ${r.account}. Payments through its links are found when you open Invoices.`
                  : p === "stripe"
                    ? "Link your own Stripe account. Customers pay by card; the money goes to your Stripe."
                    : "Link your own PayPal business account. Customers pay through a PayPal invoice."}
            </p>
          </div>
          {r.available && !r.connected && (
            <button type="button" className={primary} disabled={busy !== null} onClick={() => connect(p)}>
              {busy === p ? "Opening…" : `Connect ${r.label}${r.test_mode ? " (test mode)" : ""}`}
            </button>
          )}
          {r.connected && confirming !== p && (
            <button type="button" className={button} disabled={busy !== null} onClick={() => setConfirming(p)}>
              Disconnect
            </button>
          )}
        </div>
        {confirming === p && (
          <div className="mt-2 flex flex-wrap items-center gap-2 rounded-xl bg-ground p-3 text-sm">
            <span>Disconnect {r.label}? Links already on invoices keep working in your {r.label} account.</span>
            <button type="button" className={primary} disabled={busy !== null} onClick={() => disconnect(p)}>
              Yes, disconnect {r.label}
            </button>
            <button type="button" className={button} onClick={() => setConfirming(null)}>
              Cancel
            </button>
          </div>
        )}
      </div>
    );
  }

  const me = row("paypalme");
  return (
    <section id="settings-payments" aria-labelledby="settings-payments-title" className={`${card} scroll-mt-4`}>
      <h2 id="settings-payments-title" className={heading}>
        Online payments
      </h2>
      <p className="mt-1 text-sm text-muted">
        Put a &ldquo;Pay online&rdquo; link on your invoices, paid into your own Stripe or PayPal account. Accnomos keeps
        only the account id in your OneDrive, never a password or key. A payment that comes in is shown for you to
        approve; the provider&apos;s fee goes in as its own expense.
      </p>
      {ready && !account && <p className="mt-3 text-sm text-muted">Sign in to connect a payment account.</p>}
      {error && (
        <div className="mt-3">
          <RuntimeErrorNote message={error} title="Online payments" />
        </div>
      )}
      {note && (
        <p role="status" className="mt-3 rounded-xl bg-teal-tint px-4 py-3 text-sm font-bold text-teal-dark">
          {note}
        </p>
      )}
      {account && rows && (
        <div className="mt-2 divide-y divide-border">
          {providerRow("stripe")}
          {providerRow("paypal")}
          {me && (
            <div className="py-3">
              <p className="text-[15px] font-bold text-ink">PayPal.me</p>
              <p className="text-sm text-muted">
                No account linking: the link asks for the amount in pounds. PayPal cannot tell Accnomos about these
                payments, so record them yourself when they arrive. Real money, there is no test mode.
              </p>
              <div className="mt-2 flex flex-wrap items-end gap-2">
                <div className="min-w-0 flex-1">
                  <label className="text-xs font-bold text-muted" htmlFor="settings-paypalme">
                    PayPal.me name
                  </label>
                  <input
                    id="settings-paypalme"
                    className={input}
                    placeholder="e.g. SamBuilds"
                    autoComplete="off"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                  />
                </div>
                <button type="button" className={primary} disabled={busy !== null || !username.trim()} onClick={savePaypalMe}>
                  Save
                </button>
                {me.connected &&
                  (confirming === "paypalme" ? (
                    <button type="button" className={button} onClick={() => disconnect("paypalme")}>
                      Yes, remove it
                    </button>
                  ) : (
                    <button type="button" className={button} onClick={() => setConfirming("paypalme")}>
                      Remove
                    </button>
                  ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
