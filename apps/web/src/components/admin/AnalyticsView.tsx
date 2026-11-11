"use client";

import { useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import AdminFrame, { ErrorLine, MiniChart, Stat, card, h2, input, td, th, useLoad } from "./parts";
import { fieldLabel } from "@/components/invoices/Modal";
import { adminApi } from "@/lib/billing-api";
import type { FeatureCounts } from "@/lib/admin";

export default function AnalyticsView() {
  return (
    <AdminFrame title="Analytics" description="First-party usage: no third-party scripts, and nothing from users who opted out.">
      {(account) => <Body account={account} />}
    </AdminFrame>
  );
}

const FEATURE_LABEL: Record<keyof FeatureCounts, string> = {
  document_scanned: "Documents scanned", proposal_approved: "Approvals", bank_synced: "Bank syncs", ask: "Ask questions", vat_export: "VAT exports", itsa_export: "Income Tax exports", ebay_sync: "eBay syncs",
};
const iso = (d: Date) => d.toISOString().slice(0, 10);
const pct = (r: number | null) => (r === null ? "no data yet" : `${(r * 100).toFixed(1)}%`);

function Body({ account }: { account: AccountInfo }) {
  const [to, setTo] = useState(() => iso(new Date()));
  const [from, setFrom] = useState(() => iso(new Date(Date.now() - 29 * 86_400_000)));
  const { data, error } = useLoad(() => adminApi.analytics(account, { from, to }), [account, from, to]);
  const funnel = data ? [["Signed up", data.funnel.signed_up], ["First document", data.funnel.first_document], ["First approval", data.funnel.first_approval]] as const : [];
  const top = Math.max(1, ...funnel.map(([, n]) => n));
  return (
    <>
      <div className="flex flex-wrap gap-3">
        <label><span className={fieldLabel}>From</span><input type="date" className={`${input} block`} value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label><span className={fieldLabel}>To</span><input type="date" className={`${input} block`} value={to} onChange={(e) => setTo(e.target.value)} /></label>
      </div>
      <ErrorLine error={error} />
      {data && (
        <>
          <section className={card} aria-labelledby="an-dau"><h2 id="an-dau" className={h2}>Daily active accounts</h2><MiniChart kind="line" data={data.daily_active} label="Daily active accounts" /></section>
          <section className={card} aria-labelledby="an-funnel"><h2 id="an-funnel" className={h2}>Sign-up to first document to first approval</h2>
            <ul className="mt-2 space-y-2">{funnel.map(([label, n]) => (
              <li key={label}><div className="flex justify-between text-sm"><span className="font-bold">{label}</span><span>{n}</span></div>
                <div className="mt-1 h-3 rounded-full bg-ground"><div className="h-3 rounded-full bg-teal" style={{ width: `${(n / top) * 100}%` }} /></div></li>
            ))}</ul></section>
          <div className="grid grid-cols-2 gap-3 min-[900px]:grid-cols-4">
            <Stat label="Trials ended" value={data.trial_conversion.trials_ended} />
            <Stat label="Converted to paid" value={data.trial_conversion.converted} hint={data.trial_conversion.rate === null ? "no trials ended in this range" : `${pct(data.trial_conversion.rate)} of trials`} />
            <Stat label="Cancelled" value={data.churn.cancelled} hint={data.churn.rate === null ? `of ${data.churn.active_at_start} paying` : `churn ${pct(data.churn.rate)}`} />
          </div>
          <section className={card} aria-labelledby="an-feat"><h2 id="an-feat" className={h2}>Feature use</h2>
            <dl className="mt-2 divide-y divide-border">{(Object.keys(FEATURE_LABEL) as (keyof FeatureCounts)[]).map((k) => [k, data.features[k]] as const).map(([k, v]) => <div key={k} className="flex justify-between py-2 text-sm"><dt className="font-bold">{FEATURE_LABEL[k]}</dt><dd>{v.toLocaleString("en-GB")}</dd></div>)}</dl></section>
          <section className={card} aria-labelledby="an-err"><h2 id="an-err" className={h2}>Top errors by route</h2>
            <table className="mt-2 w-full"><thead><tr className="border-b border-border"><th className={th}>Route</th><th className={th}>Count</th></tr></thead>
              <tbody>{data.errors_by_route.map((e) => <tr key={e.route} className="border-b border-border last:border-0"><td className={td}>{e.route}</td><td className={td}>{e.count}</td></tr>)}
                {data.errors_by_route.length === 0 && <tr><td className={td} colSpan={2}>None recorded.</td></tr>}</tbody></table>
            <p className="mt-2 text-xs text-muted">Detail for each error is in Sentry, where it is enabled.</p></section>
        </>
      )}
    </>
  );
}
