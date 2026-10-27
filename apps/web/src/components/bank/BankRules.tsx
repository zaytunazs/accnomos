"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { runtime, type RtBankRule, type RtBankRuleIn } from "@/lib/runtime";

const OPS = [
  { op: "contains", label: "contains" },
  { op: "equals", label: "is exactly" },
  { op: "regex", label: "matches pattern" },
] as const;

const DIRECTIONS = [
  { v: "out", label: "Money out" },
  { v: "in", label: "Money in" },
  { v: "either", label: "Either way" },
] as const;

const inputCls = "h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px] font-medium";
const labelCls = "text-[13px] font-bold text-muted";

const blank: RtBankRuleIn = {
  name: "",
  match: { op: "contains", value: "" },
  amount_min_pence: null,
  amount_max_pence: null,
  direction: "out",
  action: { account: "", vat_code: "N", contact: null, job_id: null },
};

/** "£12.34" -> 1234; "" -> null. */
function toPence(text: string): number | null {
  const t = text.trim().replace("£", "").replace(",", "");
  if (!t) return null;
  const n = Math.round(Number(t) * 100);
  return Number.isFinite(n) ? n : null;
}

function fromPence(pence: number | null): string {
  return pence === null ? "" : String(pence / 100);
}

function RuleForm({
  initial,
  accounts,
  vatCodes,
  busy,
  error,
  onSave,
  onCancel,
}: {
  initial: RtBankRuleIn;
  accounts: string[];
  vatCodes: string[];
  busy: boolean;
  error: string | null;
  onSave: (rule: RtBankRuleIn) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<RtBankRuleIn>(initial);
  const [minText, setMinText] = useState(fromPence(initial.amount_min_pence));
  const [maxText, setMaxText] = useState(fromPence(initial.amount_max_pence));
  const set = <K extends keyof RtBankRuleIn>(k: K, v: RtBankRuleIn[K]) => setForm((f) => ({ ...f, [k]: v }));

  function save() {
    onSave({ ...form, amount_min_pence: toPence(minText), amount_max_pence: toPence(maxText) });
  }

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-ground p-4">
      <p className="text-[15px] font-extrabold">When the description contains X, code it to Y</p>
      <div className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Rule name (for you)</span>
          <input aria-label="Rule name" className={inputCls} value={form.name} onChange={(e) => set("name", e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Direction</span>
          <select aria-label="Direction" className={inputCls} value={form.direction} onChange={(e) => set("direction", e.target.value as RtBankRuleIn["direction"])}>
            {DIRECTIONS.map((d) => (
              <option key={d.v} value={d.v}>{d.label}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Description…</span>
          <select aria-label="Match type" className={inputCls} value={form.match.op} onChange={(e) => set("match", { ...form.match, op: e.target.value as RtBankRuleIn["match"]["op"] })}>
            {OPS.map((o) => (
              <option key={o.op} value={o.op}>{o.label}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>…this text{form.match.op === "regex" ? " (plain pattern: no (a+)+ or \\1)" : ""}</span>
          <input aria-label="Match text" className={inputCls} value={form.match.value} onChange={(e) => set("match", { ...form.match, value: e.target.value })} />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Amount from (£, optional)</span>
          <input aria-label="Minimum amount in pounds" inputMode="decimal" className={inputCls} value={minText} onChange={(e) => setMinText(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Amount to (£, optional)</span>
          <input aria-label="Maximum amount in pounds" inputMode="decimal" className={inputCls} value={maxText} onChange={(e) => setMaxText(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Code it to (account)</span>
          <select aria-label="Account" className={inputCls} value={form.action.account} onChange={(e) => set("action", { ...form.action, account: e.target.value })}>
            <option value="">Choose an account…</option>
            {accounts.map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>VAT code</span>
          <select aria-label="VAT code" className={inputCls} value={form.action.vat_code ?? ""} onChange={(e) => set("action", { ...form.action, vat_code: e.target.value || null })}>
            <option value="">None</option>
            {vatCodes.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Contact (optional)</span>
          <input aria-label="Contact" className={inputCls} value={form.action.contact ?? ""} onChange={(e) => set("action", { ...form.action, contact: e.target.value || null })} />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Job id (optional)</span>
          <input aria-label="Job id" className={inputCls} value={form.action.job_id ?? ""} onChange={(e) => set("action", { ...form.action, job_id: e.target.value || null })} />
        </label>
      </div>
      {error && (
        <p role="alert" className="text-sm font-semibold text-warn-ink">{error}</p>
      )}
      <div className="flex gap-2">
        <button type="button" disabled={busy} onClick={save} className="h-11 flex-1 rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60">
          {busy ? "Saving…" : "Save rule"}
        </button>
        <button type="button" onClick={onCancel} className="h-11 flex-1 rounded-xl border border-border bg-white px-5 text-[15px] font-bold hover:bg-ground">
          Cancel
        </button>
      </div>
    </div>
  );
}

/** Bank rules: list in evaluation order, with add, edit, reorder and delete (confirmed). */
export default function BankRules({ account, prefill, onPrefillUsed }: {
  account: AccountInfo;
  /** A rule draft from "Create rule from this": opens the form pre-filled, once. */
  prefill: RtBankRule | null;
  onPrefillUsed: () => void;
}) {
  const [rules, setRules] = useState<RtBankRule[] | null>(null);
  const [accounts, setAccounts] = useState<string[]>([]);
  const [vatCodes, setVatCodes] = useState<string[]>(["S", "R", "Z", "E", "O", "N"]);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [r, opts] = await Promise.all([runtime.bank.rules(account), runtime.bank.codingOptions(account)]);
      setRules(r);
      setAccounts(opts.accounts);
      setVatCodes(opts.vat_codes);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [account]);

  useEffect(() => {
    (async () => {
      await reload();
    })().catch(() => null);
  }, [reload]);

  // A fresh prefill (from "Create rule from this") opens the add form once.
  const [seenPrefill, setSeenPrefill] = useState<RtBankRule | null>(null);
  if (prefill !== seenPrefill) {
    setSeenPrefill(prefill);
    if (prefill) {
      setAdding(true);
      setEditing(null);
    }
  }

  async function mutate(run: (a: AccountInfo) => Promise<unknown>, note: string) {
    setBusy(true);
    setFormError(null);
    try {
      await run(account);
      setAdding(false);
      setEditing(null);
      setConfirmingDelete(null);
      onPrefillUsed();
      await reload();
    } catch (e) {
      setFormError(`${note}: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  if (rules === null) {
    return <p className="py-6 text-center text-sm font-semibold text-muted">{error ?? "Reading your bank rules…"}</p>;
  }

  const formInitial: RtBankRuleIn = prefill && adding
    ? { name: prefill.name, match: prefill.match, amount_min_pence: prefill.amount_min_pence, amount_max_pence: prefill.amount_max_pence, direction: prefill.direction, action: prefill.action }
    : editing
      ? (() => {
        const r = rules.find((x) => x.id === editing);
        return r ? { name: r.name, match: r.match, amount_min_pence: r.amount_min_pence, amount_max_pence: r.amount_max_pence, direction: r.direction, action: r.action } : blank;
      })()
      : blank;

  async function move(id: string, dir: -1 | 1) {
    if (rules === null) return;
    const ids = rules.map((r) => r.id);
    const i = ids.indexOf(id);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    setBusy(true);
    try {
      setRules(await runtime.bank.reorderRules(account, ids));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">Rules run in order and the first match wins. Matching is plain code, never the AI.</p>
      {error && (
        <p role="alert" className="text-sm font-semibold text-warn-ink">{error}</p>
      )}
      {rules.length === 0 && !adding ? (
        <p className="py-6 text-center text-sm font-semibold text-muted">No rules yet. Add one, or approve a bank line and choose “Create rule from this”.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {rules.map((r, i) => (
            <li key={r.id} className="flex flex-col gap-2 rounded-xl border border-border p-4">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="font-bold">{r.name || `Rule ${i + 1}`}</span>
                <span className="rounded-full bg-ground px-2 py-0.5 text-[12px] font-bold text-muted">#{i + 1} of {rules.length}</span>
              </div>
              <p className="text-sm">
                When the description <strong>{r.match.op}</strong> {r.match.value}
                {r.direction !== "either" ? ` · money ${r.direction}` : ""}
                {(r.amount_min_pence !== null || r.amount_max_pence !== null) ? ` · ${(r.amount_min_pence ?? 0) / 100}–${r.amount_max_pence === null ? "…" : r.amount_max_pence / 100}` : ""} →{" "}
                <strong>{r.action.account}</strong>
                {r.action.vat_code ? ` (VAT ${r.action.vat_code})` : ""}
                {r.action.contact ? ` · ${r.action.contact}` : ""}
              </p>
              {editing === r.id ? (
                <RuleForm
                  initial={formInitial}
                  accounts={accounts}
                  vatCodes={vatCodes}
                  busy={busy}
                  error={formError}
                  onSave={(body) => void mutate((a) => runtime.bank.updateRule(a, r.id, body), "Could not save the rule")}
                  onCancel={() => { setEditing(null); setFormError(null); onPrefillUsed(); }}
                />
              ) : (
                <div className="flex flex-wrap gap-2">
                  <button type="button" disabled={busy} onClick={() => { setEditing(r.id); setAdding(false); setFormError(null); }} aria-label={`Edit rule ${r.name || r.match.value}`} className="h-10 rounded-xl border border-border bg-white px-4 text-sm font-bold hover:bg-ground disabled:opacity-60">
                    Edit
                  </button>
                  <button type="button" disabled={busy || i === 0} onClick={() => void move(r.id, -1)} aria-label={`Move rule ${r.name || r.match.value} up`} className="h-10 rounded-xl border border-border bg-white px-4 text-sm font-bold hover:bg-ground disabled:opacity-60">
                    ↑ Up
                  </button>
                  <button type="button" disabled={busy || i === rules.length - 1} onClick={() => void move(r.id, 1)} aria-label={`Move rule ${r.name || r.match.value} down`} className="h-10 rounded-xl border border-border bg-white px-4 text-sm font-bold hover:bg-ground disabled:opacity-60">
                    ↓ Down
                  </button>
                  {confirmingDelete === r.id ? (
                    <>
                      <button type="button" disabled={busy} onClick={() => void mutate((a) => runtime.bank.deleteRule(a, r.id), "Could not delete the rule")} aria-label={`Confirm delete rule ${r.name || r.match.value}`} className="h-10 rounded-xl bg-warn-bg px-4 text-sm font-bold text-warn-ink disabled:opacity-60">
                        {busy ? "…" : "Confirm delete"}
                      </button>
                      <button type="button" onClick={() => setConfirmingDelete(null)} className="h-10 rounded-xl border border-border bg-white px-4 text-sm font-bold hover:bg-ground">
                        Keep
                      </button>
                    </>
                  ) : (
                    <button type="button" disabled={busy} onClick={() => setConfirmingDelete(r.id)} aria-label={`Delete rule ${r.name || r.match.value}`} className="h-10 rounded-xl border border-border bg-white px-4 text-sm font-bold hover:bg-ground disabled:opacity-60">
                      Delete
                    </button>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {adding ? (
        <RuleForm
          initial={formInitial}
          accounts={accounts}
          vatCodes={vatCodes}
          busy={busy}
          error={formError}
          onSave={(body) => void mutate((a) => runtime.bank.createRule(a, body), "Could not save the rule")}
          onCancel={() => { setAdding(false); setFormError(null); onPrefillUsed(); }}
        />
      ) : (
        <div>
          <button type="button" onClick={() => { setAdding(true); setEditing(null); setFormError(null); }} className="h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark">
            Add a rule
          </button>
        </div>
      )}
    </div>
  );
}
