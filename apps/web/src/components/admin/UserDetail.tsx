"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import AdminFrame, { ConfirmDialog, ErrorLine, card, h2, input, td, th, useLoad } from "./parts";
import { fieldLabel, primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { adminApi } from "@/lib/billing-api";
import { PLAN_CODES, PLAN_NAMES, STATUS_LABEL, longDate, money, type PlanCode } from "@/lib/billing";
import { fromUnix, type AdminAction, type AdminUserPatch } from "@/lib/admin";

export default function UserDetail() {
  const [id, setId] = useState<string | null>(null);
  useEffect(() => {
    queueMicrotask(() => setId(new URLSearchParams(window.location.search).get("id")));
  }, []);
  return (
    <AdminFrame title="User" description="One account: plan, usage, payments and what you have done to it.">
      {(account) => (id ? <Body account={account} id={id} /> : <p className="text-sm text-muted">No account chosen. <Link href="/admin/users" className="font-bold text-teal-dark underline">Back to users</Link></p>)}
    </AdminFrame>
  );
}

interface Pending {
  title: string;
  body: ReactNode;
  run: () => Promise<unknown>;
}

function Body({ account, id }: { account: AccountInfo; id: string }) {
  const { data, error, reload } = useLoad(() => adminApi.user(account, id), [account, id]);
  const [pending, setPending] = useState<Pending | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [notes, setNotes] = useState<string | null>(null);
  const [plan, setPlan] = useState<PlanCode>("comprehensive");
  const [days, setDays] = useState("30");
  const [until, setUntil] = useState("");
  const [code, setCode] = useState("");

  if (error) return <ErrorLine error={error} />;
  if (!data) return <p className="text-sm text-muted">Loading…</p>;
  const a = data.account;
  const sub = data.stripe?.subscription ?? null;

  const act = (title: string, body: ReactNode, action: AdminAction) =>
    setPending({
      title,
      body,
      run: async () => {
        const r = await adminApi.action(account, id, action);
        setNotice(r.url ? `Portal link, valid for a short time: ${r.url}` : (r.message ?? "Done."));
      },
    });
  const patch = (title: string, body: ReactNode, p: AdminUserPatch) =>
    setPending({
      title,
      body,
      run: async () => {
        await adminApi.patchUser(account, id, p);
        setNotice("Saved.");
      },
    });

  const dl = (label: string, value: ReactNode) => (
    <div className="flex justify-between gap-3 py-2 text-sm"><dt className="font-bold">{label}</dt><dd className="text-right">{value}</dd></div>
  );

  return (
    <>
      <p className="text-sm"><Link href="/admin/users" className="font-bold text-teal-dark underline underline-offset-2">All users</Link></p>
      {notice && <p role="status" className="rounded-xl bg-teal-tint p-3 text-sm font-bold text-teal-dark">{notice}</p>}

      <section aria-labelledby="u-account" className={card}>
        <h2 id="u-account" className={h2}>{a.email}</h2>
        <dl className="mt-2 divide-y divide-border">
          {dl("Name", a.display_name ?? "—")}
          {dl("Signed in with", a.auth_kind || "—")}
          {dl("Plan", PLAN_NAMES[a.plan_code] ?? a.plan_code)}
          {dl("Status", STATUS_LABEL[a.status] ?? a.status)}
          {dl("Billing", a.billing_interval === "year" ? "Yearly" : a.billing_interval === "month" ? "Monthly" : "—")}
          {dl("Trial ends", longDate(a.trial_ends_at))}
          {dl("Free until", longDate(a.comp_until))}
          {dl("Signed up", longDate(a.created_at))}
          {dl("Last seen", longDate(a.last_seen_at))}
          {dl("Country", a.country ?? "—")}
        </dl>
      </section>

      <section aria-labelledby="u-actions" className={card}>
        <h2 id="u-actions" className={h2}>Actions</h2>
        <p className="text-sm text-muted">Each asks you to confirm first and is recorded in the audit log.</p>
        <div className="mt-3 grid gap-4 min-[700px]:grid-cols-2">
          <div className="flex items-end gap-2">
            <label className="flex-1"><span className={fieldLabel}>Change plan</span>
              <select className={`${input} w-full`} value={plan} onChange={(e) => setPlan(e.target.value as PlanCode)}>
                {PLAN_CODES.map((c) => <option key={c} value={c}>{PLAN_NAMES[c]}</option>)}
              </select></label>
            <button type="button" className={secondaryButton} onClick={() => patch("Change plan", <>Move {a.email} to {PLAN_NAMES[plan]}? This changes their limits at once; it does not charge or refund anything in Stripe.</>, { plan_code: plan })}>Change</button>
          </div>
          <div className="flex items-end gap-2">
            <label className="flex-1"><span className={fieldLabel}>Extend trial (days)</span>
              <input className={`${input} w-full`} inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)} /></label>
            <button type="button" className={secondaryButton} disabled={!(Number(days) > 0)} onClick={() => act("Extend trial", <>Add {days} days to the trial of {a.email}?</>, { action: "extend_trial", days: Number(days) })}>Extend</button>
          </div>
          <div className="flex items-end gap-2">
            <label className="flex-1"><span className={fieldLabel}>Set free until</span>
              <input type="date" className={`${input} w-full`} value={until} onChange={(e) => setUntil(e.target.value)} /></label>
            <button type="button" className={secondaryButton} disabled={!until} onClick={() => patch("Set free until", <>Give {a.email} free access until {longDate(until)}? Their status becomes Free access.</>, { comp_until: until, status: "comped" })}>Set</button>
          </div>
          <div className="flex items-end gap-2">
            <label className="flex-1"><span className={fieldLabel}>Apply a code</span>
              <input className={`${input} w-full`} value={code} onChange={(e) => setCode(e.target.value)} /></label>
            <button type="button" className={secondaryButton} disabled={!code.trim()} onClick={() => act("Apply code", <>Apply the code {code.trim().toUpperCase()} to {a.email}?</>, { action: "apply_code", code: code.trim() })}>Apply</button>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" className={secondaryButton} onClick={() => act("Cancel at period end", <>Cancel the subscription of {a.email} at the end of the current period? They keep access until then.</>, { action: "cancel_at_period_end" })}>Cancel at period end</button>
          <button type="button" className={secondaryButton} onClick={() => act("Resume subscription", <>Resume the subscription of {a.email}, undoing a pending cancellation?</>, { action: "resume" })}>Resume</button>
          <button type="button" className={secondaryButton} onClick={() => act("Send portal link", <>Make a link to the Stripe billing portal of {a.email}? It is shown here for you to send; nothing is emailed.</>, { action: "send_portal_link" })}>Send portal link</button>
          <button type="button" className={secondaryButton} onClick={() => act("Grant top-up", <>Give {a.email} 100 extra AI-read documents, free of charge, valid for 12 months?</>, { action: "grant_topup", docs: 100 })}>Grant top-up (100 documents)</button>
        </div>
      </section>

      <section aria-labelledby="u-usage" className={card}>
        <h2 id="u-usage" className={h2}>Usage history</h2>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[28rem]"><thead><tr className="border-b border-border"><th className={th}>Month</th><th className={th}>Documents</th><th className={th}>Ask</th><th className={th}>Invoices</th><th className={th}>Top-up left</th></tr></thead>
            <tbody>{data.usage_history.map((u) => <tr key={u.month} className="border-b border-border last:border-0"><td className={td}>{u.month.slice(0, 7)}</td><td className={td}>{u.docs}</td><td className={td}>{u.ask}</td><td className={td}>{u.invoices}</td><td className={td}>{u.topup_docs_remaining}</td></tr>)}
              {data.usage_history.length === 0 && <tr><td className={td} colSpan={5}>No usage yet.</td></tr>}</tbody></table>
        </div>
      </section>

      <section aria-labelledby="u-stripe" className={card}>
        <h2 id="u-stripe" className={h2}>Stripe</h2>
        {!data.stripe ? <p className="mt-1 text-sm text-muted">No Stripe customer yet (no card added), or Stripe is not set up on this server.</p> : (
          <>
            <dl className="mt-2 divide-y divide-border">
              {dl("Customer", data.stripe.customer || "—")}
              {sub && dl("Subscription", `${sub.status}${sub.cancel_at_period_end ? ", cancels at period end" : ""}`)}
              {sub && dl("Current period ends", longDate(fromUnix(sub.current_period_end)))}
              {sub?.trial_end ? dl("Stripe trial ends", longDate(fromUnix(sub.trial_end))) : null}
            </dl>
            {data.stripe.error && <p role="alert" className="mt-2 text-sm font-bold text-red-700">Stripe: {data.stripe.error}</p>}
            {data.stripe.invoices.length > 0 && (
              <ul className="mt-2 text-sm">{data.stripe.invoices.map((i) => <li key={i.id} className="flex justify-between border-t border-border py-1.5"><span>{longDate(fromUnix(i.created))} · {i.number ?? i.id} · {i.status}</span><span>{i.hosted_invoice_url ? <a href={i.hosted_invoice_url} target="_blank" rel="noreferrer" className="font-bold text-teal-dark underline underline-offset-2">{money(i.total)}</a> : money(i.total)}{i.currency && i.currency !== "gbp" ? ` ${i.currency.toUpperCase()}` : ""}</span></li>)}</ul>
            )}
          </>
        )}
      </section>

      <section aria-labelledby="u-redeem" className={card}>
        <h2 id="u-redeem" className={h2}>Redemptions</h2>
        {data.redemptions.length === 0 ? <p className="mt-1 text-sm text-muted">No codes redeemed.</p> : <ul className="mt-1 text-sm">{data.redemptions.map((r) => <li key={r.id}>{r.code} · {longDate(r.redeemed_at)}</li>)}</ul>}
      </section>

      <section aria-labelledby="u-notes" className={card}>
        <h2 id="u-notes" className={h2}>Notes</h2>
        <textarea aria-label="Notes" className="mt-2 w-full rounded-xl border border-border p-3 text-sm" rows={4} value={notes ?? data.notes ?? ""} onChange={(e) => setNotes(e.target.value)} />
        <button type="button" className={`${primaryButton} mt-2`} disabled={notes === null || notes === (data.notes ?? "")} onClick={() => patch("Save notes", <>Save these notes on {a.email}? Support notes are visible only to administrators.</>, { notes: notes ?? "" })}>Save notes</button>
      </section>

      <section aria-labelledby="u-audit" className={card}>
        <h2 id="u-audit" className={h2}>Audit</h2>
        <ul className="mt-1 text-sm">{data.audit.map((r) => <li key={r.id} className="border-t border-border py-1.5 first:border-0">{longDate(r.at)} · {r.admin_email} · <strong>{r.action}</strong> <span className="text-muted">{JSON.stringify(r.detail)}</span></li>)}
          {data.audit.length === 0 && <li className="text-muted">Nothing yet.</li>}</ul>
      </section>

      {pending && (
        <ConfirmDialog
          title={pending.title}
          body={pending.body}
          onCancel={() => setPending(null)}
          onConfirm={async () => {
            await pending.run();
            setPending(null);
            setNotes(null);
            reload();
          }}
        />
      )}
    </>
  );
}
