"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { AccountInfo } from "@azure/msal-browser";
import { errorText, useAccount } from "@/components/jobs/useAccount";
import { RuntimeErrorNote } from "@/components/States";
import QueryThreads from "@/components/accountant/QueryThreads";
import {
  getClientContext,
  KIND_LABELS,
  onClientContextChange,
  parseQueryLink,
  setClientContext,
  type ClientAccess,
  type ClientContext,
  type RtClientSummary,
  type RtPortal,
} from "@/lib/accountant";
import { accountantApi } from "@/lib/runtime";

const day = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "Europe/London" });

function useClientContext(): ClientContext | null | undefined {
  const [ctx, setCtx] = useState<ClientContext | null | undefined>(undefined);
  useEffect(() => {
    queueMicrotask(() => setCtx(getClientContext()));
    return onClientContextChange(() => setCtx(getClientContext()));
  }, []);
  return ctx;
}

/** /accountant: the clients whose books are shared with you; open one in view or edit, and its queries. */
export default function Portal() {
  const account = useAccount();
  const ctx = useClientContext();
  const [query, setQuery] = useState<URLSearchParams | null>(null);

  useEffect(() => {
    queueMicrotask(() => setQuery(new URLSearchParams(window.location.search)));
  }, []);

  if (account === undefined || ctx === undefined || query === null) return <p className="mt-6 text-sm text-muted">Loading…</p>;
  if (account === null) {
    return (
      <p className="mt-6 rounded-2xl border border-border bg-white p-4 text-sm text-ink">
        Sign in with the Microsoft account your clients shared their books with to see them here.
      </p>
    );
  }
  if (ctx) {
    return (
      <div className="mt-6 space-y-4">
        <QueryThreads
          key={`${ctx.driveId}:${ctx.itemId}`}
          account={account}
          me="accountant"
          canAsk
          prefill={parseQueryLink(query.get("query"))}
          heading={`Queries with ${ctx.name || "this client"}`}
        />
      </div>
    );
  }
  return <ClientList account={account} addCode={query.get("client") ?? ""} />;
}

function ClientList({ account, addCode }: { account: AccountInfo; addCode: string }) {
  const router = useRouter();
  const [portal, setPortal] = useState<RtPortal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState(addCode);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setPortal(await accountantApi.portal(account));
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setStatus("");
    try {
      const link = await accountantApi.addClient(account, code);
      setStatus(`Added ${link.name || "the client's books"}.`);
      setCode("");
      await load();
    } catch (err) {
      setStatus(`Could not add it: ${errorText(err)}`);
    } finally {
      setBusy(false);
    }
  }

  async function remove(c: RtClientSummary) {
    setBusy(true);
    try {
      await accountantApi.removeClient(account, c.code);
      setStatus(`Removed ${c.name} from this list. Their sharing is unchanged; only they can stop it.`);
      await load();
    } catch (err) {
      setStatus(`Could not remove it: ${errorText(err)}`);
    } finally {
      setBusy(false);
    }
  }

  function open(c: RtClientSummary, access: ClientAccess) {
    setClientContext({ driveId: c.drive_id, itemId: c.item_id, name: c.name, access });
    router.push("/");
  }

  return (
    <div className="mt-6 space-y-4">
      {error && <RuntimeErrorNote message={error} />}
      {portal?.note && <p className="rounded-xl border border-warn-border bg-warn-bg p-3 text-sm text-warn-ink">{portal.note}</p>}
      {portal === null && !error && <p className="text-sm text-muted">Looking for books shared with you…</p>}
      {portal && portal.clients.length === 0 && (
        <p className="rounded-2xl border border-border bg-white p-4 text-sm text-ink">
          No client books found yet. When a client invites you, add the client code from their invitation email below.
        </p>
      )}
      <ul aria-label="Your clients" className="space-y-3">
        {portal?.clients.map((c) => (
          <li key={c.code}>
            <article aria-label={c.name} className="rounded-2xl border border-border bg-white p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-[17px] font-extrabold text-ink">{c.name}</h2>
                <span className="text-[13px] font-semibold text-muted">
                  {[c.kind ? KIND_LABELS[c.kind] : null, c.access === "edit" ? "View and edit" : c.access === "read" ? "View only" : null]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </div>
              {c.error ? (
                <p className="mt-2 text-sm text-warn-ink">{c.error}</p>
              ) : (
                <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
                  <div>
                    <dt className="text-muted">VAT</dt>
                    <dd className="font-semibold text-ink">
                      {c.vat
                        ? `${c.vat.period} due ${day(c.vat.due)} (${c.vat.days_left} days)`
                        : c.vat_registered === false
                          ? "Not VAT-registered"
                          : "Not set by the client"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted">Waiting in Review</dt>
                    <dd className="font-semibold text-ink">
                      {c.review_waiting}
                      {c.needs_a_look ? ` + ${c.needs_a_look} need a look` : ""}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted">Open queries</dt>
                    <dd className="font-semibold text-ink">
                      {c.open_queries}
                      {c.open_queries ? ` (${c.waiting_on_you} for you, ${c.waiting_on_client} for them)` : ""}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted">Last activity</dt>
                    <dd className="font-semibold text-ink">{c.last_activity ? day(c.last_activity) : "None yet"}</dd>
                  </div>
                </dl>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                {!c.error && (
                  <button
                    type="button"
                    onClick={() => open(c, "read")}
                    aria-label={`Open ${c.name} (view only)`}
                    className="h-11 rounded-xl bg-teal px-4 text-sm font-bold text-white"
                  >
                    Open (view only)
                  </button>
                )}
                {!c.error && c.access === "edit" && (
                  <button
                    type="button"
                    onClick={() => open(c, "edit")}
                    aria-label={`Open ${c.name} to edit`}
                    className="h-11 rounded-xl border-2 border-teal bg-white px-4 text-sm font-bold text-teal-dark"
                  >
                    Open to edit
                  </button>
                )}
                {c.source !== "shared_with_me" && (
                  <button
                    type="button"
                    onClick={() => remove(c)}
                    disabled={busy}
                    aria-label={`Remove ${c.name} from this list`}
                    className="h-11 rounded-xl px-3 text-sm font-bold text-muted hover:bg-ground"
                  >
                    Remove from list
                  </button>
                )}
              </div>
            </article>
          </li>
        ))}
      </ul>

      <form onSubmit={add} aria-labelledby="add-client" className="rounded-2xl border border-border bg-white p-4">
        <h2 id="add-client" className="text-[17px] font-extrabold text-ink">
          Add a client by code
        </h2>
        <p className="mt-1 text-sm text-muted">
          The invitation email has a client code (or a link). Microsoft&apos;s “shared with me” list, which finds clients
          automatically, stops working after November 2026, so codes you add are kept in your own OneDrive.
        </p>
        <label className="mt-2 block text-sm font-semibold text-ink">
          Client code or link
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
            maxLength={1000}
            className="mt-1 h-11 w-full rounded-xl border border-border px-3 text-[15px]"
          />
        </label>
        <button type="submit" disabled={busy || !code.trim()} className="mt-2 h-11 rounded-xl bg-teal px-5 text-[15px] font-extrabold text-white disabled:opacity-60">
          Add client
        </button>
        <p role="status" className="mt-2 min-h-5 text-sm text-ink">
          {status}
        </p>
      </form>
    </div>
  );
}
