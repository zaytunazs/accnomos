"use client";

import { useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import AdminFrame, { ConfirmDialog, ErrorLine, card, h2, input, td, th, useLoad } from "./parts";
import Modal, { fieldLabel, primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { adminApi } from "@/lib/billing-api";
import { describeCode, type CodeKind, type PromoCode } from "@/lib/admin";
import { PLAN_CODES, PLAN_NAMES, longDate, type PlanCode } from "@/lib/billing";

export default function Codes() {
  return (
    <AdminFrame title="Promo codes" description="Percent off, money off or free months, with optional limits.">
      {(account) => <Body account={account} />}
    </AdminFrame>
  );
}

interface Form {
  code: string;
  kind: CodeKind;
  value: string;
  plans: PlanCode[];
  max: string;
  expires: string;
  active: boolean;
  editing: boolean;
}
const blank: Form = { code: "", kind: "percent", value: "", plans: [], max: "", expires: "", active: true, editing: false };

function Body({ account }: { account: AccountInfo }) {
  const { data, error, reload } = useLoad(() => adminApi.codes(account), [account]);
  const [form, setForm] = useState<Form | null>(null);
  const [pending, setPending] = useState<Form | null>(null);
  const set = (p: Partial<Form>) => setForm((f) => (f ? { ...f, ...p } : f));

  const edit = (c: PromoCode) =>
    setForm({ code: c.code, kind: c.kind, value: String(c.value), plans: c.plan_codes ?? [], max: c.max_redemptions?.toString() ?? "", expires: c.expires_at?.slice(0, 10) ?? "", active: c.active, editing: true });
  const valid = form && form.code.trim() && Number(form.value) > 0 && (form.kind !== "percent" || Number(form.value) <= 100);

  async function save(f: Form) {
    // The kind and value of a code are fixed once made (PATCH takes only these four).
    const limits = {
      plan_codes: f.plans.length ? f.plans : null,
      max_redemptions: f.max ? Number(f.max) : null,
      expires_at: f.expires ? `${f.expires}T23:59:59Z` : null,
      active: f.active,
    };
    if (f.editing) await adminApi.patchCode(account, f.code, limits);
    else
      await adminApi.createCode(account, {
        code: f.code.trim().toUpperCase(),
        kind: f.kind,
        value: f.kind === "fixed" ? Math.round(Number(f.value)) : Number(f.value),
        ...limits,
      });
    setPending(null);
    setForm(null);
    reload();
  }

  return (
    <>
      <section className={card} aria-labelledby="codes-h">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="codes-h" className={h2}>Codes</h2>
          <div className="flex gap-2">
            <button type="button" className={secondaryButton} onClick={() => setForm({ ...blank, code: "YEARFREE", kind: "free_months", value: "12" })}>Preset: 12 months free</button>
            <button type="button" className={primaryButton} onClick={() => setForm({ ...blank })}>New code</button>
          </div>
        </div>
        <ErrorLine error={error} />
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[40rem]" data-codes-table="">
            <thead><tr className="border-b border-border"><th className={th}>Code</th><th className={th}>Gives</th><th className={th}>Plans</th><th className={th}>Used</th><th className={th}>Expires</th><th className={th}>Active</th><th className={th}><span className="sr-only">Edit</span></th></tr></thead>
            <tbody>
              {data?.map((c) => (
                <tr key={c.code} className="border-b border-border last:border-0">
                  <td className={`${td} font-bold`}>{c.code}</td>
                  <td className={td}>{describeCode(c)}</td>
                  <td className={td}>{c.plan_codes ? c.plan_codes.map((p) => PLAN_NAMES[p]).join(", ") : "Any"}</td>
                  <td className={td}>{c.redeemed_count}{c.max_redemptions !== null ? ` of ${c.max_redemptions}` : ""}</td>
                  <td className={td}>{c.expires_at ? longDate(c.expires_at) : "Never"}</td>
                  <td className={td}>{c.active ? "Yes" : "No"}</td>
                  <td className={td}><button type="button" className="font-bold text-teal-dark underline" onClick={() => edit(c)} aria-label={`Edit ${c.code}`}>Edit</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {form && !pending && (
        <Modal id="code-form-title" title={form.editing ? `Edit ${form.code}` : "New promo code"} onClose={() => setForm(null)}>
          <form className="mt-3 grid gap-3" onSubmit={(e) => { e.preventDefault(); if (valid) setPending(form); }}>
            <label><span className={fieldLabel}>Code</span><input className={`${input} w-full uppercase`} value={form.code} disabled={form.editing} onChange={(e) => set({ code: e.target.value })} /></label>
            <label><span className={fieldLabel}>Kind</span>
              <select className={`${input} w-full`} value={form.kind} disabled={form.editing} onChange={(e) => set({ kind: e.target.value as CodeKind })}>
                <option value="percent">Percent off</option><option value="fixed">Money off (pence)</option><option value="free_months">Free months</option>
              </select></label>
            <label><span className={fieldLabel}>{form.kind === "percent" ? "Percent (1 to 100)" : form.kind === "fixed" ? "Pence off" : "Months free"}</span>
              <input className={`${input} w-full`} inputMode="numeric" value={form.value} disabled={form.editing} onChange={(e) => set({ value: e.target.value })} /></label>
            <fieldset><legend className={fieldLabel}>Only for these plans (none ticked: any)</legend>
              <div className="mt-1 flex flex-wrap gap-3">{PLAN_CODES.map((p) => <label key={p} className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={form.plans.includes(p)} onChange={(e) => set({ plans: e.target.checked ? [...form.plans, p] : form.plans.filter((x) => x !== p) })} />{PLAN_NAMES[p]}</label>)}</div></fieldset>
            <label><span className={fieldLabel}>Maximum redemptions (blank: no limit)</span><input className={`${input} w-full`} inputMode="numeric" value={form.max} onChange={(e) => set({ max: e.target.value })} /></label>
            <label><span className={fieldLabel}>Expires on (blank: never)</span><input type="date" className={`${input} w-full`} value={form.expires} onChange={(e) => set({ expires: e.target.value })} /></label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.active} onChange={(e) => set({ active: e.target.checked })} />Active</label>
            <div className="flex gap-2"><button type="submit" className={primaryButton} disabled={!valid}>Review</button><button type="button" className={secondaryButton} onClick={() => setForm(null)}>Cancel</button></div>
          </form>
        </Modal>
      )}
      {pending && (
        <ConfirmDialog
          title={pending.editing ? "Save changes to code" : "Create code"}
          body={<>{pending.editing ? "Update" : "Create"} <strong>{pending.code.trim().toUpperCase()}</strong>: {describeCode({ kind: pending.kind, value: Number(pending.value) })}{pending.plans.length ? ` on ${pending.plans.map((p) => PLAN_NAMES[p]).join(", ")}` : " on any plan"}{pending.max ? `, at most ${pending.max} times` : ""}{pending.expires ? `, until ${longDate(pending.expires)}` : ""}. {pending.active ? "" : "It will be inactive."}</>}
          confirmLabel={pending.editing ? "Save" : "Create"}
          onCancel={() => setPending(null)}
          onConfirm={() => save(pending)}
        />
      )}
    </>
  );
}
