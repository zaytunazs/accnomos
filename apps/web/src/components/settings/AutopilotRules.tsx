"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "@/lib/msal";
import ByWhom from "@/components/ByWhom";
import Explain from "@/components/Explain";
import SignInCta from "@/components/SignInCta";
import { EmptyState, LoadingSkeleton } from "@/components/States";
import { autopilotOn, gbp, runtime, setAutopilotOn, type RtRule } from "@/lib/runtime";

/** Settings › Autopilot rules: the rules in _System/Rules/rules.json, with Remove, and the master switch. */
export default function AutopilotRules({ card, heading }: { card: string; heading: string }) {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [rules, setRules] = useState<RtRule[] | null>(null);
  const [on, setOn] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    queueMicrotask(() => setOn(autopilotOn()));
    (async () => {
      try {
        if (!msalConfigured()) return;
        const msal = await getMsal();
        const acct = msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
        if (!acct) return;
        setAccount(acct);
        setRules(await runtime.rules(acct));
      } catch (e) {
        setNote((e as Error).message);
      }
    })();
  }, []);

  function toggle() {
    setAutopilotOn(!on);
    setOn(!on);
  }

  async function remove(key: string) {
    if (!account) return;
    setBusy(key);
    try {
      await runtime.removeRule(account, key);
      setRules((rs) => (rs ?? []).filter((r) => r.supplier_key !== key));
      setNote("Rule removed. Autopilot won't post for that supplier again.");
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section aria-labelledby="settings-rules" className={card}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h3 id="settings-rules" className={heading}>
            Autopilot rules
          </h3>
          <Explain title="What Autopilot will and will not post">
            <p>
              Autopilot only posts at level L2, and only a purchase that matches a rule you saved
              by ticking “Always do this” — same supplier, same VAT number, same VAT treatment,
              and a total no more than twice the usual. Every code check must pass with no
              warnings, including the second reading agreeing.
            </p>
            <p>
              Each posting goes through the normal approval code, is audited, and stays listed
              under Approved by Autopilot for 30 days with Undo. Undo adds a reversing entry and
              puts the proposal back in Review.
            </p>
            <p>
              It will never create a rule on its own, never post sales invoices or mileage
              claims, never post above twice the usual, never post when a check warns, and never
              delete or edit a ledger event. Anything else waits in Review with a line saying why
              Autopilot left it for you.
            </p>
          </Explain>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          onClick={toggle}
          className={`h-10 rounded-full border px-4 text-sm font-extrabold ${
            on ? "border-teal bg-teal-tint text-teal-dark" : "border-border bg-ground text-muted"
          }`}
        >
          Autopilot {on ? "on" : "off"}
        </button>
      </div>
      <p className="mt-1 text-sm text-muted">
        Saved when you tick &ldquo;Always do this&rdquo;. Autopilot only posts when every check passes, the VAT number is the
        same and the total is no more than twice the usual. {on ? "" : "Switched off on this device: every scan waits for you."}
      </p>
      <ByWhom className="mt-1" code="Posting by code at L2 only" ai="rules by you" />
      {rules === null ? (
        account ? (
          <div className="mt-3">
            <LoadingSkeleton lines={2} label="Loading your Autopilot rules…" />
          </div>
        ) : (
          <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-muted">
            <SignInCta />
            <span>to see the rules in your OneDrive.</span>
          </p>
        )
      ) : rules.length === 0 ? (
        <div className="mt-3">
          <EmptyState
            title="No rules yet"
            body="Tick “Always do this” when you approve and the rule will appear here."
            action={
              <Link
                href="/review"
                className="inline-flex h-11 items-center whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark"
              >
                Go to Review
              </Link>
            }
          />
        </div>
      ) : (
        <>
          {/* Phone: one card per rule. Wider screens: the rules table. */}
          <ul className="mt-3 flex flex-col gap-2 sm:hidden">
            {rules.map((rule) => (
              <li
                key={rule.supplier_key}
                className="flex items-center justify-between gap-3 rounded-xl border border-border p-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-[15px] font-bold">
                    {rule.supplier_name || rule.supplier_key}
                  </p>
                  <p className="mt-0.5 text-[13px] text-muted">
                    {rule.category} · {rule.vat_code ?? "no code"} · usually {gbp(rule.typical_gross_pence / 100)} · used {rule.hits}×
                  </p>
                </div>
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => remove(rule.supplier_key)}
                  aria-label={`Remove rule for ${rule.supplier_name || rule.supplier_key}`}
                  className="h-9 shrink-0 whitespace-nowrap rounded-xl border border-border bg-white px-3 text-[13px] font-bold text-ink disabled:opacity-60"
                >
                  {busy === rule.supplier_key ? "Removing…" : "Remove"}
                </button>
              </li>
            ))}
          </ul>
          <div className="relative mt-3 hidden overflow-x-auto sm:block">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-xs font-bold text-muted">
                <th scope="col" className="py-2 pr-3">Supplier</th>
                <th scope="col" className="py-2 pr-3">Category</th>
                <th scope="col" className="py-2 pr-3">Code</th>
                <th scope="col" className="py-2 pr-3">Usual</th>
                <th scope="col" className="py-2 pr-3">Used</th>
                <th scope="col" className="py-2">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rules.map((rule) => (
                <tr key={rule.supplier_key} className="text-ink">
                  <td className="py-2 pr-3 font-bold">{rule.supplier_name || rule.supplier_key}</td>
                  <td className="py-2 pr-3 text-muted">{rule.category}</td>
                  <td className="py-2 pr-3 text-muted">{rule.vat_code ?? "—"}</td>
                  <td className="py-2 pr-3 text-muted">{gbp(rule.typical_gross_pence / 100)}</td>
                  <td className="py-2 pr-3 text-muted">{rule.hits}×</td>
                  <td className="py-2 text-right">
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => remove(rule.supplier_key)}
                      className="h-9 rounded-xl border border-border bg-white px-3 text-[13px] font-bold text-ink disabled:opacity-60"
                    >
                      {busy === rule.supplier_key ? "Removing…" : "Remove"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </>
      )}
      {note && (
        <p role="status" className="mt-2 text-sm font-bold text-teal-dark">
          {note}
        </p>
      )}
    </section>
  );
}
