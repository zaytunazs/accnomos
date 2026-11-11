"use client";

import { useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import AdminFrame, { ConfirmDialog, ErrorLine, card, h2, input, useLoad } from "./parts";
import { fieldLabel, primaryButton } from "@/components/invoices/Modal";
import { adminApi } from "@/lib/billing-api";
import type { AdminPlan } from "@/lib/admin";
import { LIMIT_ROWS, money, type LimitValue } from "@/lib/billing";

export default function Plans() {
  return (
    <AdminFrame title="Plans" description="Limits and availability. Changes apply at once, with no deploy.">
      {(account) => <Body account={account} />}
    </AdminFrame>
  );
}

const show = (v: LimitValue | undefined) => (v === null ? "unlimited" : v === undefined ? "" : v === true ? "yes" : v === false ? "no" : String(v));
export function parseLimit(text: string): LimitValue | undefined {
  const t = text.trim().toLowerCase();
  if (t === "") return undefined;
  if (t === "unlimited") return null;
  if (t === "yes" || t === "true") return true;
  if (t === "no" || t === "false") return false;
  const n = Number(t);
  return Number.isFinite(n) ? n : text.trim();
}

function Body({ account }: { account: AccountInfo }) {
  const { data, error, reload } = useLoad(() => adminApi.plans(account), [account]);
  return (
    <>
      <ErrorLine error={error} />
      <p className={`${card} text-sm text-muted`}>
        Prices are shown ex VAT. A price change creates a new Stripe price; it does not move existing subscribers by itself. Type <em>unlimited</em>, a number, <em>yes</em>, <em>no</em> or text for each limit.
      </p>
      {data?.map((p) => <PlanCard key={p.code} plan={p} account={account} onSaved={reload} />)}
    </>
  );
}

function PlanCard({ plan, account, onSaved }: { plan: AdminPlan; account: AccountInfo; onSaved: () => void }) {
  const keys = [...new Set([...LIMIT_ROWS.map((r) => r.key).filter((k): k is string => !!k), ...Object.keys(plan.limits)])];
  const [limits, setLimits] = useState<Record<string, string>>(() => Object.fromEntries(keys.map((k) => [k, show(plan.limits[k])])));
  const [active, setActive] = useState(plan.active);
  const [month, setMonth] = useState(String(plan.price_month_pence));
  const [year, setYear] = useState(String(plan.price_year_pence));
  const [confirm, setConfirm] = useState(false);
  const priceChanged = Number(month) !== plan.price_month_pence || Number(year) !== plan.price_year_pence;

  async function save() {
    const out: Record<string, unknown> = {};
    for (const k of keys) {
      const v = parseLimit(limits[k] ?? "");
      if (v !== undefined) out[k] = v;
    }
    await adminApi.patchPlan(account, plan.code, { limits: out, active, ...(priceChanged ? { price_month_pence: Number(month), price_year_pence: Number(year) } : {}) });
    setConfirm(false);
    onSaved();
  }

  return (
    <section className={card} aria-labelledby={`plan-${plan.code}`} data-plan-edit={plan.code}>
      <h2 id={`plan-${plan.code}`} className={h2}>{plan.name} <span className="text-sm font-normal text-muted">{money(plan.price_month_pence)} a month · {money(plan.price_year_pence)} a year</span></h2>
      <label className="mt-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />Active (shown on the pricing page and open to new sign-ups)</label>
      <div className="mt-3 grid gap-3 min-[700px]:grid-cols-4">
        <label><span className={fieldLabel}>Monthly price (pence)</span><input className={`${input} w-full`} inputMode="numeric" value={month} onChange={(e) => setMonth(e.target.value)} /></label>
        <label><span className={fieldLabel}>Yearly price (pence)</span><input className={`${input} w-full`} inputMode="numeric" value={year} onChange={(e) => setYear(e.target.value)} /></label>
      </div>
      <div className="mt-3 grid gap-3 min-[700px]:grid-cols-3">
        {keys.map((k) => (
          <label key={k}><span className={fieldLabel}>{k}</span><input className={`${input} w-full`} value={limits[k] ?? ""} onChange={(e) => setLimits({ ...limits, [k]: e.target.value })} /></label>
        ))}
      </div>
      <button type="button" className={`${primaryButton} mt-3`} onClick={() => setConfirm(true)}>Save {plan.name}</button>
      {confirm && (
        <ConfirmDialog
          title={`Save ${plan.name}`}
          body={<>Apply these limits{active !== plan.active ? ` and set the plan ${active ? "active" : "inactive"}` : ""} now? {priceChanged ? <strong>This also changes the price and creates a new Stripe price.</strong> : null}</>}
          confirmLabel="Save"
          onCancel={() => setConfirm(false)}
          onConfirm={save}
        />
      )}
    </section>
  );
}
