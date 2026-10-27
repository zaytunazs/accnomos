"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "@/lib/msal";
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
        <h2 id="settings-rules" className={heading}>
          Autopilot rules
        </h2>
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
      {rules === null ? (
        <p className="mt-3 text-sm text-muted">{account ? "Loading…" : "Sign in to see the rules in your OneDrive."}</p>
      ) : rules.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No rules yet.</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
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
      )}
      {note && (
        <p role="status" className="mt-2 text-sm font-bold text-teal-dark">
          {note}
        </p>
      )}
    </section>
  );
}
